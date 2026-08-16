from loguru import logger

from app.config.settings import settings


def create_llm():
    provider = settings.llm_provider.lower()
    from livekit.plugins import openai

    if provider == "azure" and settings.azure_openai_api_key:
        logger.info(f"LLM: azure {settings.azure_openai_deployment}")
        return openai.LLM.with_azure(
            model=settings.azure_openai_deployment,
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            temperature=settings.llm_temperature,
        )
    logger.info(f"LLM: openai {settings.llm_model}")
    return openai.LLM(
        model=settings.llm_model,
        api_key=settings.openai_api_key,
        temperature=settings.llm_temperature,
        parallel_tool_calls=False,
    )
