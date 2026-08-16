"""Live conversation state, persisted to the backend on every change.

This is what makes dropped-call recovery real: if the call dies mid-flow the
next call from the same number gets this state back via /agent/call-context
and resumes instead of restarting. Tools update `collected` as facts arrive;
`asked` tracks what the caller has already answered so the prompt can forbid
re-asking.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.gateway.clinic import ClinicGateway
from app.state.language import tag_language


@dataclass
class CallState:
    call_id: str
    phone: str | None = None
    direction: str = "inbound"
    stage: str = "greeting"
    language: str = "en"
    collected: dict[str, Any] = field(default_factory=dict)
    transcript: list[dict] = field(default_factory=list)
    context: dict = field(default_factory=dict)  # /agent/call-context payload
    completed: bool = False
    disposition: str | None = None
    _dirty: bool = field(default=False, repr=False)

    def note(self, **facts: Any) -> None:
        """Record collected facts (patient name, specialty, slot, ...)."""
        for key, value in facts.items():
            if value is not None:
                self.collected[key] = value
        self._dirty = True

    def set_stage(self, stage: str) -> None:
        if stage != self.stage:
            self.stage = stage
            self._dirty = True

    def add_turn(self, role: str, text: str) -> None:
        if not text:
            return
        language = tag_language(text)
        if role == "user":
            self.language = language
        self.transcript.append({"role": role, "text": text, "lang": language})
        self._dirty = True

    def summary_line(self) -> str:
        parts = []
        c = self.collected
        if c.get("patient_name"):
            parts.append(f"patient={c['patient_name']}")
        if c.get("intent"):
            parts.append(f"intent={c['intent']}")
        if c.get("specialty"):
            parts.append(f"specialty={c['specialty']}")
        if c.get("practitioner_name"):
            parts.append(f"doctor={c['practitioner_name']}")
        if c.get("branch_name"):
            parts.append(f"branch={c['branch_name']}")
        if c.get("candidate_slot"):
            slot = c["candidate_slot"]
            parts.append(f"discussing_slot={slot.get('date_local')} {slot.get('start_hm')}")
        if c.get("appointment_id"):
            parts.append(f"booked_appointment={c['appointment_id']}")
        return ", ".join(parts) or "nothing collected yet"

    def persist_soon(self) -> None:
        """Fire-and-forget upsert; never blocks the voice path."""
        if not self._dirty:
            return
        self._dirty = False
        asyncio.create_task(
            ClinicGateway.save_session_state(
                self.call_id,
                {
                    "phone": self.phone,
                    "status": "active",
                    "stage": self.stage,
                    "language": self.language,
                    "collected": self.collected,
                    "summary": self.summary_line(),
                },
            )
        )

    async def persist_final(self) -> None:
        await ClinicGateway.save_session_state(
            self.call_id,
            {
                "phone": self.phone,
                "status": "completed" if self.completed else "dropped",
                "stage": self.stage,
                "language": self.language,
                "collected": self.collected,
                "summary": self.summary_line(),
            },
        )
