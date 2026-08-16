"""Relative-date templating so scenarios stay green on any day they run.

Every scenario file says things like "{next_wednesday}" and the resolver
turns it into a real clinic-local date at run time. next_<weekday> is
strictly in the future (1..7 days out)."""

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def today_ist() -> date:
    return datetime.now(IST).date()


def resolve_token(token: str) -> str:
    if token.endswith("_speakable"):
        return speakable(resolve_token(token[: -len("_speakable")]))
    base = today_ist()
    if token == "today":
        return base.isoformat()
    if token == "tomorrow":
        return (base + timedelta(days=1)).isoformat()
    if token == "day_after":
        return (base + timedelta(days=2)).isoformat()
    match = re.fullmatch(r"next_(\w+)", token)
    if match and match.group(1) in WEEKDAYS:
        target = WEEKDAYS.index(match.group(1))
        days = (target - base.weekday()) % 7
        return (base + timedelta(days=days or 7)).isoformat()
    match = re.fullmatch(r"in_(\d+)_days", token)
    if match:
        return (base + timedelta(days=int(match.group(1)))).isoformat()
    raise ValueError(f"Unknown date token {{{token}}}")


TOKEN_RE = re.compile(r"\{([a-z_0-9]+)\}")


def resolve_dates(value):
    """Recursively resolve {tokens} in strings within dicts/lists."""
    if isinstance(value, str):
        def _sub(match):
            try:
                return resolve_token(match.group(1))
            except ValueError:
                return match.group(0)

        return TOKEN_RE.sub(_sub, value)
    if isinstance(value, dict):
        return {k: resolve_dates(v) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_dates(v) for v in value]
    return value


def speakable(date_iso: str) -> str:
    """'2026-08-19' -> 'Wednesday the 19th' — used inside scripted user turns
    so the *user* says natural dates, not ISO."""
    d = date.fromisoformat(date_iso)
    return d.strftime("%A %d %B").replace(" 0", " ")
