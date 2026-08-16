"""Component latency probes — measured against the real provider APIs, per
language, so the README's latency numbers are evidence, not vibes.

    poetry run python -m evals.latency_probe

Measures:
- LLM TTFT: streamed chat completion using the REAL system prompt size, first
  content token wall-clock (EN and HI user turns).
- TTS TTFB: Cartesia sonic-2 streaming bytes endpoint, first audio chunk
  wall-clock (EN and HI sentences, the actual Arushi voice).
- STT: synthesises those sentences with the TTS, then transcribes — Deepgram
  nova-3 language=multi when a key is configured, else OpenAI
  gpt-4o-transcribe. Reported as one-shot wall-clock (NOT streaming partials),
  plus a rough content-match ratio per language as an accuracy sanity check.

Honesty: these are component floors on this machine's network. Live-call E2E
adds VAD/EOU turn detection and jitter — see call_latency_metrics for that.
"""

import asyncio
import io
import json
import statistics
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.config.settings import settings

EN_SENTENCES = [
    "Do you have anything with a dermatologist on Saturday around one?",
    "I'd like to reschedule my appointment to Friday morning please.",
    "What's the earliest slot available at the HSR Layout branch?",
    "My name is Ananya Iyer, booking for my son Aarav.",
    "Can I see Dr. Meera Shridhar next Wednesday evening?",
]
HI_SENTENCES = [
    "क्या शनिवार को एक बजे के आसपास त्वचा विशेषज्ञ से मिल सकते हैं?",
    "मुझे अपनी अपॉइंटमेंट शुक्रवार सुबह के लिए बदलनी है।",
    "एचएसआर लेआउट ब्रांच में सबसे जल्दी कौन सा स्लॉट मिलेगा?",
    "मेरा नाम विकास शर्मा है, अपने बेटे के लिए बुक करना है।",
    "अगले बुधवार शाम को डॉक्टर मीरा से मिलना है।",
]

SYSTEM_PROMPT_SAMPLE = (
    "You are Asha, the telephone receptionist for Apollo Clinic Bengaluru "
    "(Indiranagar and HSR Layout). Mirror the caller's language (English/Hindi/"
    "Hinglish). Book fast, never re-ask, offer at most three slots. " * 20
)  # padded to approximate the real prompt's token count


def p50(values):
    return round(statistics.median(values), 1) if values else None


async def probe_llm_ttft(client: httpx.AsyncClient) -> dict:
    results = {}
    for lang, sentences in (("en", EN_SENTENCES), ("hi", HI_SENTENCES)):
        ttfts = []
        for sentence in sentences:
            start = time.perf_counter()
            first = None
            async with client.stream(
                "POST",
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": settings.llm_model,
                    "stream": True,
                    "temperature": 0.3,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT_SAMPLE},
                        {"role": "user", "content": sentence},
                    ],
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: ") and '"content"' in line:
                        first = time.perf_counter()
                        break
            if first:
                ttfts.append((first - start) * 1000)
        results[lang] = {"ttft_ms_p50": p50(ttfts), "ttft_ms_all": [round(t, 1) for t in ttfts]}
    return results


