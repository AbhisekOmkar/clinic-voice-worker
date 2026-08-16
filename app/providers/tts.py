"""TTS factory.

Cartesia sonic-3 with a native Hinglish voice ("Arushi"): one voice that
renders both English and Hindi (Devanagari or romanised) naturally, so the
agent's own code-switching doesn't sound like two stitched engines.
"""

from loguru import logger

from app.config.settings import settings


def create_tts(voice_id: str | None = None):
    from livekit.plugins import cartesia

    resolved_voice = voice_id or settings.cartesia_voice_id
    logger.info(f"TTS: cartesia {settings.cartesia_model} voice={resolved_voice[:8]}…")
    return cartesia.TTS(
        model=settings.cartesia_model,
        voice=resolved_voice,
        api_key=settings.cartesia_api_key,
    )
