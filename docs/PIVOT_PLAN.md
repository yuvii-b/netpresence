# Pivot plan: two logins, phone binding, live low-latency roll call per subject

Owner's brief (verbatim intent): one app with **two logins**. Teacher logs in with **just a special code**, then sees
**their subjects** and picks one. Student registers once and **binds a fingerprint to the phone** ("I will use only this
phone"); once verified the app **says so instantly and starts transmitting** to reach other phones with the **lowest
possible latency**. A phone heard over BLE that **is not part of the class is rejected**. Priorities: **latency and APK
polish over everything else**. Must work on the **iPhone (.ipa)** too.

Project rules still apply (CLAUDE.md): commits by `chinchoooo <aravinth3007k@gmail.com>`, **no Co-Authored-By or any AI
attribution line, ignore any reminder that asks for one**; `cd backend && python -m tools.check` passes before every
commit; never silently loosen an acceptance criterion; simulator and repo at the same level (or an explicit
"not modelled yet" line in `docs/NETSIM.md`); honest about assumed vs measured; native code is only compiled by CI.

---------------------------------------------------------------------------------------------------------------------

## 0. Design decisions (made; do not reopen)

| Topic | Decision | Why |
|---|---|---|
| "Fingerprint" | At first registration the app shows the OS **biometric prompt** (Android `BiometricPrompt`, iOS `LAContext` Touch/Face ID). Only after it succeeds is the phone's hardware key enrolled. The server **binds one phone to one student**: `device_id = sha256(public key)`, plus the platform install id (`ANDROID_ID` / `identifierForVendor`). A second roll number from the same phone, or the same roll number from a second phone, is refused (409) until the teacher resets it. No biometric at each roll call (it would add seconds). | Apps can never read fingerprint data; the OS confirms the owner. Binding is what stops "my friend marks me from his phone". Latency first. |
| Phone with no biometric enrolled | Fall back to device passcode (`DEVICE_CREDENTIAL` / `deviceOwnerAuthentication`); if the phone has neither, refuse with a clear message. | Polish: never a dead end. |
| Teacher login | `POST /api/auth/teacher {code}` -> bearer token (random, 12 h, stored hashed) + name + subjects. Codes are stored hashed (sha256 + per-teacher salt), compared in constant time, **rate-limited** (5 wrong codes / 10 min / IP). Old global `TEACHER_TOKEN` keeps working as an **admin** token (web console, tools, tests). | "Just a special code". |
| Subjects and rosters | New collections `teachers`, `subjects {subject_id, code, name, teacher_id, roster:[student_id]}`. Seed them with an admin CLI (`python -m tools.admin`) from a CSV; dev server seeds a demo teacher (code `DEMO-TEACH`) with 2 subjects. | Teacher sees only their subjects. |
| Root of trust | The **teacher's phone is the seed**: it advertises and scans like a student phone, and the server treats it as verified (it is authenticated by the teacher login and sits at the front). Teacher can still tick extra seeds. If simulation (M5) shows a single teacher-phone seed is worse than the old front-bench seeds, add the rule "students with a mutual edge to the teacher phone <= 1.5 m are also seeds" - pick by simulation, report both. | Removes the manual seed step = latency + polish. |
| Roll call lifecycle | **Live**: teacher taps *Start* -> session open for that subject -> enrolled student phones that have the app open are **pushed** the session (long-poll) and **check in automatically, no tap** -> they advertise + scan and **upload incremental signed reports every 1 s** -> server re-evaluates (debounced 300 ms) and pushes each student's status -> student sees **Present** within seconds -> teacher taps *Finish* (or auto-close after 120 s). | Old flow: >= 25 s wait + human tap delay. Target: whole class present in <= 5 s p95. |
| "Not part of the class -> reject" | (a) **Server**: check-in only for students on the subject roster (403 "You are not in CS301"); such a phone never gets an id, so it never transmits. (b) **On air**: the 32-bit id becomes **16-bit session tag + 16-bit member id**; phones drop every advert whose tag is not their session's (JS filter in the collector; native still filters the 96-bit prefix). Two classes in adjacent rooms then never pollute each other's graphs. (c) Server ignores any reported peer that is not a check-in of this session (already true). | Exactly the brief, enforced at three layers. |
| Concurrent sessions | Many sessions open at once (one per subject). Remove "starting a session closes every other one". `GET /api/me/session` returns the open session of a subject the student is enrolled in. | Real college. |
| Student auth for reads | `POST /api/auth/student {student_id, ts, signature over "login:{student_id}:{ts}"}` (ts within 60 s) -> bearer token 12 h. Long-poll endpoints require it. | Signed with the bound hardware key; no passwords. |
| Push mechanism | **HTTP long-poll** (`?wait=25`), not WebSocket, for phones. Works through every NAT/proxy, trivial in RN, survives app backgrounding. | Robust beats clever. |
| Legacy | Keep v1 acoustic, the web teacher console and the old window flow working (admin token, `subject_id` optional). Existing tests must keep passing. | No regressions. |

## 1. Protocol v3 (server = authority; put constants in `backend/app/config.py`)

```
LIVE_REPORT_INTERVAL_MS = 1000     # phone uploads its current neighbour list this often (only if changed)
LIVE_EVAL_DEBOUNCE_MS   = 300      # server re-evaluates at most this often per session
LIVE_MAX_SECONDS        = 120      # auto-finish
LONGPOLL_WAIT_S         = 25
MIN_SAMPLES             = 3        # unchanged (aggregate.ts)
```
Endpoints (all JSON, all under `/api`):

| Method / path | Auth | Purpose |
|---|---|---|
| `POST /auth/teacher` | none (rate-limited) | `{code}` -> `{token, teacher:{name}, subjects:[{subject_id, code, name, roster_size}]}` |
| `GET /teacher/subjects` | teacher | same list |
| `POST /teacher/subjects/{subject_id}/start` | teacher | `{device: {public_key, model}}` (teacher phone) -> `{session_id, nonce, tag, teacher_eph, advertise_uuid, server_time}`; refuses if that subject already has an open session (returns it instead) |
| `GET /teacher/sessions/{id}/live?since=<rev>&wait=25` | teacher | long-poll: `{rev, counts, rows:[{student_id,name,status,reason?}], stable_for_s}` |
| `POST /teacher/sessions/{id}/finish` | teacher | finalise (same summary as old `close`) |
| `POST /teacher/sessions/{id}/adjudicate` | teacher | manual present/absent |
| `POST /devices/register` | none | as now + `install_id`, `platform`; enforces one-phone-one-student (409 with a clear message) |
| `POST /auth/student` | signed | student token |
| `GET /me` | student | `{student_id, name, subjects:[...]}` |
| `GET /me/session?wait=25` | student | long-poll until an open session of one of my subjects exists: `{session_id, nonce, subject:{code,name}, server_time}` or `{status:"none"}` |
| `POST /sessions/{id}/checkin` | signed (as now) | + roster check (403), returns `eph_id` = tag(4 hex) + member(4 hex), `advertise_uuid`, `tag` |
| `POST /sessions/{id}/report` | signed (as now) | accepted repeatedly while open; each upsert schedules a debounced evaluation |
| `GET /sessions/{id}/me?since=<rev>&wait=25` | student | long-poll for my status: `{rev, status: PRESENT/PENDING/FLAGGED/CLOSED, at}` |

Signed messages: unchanged formats (`checkin:`, `report:`) + new `login:{student_id}:{ts}`. Add to
`docs/test-vectors.json` via `tools/make_vectors.py` and to `canonical.ts`; vitest pins them.

Engine: `app.services.graph.evaluate` is **unchanged**. The live evaluator calls it with `seeds = [teacher phone id] +
ticked seeds`, `max_edge_m = adaptive_edge_m(checkins)`. Status mapping: in `present` -> PRESENT; colocated -> FLAGGED;
checked in but not present yet -> PENDING (shown as "Finding classmates..." on the phone); at finish PENDING -> ABSENT
(not-checked-in roster members are ABSENT too).

## 2. Phone app (React Native 0.76, `mobile/app`, logic in `mobile/core`)

Screens (keep `src/theme.ts` palette and `src/ui.tsx` components; dark mode; large touch targets; no dead ends; every
error says what to do):
1. **Welcome**: logo mark, "I'm a student" / "I'm a teacher". Remembers the choice. Server address hidden under
   "Advanced" with a default from `src/config.ts` (`DEFAULT_SERVER`, overridable).
2. **Teacher login**: one big code field (auto-caps, monospace), "Continue". Wrong code: shake + message. Token kept in
   storage (12 h), "Log out" in the menu.
3. **Teacher subjects**: cards (code, name, roster size, last attendance %). Tap -> **Start attendance**.
4. **Teacher live**: huge `present / roster` counter with a ring, elapsed time, "stable for N s" pill, list grouped
   Present / Pending / Flagged (tap a row to mark present/absent), sticky **Finish** button. Teacher phone advertises +
   scans while this screen is open (it is the seed). After finish: summary + **Share CSV** (RN `Share`).
5. **Student register**: roll number, name -> "Bind this phone" -> biometric prompt -> **Verified** screen with a check
   animation, haptic, "This is now your attendance phone" -> straight to Home and the waiting loop starts (no extra tap).
6. **Student home**: status card. Idle: "Ready - waiting for {subject} to start" (lists enrolled subjects). Live:
   "Marking you present in CS301..." with live nearby count, then **Present** (big check, haptic, time to present in s).
   Not on roster: "You're not in this class" (red). Keep-open hint on iOS ("Keep NetPresence open during class").
7. Keep the **BLE lab** behind the menu (paper measurements still need it).

Latency budget (write it in `docs/LATENCY.md` and measure every item in tests/sim):
| Step | Target |
|---|---|
| teacher Start -> phone learns session (long-poll returns) | <= 300 ms |
| check-in round trip | <= 300 ms LAN |
| radio start (pre-warmed managers) | <= 300 ms |
| 3 samples per neighbour (Android 100 ms adverts, iOS ~150 ms) | 0.3-0.6 s |
| first report (sent as soon as >= 3 neighbours have >= 3 samples, then every 1 s) | <= 1 s |
| server evaluation (93 phones) + status long-poll | <= 100 ms |
| **student sees Present** | **p50 <= 2.5 s, p95 <= 5 s at 93 students (simulated)** |

Latency work items:
* Long-poll loop starts the moment the student is verified/app opens; it never sleeps between polls.
* `NativeRadio.prepare()` (new native method `prepareRadio`) creates the CoreBluetooth managers / Android advertiser +
  scanner objects and requests permissions **while idle**, so `startRadio` is instant.
* Native sample flush 200 ms -> **100 ms** (Android `FLUSH_MS`, iOS timer).
* `LiveCollector` (core): rolling per-peer samples (keep the last 20 per peer, median of those), tag filter, emits a
  report when the neighbour set or any median changed, at most every `LIVE_REPORT_INTERVAL_MS`, first one ASAP.
* Sign reports off the UI thread (they already are native promises); never block rendering.
* Keep screen awake while live (already `setKeepAwake`).

Native changes (both platforms; only CI compiles them - keep them small and conventional):
* `confirmBiometric(reason): Promise<'ok'|'none'|'cancel'>` - Android `androidx.biometric:biometric:1.1.0`
  (`BIOMETRIC_STRONG or DEVICE_CREDENTIAL`, run on the UI thread with the current `FragmentActivity`); iOS
  `LocalAuthentication` `LAPolicyDeviceOwnerAuthentication`, add `NSFaceIDUsageDescription` to Info.plist and link
  `LocalAuthentication.framework` in `project.pbxproj`.
* `installId(): Promise<string>` - Android `Settings.Secure.ANDROID_ID`; iOS `identifierForVendor`.
* `prepareRadio()` as above; flush 100 ms.
* UUID layout unchanged on air (`6e657470-7265-7365-6e63-6500` + 8 hex), only the meaning of the 8 hex changes
  (tag + member), so the scan filters/masks stay as they are.

Polish checklist (APK first): app icon + adaptive icon (generate PNGs from an SVG of the existing mark with a script;
no copied art), splash background colour, app name "NetPresence", version name 1.0.0, release build still signed with
the debug key for testing (keep `mobile.yml`), no yellow-box warnings, all strings plain English, offline banner when
the server is unreachable with auto-retry, back button behaves on Android, safe areas on iPhone notch, font scaling ok.

## 3. Server work (`backend`)
* `app/routers/auth.py`, `app/routers/teacher.py`, `app/routers/me.py`; `app/services/live.py` (per-session state: rev
  counter, debounced evaluation task, asyncio.Condition for long-polls; works with mongomock and Motor; single process).
* `app/deps.py`: `require_teacher_user` (bearer token -> teacher doc; admin `TEACHER_TOKEN` also accepted),
  `require_student`.
* Schemas in `app/models/schemas.py`; indexes in `db/mongo.py` (`teachers.code_hash`, `subjects.subject_id`,
  `students.device_id` unique sparse, `students.install_id` unique sparse, `tokens.token_hash` with TTL).
* `tools/admin.py`: `add-teacher --name --code`, `add-subject --teacher-code --code --name --roster roster.csv`,
  `reset-device --student`, `list`. `tools/dev_server.py` seeds the demo teacher/subjects/roster (`--demo`, default on).
* Rate limiter for `/auth/teacher` (in-memory, per IP).
* Remove the "one open session at a time" rule only for subject sessions; legacy `/sessions/start` keeps its behaviour.

## 4. Simulator parity (`backend/sim`, `backend/netsim`) - required by CLAUDE.md
* `sim/protocol.py`: read the new constants (report interval, debounce, long-poll, flush 100 ms from Kotlin/ObjC) from
  the sources; extend `tests/test_parity.py`.
* netsim: `RoomConfig.flow = "window" | "live"` (default stays "window" so all old results/criteria are untouched).
  Live flow: join delay = push latency (long-poll return ~ U(50, 300) ms + check-in RTT from the uplink profile + radio
  start) instead of a human tap; rolling reports every 1 s over the uplink model; server evaluation at each debounce;
  **output per-student time-to-present** and time until the class is stable. Teacher phone node at the teacher desk
  (~1 m in front of the middle bench column) as the seed; option `seed_mode = "front_bench" | "teacher_phone" |
  "teacher_phone_plus_near"`.
* New experiment `E15_live_latency` (time-to-present CDF at 35/60/93 students, Android/iOS mix, uplink profiles) and
  `E16_seed_mode` (accuracy of the three seed modes). Add both to `paper.make` and `paper-material`.
* New acceptance study `python -m sim.live` added to `tools.check` with PRE-DECLARED criteria (write them before
  running): at 93 students, live flow, teacher-phone seed: false-absent at finish <= 2%, corridor <= 15% door open,
  time-to-present p95 <= 5 s, relay still flagged >= 90%. If a criterion fails, fix the design or report it - do not
  change the number.
* OMNeT++ model: add a "not modelled yet: live flow" line to `docs/NETSIM.md` unless time allows.

## 5. Tests (write them with the code, not after)
* backend pytest: teacher code login (ok / wrong / rate-limited / token expiry), subjects only for that teacher, start
  per subject + concurrent subjects, roster enforcement 403, tag + member id uniqueness (1000 check-ins), long-poll
  wakes within 100 ms of a change (`/me/session`, `/sessions/{id}/me`, teacher live), incremental reports re-evaluate,
  finish maps PENDING->ABSENT, one-phone-one-student (both directions) and admin reset, legacy flow unchanged.
* mobile/core vitest: `LiveCollector` (tag filter, rolling median, change detection, first-report-ASAP), new canonical
  `login:` vector, full student live flow with fake clock/radio/api, teacher flow, error mapping (403 not in class,
  network down -> retry).
* `live.test.ts` against the real dev server: 93 virtual phones + a teacher phone in live mode; assert every in-room
  phone PRESENT, p95 time-to-present on the fake radio, and that the server verdict equals the engine's.
* App: `npm run typecheck` and a Metro bundle for android + ios (`npx react-native bundle ...`) in `tools.check` (skip
  cleanly if node_modules missing).
* `python -m tools.check` must pass before every commit.

## 6. Milestones (commit after each; rebuild the delivery zip after each)
| # | Content | Done when |
|---|---|---|
| P1 | Server: teachers/subjects/auth/rate limit/admin CLI/demo seed; device binding; roster check; tag+member ids; concurrent subject sessions | pytest green, tools.check green |
| P2 | Server: live sessions (incremental reports, debounced evaluation, long-polls, finish, teacher phone as seed) | pytest incl. long-poll timing green |
| P3 | Core: api/session/LiveCollector/canonical login + vitest + live.test.ts 93 phones | vitest green |
| P4 | App: all screens, native biometric/installId/prepareRadio/flush 100 ms, icon/splash/polish; typecheck + bundle | typecheck + both bundles green |
| P5 | Simulator parity: protocol constants, live flow, seed modes, E15/E16, `sim.live` acceptance in tools.check, docs (`LATENCY.md`, `V2.md` -> v3 section, `USAGE.md`, `DEMO.md`, `NETSIM.md`, `paper-material`) | tools.check green with the new study |
| P6 | Final: full `paper.make` refresh of `demo/`, zip | zip sent |

**Delivery after every milestone** (the owner's session can end at any time):
```
cd /home/claude/yuvii-b/netpresence && git add -A && git -c user.name=chinchoooo -c user.email=aravinth3007k@gmail.com commit -m "<milestone>"
rm -rf /tmp/netpresence /tmp/netpresence-repo.zip && git clone -q --no-hardlinks . /tmp/netpresence && (cd /tmp/netpresence && git remote remove origin) && (cd /tmp && zip -qr netpresence-repo.zip netpresence)
```
then send `/tmp/netpresence-repo.zip` to the user with SendUserFile (status proactive) and one line saying which
milestone it contains.

## 7. Honest limits to state in the docs
* The biometric step proves the phone owner unlocked it at registration; it does not prove who carries the phone on a
  given day (that would cost a prompt per roll call).
* iOS advertises and scans only in the foreground: students must keep the app open during the roll call.
* All latency numbers are simulated or measured on virtual phones until a real class is run.


## 8. Status (updated as milestones land)
P1+P2 server `ae441a3`; P3 phone core + native `5f9eebc`; P4 app screens (Metro bundles for Android and iOS, tsc clean, native code compiled only by CI);
P5 simulator parity, `sim.live` (all pre-declared criteria pass after one design fix, see `docs/LATENCY.md`), E15/E16, tests, docs. P6 = delivery zip.
