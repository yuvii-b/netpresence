# NetPresence — Status Notes

Last reviewed: 2026-08-17, against `NetPresence-12-Week-Plan.pdf` (Weeks 1-4). Legacy `fskEncoder.js` / `fskDecoder.js` are excluded — the live audio path is `toneEncoder.js` / `toneDecoder.js`.

## 1. Plan conformance — Weeks 1-4

| Week | Requirement | Status | Notes |
|---|---|---|---|
| 1 | Lock architecture: FastAPI + WebSocket + MongoDB | Done | Matches what's actually built. |
| 1 | Domain + Let's Encrypt HTTPS | Not done | Deferred deliberately — running on ngrok for now. |
| 2 | FastAPI backend, real HTTPS domain | Partial | Backend runs; exposed via a rotating ngrok free-tier URL (`frontend/src/services/api.js`), not a persistent cloud VM/domain. Deliberately left as-is. |
| 2 | Create session / list sessions / submit attendance endpoints | Done | `POST /api/sessions/start`, `GET /api/sessions/list`, `POST /api/attendance/submit` all implemented. |
| 2 | MongoDB schema, sessions persisted | Done | `sessions` and `attendance` collections now exist with unique indexes. `students`, `device_keys`, `anomaly_log` intentionally not created yet — they belong to Week 5+ (auth) and Week 7+ (anti-cheat). |
| 2 | Mobile-first teacher/student pages over HTTPS | Done (deviation) | Built as a React/Vite app rather than plain HTML/JS. Functionally equivalent. |
| 3 | 18-20 kHz near-ultrasound FSK tokens | Not done | Actual tone range is ~800 Hz-3.1 kHz — audible, not ultrasonic. Deliberately left as-is. |
| 3 | Token rotates every 5-10s | Not done | Token is static for the whole session; see [Timers](#2-timers--expiry-values) below. |
| 3 | Mic decode, client-side | Done | Continuous rolling-window Goertzel decode instead of discrete 3s captures — a design variation, not a gap. |
| 4 | Token in submission payload, validated against session window | Done | `token_service.validate_submission`. |
| 4 | Nonce / single-use check | Done | In-memory `used_tokens` set, keyed by `session_id:student_id:token`. |
| 4 | Teacher dashboard: start session + live submission count | Done | Backed by a WebSocket broadcast, filtered client-side by session ID. |

## 2. Timers & expiry values

| Constant | Value | Where | Meaning |
|---|---|---|---|
| `TOKEN_VALIDITY_SECONDS` | 60s | `backend/app/config.py` | Session window: a submission is only accepted within 60s of `start_session` being called — fixed at session start, does **not** extend while the teacher keeps emitting. |
| Token rotation | none | — | The same token plays on loop for the entire session; it does not regenerate every 5-10s as the plan specifies. |
| `TONE_MS` / `GAP_MS` | 400ms / 150ms | `toneEncoder.js` | Duration of each tone and silence gap between characters. |
| `WINDOW_MS` | 100ms | `toneDecoder.js` | Analysis window size for the Goertzel frequency detector. |
| `DEBOUNCE_MS` (comment only, not enforced by a timer) | 250ms | `toneDecoder.js` | Intended minimum gap before re-accepting the same symbol; actual re-arming is driven by silence detection (`armed` flag), not a wall-clock debounce. |

## 3. Current limitations

- **Audible tones, not near-ultrasound.** Tone range (~800 Hz-3.1 kHz) is within normal human hearing, contradicting the plan's "ambient/inaudible" proximity premise. Left as-is per explicit decision.
- **No token rotation.** One token is valid for the whole 60s session; capturing it once is enough to replay-attempt for the rest of the window (blocked only by the per-student nonce, not by token freshness).
- **Fixed session expiry, not a rolling window.** If a teacher keeps a session open past 60s, no new submissions are accepted even though audio is still playing.
- **Nonce/session state is in-memory only** (`token_service.py`). A backend restart wipes `active_sessions` and `used_tokens`. Any session document left as `status: "active"` in MongoDB when the server restarts will never transition to `"stopped"` unless the teacher explicitly stops it again after restart.
- **ngrok deployment.** URL is hardcoded and rotates on tunnel restart; not a durable HTTPS domain. Left as-is per explicit decision.
- **No session-scoped WebSocket rooms.** A single `/ws` broadcast channel serves all connected clients; each teacher dashboard filters events client-side by its own `session_id`. Fine at current scale, wouldn't scale cleanly to many concurrent classrooms.
- **No auth yet (by design).** `student_id` is free text typed by the student — nothing binds it to a real identity. This is explicitly Week 5-6 scope (WebAuthn/Passkeys).
- **Student session selection is automatic, not manual.** `StudentScanner` always picks the first `status: "active"` session from `/api/sessions/list`; if two sessions are active at once, there's no UI to choose between them.

## 4. Potential improvements

- Move tone frequencies into the 18-20 kHz band (or explicitly update the report to describe an audible-tone design instead, if keeping current frequencies).
- Rotate the token server-side every 5-10s and push the new token to the teacher's page over WebSocket, re-encoding it live.
- Make the session window a rolling/heartbeat-based expiry instead of a fixed 60s from start, so a longer-running session doesn't stop accepting valid submissions partway through.
- Persist `active_sessions` / `used_tokens` to MongoDB (or Redis) so replay protection and session state survive a backend restart.
- Add a scheduled/startup cleanup job that marks any `sessions` document left `status: "active"` for longer than its `expires_at` as `"expired"`.
- Move off ngrok to a real cloud VM + domain + Let's Encrypt certificate (Week 1/2 requirement).
- Scope the WebSocket broadcast per session (e.g. a room/topic keyed by `session_id`) instead of client-side filtering, ahead of multi-classroom scale.
- Give students a manual session picker in the UI for the (currently unhandled) case of multiple concurrent active sessions.
