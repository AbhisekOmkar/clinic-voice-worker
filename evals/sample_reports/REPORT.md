# Eval report

- run: `20260816_172641`  
- model: `gpt-4.1`  
- started: 2026-08-16T17:28:49.037333+00:00  

## Per-language summary

| language | scenarios | passed | success | avg turns→done | redundant Q/call | judge lang violations | script drift | LLM TTFT p50 (ms) | hindi quality |
|---|---|---|---|---|---|---|---|---|---|
| en | 8 | 8 | 1.0 | 2.4 | 0.0 | 0 | 0 | 969.4 | None |
| hi | 3 | 3 | 1.0 | 2.5 | 0.0 | 2 | 0 | 901.8 | 4.3 |
| mixed | 1 | 1 | 1.0 | 2 | 0.0 | 2 | 0 | 839.0 | 4 |

## Scenarios

| scenario | lang | passed | completed | turns→done | redundant | lang issues | notes |
|---|---|---|---|---|---|---|---|
| book_specific_date_around_time_en | en | ✅ | ✅ | 2 | 0 | 0 |  |
| book_weekday_preference_en | en | ✅ | ✅ | 2 | 0 | 0 |  |
| book_after_work_hi | hi | ✅ | ✅ | 2 | 0 | 0 |  |
| book_thursday_morning_mixed | mixed | ✅ | ✅ | 2 | 0 | 2 |  |
| earliest_cross_branch_en | en | ✅ | ✅ | 2 | 0 | 0 |  |
| returning_patient_en | en | ✅ | ✅ | 2 | 0 | 0 |  |
| family_line_hi | hi | ✅ | ✅ | 3 | 0 | 0 |  |
| dropped_call_resume_en | en | ✅ | ✅ | 2 | 0 | 0 |  |
| callback_recognition_en | en | ✅ | ✅ | 3 | 0 | 0 |  |
| stale_availability_recheck_en | en | ✅ | ✅ | 3 | 0 | 0 |  |
| slot_taken_race_en | en | ✅ | ✅ | 3 | 0 | 0 |  |
| human_handoff_hi | hi | ✅ | — | — | 0 | 2 |  |

## Where this harness gives false confidence

- **Text mode skips the ears and mouth.** These runs exercise prompt, LLM, tools,
  backend and database — but not STT mishearings, TTS pronunciation, barge-in or
  endpointing. A perfect score here can still stutter on a real call. Component
  latency probes and live-call metrics (call_latency_metrics) cover that gap
  partially; only live calls close it.
- **Scripted callers are cooperative.** Turns provide information the way the
  script author expected. Real callers ramble, self-correct and talk over the
  agent; turns-to-completion here is a lower bound.
- **LLM judges share DNA with the agent.** The judge model can be blind to the
  same Hindi awkwardness the agent produces. Deterministic script-drift counts
  are reported alongside for that reason; treat judge zeros as "nothing obvious",
  not "perfect".
- **One run is one sample.** LLMs are stochastic; a pass at temperature 0.3 is
  not a guarantee. Re-run with --repeat for stability checks before drawing
  conclusions from a single green table.
- **Latency numbers in this report are LLM TTFT only.** End-to-end voice latency
  adds EOU detection, STT finalisation, TTS TTFB and network — see the latency
  probe report and per-call metrics for those components.
