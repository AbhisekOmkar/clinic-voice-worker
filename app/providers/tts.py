"""TTS factory.

Cartesia sonic-3 with a native Hinglish voice ("Arushi"): one voice that
renders both English and Hindi (Devanagari or romanised) naturally, so the
agent's own code-switching doesn't sound like two stitched engines.
"""

from loguru import logger

from app.config.settings import settings


def create_tts():
    from livekit.plugins import cartesia

    logger.info(f"TTS: cartesia {settings.cartesia_model} voice={settings.cartesia_voice_id[:8]}…")
    return cartesia.TTS(
        model=settings.cartesia_model,
        voice=settings.cartesia_voice_id,
        api_key=settings.cartesia_api_key,
    )
