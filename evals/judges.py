"""LLM judges for qualities that deterministic checks can't grade.

Design (borrowed from a production backtesting harness):
- judges classify with a rubric, at temperature 0.1, strict JSON out;
- a judge failure returns None scores (skip semantics) — never a fake 0;
- deterministic script-based language checks run alongside and the report
  shows both, because judges can be wrong too.
"""

import json

from loguru import logger
from openai import AsyncOpenAI

from app.config.settings import settings

JUDGE_MODEL = "gpt-4.1"

_client: AsyncOpenAI | None = None


def client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


async def _judge(system: str, user: str) -> dict | None:
    try:
        response = await client().chat.completions.create(
            model=JUDGE_MODEL,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return json.loads(response.choices[0].message.content)
    except Exception as exc:
        logger.warning(f"judge failed (skipping, not zeroing): {exc}")
        return None


def _format_transcript(transcript: list[dict]) -> str:
    lines = []
    for i, turn in enumerate(transcript):
        lines.append(f"[{i}] {turn['role'].upper()}: {turn['text']}")
    return "\n".join(lines)


REDUNDANT_SYSTEM = """You audit a clinic phone agent's transcript for REDUNDANT QUESTIONS — the agent asking for information the caller already provided in this call, or that the agent was told it already knows (listed as known-context).

Count ONLY true re-asks:
- asking again for a name/date/doctor/branch/time the caller already gave;
- asking for something explicitly present in known-context.
Do NOT count:
- a single confirmation restating details before booking ("So that's Wednesday 5:30 with Dr. Meera?");
- asking to disambiguate between several patients on a family line (that is required behaviour);
- asking for a FULL name when only a first name was given.

Return JSON: {"redundant_questions": [{"turn": <agent turn index>, "asked_for": "...", "already_known_from": "..."}]}
Empty list if none."""


async def judge_redundant(transcript: list[dict], known_context: str) -> dict | None:
    return await _judge(
        REDUNDANT_SYSTEM,
        f"Known-context at call start:\n{known_context or '(none)'}\n\nTranscript:\n{_format_transcript(transcript)}",
    )


LANGUAGE_SYSTEM = """You audit a bilingual (English/Hindi) clinic phone agent for LANGUAGE DISCIPLINE.

Rules the agent must follow:
1. Reply in the caller's language each turn. Pure-English caller turn -> pure-English reply (clinic names, doctor names, times are fine). Pure-Hindi caller turn -> Hindi reply (doctor names/brand fine; stray unnecessary English sentences are a violation).
2. If the caller code-switches (Hinglish), a natural Hinglish reply is CORRECT, and should sound like one fluent speaker, not two stitched languages.
3. Hindi must be natural, respectful (आप), grammatical; word-by-word translations from English are violations.

Return JSON:
{"violations": [{"turn": <agent turn index>, "type": "drift_to_other_language"|"unnatural_mix"|"bad_hindi", "note": "..."}],
 "hindi_quality": <1-5 or null if no Hindi in call>,
 "code_switch_naturalness": <1-5 or null if no code-switching>}"""


async def judge_language(transcript: list[dict]) -> dict | None:
    return await _judge(LANGUAGE_SYSTEM, f"Transcript:\n{_format_transcript(transcript)}")


def deterministic_language_check(transcript: list[dict]) -> list[dict]:
    """Script-level drift detection: agent turn script vs preceding user turn.
    Catches the blunt failures (Devanagari in an English conversation and
    vice versa); the judge handles nuance like romanised Hindi."""
    violations = []
    previous_user_lang = None
    for i, turn in enumerate(transcript):
        if turn["role"] == "user":
            previous_user_lang = turn.get("lang")
        elif turn["role"] == "agent" and previous_user_lang in ("en", "hi"):
            agent_lang = turn.get("lang")
            if previous_user_lang == "en" and agent_lang == "hi":
                violations.append({"turn": i, "type": "script_drift", "note": "Hindi reply to pure-English turn"})
            if previous_user_lang == "hi" and agent_lang == "en":
                violations.append({"turn": i, "type": "script_drift", "note": "English reply to pure-Hindi turn"})
    return violations
