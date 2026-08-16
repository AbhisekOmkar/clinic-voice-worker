from app.prompts.system import build_context_block, build_system_prompt, opening_line
from app.state.session_state import CallState


def make_state(**context) -> CallState:
    state = CallState(call_id="c1", phone="+919812345678")
    state.context = {
        "now_local": "2026-08-16T22:00:00+05:30",
        "today_local": "2026-08-16",
        "known_patients": [],
        "upcoming_appointments": [],
        "resumable_session": None,
        "pending_callback": None,
        "catalog": {"branches": [], "practitioners": []},
        **context,
    }
    return state


def test_new_caller_context():
    block = build_context_block(make_state())
    assert "new caller" in block
    assert "2026-08-16" in block


def test_returning_patient_greeting():
    state = make_state(known_patients=[{"patient_id": "p1", "full_name": "Rakesh Gupta"}])
    assert "returning patient" in build_context_block(state)
    assert "Rakesh" in opening_line(state)


def test_family_line_flags_disambiguation():
    state = make_state(
        known_patients=[
            {"patient_id": "p1", "full_name": "Rakesh Gupta"},
            {"patient_id": "p2", "full_name": "Meena Gupta"},
        ]
    )
    block = build_context_block(state)
    assert "FAMILY LINE" in block
    assert "Rakesh Gupta" in block and "Meena Gupta" in block


def test_dropped_call_resume_in_hindi_opens_in_hindi():
    state = make_state(
        resumable_session={
            "stage": "choosing_slot",
            "language": "hi",
            "summary": "patient=Rakesh, doctor=Dr. Meera, discussing_slot=2026-08-19 17:30",
            "collected": {},
            "updated_at": "2026-08-16T21:58:00",
        }
    )
    assert "DROPPED CALL TO RESUME" in build_context_block(state)
    line = opening_line(state)
    assert "कट" in line  # opens in Hindi acknowledging the drop


def test_callback_context_opens_with_purpose():
    state = make_state(
        pending_callback={
            "outbound_id": "o1",
            "purpose": "Confirm tomorrow's dermatology appointment",
            "context": {},
        }
    )
    assert "CALLBACK" in build_context_block(state)
    assert "calling back" in opening_line(state)


def test_allcaps_doctor_rendered_naturally_in_roster():
    state = make_state(
        catalog={
            "branches": [],
            "practitioners": [
                {
                    "practitioner_id": "dr-meera-shridhar",
                    "full_name": "DR. MEERA SHRIDHAR",
                    "specialty": "Dermatology",
                    "fee_inr": 800,
                    "weekly_schedule": [{"branch_id": "br-indiranagar"}],
                }
            ],
        }
    )
    prompt = build_system_prompt(state)
    assert "Dr. Meera Shridhar" in prompt  # roster shows the speakable form
    assert "never spell out letters" in prompt.lower() or "never spell" in prompt
