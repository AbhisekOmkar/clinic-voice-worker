from app.tools.booking import (
    book_appointment,
    cancel_appointment,
    find_my_appointments,
    get_availability,
    reschedule_appointment,
)
from app.tools.end_call import end_call
from app.tools.escalation import log_followup

ALL_TOOLS = [
    get_availability,
    book_appointment,
    reschedule_appointment,
    cancel_appointment,
    find_my_appointments,
    log_followup,
    end_call,
]

__all__ = [
    "ALL_TOOLS",
    "book_appointment",
    "cancel_appointment",
    "end_call",
    "find_my_appointments",
    "get_availability",
    "log_followup",
    "reschedule_appointment",
]
