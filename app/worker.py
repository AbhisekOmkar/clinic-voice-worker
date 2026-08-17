"""Worker entrypoint: registers with LiveKit and serves clinic calls.

Run:  python -m app.worker dev        (local dev)
      python -m app.worker start      (production)
      python -m app.worker download-files   (prefetch turn-detector models)
"""

import json
import time

from dotenv import load_dotenv

load_dotenv(dotenv_path=".env", override=True)

from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli  # noqa: E402
from loguru import logger  # noqa: E402

from app.config.logging import bind_call, configure_logging  # noqa: E402
from app.config.settings import settings  # noqa: E402
from app.gateway.clinic import ClinicGateway  # noqa: E402
from app.state.session_state import CallState  # noqa: E402

configure_logging()


def prewarm(proc) -> None:
    from app.providers.vad import load_vad

    proc.userdata["vad"] = load_vad()
    logger.info("Prewarmed Silero VAD")


def _extract_sip_phone(room) -> str | None:
    for participant in room.remote_participants.values():
        phone = participant.attributes.get("sip.phoneNumber")
        if phone:
            return phone
    return None


async def _wait_for_answer(ctx, timeout_seconds: int = 55) -> bool:
    """Poll the SIP participant's callStatus until the callee picks up."""
    import asyncio

    elapsed = 0.0
    while elapsed < timeout_seconds:
        sip_participants = [
            p
            for p in ctx.room.remote_participants.values()
            if p.attributes.get("sip.callStatus")
        ]
        if sip_participants:
            status = sip_participants[0].attributes.get("sip.callStatus")
            if status == "active":
                return True
            if status in ("hangup", "automation"):
                return False
        elif elapsed > 8:
            # SIP participant left (rejected/failed) before ever going active
            return False
        await asyncio.sleep(0.5)
        elapsed += 0.5
    return False


async def entrypoint(ctx: JobContext) -> None:
    boot_start = time.time()
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    metadata = {}
    if ctx.job.metadata:
        try:
            metadata = json.loads(ctx.job.metadata)
        except json.JSONDecodeError:
            logger.warning("Unparseable job metadata; continuing with defaults")

    call_id = metadata.get("call_id") or f"call-{ctx.room.name}"
    direction = metadata.get("direction", "inbound")
    phone = metadata.get("phone")

    participant = await ctx.wait_for_participant()
    sip_phone = _extract_sip_phone(ctx.room)
    if sip_phone:
        phone = sip_phone
        direction = metadata.get("direction", "inbound")
    if phone and phone.startswith("web:"):
        phone = None

    if direction == "outbound":
        # The room's SIP participant is ringing the patient — hold the agent
        # until they actually pick up (or give up and record no_answer).
        answered = await _wait_for_answer(ctx, timeout_seconds=55)
        if not answered:
            logger.info("Outbound call not answered")
            if metadata.get("outbound_id"):
                await ClinicGateway.update_outbound_status(metadata["outbound_id"], "no_answer")
            await ClinicGateway.end_call(
                metadata.get("call_id") or call_id,
                {"disposition": "no_answer", "transcript": [], "completed": False},
            )
            ctx.shutdown(reason="no_answer")
            return

    bind_call(call_id, phone)
    logger.info(f"Call starting: direction={direction} phone={phone} room={ctx.room.name}")

    state = CallState(call_id=call_id, phone=phone, direction=direction)

    # One round trip gives recognition + resume + callback + clock context.
    context = await ClinicGateway.call_context(phone, call_id)
    try:
        catalog = {
            "branches": (await ClinicGateway.get("/branches"))["branches"],
            "practitioners": (await ClinicGateway.get("/practitioners"))["practitioners"],
        }
    except Exception as exc:
        logger.error(f"catalog load failed: {exc}")
        catalog = {"branches": [], "practitioners": []}
    context["catalog"] = catalog
    context["agent_config"] = await ClinicGateway.agent_config(metadata.get("agent_id"))
    if context["agent_config"]:
        logger.info(f"Using agent persona: {context['agent_config'].get('name')}")
    if direction == "outbound":
        context["outbound_call"] = {
            "purpose": metadata.get("purpose") or "a call from the clinic",
            "outbound_id": metadata.get("outbound_id"),
        }
        # An outbound dial is never a resume/callback of itself
        context["resumable_session"] = None
        context["pending_callback"] = None
    state.context = context
    if context.get("resumable_session", {}) and context["resumable_session"]:
        state.collected.update(context["resumable_session"].get("collected", {}))
        if context["resumable_session"].get("language"):
            state.language = context["resumable_session"]["language"]

    await ClinicGateway.register_call(call_id, direction, phone, ctx.room.name)

    from app.agents.receptionist import ReceptionistRunner

    runner = ReceptionistRunner(ctx, state, vad=ctx.proc.userdata.get("vad"), participant=participant)
    runner.build_session()

    async def cleanup() -> None:
        try:
            callback = (state.context or {}).get("pending_callback")
            if callback and state.completed:
                await ClinicGateway.mark_callback_handled(callback["outbound_id"])
            outbound = (state.context or {}).get("outbound_call")
            if outbound and outbound.get("outbound_id"):
                had_conversation = any(t["role"] == "user" for t in state.transcript)
                await ClinicGateway.update_outbound_status(
                    outbound["outbound_id"],
                    "completed" if had_conversation else "no_answer",
                )
            await state.persist_final()
            await ClinicGateway.end_call(
                call_id,
                {
                    "disposition": state.disposition or ("completed" if state.completed else "disconnected"),
                    "transcript": state.transcript,
                    "completed": state.completed,
                    "duration_seconds": round(time.time() - boot_start, 1),
                },
            )
            await ClinicGateway.save_latency_metrics(call_id, await runner.usage_summary())
            logger.info(f"Call cleanup done: completed={state.completed} disposition={state.disposition}")
        except Exception as exc:
            logger.error(f"cleanup failed: {exc}")

    ctx.add_shutdown_callback(cleanup)

    await runner.start()
    logger.info(f"Agent live in {round((time.time() - boot_start) * 1000)}ms")


def main() -> None:
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            agent_name=settings.agent_name,
            initialize_process_timeout=60.0,
        )
    )


if __name__ == "__main__":
    main()
