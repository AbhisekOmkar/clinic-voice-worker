"""Per-turn latency collection from LiveKit AgentSession metrics events.

Captured per conversational turn and tagged with the language of the user
turn that triggered it, so the eval harness can report EN vs HI separately:
- eou_delay_ms   — end of user speech -> turn committed (VAD + turn detector)
- llm_ttft_ms    — LLM time-to-first-token
- tts_ttfb_ms    — TTS time-to-first-audio-byte
- e2e_ms         — eou + ttft + ttfb (+ network inside each)
- stt_final_ms   — STT finalisation delay when the provider reports it
"""

import statistics
from dataclasses import dataclass, field

from loguru import logger


@dataclass
class TurnLatency:
    turn_index: int
    language: str = "en"
    eou_delay_ms: float | None = None
    stt_final_ms: float | None = None
    llm_ttft_ms: float | None = None
    tts_ttfb_ms: float | None = None

    @property
    def e2e_ms(self) -> float | None:
        parts = [self.eou_delay_ms, self.llm_ttft_ms, self.tts_ttfb_ms]
        known = [p for p in parts if p is not None]
        return round(sum(known), 1) if len(known) == 3 else None


@dataclass
class LatencyCollector:
    turns: list[TurnLatency] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    _current: TurnLatency | None = None

    def _turn(self) -> TurnLatency:
        if self._current is None:
            self._current = TurnLatency(turn_index=len(self.turns))
        return self._current

    def on_metrics(self, metric_obj, language: str) -> None:
        name = type(metric_obj).__name__
        try:
            if "EOU" in name:
                self._turn().eou_delay_ms = round(
                    float(getattr(metric_obj, "end_of_utterance_delay", 0)) * 1000, 1
                )
                self._turn().language = language
                transcription_delay = getattr(metric_obj, "transcription_delay", None)
                if transcription_delay is not None:
                    self._turn().stt_final_ms = round(float(transcription_delay) * 1000, 1)
            elif "LLM" in name:
                ttft = getattr(metric_obj, "ttft", None)
                if ttft is not None and ttft >= 0:
                    self._turn().llm_ttft_ms = round(float(ttft) * 1000, 1)
                self._accumulate_usage(
                    "llm",
                    prompt_tokens=getattr(metric_obj, "prompt_tokens", 0),
                    completion_tokens=getattr(metric_obj, "completion_tokens", 0),
                )
            elif "TTS" in name:
                ttfb = getattr(metric_obj, "ttfb", None)
                if ttfb is not None and ttfb >= 0:
                    turn = self._turn()
                    if turn.tts_ttfb_ms is None:  # first synthesis of the turn
                        turn.tts_ttfb_ms = round(float(ttfb) * 1000, 1)
                self._accumulate_usage(
                    "tts", characters=getattr(metric_obj, "characters_count", 0)
                )
                self._commit()
            elif "STT" in name:
                self._accumulate_usage("stt", audio_seconds=getattr(metric_obj, "audio_duration", 0))
        except Exception as exc:
            logger.debug(f"metrics parse skipped ({name}): {exc}")

    def _commit(self) -> None:
        if self._current is not None:
            self.turns.append(self._current)
            self._current = None

    def _accumulate_usage(self, kind: str, **values) -> None:
        bucket = self.usage.setdefault(kind, {})
        for key, value in values.items():
            try:
                bucket[key] = round(bucket.get(key, 0) + float(value or 0), 3)
            except (TypeError, ValueError):
                pass

    def aggregates(self) -> dict:
        self._commit()
        result: dict = {"turn_count": len(self.turns)}
        for lang_filter, label in ((None, "all"), ("en", "en"), ("hi", "hi"), ("mixed", "mixed")):
            rows = [
                t for t in self.turns if lang_filter is None or t.language == lang_filter
            ]
            if not rows:
                continue
            bucket: dict = {"turns": len(rows)}
            for field_name in ("eou_delay_ms", "llm_ttft_ms", "tts_ttfb_ms", "e2e_ms"):
                values = [
                    getattr(t, field_name)
                    for t in rows
                    if getattr(t, field_name) is not None
                ]
                if values:
                    bucket[field_name] = {
                        "p50": round(statistics.median(values), 1),
                        "max": round(max(values), 1),
                        "n": len(values),
                    }
            result[label] = bucket
        return result

    def payload(self) -> dict:
        aggregates = self.aggregates()
        return {
            "turns": [
                {
                    "turn_index": t.turn_index,
                    "language": t.language,
                    "eou_delay_ms": t.eou_delay_ms,
                    "stt_final_ms": t.stt_final_ms,
                    "llm_ttft_ms": t.llm_ttft_ms,
                    "tts_ttfb_ms": t.tts_ttfb_ms,
                    "e2e_ms": t.e2e_ms,
                }
                for t in self.turns
            ],
            "aggregates": aggregates,
            "providers": self.usage,
        }
