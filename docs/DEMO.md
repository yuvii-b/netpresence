# Run everything and show it to your professor

Three parts: **A. the simulator and paper results (no phones)**, **B. the live system (server + teacher screen + phones)**,
**C. how it works, for the viva**. App install details are in `docs/INSTALL.md`.

## 0. One-time setup on Windows (10 minutes)
1. Install Python 3.11+ (tick "Add to PATH"), Node 20+, Git.
2. `git clone https://github.com/yuvii-b/netpresence.git`, then `cd netpresence`, `git checkout v2-proximity-graph`
   (after you have pushed the patches: `git am np-patches\*.patch`, `git push origin v2-proximity-graph`).
3. ```
   cd backend
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt -r requirements-dev.txt -r requirements-paper.txt
   ```

## A. Simulator and paper results (inside `backend`, venv active)
| Command | What it shows | Time |
|---|---|---|
| `python -m tools.check` | all tests + the 93-student room study + the Android/iOS study + phone code against a live server; every acceptance criterion prints PASS/FAIL | ~4 min |
| `python -m netsim.run --preset class93 --trials 60` | one headline number set: false-absent, corridor admitted, hops | ~1 min |
| `python -m netsim.run --preset class60 --set door_open=false --set ios_share=0.5 --set models.iphone.tx=12` | any what-if; `--set` takes any field of `netsim/config.py` | seconds |
| `python -m paper.make --quick` | ALL 14 experiments (accuracy, ablations, attacks, Android/iOS, speed, uplink, BLE collisions, robustness, baselines, back-bench heatmap, large halls, energy ...) with tables and figures | ~1.5 min |
| `python -m paper.make --workers 4` | the full, publishable run (many classrooms per point); cached, safe to stop and resume | hours |
| `python -m netsim.loadtest --local --phones 93` | 93 virtual phones with real signatures against the real server code | seconds |

Results land in `backend\paper\out\`: open `summary.md` (all tables), `figures\*.png` (put these in slides), `tables\*.tex` (paper).
Show the professor: `figures\e09_baselines.png` (NetPresence vs manual / beacon / acoustic / QR), `e03_attacks.png` (relay attack and defence),
`e01_accuracy.png`, `e10_backbench.png` (nobody at the back is missed).

**Animated simulator (OMNeT++, the standard network simulator):** install OMNeT++ 6.1 and build the model once (`omnet/README.md`), then
`python -m netsim.omnet_run --preset class93 --seed 1 --gui` and press Run in Qtenv: phones tap, advertise and scan, adverts fly
between phones, reports go up, then the real engine colours each phone present / absent / flagged and draws the proximity graph.
`--relays 2` shows the relay attack being flagged. `--compare` checks it against the Python simulator on the same rooms.

**Be honest in the viva:** every radio number is *simulated with assumed values* (each parameter is tagged spec / assumed / measured in
`netsim/config.py`). The simulator reads the protocol constants from the real app code, and the engine it runs IS the server's engine.
Real numbers come only after the BLE-lab measurements (below) go in `backend\paper\real\`. `--quick` numbers have wide error bars.

## B. Live system
1. **Get the apps.** GitHub -> repo -> Releases -> "Latest build": `NetPresence-android.apk` and `NetPresence-ios-unsigned.ipa`
   (or Actions -> Mobile builds -> newest green run -> Artifacts). These are built by GitHub, not on your PC.
   *Never run on a real phone yet: expect a bug or two and tell the professor so.*
2. **Server** (laptop, same Wi-Fi as the phones): `cd backend`, `python -m tools.dev_server --host 0.0.0.0`.
   Token is `dev-teacher-token`. Find your IPv4 (`ipconfig`), allow Python through the firewall (private network).
   Check `http://<ip>:8000/docs` opens on a phone browser. In-memory database: restart = clean slate.
3. **Teacher screen:** `cd frontend`, `npm install`, create `.env.local` (plain text) with `VITE_API_BASE_URL=http://<ip>:8000`,
   `npm run dev`, open the printed address, enter the token.
4. **Android:** copy APK, install, allow Nearby devices (Android 11 and older: switch Location on).
   **iPhone:** sideload the .ipa with Sideloadly + a free Apple ID (7-day validity), enable Developer Mode, allow Bluetooth and Local Network.
5. **Demo flow (needs >= 4-6 phones; with 2-3 set Witnesses k = 1):**
   - phones: enter roll number, name, server address once.
   - teacher: Start roll call. Students tap **Mark me present** within 20 s; apps stay open ~25 s.
   - teacher: tick the front-bench seed students, enter the headcount, Close. PRESENT / FLAGGED / ABSENT appear; review FLAGGED.
6. **Show an attack live:** one phone sits outside the door = not admitted; two phones side by side (one pretending to be remote)
   = flagged "same radio".
7. **Measure for the paper (BLE lab, optional but valuable):** in the app's **BLE lab**, put two phones at 0.5/1/1.5/2/3/4 m, in hand / on desk / in pocket,
   record, export CSV v2 into `backend\paper\real\traces\`; `python -m tools.fit_pathloss` fits the real path-loss numbers; rerun `paper.make`
   and E13 switches from SYNTHETIC to real. Real roll calls: add rows to `paper\real\sessions.csv` (format in `paper\real\README.md`) for E12.
8. **Server stress test on your real Wi-Fi:** `python -m netsim.loadtest --server http://<ip>:8000 --token dev-teacher-token --phones 93`.

## C. How it works (the 60-second explanation)
- At the start each phone **checks in** with an ECDSA P-256 signature (keys live in the phone's secure hardware). The server hands it a
  random 32-bit id, carried in a Bluetooth LE advert (a 128-bit service UUID, so it works the same on Android and iPhone).
- For 20 s + 5 s everyone advertises and scans. Each phone keeps the **median RSSI** per neighbour (>= 3 samples) and uploads a **signed report**
  (retry 0.5 s doubling to 4 s, 5 s timeout).
- The server builds a **proximity graph**: an edge exists only if both ends hear each other and the distance (from RSSI, path-loss model,
  adaptive threshold 2-3.5 m) is small. Per-platform offsets are self-calibrated (iPhones transmit differently).
- **Trust floods from the teacher** (seed students on the front bench verified by eye) along edges, bounded by TTL 8 hops / 15 m.
  A student is PRESENT only with **k = 2 vertex-disjoint paths** from the seeds (Menger): one friend cannot vouch for you.
- Attacks: corridor phones lack paths; a remote forger has no mutual edges; collusion needs >= k in-room accomplices (raise k);
  a **relay** (radio forwarding a remote friend's id) is caught because two ids show the same readings at every observer
  (co-location check) and are flagged for the teacher.
- Why not acoustic (v1): iPhone microphones need ~13 dB more signal, noise and walls break it, a recording can be forwarded
  (see E09/E10).
- Limits to state: tiny rooms (< ~20 phones) are weak, large halls (> ~150) need a larger TTL, a fresh server has no per-model offset table
  (hurts small classes), phones in pockets/bags look farther (sim finding), and nothing has been measured on real phones yet.
