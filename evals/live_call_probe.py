"""Headless LIVE audio smoke test.

Joins a real LiveKit room as a caller (via the backend's /webcall endpoint,
exactly like the dashboard's browser tester), speaks synthesized utterances
into the room, records how much agent audio comes back, then verifies in the
backend that the full loop happened: STT heard us, the LLM booked, TTS spoke,
transcript + latency metrics persisted.

Run with the worker (`make dev`) and backend (`make run`) already up:

    poetry run python -m evals.live_call_probe

This closes the gap the text-mode evals leave open: it exercises the actual
audio path end to end without a human on the mic.
"""

import asyncio
import time

import httpx
from livekit import rtc
from loguru import logger

from app.config.settings import settings

CALLER_PHONE = "+919810000042"
SAMPLE_RATE = 16000

UTTERANCES = [
    (
        6.0,  # wait for greeting to finish before speaking
        "Hi, I'd like to see a dermatologist tomorrow morning. My name is Priya Testwal.",
    ),
    (
        14.0,  # give the agent time to run availability + offer slots
        "The first slot you said is fine, please book it.",
    ),
]
HANG_AFTER = 18.0  # let the booking + confirmation land before leaving


async def synthesize(client: httpx.AsyncClient, text: str) -> bytes:
    response = await client.post(
        "https://api.cartesia.ai/tts/bytes",
        headers={
            "Authorization": f"Bearer {settings.cartesia_api_key}",
            "Cartesia-Version": "2025-04-16",
        },
        json={
            "model_id": settings.cartesia_model,
            "transcript": text,
            "voice": {"mode": "id", "id": "694f9389-aac1-45b6-b726-9d9369183238"},  # a different voice than the agent
            "language": "en",
            "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": SAMPLE_RATE},
        },
        timeout=30.0,
    )
    response.raise_for_status()
    return response.content


async def main() -> None:
    backend = httpx.AsyncClient(base_url=f"{settings.platform_url}/api/v1", timeout=20.0)

    # Clean slate for the probe number, keep clinic catalog
    await backend.post("/admin/reset")

    webcall = (await backend.post("/webcall", json={"caller_phone": CALLER_PHONE})).json()
    call_id = webcall["call_id"]
    logger.info(f"webcall created: {call_id} room={webcall['room_name']}")

    async with httpx.AsyncClient() as tts_client:
        audio_clips = [await synthesize(tts_client, text) for _, text in UTTERANCES]

    room = rtc.Room()
    agent_audio_frames = 0

    @room.on("track_subscribed")
    def on_track(track, publication, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            logger.info(f"subscribed to agent audio from {participant.identity}")

            async def drain():
                nonlocal agent_audio_frames
                stream = rtc.AudioStream(track)
                async for _ in stream:
                    agent_audio_frames += 1

            asyncio.create_task(drain())

    await room.connect(webcall["livekit_url"], webcall["token"])
    logger.info(f"connected as {room.local_participant.identity}")

    source = rtc.AudioSource(SAMPLE_RATE, 1)
    track = rtc.LocalAudioTrack.create_audio_track("mic", source)
    await room.local_participant.publish_track(
        track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    )

    samples_per_frame = SAMPLE_RATE // 100  # 10ms

    async def push_pcm(pcm: bytes) -> None:
        for offset in range(0, len(pcm) - samples_per_frame * 2 + 1, samples_per_frame * 2):
            frame = rtc.AudioFrame(
                data=pcm[offset : offset + samples_per_frame * 2],
                sample_rate=SAMPLE_RATE,
                num_channels=1,
                samples_per_channel=samples_per_frame,
            )
            await source.capture_frame(frame)
            await asyncio.sleep(0.01)

    started = time.time()
    for (delay, text), clip in zip(UTTERANCES, audio_clips):
        await asyncio.sleep(delay)
        logger.info(f'speaking: "{text}"')
        await push_pcm(clip)
    await asyncio.sleep(HANG_AFTER)
    logger.info(f"probe done in {round(time.time() - started, 1)}s; disconnecting")
    await room.disconnect()
    await asyncio.sleep(3)  # let worker cleanup callbacks flush

    # ---- Verification against the backend ----
    failures: list[str] = []
    call = (await backend.get(f"/calls/{call_id}")).json()
    transcript = (call.get("call") or {}).get("transcript") or []
    user_turns = [t for t in transcript if t["role"] == "user"]
    agent_turns = [t for t in transcript if t["role"] == "agent"]
    if not user_turns:
        failures.append("no user turns in transcript — STT path did not produce text")
    if len(agent_turns) < 2:
        failures.append(f"expected >=2 agent turns, got {len(agent_turns)}")
    if agent_audio_frames < 100:
        failures.append(f"agent audio barely flowed ({agent_audio_frames} frames) — TTS path suspect")

    appointments = (await backend.get("/appointments", params={"phone": CALLER_PHONE})).json()[
        "appointments"
    ]
    if not appointments:
        failures.append("no appointment was booked for the probe caller")
    else:
        logger.info(
            f"booked: {appointments[0]['practitioner_name']} {appointments[0].get('display')} "
            f"(pms={appointments[0].get('pms', {}).get('status')})"
        )

    metrics = call.get("latency_metrics") or {}
    if not (metrics.get("aggregates") or {}).get("turn_count"):
        failures.append("no latency metrics were persisted for the call")
    else:
        logger.info(f"latency aggregates: {metrics['aggregates'].get('all')}")

    print("\n--- transcript ---")
    for turn in transcript:
        print(f"  {turn['role']:5s} [{turn.get('lang')}]: {turn['text']}")
    print(f"--- agent audio frames received: {agent_audio_frames}")

    await backend.aclose()
    if failures:
        print("\nLIVE PROBE FAILURES:")
        for failure in failures:
            print(f"  ✗ {failure}")
        raise SystemExit(1)
    print("\n✅ LIVE PROBE PASSED — full audio loop (STT→LLM tools→TTS→DB) verified")


if __name__ == "__main__":
    asyncio.run(main())
