from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    environment: str = "local"
    log_level: str = "INFO"

    agent_name: str = "clinic-voice-agent"
    http_port: int = 8081
    worker_load_threshold: float = 0.8

    # LiveKit
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""

    # Platform backend
    platform_url: str = "http://localhost:4226"
    internal_service_key: str = ""

    # Providers
    stt_provider: str = "deepgram"  # deepgram | openai
    stt_model: str = "nova-3"
    stt_language: str = "multi"  # Deepgram nova-3 code-switching mode (covers en + hi)
    openai_stt_model: str = "gpt-4o-transcribe"

    llm_provider: str = "openai"  # openai | azure
    llm_model: str = "gpt-4.1"
    llm_temperature: float = 0.3

    tts_provider: str = "cartesia"
    cartesia_model: str = "sonic-2"
    cartesia_voice_id: str = "95d51f79-c397-46f9-b49a-23763d3eaa2d"  # "Arushi" — Hinglish bilingual

    # Turn taking / interruptions
    min_endpointing_delay: float = 0.4
    max_endpointing_delay: float = 5.0
    allow_interruptions: bool = True
    enable_noise_cancellation: bool = True
    # Speak a holding phrase if a tool call runs longer than this
    tool_holding_phrase_after_seconds: float = 1.2

    # API keys
    openai_api_key: str = ""
    deepgram_api_key: str = ""
    cartesia_api_key: str = ""
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_deployment: str = "gpt-4o"
    azure_openai_api_version: str = "2024-12-01-preview"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
