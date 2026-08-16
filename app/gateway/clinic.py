"""Typed wrappers over the platform backend used by tools and the agent."""

from loguru import logger

from app.gateway.base import BaseGateway


class ClinicGateway(BaseGateway):
    @classmethod
    async def call_context(cls, phone: str | None, call_id: str | None) -> dict:
        try:
            return await cls.get(
                "/agent/call-context", params={"phone": phone or "", "call_id": call_id or ""}
            )
        except Exception as exc:
            logger.warning(f"call_context failed: {exc}")
            return {}

    @classmethod
    async def availability(cls, **params) -> dict:
        clean = {k: v for k, v in params.items() if v not in (None, "", [])}
        return await cls.get("/availability", params=clean)

    @classmethod
    async def book(cls, payload: dict) -> tuple[int, dict]:
        return await cls.post("/appointments", json=payload)

    @classmethod
    async def reschedule(cls, appointment_id: str, payload: dict) -> tuple[int, dict]:
        return await cls.post(f"/appointments/{appointment_id}/reschedule", json=payload)

    @classmethod
    async def cancel(cls, appointment_id: str, payload: dict) -> tuple[int, dict]:
        return await cls.post(f"/appointments/{appointment_id}/cancel", json=payload)

    @classmethod
    async def create_followup(cls, payload: dict) -> tuple[int, dict]:
        return await cls.post("/followups", json=payload)

    @classmethod
    async def register_call(cls, call_id: str, direction: str, phone: str | None, room: str) -> None:
        try:
            await cls.post(
                "/calls",
                json={"call_id": call_id, "direction": direction, "phone": phone, "room_name": room},
            )
        except Exception as exc:
            logger.warning(f"register_call failed: {exc}")

    @classmethod
    async def end_call(cls, call_id: str, payload: dict) -> None:
        try:
            await cls.post(f"/calls/{call_id}/end", json=payload)
        except Exception as exc:
            logger.warning(f"end_call report failed: {exc}")

    @classmethod
    async def save_session_state(cls, call_id: str, state: dict) -> None:
        try:
            await cls.put(f"/call-sessions/{call_id}", json=state)
        except Exception as exc:
            logger.warning(f"save_session_state failed: {exc}")

    @classmethod
    async def save_latency_metrics(cls, call_id: str, metrics: dict) -> None:
        try:
            await cls.put(f"/call-latency-metrics/{call_id}", json=metrics)
        except Exception as exc:
            logger.warning(f"save_latency_metrics failed: {exc}")

    @classmethod
    async def mark_callback_handled(cls, outbound_id: str) -> None:
        try:
            await cls.client().patch(
                f"/outbound-calls/{outbound_id}", json={"status": "completed"}
            )
        except Exception as exc:
            logger.warning(f"mark_callback_handled failed: {exc}")
