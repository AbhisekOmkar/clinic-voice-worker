"""Booking tool belt: availability search + full appointment lifecycle.

Schema discipline: the model supplies natural-language-adjacent arguments
(names, dates, HH:MM). Resolution to ids and all correctness rules (grid
validation, conflicts, buffers, fees) live server-side. Every mutating tool
refreshes the call session state so a dropped call resumes correctly.
"""

import json

from livekit.agents import RunContext

from app.gateway.clinic import ClinicGateway
from app.state.session_state import CallState
from app.tools.catalog import display_name, resolve_branch, resolve_practitioner
from app.tools.utils import clinic_tool


def _state(ctx: RunContext) -> CallState:
    return ctx.userdata


def _compact_slots(slots: list[dict]) -> list[dict]:
    return [
        {
            "date": s["date_local"],
            "time": s["start_hm"],
            "say": s["display"],
            "doctor": display_name(s["practitioner_name"]),
            "practitioner_name": s["practitioner_name"],
            "specialty": s["specialty"],
            "branch": s["branch_name"],
            "fee_inr": s["fee_inr"],
        }
        for s in slots
    ]


@clinic_tool
async def get_availability(
    ctx: RunContext,
    specialty: str | None = None,
    doctor_name: str | None = None,
    branch: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    weekdays: str | None = None,
    after_time: str | None = None,
    before_time: str | None = None,
    near_time: str | None = None,
    earliest: bool = False,
) -> str:
    """Search LIVE appointment availability. Call this EVERY time you need slot
    options — including when the caller changes the requested day/time — never
    reuse earlier results, they go stale.

    Args:
        specialty: Department, e.g. "Dermatology", "General Medicine", "Paediatrics", "Obstetrics & Gynaecology", "Orthopaedics", "Endocrinology".
        doctor_name: Specific doctor if the caller asked for one, e.g. "Dr. Meera".
        branch: "Indiranagar" or "HSR Layout" if the caller cares about location; leave empty to search BOTH branches.
        date_from: Start date YYYY-MM-DD (clinic-local). For "today" use today's date from your context.
        date_to: End date YYYY-MM-DD inclusive. Same as date_from for a single day.
        weekdays: Comma-separated recurring preference, e.g. "monday,wednesday" for "Mondays and Wednesdays work for me".
        after_time: Earliest acceptable start HH:MM 24h, e.g. "16:00" for "after 4".
        before_time: Latest acceptable end HH:MM 24h, e.g. "12:00" for "morning".
        near_time: Target time HH:MM to sort results by closeness, e.g. "13:00" for "around 1".
        earliest: true when the caller wants the SOONEST option — this searches across ALL doctors and BOTH branches; do not pick a single doctor first.
    """
    state = _state(ctx)
    catalog = state.context.get("catalog", {})
    params: dict = {
        "specialty": specialty,
        "date_from": date_from,
        "date_to": date_to,
        "weekdays": weekdays,
        "after_time": after_time,
        "before_time": before_time,
        "near_time": near_time,
        "limit": 6,
    }
    if earliest:
        params["scope"] = "earliest"
    if doctor_name:
        practitioner = resolve_practitioner(catalog, doctor_name)
        if practitioner is None:
            known = ", ".join(
                display_name(p["full_name"]) for p in catalog.get("practitioners", [])
            )
            return json.dumps(
                {"error": "UNKNOWN_DOCTOR", "message": f"No doctor matching '{doctor_name}'.", "doctors": known}
            )
        params["practitioner_id"] = practitioner["practitioner_id"]
    if branch:
        resolved = resolve_branch(catalog, branch)
        if resolved is None:
            return json.dumps(
                {"error": "UNKNOWN_BRANCH", "message": f"No branch matching '{branch}'. Branches: Indiranagar, HSR Layout."}
            )
        params["branch_id"] = resolved["branch_id"]

    result = await ClinicGateway.availability(**params)
    state.set_stage("choosing_slot")
    state.note(
        intent=state.collected.get("intent", "book"),
        specialty=specialty or state.collected.get("specialty"),
        branch_name=(resolve_branch(catalog, branch) or {}).get("name") if branch else state.collected.get("branch_name"),
    )
    slots = _compact_slots(result.get("slots", []))
    if slots:
        state.note(candidate_slot={"date_local": slots[0]["date"], "start_hm": slots[0]["time"]})
    state.persist_soon()
    payload = {
        "as_of": result.get("as_of"),
        "today": result.get("today"),
        "total_matching": result.get("total_matching", 0),
        "slots": slots,
    }
    if not slots:
        payload["note"] = (
            "No slots match. Widen the search (other branch, other day, or drop filters) before saying nothing is available."
        )
    return json.dumps(payload, ensure_ascii=False)


