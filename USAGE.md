# NetPresence - overall usage

Instant classroom roll call from phone proximity. Phones broadcast a random id over Bluetooth LE and report the signal strength of
the ids they hear; the server builds a proximity graph, floods trust outward from the teacher's verified front-bench students, and marks
a student PRESENT only with 2 independent trust paths. About 25 s for 93 students. Android and iPhone. This repo holds the system,
the network simulators used to evaluate it, and the paper material.

> Status in one line: the server, teacher screen, phone protocol code and both simulators are tested; **every radio number is simulated
> with assumed values**, and the Android/iPhone apps have only been compiled by GitHub Actions, never run on a real phone.

## 1. What is where
| Folder | What |
|---|---|
| `backend/app` | the server (FastAPI) and the trust engine `services/graph.py` |
| `frontend` | teacher console (React) |
| `mobile/core`, `mobile/app` | phone protocol code (TypeScript) and the Android/iOS app (React Native + native BLE) |
| `backend/netsim` | the network simulator: channel, BLE link layer, phones, uplink, attacks, baselines, metrics |
| `omnet` | the same roll call as an **OMNeT++** model with its animated Qtenv viewer |
| `backend/paper` | one command that runs experiments E01-E14 and writes figures/tables for the paper |
| `paper-material` | everything needed to WRITE the paper: claims, evidence map, method facts, threat model, limits, checklist |
| `demo` | ready-made results to show: figures, tables, key numbers (see `demo/README.md`) |
| `docs` | design (`V2.md`), simulator (`NETSIM.md`), plan, install (`INSTALL.md`), demo script (`DEMO.md`) |

## 2. Set up (Windows, once)
Install Python 3.11+ (add to PATH), Node 20+, Git. Then:
```
git clone https://github.com/yuvii-b/netpresence.git
cd netpresence
git checkout v2-proximity-graph
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt -r requirements-paper.txt
```
(Linux/macOS: `source venv/bin/activate`.) All commands below run from `backend` with the venv active.

## 3. Check that everything works (4 min)
```
python -m tools.check
```
Runs the tests, the 93-student room study, the Android/iOS study and the phone code against a live server. Every acceptance
criterion prints PASS/FAIL.

## 4. Simulator
```
python -m netsim.run --preset class93 --trials 60
python -m netsim.run --preset class60 --set door_open=false --set ios_share=0.5 --set models.iphone.tx=12
python -m netsim.loadtest --local --phones 93
```
`--set KEY=VALUE` changes any field of `netsim/config.py` (each field is tagged spec / assumed / measured). Presets: class93, class60,
class35, class20, lab6, exam.

## 5. Paper results
```
python -m paper.make --quick          # 14 experiments, ~1.5 min, wide error bars (smoke test only)
python -m paper.make --workers 4      # full run; cached, safe to stop and resume
python -m paper.key_numbers           # headline numbers as one Markdown page
```
Output: `backend\paper\out\` (`summary.md`, `figures\*.png|pdf`, `tables\*.md|tex`, `results\*.json`, `KEY_NUMBERS.md`).
Real-phone data (when you have it) goes in `backend\paper\real\` (formats in its README); E12 and E13 then become real comparisons.
What to write and how: `paper-material/PAPER_MATERIAL.md`.

## 6. OMNeT++ (animated simulator)
Install OMNeT++ 6.1 for Windows (omnetpp.org), open its `mingwenv.cmd` shell, then once:
```
cd <repo>\omnet
opp_makemake -f --deep -o netpresence -O out
make MODE=release
```
Then from `backend`:
```
python -m netsim.omnet_run --preset class93 --seed 1 --gui        # watch it run in Qtenv
python -m netsim.omnet_run --preset class93 --relays 2 --gui      # relay attack and its detection
python -m netsim.omnet_run --compare --preset class60 --seeds 12  # OMNeT++ vs Python, same rooms
```
In Qtenv press Run: yellow = tapped, blue = scanning, purple = uploading; at the deadline the real engine colours phones
green = present, red = absent, orange = flagged, and draws the proximity graph. Details: `omnet/README.md`.

## 7. The live system (laptop + phones on the same Wi-Fi)
1. Phones: download `NetPresence-android.apk` / `NetPresence-ios-unsigned.ipa` from GitHub Releases ("Latest build") or Actions -> Mobile builds -> Artifacts.
   Android: install, allow Nearby devices (Android 11-: Location on). iPhone: sideload with Sideloadly + free Apple ID (7-day validity), Developer Mode on.
2. Server: `python -m tools.dev_server --host 0.0.0.0` (in-memory DB, teacher token `dev-teacher-token`). Allow Python through the firewall; note your IPv4.
3. Teacher screen: in `frontend`: `npm install`, create `.env.local` containing `VITE_API_BASE_URL=http://<your-ip>:8000`, `npm run dev`, open the printed address, enter the token.
4. Phones: enter roll number, name, server address once. Teacher: Start roll call -> students tap "Mark me present" within 20 s and keep the app open ~25 s ->
   tick the front-bench seeds -> Close -> review FLAGGED rows. With 2-3 phones set Witnesses k = 1.
