from loguru import logger

from app.config.settings import settings


def create_llm(model: str | None = None, temperature: float | None = None):
    provider = settings.llm_provider.lower()
    from livekit.plugins import openai

    resolved_temperature = settings.llm_temperature if temperature is None else temperature
    if provider == "azure" and settings.azure_openai_api_key:
        logger.info(f"LLM: azure {settings.azure_openai_deployment}")
        return openai.LLM.with_azure(
            model=settings.azure_openai_deployment,
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            temperature=resolved_temperature,
        )
    resolved_model = model or settings.llm_model
    logger.info(f"LLM: openai {resolved_model}")
    return openai.LLM(
        model=resolved_model,
        api_key=settings.openai_api_key,
        temperature=resolved_temperature,
        parallel_tool_calls=False,
    )
