"""TTS factory.

Default: Cartesia sonic-3 with a native Hinglish voice ("Arushi") — one voice
that renders both English and Hindi naturally, so the agent's own
code-switching doesn't sound like two stitched engines.
Alternative provider: OpenAI gpt-4o-mini-tts (multilingual) for personas that
prefer it.
"""

from loguru import logger

from app.config.settings import settings

OPENAI_TTS_VOICES = {"alloy", "ash", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer"}


def create_tts(
    provider: str | None = None,
    voice_id: str | None = None,
    model: str | None = None,
    speed: float | None = None,
):
    resolved_provider = (provider or settings.tts_provider).lower()

    if resolved_provider == "openai":
        from livekit.plugins import openai

        resolved_model = model if model and "tts" in model else "gpt-4o-mini-tts"
        resolved_voice = voice_id if voice_id in OPENAI_TTS_VOICES else "coral"
        logger.info(f"TTS: openai {resolved_model} voice={resolved_voice}")
        kwargs = {"model": resolved_model, "voice": resolved_voice, "api_key": settings.openai_api_key}
        if speed:
            kwargs["speed"] = speed
        return openai.TTS(**kwargs)

    from livekit.plugins import cartesia

    resolved_model = model or settings.cartesia_model
    resolved_voice = voice_id or settings.cartesia_voice_id
    logger.info(f"TTS: cartesia {resolved_model} voice={resolved_voice[:8]}…")
    kwargs = {
        "model": resolved_model,
        "voice": resolved_voice,
        "api_key": settings.cartesia_api_key,
    }
    if speed:
        kwargs["speed"] = speed
    return cartesia.TTS(**kwargs)
