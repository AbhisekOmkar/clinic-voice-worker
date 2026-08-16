"""Scenario runner: drives the REAL agent (real LLM, real tools, real backend,
real database) through scripted multi-turn conversations in text mode.

What's real: prompt, LLM, tool schema/loop, backend correctness (bookings,
conflicts, PMS), session-state persistence.
What's bypassed: audio (STT/TTS/VAD/turn detection) — measured separately by
latency_probe.py and by live-call metrics. That gap is stated in the report.
"""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field

import yaml
from loguru import logger

from app.metrics.latency import LatencyCollector
from app.prompts.system import build_system_prompt, opening_line
from app.state.language import tag_language
from app.state.session_state import CallState
from app.tools import ALL_TOOLS
from evals.dates import resolve_dates
from evals.judges import (
    deterministic_language_check,
    judge_language,
    judge_redundant,
)
from evals.seeding import Backend


@dataclass
class ScenarioResult:
    scenario_id: str
    language: str
    category: str
    passed: bool = False
    completed: bool = False
    disposition: str | None = None
    turns_total: int = 0
    turns_to_completion: int | None = None
    tool_calls: list[dict] = field(default_factory=list)
    tool_expectation_failures: list[str] = field(default_factory=list)
    db_assertion_failures: list[str] = field(default_factory=list)
    redundant_questions: list[dict] | None = None
    language_violations: list[dict] | None = None
    script_language_violations: list[dict] = field(default_factory=list)
    hindi_quality: float | None = None
    code_switch_naturalness: float | None = None
    llm_ttft_ms: list[float] = field(default_factory=list)
    turn_wall_ms: list[float] = field(default_factory=list)
    transcript: list[dict] = field(default_factory=list)
    error: str | None = None


def load_scenario(path: str) -> dict:
    with open(path) as f:
        scenario = yaml.safe_load(f)
    return resolve_dates(scenario)