@clinic_tool
async def book_appointment(
    ctx: RunContext,
    patient_full_name: str,
    doctor_name: str,
    branch: str,
    date: str,
    start_time: str,
    reason: str | None = None,
    patient_phone: str | None = None,
) -> str:
    """Book an appointment. Only call after the caller has agreed to a specific
    doctor + branch + date + time, AND you have their full name.

    Args:
        patient_full_name: The patient's FULL name (first + last). Required every time — bookings are never anonymous, even for recognised numbers.
        doctor_name: The doctor to book, e.g. "Dr. Rajendra S".
        branch: "Indiranagar" or "HSR Layout" — must be the branch you told the caller.
        date: YYYY-MM-DD clinic-local date.
        start_time: HH:MM 24h slot start you offered.
        reason: Short visit reason if the caller mentioned one, e.g. "skin rash".
        patient_phone: Only when booking for a DIFFERENT number than the caller's own (e.g. booking for a relative reachable elsewhere).
    """
    state = _state(ctx)
    catalog = state.context.get("catalog", {})
    practitioner = resolve_practitioner(catalog, doctor_name)
    resolved_branch = resolve_branch(catalog, branch)
    if practitioner is None or resolved_branch is None:
        return json.dumps({"error": "RESOLUTION_FAILED", "message": "Doctor or branch not recognised — re-run get_availability and use its exact names."})

    status, body = await ClinicGateway.book(
        {
            "patient_name": patient_full_name.strip(),
            "phone": patient_phone or state.phone or "",
            "practitioner_id": practitioner["practitioner_id"],
            "branch_id": resolved_branch["branch_id"],
            "date_local": date,
            "start_hm": start_time,
            "reason": reason,
            "call_id": state.call_id,
        }
    )
    if status == 200:
        appointment = body["appointment"]
        state.completed = True
        state.disposition = "booked"
        state.set_stage("booked")
        state.note(
            patient_name=appointment["patient_name"],
            practitioner_name=appointment["practitioner_name"],
            branch_name=appointment["branch_name"],
            appointment_id=appointment["appointment_id"],
            candidate_slot=None,
        )
        state.persist_soon()
        speak = body["speak_back"]
        return json.dumps(
            {
                "booked": True,
                "appointment_id": appointment["appointment_id"],
                "confirm_to_caller": {
                    "patient": speak["patient_name"],
                    "doctor": display_name(speak["practitioner_name"]),
                    "branch": f"{speak['branch_name']} ({speak['branch_area']})",
                    "when": speak["when"],
                    "fee": speak["fee"],
                },
                "pms_sync": body.get("pms_sync"),
            },
            ensure_ascii=False,
        )
    if status == 409:
        detail = body.get("detail", {})
        state.persist_soon()
        return json.dumps(
            {
                "booked": False,
                "error": detail.get("code", "CONFLICT"),
                "message": detail.get("message"),
                "fresh_alternatives": _compact_slots(detail.get("alternatives", [])),
                "instruction": "Apologise briefly that the slot just went, then offer the fresh alternatives.",
            },
            ensure_ascii=False,
        )
    if status == 422:
        return json.dumps({"booked": False, "error": "VALIDATION", "detail": body.get("detail")})
    return json.dumps({"booked": False, "error": f"HTTP_{status}", "detail": body})


