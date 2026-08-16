import json

from livekit.agents import RunContext

from app.gateway.clinic import ClinicGateway
from app.tools.utils import clinic_tool


@clinic_tool
async def log_followup(
    ctx: RunContext,
    category: str,
    details: str,
    patient_name: str | None = None,
) -> str:
    """Log an issue for human staff to call back about. Use when the caller
    insists on a human, raises a clinical/medical concern, has a billing
    dispute, or asks for anything outside appointment booking. NEVER claim a
    live transfer is happening — promise a callback instead.

    Args:
        category: One of "human_request", "clinical_concern", "billing", "other".
        details: One or two sentences describing exactly what staff should handle, in English.
        patient_name: The caller's name if known.
    """
    state = ctx.userdata
    normalized = category.strip().lower().replace(" ", "_")
    if normalized not in ("human_request", "clinical_concern", "billing", "other"):
        normalized = "other"
    status, body = await ClinicGateway.create_followup(
        {
            "call_id": state.call_id,
            "phone": state.phone,
            "patient_name": patient_name or state.collected.get("patient_name"),
            "category": normalized,
            "details": details,
            "language": state.language,
        }
    )
    state.note(followup_logged=True)
    state.persist_soon()
    if status == 200:
        return json.dumps(
            {
                "logged": True,
                "tell_caller": "A staff member will call back on this number, typically within working hours today.",
            }
        )
    return json.dumps({"logged": False, "error": body})
