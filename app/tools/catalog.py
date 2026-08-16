"""Local name->id resolution over the clinic catalog loaded at call start.

The LLM speaks in names ("Dr. Meera", "Indiranagar"); the backend wants ids.
Resolution is deterministic string matching here — never an LLM guess.
"""

import re


def _norm(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"^dr\.?\s+", "", text)
    return re.sub(r"[^a-z0-9\s]", "", text)


def resolve_branch(catalog: dict, name_or_code: str | None) -> dict | None:
    if not name_or_code:
        return None
    needle = _norm(name_or_code)
    for branch in catalog.get("branches", []):
        haystacks = [
            _norm(branch["name"]),
            _norm(branch.get("area", "")),
            _norm(branch.get("code", "")),
        ]
        if any(needle in h or h in needle for h in haystacks if h):
            return branch
    return None


def resolve_practitioner(catalog: dict, name: str | None) -> dict | None:
    if not name:
        return None
    needle = _norm(name)
    best = None
    for practitioner in catalog.get("practitioners", []):
        hay = _norm(practitioner["full_name"])
        if needle == hay:
            return practitioner
        if needle in hay or all(part in hay for part in needle.split()):
            best = best or practitioner
    return best


def display_name(raw_name: str) -> str:
    """ALL-CAPS names must still be *spoken* naturally."""
    if raw_name.isupper():
        titled = raw_name.title()
        return re.sub(r"^Dr\.?\s", "Dr. ", titled)
    return raw_name