@clinic_tool
async def reschedule_appointment(
    ctx: RunContext,
    appointment_id: str,
    new_date: str,
    new_start_time: str,
    doctor_name: str | None = None,
    branch: str | None = None,
) -> str:
    """Move an existing appointment to a new slot (optionally a different
    doctor/branch). Get appointment_id from the caller context or
    find_my_appointments. Confirm the new slot with the caller first.

    Args:
        appointment_id: The id of the appointment being moved.
        new_date: YYYY-MM-DD new date.
        new_start_time: HH:MM 24h new start.
        doctor_name: Only if changing doctor.
        branch: Only if changing branch.
    """
    state = _state(ctx)
    catalog = state.context.get("catalog", {})
    payload: dict = {"date_local": new_date, "start_hm": new_start_time, "call_id": state.call_id}
    if doctor_name:
        practitioner = resolve_practitioner(catalog, doctor_name)
        if practitioner:
            payload["practitioner_id"] = practitioner["practitioner_id"]
    if branch:
        resolved = resolve_branch(catalog, branch)
        if resolved:
            payload["branch_id"] = resolved["branch_id"]

    status, body = await ClinicGateway.reschedule(appointment_id, payload)
    if status == 200:
        appointment = body["appointment"]
        fee = body.get("change_fee", {})
        state.completed = True
        state.disposition = "rescheduled"
        state.set_stage("rescheduled")
        state.note(appointment_id=appointment["appointment_id"])
        state.persist_soon()
        return json.dumps(
            {
                "rescheduled": True,
                "appointment_id": appointment["appointment_id"],
                "confirm_to_caller": {
                    "doctor": display_name(appointment["practitioner_name"]),
                    "branch": appointment["branch_name"],
                    "when": appointment["display"],
                },
                "change_fee": {
                    "applies": fee.get("applies", False),
                    "fee_inr": fee.get("fee_inr", 0),
                    "instruction": "Mention the fee ONLY if applies=true; otherwise do not bring it up.",
                },
            },
            ensure_ascii=False,
        )
    if status == 409:
        detail = body.get("detail", {})
        return json.dumps(
            {
                "rescheduled": False,
                "error": detail.get("code", "CONFLICT"),
                "message": detail.get("message"),
                "fresh_alternatives": _compact_slots(detail.get("alternatives", [])),
            },
            ensure_ascii=False,
        )
    return json.dumps({"rescheduled": False, "error": f"HTTP_{status}", "detail": body.get("detail", body)})


@clinic_tool
async def cancel_appointment(ctx: RunContext, appointment_id: str, reason: str | None = None) -> str:
    """Cancel an existing appointment after the caller confirms they want it
    cancelled.

    Args:
        appointment_id: The id of the appointment to cancel.
        reason: Caller's stated reason, if any.
    """
    state = _state(ctx)
    status, body = await ClinicGateway.cancel(appointment_id, {"reason": reason, "call_id": state.call_id})
    if status == 200:
        fee = body.get("change_fee", {})
        state.completed = True
        state.disposition = "cancelled"
        state.set_stage("cancelled")
        state.persist_soon()
        return json.dumps(
            {
                "cancelled": True,
                "was": body.get("was"),
                "change_fee": {
                    "applies": fee.get("applies", False),
                    "fee_inr": fee.get("fee_inr", 0),
                    "instruction": "Mention the fee ONLY if applies=true.",
                },
            },
            ensure_ascii=False,
        )
    return json.dumps({"cancelled": False, "error": f"HTTP_{status}", "detail": body.get("detail", body)})


@clinic_tool
async def find_my_appointments(ctx: RunContext, patient_phone: str | None = None) -> str:
    """Fetch the caller's upcoming appointments (also refreshes after changes).
    Use before rescheduling/cancelling if the context doesn't already show the
    appointment.

    Args:
        patient_phone: Only if asking about a different number than the caller's.
    """
    state = _state(ctx)
    phone = patient_phone or state.phone
    if not phone:
        return json.dumps({"appointments": [], "note": "No phone number known for this caller."})
    result = await ClinicGateway.get("/appointments", params={"phone": phone})
    appointments = [
        {
            "appointment_id": a["appointment_id"],
            "patient": a["patient_name"],
            "doctor": display_name(a["practitioner_name"]),
            "branch": a["branch_name"],
            "when": a.get("display"),
            "date": a["date_local"],
            "time": a["start_hm"],
        }
        for a in result.get("appointments", [])
    ]
    return json.dumps({"appointments": appointments}, ensure_ascii=False)