async def probe_tts_ttfb(client: httpx.AsyncClient) -> tuple[dict, dict[str, list[bytes]]]:
    results = {}
    audio: dict[str, list[bytes]] = {"en": [], "hi": []}
    for lang, sentences in (("en", EN_SENTENCES), ("hi", HI_SENTENCES)):
        ttfbs = []
        for sentence in sentences:
            start = time.perf_counter()
            first = None
            chunks = []
            async with client.stream(
                "POST",
                "https://api.cartesia.ai/tts/bytes",
                headers={
                    "Authorization": f"Bearer {settings.cartesia_api_key}",
                    "Cartesia-Version": "2025-04-16",
                },
                json={
                    "model_id": settings.cartesia_model,
                    "transcript": sentence,
                    "voice": {"mode": "id", "id": settings.cartesia_voice_id},
                    "language": lang,
                    "output_format": {
                        "container": "raw",
                        "encoding": "pcm_s16le",
                        "sample_rate": 16000,
                    },
                },
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    if first is None and chunk:
                        first = time.perf_counter()
                    chunks.append(chunk)
            if first:
                ttfbs.append((first - start) * 1000)
            audio[lang].append(b"".join(chunks))
        results[lang] = {"ttfb_ms_p50": p50(ttfbs), "ttfb_ms_all": [round(t, 1) for t in ttfbs]}
    return results, audio


def _to_wav(pcm: bytes, sample_rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


def _match_ratio(expected: str, actual: str) -> float:
    expected_tokens = {t.strip('।,.?!').lower() for t in expected.split() if t.strip('।,.?!')}
    actual_tokens = {t.strip('।,.?!').lower() for t in actual.split() if t.strip('।,.?!')}
    if not expected_tokens:
        return 0.0
    return round(len(expected_tokens & actual_tokens) / len(expected_tokens), 2)


async def probe_stt(client: httpx.AsyncClient, audio: dict[str, list[bytes]]) -> dict:
    results = {}
    use_deepgram = bool(settings.deepgram_api_key)
    for lang, sentences in (("en", EN_SENTENCES), ("hi", HI_SENTENCES)):
        latencies, matches = [], []
        for sentence, pcm in zip(sentences, audio[lang]):
            if not pcm:
                continue
            wav_bytes = _to_wav(pcm)
            start = time.perf_counter()
            transcript = ""
            try:
                if use_deepgram:
                    response = await client.post(
                        "https://api.deepgram.com/v1/listen?model=nova-3&language=multi&smart_format=true",
                        headers={
                            "Authorization": f"Token {settings.deepgram_api_key}",
                            "Content-Type": "audio/wav",
                        },
                        content=wav_bytes,
                    )
                    response.raise_for_status()
                    transcript = response.json()["results"]["channels"][0]["alternatives"][0]["transcript"]
                else:
                    files = {"file": ("probe.wav", wav_bytes, "audio/wav")}
                    response = await client.post(
                        "https://api.openai.com/v1/audio/transcriptions",
                        headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                        data={"model": settings.openai_stt_model},
                        files=files,
                    )
                    response.raise_for_status()
                    transcript = response.json().get("text", "")
            except Exception as exc:
                print(f"  stt probe error ({lang}): {exc}")
                continue
            latencies.append((time.perf_counter() - start) * 1000)
            matches.append(_match_ratio(sentence, transcript))
        results[lang] = {
            "provider": "deepgram nova-3 multi" if use_deepgram else f"openai {settings.openai_stt_model}",
            "mode": "one-shot wall-clock (streaming partials are lower in live calls)",
            "latency_ms_p50": p50(latencies),
            "content_match_ratio_avg": round(statistics.mean(matches), 2) if matches else None,
            "n": len(latencies),
        }
    return results


async def main() -> None:
    async with httpx.AsyncClient(timeout=60.0) as client:
        print("Probing LLM TTFT…")
        llm = await probe_llm_ttft(client)
        print("Probing TTS TTFB…")
        tts, audio = await probe_tts_ttfb(client)
        print("Probing STT…")
        stt = await probe_stt(client, audio)

    report = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "llm": {"model": settings.llm_model, **llm},
        "tts": {"model": f"cartesia {settings.cartesia_model} (Arushi bilingual voice)", **tts},
        "stt": stt,
        "notes": [
            "Component floors measured from this machine; live E2E adds EOU/turn detection (~min_endpointing_delay) and network jitter.",
            "Voice-path response floor ≈ EOU delay + LLM TTFT + TTS TTFB.",
        ],
    }
    runs = Path(__file__).parent / "runs"
    runs.mkdir(exist_ok=True)
    out = runs / f"latency_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nSaved {out}")


if __name__ == "__main__":
    asyncio.run(main())
