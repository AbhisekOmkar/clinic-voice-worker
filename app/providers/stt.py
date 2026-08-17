"""STT factory.

Default: Deepgram nova-3 with language='multi' — true streaming multilingual
ASR that handles English<->Hindi code-switching inside a single utterance
(no translation tables anywhere).
Fallback: OpenAI gpt-4o-transcribe over the realtime websocket, also natively
multilingual, used when a Deepgram key is unavailable.

Agent personas may override provider/model/language; a Deepgram selection
still degrades to OpenAI when no key is configured.
"""

from loguru import logger

from app.config.settings import settings


def create_stt(provider: str | None = None, model: str | None = None, language: str | None = None):
    resolved_provider = (provider or settings.stt_provider).lower()
    if resolved_provider == "deepgram" and settings.deepgram_api_key:
        from livekit.plugins import deepgram

        resolved_model = model or settings.stt_model
        resolved_language = language or settings.stt_language
        logger.info(f"STT: deepgram {resolved_model} language={resolved_language}")
        return deepgram.STT(
            model=resolved_model,
            language=resolved_language,
            api_key=settings.deepgram_api_key,
            interim_results=True,
            smart_format=True,
            punctuate=True,
        )
    if resolved_provider == "deepgram":
        logger.warning("DEEPGRAM_API_KEY missing — falling back to OpenAI STT")
        model = None  # a deepgram model name must not leak into the openai call
    from livekit.plugins import openai

    resolved_model = model or settings.openai_stt_model
    logger.info(f"STT: openai {resolved_model} (multilingual)")
    return openai.STT(
        model=resolved_model,
        api_key=settings.openai_api_key,
        # Bias the decoder: short narrowband phone utterances otherwise get
        # misrecognised into random languages. The call is only ever
        # English/Hindi/Hinglish.
        prompt=(
            "Phone call with a clinic receptionist in Bengaluru, India. "
            "The caller speaks English, Hindi, or Hinglish (never other languages). "
            "Doctor names: Meera Shridhar, Rajendra, Tejashwini, Nalini, Himabindu, Rajeev Ghat."
        ),
    )
