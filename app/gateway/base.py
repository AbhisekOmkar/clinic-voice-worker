import httpx
from loguru import logger

from app.config.settings import settings


class BaseGateway:
    """Pooled async HTTP client for platform-backend calls."""

    _client: httpx.AsyncClient | None = None

    @classmethod
    def client(cls) -> httpx.AsyncClient:
        if cls._client is None or cls._client.is_closed:
            headers = {}
            if settings.internal_service_key:
                headers["X-Internal-Service-Key"] = settings.internal_service_key
            cls._client = httpx.AsyncClient(
                base_url=f"{settings.platform_url}/api/v1",
                headers=headers,
                timeout=httpx.Timeout(10.0, connect=5.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return cls._client

    @classmethod
    async def get(cls, path: str, params: dict | None = None) -> dict:
        response = await cls.client().get(path, params=params)
        response.raise_for_status()
        return response.json()

    @classmethod
    async def post(cls, path: str, json: dict | None = None) -> tuple[int, dict]:
        """Returns (status, body) — 4xx bodies carry structured agent-facing
        errors (SLOT_TAKEN alternatives etc.) and must not raise."""
        response = await cls.client().post(path, json=json)
        return response.status_code, cls._safe_json(response)

    @classmethod
    async def put(cls, path: str, json: dict | None = None) -> tuple[int, dict]:
        response = await cls.client().put(path, json=json)
        return response.status_code, cls._safe_json(response)

    @staticmethod
    def _safe_json(response: httpx.Response) -> dict:
        try:
            return response.json()
        except Exception:
            logger.warning(f"Non-JSON response {response.status_code} from {response.request.url}")
            return {"raw": response.text[:500]}

    @classmethod
    async def aclose(cls) -> None:
        if cls._client and not cls._client.is_closed:
            await cls._client.aclose()