class ScenarioRunner:
    def __init__(self, backend: Backend):
        self.backend = backend

    async def run(self, scenario: dict) -> ScenarioResult:
        result = ScenarioResult(
            scenario_id=scenario["id"],
            language=scenario.get("language", "en"),
            category=scenario.get("category", "general"),
        )
        try:
            await self._run_inner(scenario, result)
        except Exception as exc:
            logger.opt(exception=True).error(f"scenario {scenario['id']} crashed")
            result.error = str(exc)[:500]
        return result

    async def _run_inner(self, scenario: dict, result: ScenarioResult) -> None:
        from livekit.agents import Agent, AgentSession
        from livekit.plugins import openai as lk_openai

        from app.config.settings import settings

        phone = scenario["caller"]["phone"]
        await self.backend.reset()
        artifacts = await self.backend.apply_seed(scenario.get("seed", {}), phone)

        call_id = f"eval-{scenario['id']}-{uuid.uuid4().hex[:6]}"
        state = CallState(call_id=call_id, phone=phone, direction="inbound")
        context = await self.backend.call_context(phone)
        context["catalog"] = await self.backend.catalog()
        state.context = context
        if context.get("resumable_session"):
            state.collected.update(context["resumable_session"].get("collected", {}))
            if context["resumable_session"].get("language"):
                state.language = context["resumable_session"]["language"]

        latency = LatencyCollector()
        last_offered_slots: list[dict] = []

        llm = lk_openai.LLM(
            model=settings.llm_model, api_key=settings.openai_api_key, temperature=0.3,
            parallel_tool_calls=False,
        )
        session = AgentSession(llm=llm, userdata=state)

        @session.on("metrics_collected")
        def _on_metrics(event):
            latency.on_metrics(getattr(event, "metrics", event), state.language)

        agent = Agent(instructions=build_system_prompt(state), tools=ALL_TOOLS)
        await session.start(agent)
        opening = opening_line(state)
        state.add_turn("agent", opening)
        result.transcript.append({"role": "agent", "text": opening, "lang": tag_language(opening)})

        try:
            for turn_index, turn in enumerate(scenario.get("turns", [])):
                user_text = turn["user"]
                state.add_turn("user", user_text)
                result.transcript.append(
                    {"role": "user", "text": user_text, "lang": tag_language(user_text)}
                )
                turn_tools: list[dict] = []
                started = time.perf_counter()
                run_result = await session.run(user_input=user_text)
                result.turn_wall_ms.append(round((time.perf_counter() - started) * 1000, 1))

                offered = self._consume_events(run_result, result, turn_tools, state)
                if offered:
                    last_offered_slots = offered

                self._check_turn_tools(turn, turn_tools, result, turn_index)

                if result.turns_to_completion is None and state.completed:
                    result.turns_to_completion = turn_index + 1

                action = turn.get("action_after")
                if action == "steal_first_offered_slot":
                    if last_offered_slots:
                        await self.backend.book_out_of_band(last_offered_slots[0])
                        logger.info(
                            f"[{scenario['id']}] stole offered slot "
                            f"{last_offered_slots[0]['date']} {last_offered_slots[0]['time']}"
                        )
                    else:
                        result.tool_expectation_failures.append(
                            "action steal_first_offered_slot: no slots were offered to steal"
                        )
        finally:
            await session.aclose()

        result.turns_total = len(scenario.get("turns", []))
        result.completed = state.completed
        result.disposition = state.disposition
        for turn_latency in latency.turns + ([latency._current] if latency._current else []):
            if turn_latency and turn_latency.llm_ttft_ms is not None:
                result.llm_ttft_ms.append(turn_latency.llm_ttft_ms)

        await self._check_expectations(scenario.get("expect", {}), state, result, artifacts)
        await self._run_judges(scenario, state, result)

        result.passed = (
            not result.error
            and not result.tool_expectation_failures
            and not result.db_assertion_failures
        )

    def _consume_events(self, run_result, result: ScenarioResult, turn_tools: list, state) -> list[dict]:
        offered: list[dict] = []
        for event in run_result.events:
            kind = type(event).__name__
            item = getattr(event, "item", None)
            if kind == "ChatMessageEvent" and getattr(item, "role", None) == "assistant":
                text = getattr(item, "text_content", "") or ""
                if text:
                    state.add_turn("agent", text)
                    result.transcript.append(
                        {"role": "agent", "text": text, "lang": tag_language(text)}
                    )
            elif kind == "FunctionCallEvent":
                arguments = getattr(item, "arguments", "{}")
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {"_raw": arguments}
                call = {"name": getattr(item, "name", "?"), "args": arguments}
                turn_tools.append(call)
                result.tool_calls.append(call)
            elif kind == "FunctionCallOutputEvent":
                output = getattr(item, "output", "")
                try:
                    parsed = json.loads(output) if isinstance(output, str) else output
                    if isinstance(parsed, dict) and parsed.get("slots"):
                        offered = parsed["slots"]
                except (json.JSONDecodeError, TypeError):
                    pass
        return offered

    def _check_turn_tools(self, turn: dict, turn_tools: list, result: ScenarioResult, turn_index: int) -> None:
        for expectation in turn.get("expect_tools", []) or []:
            name = expectation["name"]
            wanted_args = expectation.get("args_contains", {})
            matched = False
            for call in turn_tools:
                if call["name"] != name:
                    continue
                if all(self._arg_matches(call["args"].get(k), v) for k, v in wanted_args.items()):
                    matched = True
                    break
            if not matched:
                result.tool_expectation_failures.append(
                    f"turn {turn_index}: expected {name} with {wanted_args}, saw {turn_tools}"
                )

    @staticmethod
    def _arg_matches(actual, wanted) -> bool:
        if isinstance(wanted, bool) or isinstance(actual, bool):
            return bool(actual) == bool(wanted)
        if actual is None:
            return False
        return str(wanted).lower() in str(actual).lower()

    async def _check_expectations(self, expect: dict, state: CallState, result: ScenarioResult, artifacts: dict) -> None:
        if expect.get("completed") is True and not state.completed:
            result.db_assertion_failures.append("expected completion but call did not complete")
        if expect.get("disposition") and state.disposition != expect["disposition"]:
            result.db_assertion_failures.append(
                f"disposition: expected {expect['disposition']}, got {state.disposition}"
            )
        max_turns = expect.get("max_turns_to_completion")
        if max_turns and (result.turns_to_completion or 999) > max_turns:
            result.db_assertion_failures.append(
                f"took {result.turns_to_completion} turns; budget {max_turns}"
            )

        booking = expect.get("booking")
        if booking:
            appointments = await self.backend.appointments_for_phone(
                booking.get("phone", state.phone)
            )
            exclude = {a["appointment_id"] for a in artifacts.get("appointments", [])}
            fresh = [a for a in appointments if a["appointment_id"] not in exclude]
            match = None
            for appointment in fresh:
                ok = True
                for key, wanted in booking.items():
                    if key in ("phone",):
                        continue
                    actual = appointment.get({"date": "date_local"}.get(key, key))
                    if key == "patient_name":
                        ok = ok and str(wanted).lower() == str(actual).lower()
                    else:
                        ok = ok and str(wanted).lower() == str(actual).lower()
                if ok:
                    match = appointment
                    break
            if match is None:
                summary = [
                    {k: a.get(k) for k in ("patient_name", "practitioner_id", "branch_id", "date_local", "start_hm")}
                    for a in fresh
                ]
                result.db_assertion_failures.append(
                    f"no booking matching {booking}; fresh bookings: {summary}"
                )
        if expect.get("no_booking"):
            appointments = await self.backend.appointments_for_phone(state.phone)
            exclude = {a["appointment_id"] for a in artifacts.get("appointments", [])}
            if [a for a in appointments if a["appointment_id"] not in exclude]:
                result.db_assertion_failures.append("expected NO new booking but one exists")

        followup = expect.get("followup")
        if followup:
            wanted = followup.get("category")
            wanted_list = wanted if isinstance(wanted, list) else [wanted]
            followups = await self.backend.followups()
            if not any(f.get("category") in wanted_list for f in followups):
                result.db_assertion_failures.append(
                    f"expected followup with category in {wanted_list}; got {[f.get('category') for f in followups]}"
                )

        stolen = expect.get("booked_differs_from_stolen")
        if stolen:
            appointments = await self.backend.appointments_for_phone(state.phone)
            exclude = {a["appointment_id"] for a in artifacts.get("appointments", [])}
            fresh = [a for a in appointments if a["appointment_id"] not in exclude]
            if not fresh:
                result.db_assertion_failures.append("slot-race: no final booking exists")

    async def _run_judges(self, scenario: dict, state: CallState, result: ScenarioResult) -> None:
        judges = scenario.get("judges", []) or []
        result.script_language_violations = deterministic_language_check(result.transcript)
        known_context = self._known_context_summary(state)
        tasks = {}
        if "redundant" in judges:
            tasks["redundant"] = judge_redundant(result.transcript, known_context)
        if "language" in judges:
            tasks["language"] = judge_language(result.transcript)
        if tasks:
            outputs = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for key, output in zip(tasks.keys(), outputs):
                if isinstance(output, Exception) or output is None:
                    continue
                if key == "redundant":
                    result.redundant_questions = output.get("redundant_questions", [])
                elif key == "language":
                    result.language_violations = output.get("violations", [])
                    result.hindi_quality = output.get("hindi_quality")
                    result.code_switch_naturalness = output.get("code_switch_naturalness")

    @staticmethod
    def _known_context_summary(state: CallState) -> str:
        ctx = state.context or {}
        lines = []
        for patient in ctx.get("known_patients", []):
            lines.append(f"- known patient on this number: {patient['full_name']}")
        if ctx.get("resumable_session"):
            lines.append(f"- resumed dropped call with facts: {ctx['resumable_session'].get('summary')}")
        if ctx.get("pending_callback"):
            lines.append(f"- pending callback purpose: {ctx['pending_callback'].get('purpose')}")
        for appointment in ctx.get("upcoming_appointments", []):
            lines.append(
                f"- upcoming appointment: {appointment['patient_name']} with {appointment['practitioner_name']} {appointment['display']}"
            )
        return "\n".join(lines)
