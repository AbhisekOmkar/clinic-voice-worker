"""STT factory.

Default: Deepgram nova-3 with language='multi' — true streaming multilingual
ASR that handles English<->Hindi code-switching inside a single utterance
(no translation tables anywhere).
Fallback: OpenAI gpt-4o-transcribe over the realtime websocket, also natively
multilingual, used when a Deepgram key is unavailable.
"""

from loguru import logger

from app.config.settings import settings


def create_stt():
    provider = settings.stt_provider.lower()
    if provider == "deepgram" and settings.deepgram_api_key:
        from livekit.plugins import deepgram

        logger.info(f"STT: deepgram {settings.stt_model} language={settings.stt_language}")
        return deepgram.STT(
            model=settings.stt_model,
            language=settings.stt_language,
            api_key=settings.deepgram_api_key,
            interim_results=True,
            smart_format=True,
            punctuate=True,
        )
    if provider == "deepgram":
        logger.warning("DEEPGRAM_API_KEY missing — falling back to OpenAI STT")
    from livekit.plugins import openai

    logger.info(f"STT: openai {settings.openai_stt_model} (multilingual)")
    return openai.STT(model=settings.openai_stt_model, api_key=settings.openai_api_key)