5. Stress test the server on your Wi-Fi: `python -m netsim.loadtest --server http://<ip>:8000 --token dev-teacher-token --phones 93`.
Full guide and troubleshooting: `docs/INSTALL.md`.

### 7b. The two-login app (protocol v3, `docs/PIVOT_PLAN.md`)
* Server: `python -m tools.dev_server --host 0.0.0.0` seeds a demo teacher (code `DEMO-TEACH`) with subjects CS301 and NW204 and a roster.
  Your own: `python -m tools.admin add-teacher --name "Dr Rao" --code RAO-2026` and `add-subject --teacher-code RAO-2026 --code CS301 --name "Operating Systems" --roster roster.csv`.
* Teacher phone: I'm a teacher -> enter the code -> pick the subject -> the class starts. The teacher phone is the root of trust; keep it near the front.
  Watch the Present count climb; the Finish button says when the result is most accurate (15 s). FLAGGED students can be set Present/Absent in place. Share list = CSV.
* Every screen has a **What's happening** panel: Bluetooth on/off, the name this phone broadcasts as, the phones it hears (with signal), reports sent/failed and a time-stamped log. Send me a screenshot of it when something looks wrong.
* **Register** button on each subject card: a sheet of every roster student against every finished class (P present, A absent, F flagged), with each student's percentage and a CSV share. Under 75 % shows red.
* The teacher stays signed in for about 11 hours (Log out on the subjects screen clears it). A student keeps the registered phone until you choose Remove this phone's registration.
* Student phone (first time): I'm a student -> roll number, name, class code -> **Verify with fingerprint** -> "Phone verified". After that the app needs no taps:
  when the teacher starts the subject the phone joins by itself, starts transmitting and shows **Present**. A student who is not on that subject's roster is refused
  ("Not in this class"). One phone = one student (a second student on the same phone, or a second phone for the same student, is refused; the teacher resets with
  `python -m tools.admin reset-device --student 21CT042`).
* Simulated latency and accuracy of this flow: `python -m sim.live` (about 3 min) and `docs/LATENCY.md`.

## 8. A 10-minute demo for the professor
1. (1 min) Pitch: `paper-material/PAPER_MATERIAL.md` section 1, the "how it works" in `docs/DEMO.md`.
2. (3 min) OMNeT++ window: class93 run, then `--relays 2`. Say what the colours mean.
3. (2 min) `demo/results/figures/e09_baselines.png` (vs manual / beacon / acoustic / QR) and `e03_attacks.png`.
4. (2 min) Live: teacher console + 3-6 phones doing a real roll call (if the apps are installed).
5. (2 min) Honest limits: simulated with assumed values, apps not yet field-tested, what real measurements come next (`paper-material` section 6, 9).

## 9. Troubleshooting
| Symptom | Fix |
|---|---|
| `pip` fails on matplotlib | skip `requirements-paper.txt`; tables and numbers still work, figures are skipped |
| phone says "Can't reach http://..." | open `http://<ip>:8000/docs` in the phone browser; same Wi-Fi, firewall, `--host 0.0.0.0` |
| iPhone shows nothing | Settings -> NetPresence -> allow Local Network and Bluetooth |
| nobody shows as nearby | screens on, 1-2 m apart, Bluetooth on; Android 11- needs Location on |
| `omnet_run` says model not built | build it once (section 6) or set `NETPRESENCE_BIN` |
| "already enrolled" | teacher resets the device in the console (`DELETE /api/devices/{id}`) |
