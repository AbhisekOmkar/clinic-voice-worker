"""Tool plumbing: uniform error handling + latency masking.

Every tool is wrapped so that
- exceptions surface to the LLM as a recoverable sentence, never a crash;
- if the backend takes longer than ~1.2s the agent speaks a natural holding
  phrase in the caller's current language instead of stuttering silence.
"""

import asyncio
import functools
import random

from livekit.agents import RunContext, function_tool
from loguru import logger

from app.config.settings import settings

HOLDING_PHRASES = {
    "en": [
        "One moment, let me check that for you.",
        "Just a second, I'm pulling that up.",
        "Let me have a quick look.",
    ],
    "hi": [
        "एक सेकंड, मैं अभी देखती हूँ।",
        "बस एक पल, चेक कर रही हूँ।",
        "ज़रा रुकिए, देख लेती हूँ।",
    ],
    "mixed": [
        "One second, main check karti hoon.",
        "बस एक पल — checking.",
    ],
}


def _current_language(ctx: RunContext) -> str:
    state = getattr(ctx, "userdata", None)
    return getattr(state, "language", "en") if state else "en"


async def _speak_holding_phrase(ctx: RunContext) -> None:
    try:
        await asyncio.sleep(settings.tool_holding_phrase_after_seconds)
        language = _current_language(ctx)
        phrase = random.choice(HOLDING_PHRASES.get(language, HOLDING_PHRASES["en"]))
        session = getattr(ctx, "session", None)
        if session is not None:
            session.say(phrase, add_to_chat_ctx=False)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.debug(f"holding phrase skipped: {exc}")


def clinic_tool(func):
    """robust_function_tool + latency masking."""

    @functools.wraps(func)
    async def wrapper(ctx: RunContext, *args, **kwargs):
        masker = asyncio.create_task(_speak_holding_phrase(ctx))
        try:
            return await func(ctx, *args, **kwargs)
        except Exception as exc:
            logger.opt(exception=True).error(f"Tool {func.__name__} failed: {exc}")
            return (
                "TOOL_ERROR: something went wrong on my side. Apologise briefly, "
                "and offer to log a follow-up so staff can call the patient back."
            )
        finally:
            masker.cancel()

    return function_tool(wrapper)
