# Asha — bilingual voice AI receptionist for Apollo Clinic, Bengaluru

A production-shaped voice AI receptionist for a **real clinic with two real branches** — Apollo Clinic **Indiranagar** and **HSR Layout**, Bengaluru — that books, reschedules and cancels appointments over the phone in **English, Hindi, and mid-sentence Hinglish**, against a live scheduling backend with write-time double-booking enforcement and a mock PMS write-back.

This is the main write-up. The system is three repos, mirroring a control-plane/worker/console split:

| Repo | What it is |
|---|---|
| **clinic-voice-worker** (this repo) | LiveKit Agents worker: the voice pipeline, tools, prompt, session state, **eval harness** |
| [clinic-platform-backend](https://github.com/AbhisekOmkar/clinic-platform-backend) | FastAPI + MongoDB: slot engine, booking guards, patients, call state, **mock PMS**, LiveKit dispatch |
| [clinic-voice-dashboard](https://github.com/AbhisekOmkar/clinic-voice-dashboard) | Next.js console: calls + transcripts + latency, appointments/PMS state, **browser web-call tester** |

---

## Why LiveKit (stack justification)

I picked **LiveKit Agents** over Retell/Bolna/Vapi for reasons specific to *this* clinic brief, not convenience:

1. **The assignment's failure modes are state problems, not prompt problems.** Dropped-call resume, missed-outbound callback recognition, family-line disambiguation and stale-availability re-checks all need per-turn server-side state and a call-start context fetch that I control. In my own worker that's ~200 lines ([app/state/session_state.py](app/state/session_state.py), backend `/agent/call-context`); on a managed platform it's webhook contortions against someone else's session model.
2. **Per-component latency visibility is a hard requirement.** The brief asks for latency broken down by ASR/LLM/TTS. LiveKit's pipeline emits `EOUMetrics / LLMMetrics.ttft / TTSMetrics.ttfb` per turn, which I persist per call and split per language. Managed platforms report one blended number at best.
3. **Multilingual quality is a per-component choice.** EN+HI code-switching lives or dies on the exact ASR/TTS models: Deepgram **nova-3 `language=multi`** (streaming code-switch ASR), **Cartesia sonic-3** with a native **Hinglish voice** ("Arushi"), and **gpt-4.1** which needs no translation layer. LiveKit lets me pin exactly these and swap any one via env (`STT_PROVIDER`, `LLM_PROVIDER`) without re-platforming.
4. **Telephony neutrality.** LiveKit SIP accepts any trunk (Twilio/Telnyx/Plivo — relevant for India deployments where trunk choice is constrained). One script attaches a number: [`scripts/setup_sip_inbound.py`](https://github.com/AbhisekOmkar/clinic-platform-backend/blob/main/scripts/setup_sip_inbound.py). The browser web-call tester uses the *identical* room/agent path, so the agent is independently callable even before a PSTN number is attached.
5. **Latency/cost structure.** The worker runs in-region (LiveKit Cloud **India South**), turn-taking knobs are mine (endpointing delays, multilingual turn-detector model, interruption handling, BVC noise cancellation), and I pay raw provider rates with no platform margin.

**The honest trade-off:** LiveKit means owning worker code, dispatch and observability myself — that's exactly what the other two repos are. Retell would have demoed faster; it would not have survived the "why is Hindi EOU slow" question.

---

## What it does (mapped to the required scenarios)

| Requirement | Mechanism | Proven by |
|---|---|---|
| "Dec 13 around 1", "Mondays and Wednesdays", "after 4:30", "any Thursday morning" | LLM extracts →`get_availability(date_from/weekdays/after_time/near_time)`; **all slot math is server-side** (grid, buffers, IST) | evals 01–04 |
| Returning patient, no context | `/agent/call-context` on call start → known patients injected into prompt; greet by name, never re-verify | eval 06 |
| Missed outbound call → callback | Unanswered outbound calls recorded; caller-id match within 48 h → agent opens with the original purpose | eval 09 |
| Stale availability | Prompt discipline ("cached availability is stale availability") **plus** server-side re-validation at booking time — even if the LLM skips the re-check, the write is guarded | eval 10 |
| Earliest slot across branches/practitioners | `earliest=true` searches **all** practitioners at **both** branches server-side, sorted purely by time — the LLM never does slot math | eval 05 (Indiranagar filled → HSR surfaced) |
| Branch-specific triage | Deterministic name→id resolution + specialty/branch filters; consistent by construction | eval + backend tests |
| Dropped call recovery | Session state persisted **every turn**; next call from that number inside 30 min gets stage + collected facts + candidate slot; agent acknowledges the drop and resumes | eval 08 (booked in 2 turns) |
| Slot taken between offer and confirm | Partial **unique index** rejects the write → 409 with *fresh* alternatives → agent apologises and re-offers | eval 11 (harness steals the offered slot mid-call) |
| Family line (shared number) | Phone→patients is one-to-many; 2+ matches → prompt forces "who is this for?" before assuming | eval 07 |
| Full name before booking | Backend hard-rejects nameless bookings (422) — belt and braces with the prompt rule | backend test |
| Fees only in policy window | ₹250 applies only within 4 h of the slot; tool result carries `applies` and the prompt forbids mentioning it otherwise | backend test + eval transcripts |
| Bot/human honesty + handoff | Honest disclosure; `log_followup` records human-request/clinical/billing issues; **never** claims a live transfer | eval 12 |
| ALL-CAPS names spoken naturally | Data stores `DR. MEERA SHRIDHAR` (deliberately); display-name normalisation + prompt rule | eval transcripts |
| Correct local "today" | Every date computed in Asia/Kolkata; context injects IST now/today; tools take explicit dates only | backend TZ test |

---

## Latency — measured, not estimated

**Live call on LiveKit Cloud** (this machine → India South, OpenAI-STT fallback path, real booking made):

| Stage | p50 |
|---|---|
| End-of-utterance detection (VAD + multilingual turn detector + STT finalisation) | **1 055 ms** |
| LLM TTFT (gpt-4.1, full prompt + tools) | **911 ms** |
| TTS TTFB (Cartesia sonic-3) | **214 ms** |
| **End-to-end voice response** | **≈ 2 216 ms** |

**Component probes** (`make eval-latency`, 5 utterances per language):

| Component | EN p50 | HI p50 | Note |
|---|---|---|---|
| LLM TTFT (gpt-4.1) | 748 ms | 670 ms | streamed, real prompt size |
| TTS TTFB (sonic-3, Arushi) | 157 ms | 137 ms | Hindi is *not* slower |
| STT one-shot (gpt-4o-transcribe) | 1 016 ms | 909 ms | wall-clock, not streaming; content-match 0.73 EN / 0.98 HI |

**How the build reflects latency reasoning:** availability/booking math is a single backend round-trip on localhost (~5 ms) rather than LLM iteration; `parallel_tool_calls` disabled (voice wants one fast decision); tool JSON kept compact; holding phrases auto-play if a tool exceeds 1.2 s so silence is never exposed; endpointing 0.4 s min with the multilingual turn-detector model; interruptions enabled; BVC noise cancellation on.

**Known gap:** the provided Deepgram key was invalid (401), so live calls currently run the OpenAI STT fallback — most of that 1 055 ms EOU is STT finalisation. Dropping in a valid key switches to nova-3 `language=multi` **streaming** (~300 ms finalisation), which projects E2E to ≈ 1.4–1.6 s. The provider switch is one env var.

---

## Multilingual approach (no translation tables anywhere)

- **One prompt, one policy** — no per-language forks. The prompt states the mirroring policy (pure EN → pure EN, pure HI → pure HI with respectful आप + feminine first person, Hinglish → natural Hinglish) and requires Hindi dates/numbers spoken in Hindi.
- **ASR** is natively code-switching (nova-3 `multi`, fallback gpt-4o-transcribe) — a Hindi sentence never passes through English.
- **TTS** is a single bilingual voice (Cartesia "Arushi", built for Hinglish), so the agent's own code-switches don't sound like two stitched engines.
- **Script tagging** (Devanagari-ratio per turn) is used **only** for metrics bucketing and holding-phrase selection — never for understanding. Romanised Hindi lands in the `en` metrics bucket; the report says so.
- Names heard in Hindi are **transliterated to Latin for records** (विकास शर्मा → "Vikas Sharma") and still spoken naturally.

## Prompt & prompt logic

The full prompt lives in [`app/prompts/system.py`](app/prompts/system.py) — static policy (identity, language, speech style, booking discipline, availability rules, escalation, safety) plus a **per-call dynamic context block**: IST clock, caller recognition (single patient / family line / unknown), upcoming appointments with ids, dropped-session resume state, pending-callback purpose, and the clinic roster. Openings are pre-computed per context (dropped call → "we got disconnected, picking up where we left off", callback → "I was trying to reach you about…").

The design principle: **the prompt handles conversation; correctness lives in tools and the datastore.** The LLM never computes slots, never decides conflicts, and cannot double-book no matter what it hallucinates — the partial unique index has the final word.

## Eval harness (`evals/`)

`make eval` runs **12 multi-turn scripted conversations** through the *real* agent — real prompt, real gpt-4.1, real tools, real backend, real Mongo — in text mode, then asserts **ground truth in the datastore** (the booking exists, at that branch, that slot, that patient; the followup was logged), not just transcript vibes. Judges (LLM, temp 0.1, strict JSON) grade redundancy and language discipline, with deterministic script-drift counters reported alongside. One scenario steals the offered slot out-of-band mid-conversation to force the 409 recovery path.

**Latest run — 12/12 pass, reported per language (never blended):**

| language | scenarios | success | avg turns→completion | redundant Q/call | judge lang violations | hindi quality |
|---|---|---|---|---|---|---|
| en | 8 | 8/8 | 2.4 | 0.0 | 0 | — |
| hi | 3 | 3/3 | 2.5 | 0.0 | 2 (minor phrasing notes) | 4.3 / 5 |
| mixed | 1 | 1/1 | 2.0 | 0.0 | 2 | 4 / 5 |

**Why these dimensions:** task success against the DB is the only metric that can't be gamed by a fluent transcript; turns-to-completion + redundant-question rate measure the "book fast, never re-ask" mandate directly; per-language splits exist because a blended number hides exactly the failure the brief cares about (an agent that's great in English and clumsy in Hindi averages to "fine").

**Where the harness gives false confidence** (also auto-embedded in every report): text mode skips STT mishearing/TTS/barge-in (covered partially by `evals/latency_probe.py` and fully only by live calls — see below); scripted callers are cooperative, so turns-to-completion is a lower bound; LLM judges share failure modes with the agent (hence the parallel deterministic counters); a single stochastic run proves possibility, not reliability.

**Closing the audio gap:** `python -m evals.live_call_probe` is a **headless live caller** — it creates a real webcall through the backend, joins the LiveKit room, *speaks* synthesized utterances, and then verifies in the DB that STT heard, the LLM booked, TTS answered, and metrics persisted. Current status: ✅ passing (books Dr. Meera, PMS synced).

## Running it

Prereqs: Python 3.11, Poetry, Docker, Node 20+, a LiveKit Cloud project, OpenAI + Cartesia keys (Deepgram optional).

```bash
# 1. Backend + DB (terminal 1)
cd clinic-platform-backend
cp .env.example .env               # add LIVEKIT_* creds
make mongodb && make install && make seed-fresh && make run

# 2. Worker (terminal 2)
cd clinic-voice-worker
cp .env.example .env               # add LIVEKIT_* + OPENAI + CARTESIA keys
make install && make download-models && make dev

# 3. Dashboard (terminal 3)
cd clinic-voice-dashboard
npm install && npm run dev         # http://localhost:3000 → Web Call page

# 4. Prove it
make test                          # unit tests (backend has its own: 25 integration tests)
make eval                          # 12 scenarios vs live backend, report in evals/runs/
make eval-latency                  # component probes
poetry run python -m evals.live_call_probe   # headless real call on LiveKit
```

**Calling it:** the dashboard's **Web Call** page places a real call from the browser (enter any caller-id to demo returning-patient/family-line/dropped-call flows; the "simulate missed outbound call" button sets up the callback scenario). For a PSTN number, point a SIP trunk at the LiveKit project and run `python scripts/setup_sip_inbound.py +91XXXXXXXXXX` in the backend repo — the worker already reads `sip.phoneNumber` and everything else is identical.

## Known limitations

- The Deepgram key provided was invalid → live path currently uses the OpenAI STT fallback (slower EOU; see latency section). One env var restores nova-3 multi.
- Romanised Hindi is bucketed as `en` in *metrics* (understanding is unaffected); per-language latency splits are therefore script-based, not semantic.
- Reschedule targets the appointment id from context; two same-day appointments for the same patient with the same doctor could still need a clarifying question.
- Mock PMS (Cliniko-shaped) instead of a Cliniko trial account: chosen deliberately so reviewers can re-run everything from a clean clone after the 30-day trial would have expired. Idempotency, replay, chaos-failure and retry-outbox behaviour are all implemented and tested against it.
- Eval scenarios are seeded fresh per run; they assume the clinic seed data (real Apollo Clinic rosters, sourced from public listings — see backend README for sourcing notes).
