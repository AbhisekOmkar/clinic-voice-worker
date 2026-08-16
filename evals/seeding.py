"""Scenario seeding + ground-truth reads, all via the backend API (the same
surface the agent uses), so evals run from a clean clone with no DB client."""

import httpx

from app.config.settings import settings


class Backend:
    def __init__(self):
        headers = {}
        if settings.internal_service_key:
            headers["X-Internal-Service-Key"] = settings.internal_service_key
        self.client = httpx.AsyncClient(
            base_url=f"{settings.platform_url}/api/v1", headers=headers, timeout=15.0
        )

    async def reset(self) -> None:
        response = await self.client.post("/admin/reset")
        response.raise_for_status()

    async def apply_seed(self, seed: dict, caller_phone: str) -> dict:
        """Returns artifacts (e.g. seeded appointment ids) for assertions."""
        artifacts: dict = {"appointments": []}
        for appointment in seed.get("appointments", []):
            response = await self.client.post(
                "/appointments",
                json={
                    "patient_name": appointment["patient_name"],
                    "phone": appointment.get("phone", caller_phone),
                    "practitioner_id": appointment["practitioner_id"],
                    "branch_id": appointment["branch_id"],
                    "date_local": appointment["date"],
                    "start_hm": appointment["start_hm"],
                    "reason": appointment.get("reason"),
                },
            )
            response.raise_for_status()
            artifacts["appointments"].append(response.json()["appointment"])
        for patient in seed.get("patients", []):
            # Patients materialise via bookings normally; bare patients are
            # created through a synthetic completed call booking-less path:
            # simplest honest route — a followup-less direct insert isn't
            # exposed, so seed patients through a booking when provided, else
            # via the patients implicit path (skip).
            pass
        if seed.get("outbound_call"):
            payload = dict(seed["outbound_call"])
            payload.setdefault("phone", caller_phone)
            payload.setdefault("status", "no_answer")
            response = await self.client.post("/outbound-calls", json=payload)
            response.raise_for_status()
            artifacts["outbound"] = response.json()
        if seed.get("dropped_session"):
            session = dict(seed["dropped_session"])
            call_id = session.pop("call_id", "eval-prior-call")
            session.setdefault("phone", caller_phone)
            session.setdefault("status", "dropped")
            response = await self.client.put(f"/call-sessions/{call_id}", json=session)
            response.raise_for_status()
            artifacts["dropped_session_call_id"] = call_id
        return artifacts

    async def book_out_of_band(self, slot: dict, patient_name: str = "Walk In Competitor") -> dict:
        """Steal a slot mid-conversation (slot-taken race scenario)."""
        practitioner = await self._practitioner_by_name(slot["practitioner_name"])
        branches = (await self.client.get("/branches")).json()["branches"]
        branch = next(b for b in branches if b["name"] == slot["branch"])
        response = await self.client.post(
            "/appointments",
            json={
                "patient_name": patient_name,
                "phone": "+919700000099",
                "practitioner_id": practitioner["practitioner_id"],
                "branch_id": branch["branch_id"],
                "date_local": slot["date"],
                "start_hm": slot["time"],
            },
        )
        response.raise_for_status()
        return response.json()

    async def _practitioner_by_name(self, full_name: str) -> dict:
        practitioners = (await self.client.get("/practitioners")).json()["practitioners"]
        for p in practitioners:
            if p["full_name"].lower() == full_name.lower():
                return p
        raise ValueError(f"Unknown practitioner {full_name}")

    async def appointments_for_phone(self, phone: str) -> list[dict]:
        response = await self.client.get("/appointments", params={"phone": phone})
        return response.json()["appointments"]

    async def followups(self) -> list[dict]:
        response = await self.client.get("/followups")
        return response.json()["followups"]

    async def call_context(self, phone: str) -> dict:
        response = await self.client.get("/agent/call-context", params={"phone": phone})
        return response.json()

    async def catalog(self) -> dict:
        return {
            "branches": (await self.client.get("/branches")).json()["branches"],
            "practitioners": (await self.client.get("/practitioners")).json()["practitioners"],
        }

    async def aclose(self) -> None:
        await self.client.aclose()
