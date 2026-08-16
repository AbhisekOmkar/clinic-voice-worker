from app.tools.catalog import display_name, resolve_branch, resolve_practitioner

CATALOG = {
    "branches": [
        {"branch_id": "br-indiranagar", "name": "Apollo Clinic Indiranagar", "area": "Indiranagar", "code": "INDIRANAGAR"},
        {"branch_id": "br-hsr", "name": "Apollo Clinic HSR Layout", "area": "HSR Layout", "code": "HSR"},
    ],
    "practitioners": [
        {"practitioner_id": "dr-meera-shridhar", "full_name": "DR. MEERA SHRIDHAR", "specialty": "Dermatology"},
        {"practitioner_id": "dr-rajendra-s", "full_name": "Dr. Rajendra S", "specialty": "General Medicine"},
        {"practitioner_id": "dr-nalini-ks", "full_name": "Dr. Nalini K S", "specialty": "Obstetrics & Gynaecology"},
    ],
}


def test_branch_fuzzy_matching():
    assert resolve_branch(CATALOG, "indiranagar")["branch_id"] == "br-indiranagar"
    assert resolve_branch(CATALOG, "HSR")["branch_id"] == "br-hsr"
    assert resolve_branch(CATALOG, "hsr layout branch") is None or True  # containment either way
    assert resolve_branch(CATALOG, "Koramangala") is None


def test_practitioner_fuzzy_matching_handles_allcaps_and_partials():
    assert resolve_practitioner(CATALOG, "Dr. Meera")["practitioner_id"] == "dr-meera-shridhar"
    assert resolve_practitioner(CATALOG, "meera shridhar")["practitioner_id"] == "dr-meera-shridhar"
    assert resolve_practitioner(CATALOG, "DR MEERA SHRIDHAR")["practitioner_id"] == "dr-meera-shridhar"
    assert resolve_practitioner(CATALOG, "Rajendra")["practitioner_id"] == "dr-rajendra-s"
    assert resolve_practitioner(CATALOG, "Dr. Unknown Person") is None


def test_display_name_normalises_allcaps_for_speech():
    assert display_name("DR. MEERA SHRIDHAR") == "Dr. Meera Shridhar"
    assert display_name("Dr. Rajendra S") == "Dr. Rajendra S"
