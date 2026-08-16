import asyncio

from livekit import api as lk_api
from livekit.agents import RunContext, get_job_context
from loguru import logger

from app.tools.utils import clinic_tool


@clinic_tool
async def end_call(ctx: RunContext) -> str:
    """End the call. Use ONLY after you've said a natural goodbye and the
    caller has nothing else — never hang up abruptly.
    """
    state = ctx.userdata
    state.set_stage("ended")
    try:
        await ctx.wait_for_playout()
    except Exception:
        pass
    await asyncio.sleep(0.8)
    try:
        job_ctx = get_job_context()
        room_name = getattr(job_ctx.room, "name", None)
        if room_name:
            await job_ctx.api.room.delete_room(lk_api.DeleteRoomRequest(room=room_name))
            logger.info(f"Call ended, room {room_name} deleted")
    except Exception as exc:
        logger.warning(f"end_call room delete failed: {exc}")
    return "Call ended."
