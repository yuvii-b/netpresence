# Install and run NetPresence

Honest status first: the server, teacher console and the phone protocol code are tested. The Android and iPhone apps
have **never been run on a real phone**, so expect to report a bug or two. See `mobile/README.md` for the verification table.

You need: a Windows/macOS/Linux laptop (runs the server and teacher screen), one or more phones on the **same Wi-Fi**.

## 1. Get the apps
* **From a release (easiest):** open the repo's **Releases** page and download `NetPresence-android.apk` and
  `NetPresence-ios-unsigned.ipa`.
* **No release yet:** open **Actions -> Mobile builds -> latest green run -> Artifacts** and download the same two files (unzip them).
* The builds are made by GitHub's servers from this repo (`.github/workflows/mobile.yml`); no Mac or Android SDK needed.

## 2. Run the server (laptop)
Install Python 3.11+ and Node 20+. Then, in the project folder:
```
cd backend
python -m venv venv
venv\Scripts\activate            # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m tools.dev_server --host 0.0.0.0
```
This uses a throw-away in-memory database (no MongoDB needed); the teacher token is `dev-teacher-token`.
Optional: set `ENROL_CODE=SOMECODE` before starting, and phones must enter that class code to register.
Leave the window open. Find the laptop's Wi-Fi IPv4 address (`ipconfig` / `ifconfig`), e.g. `192.168.1.4`.
Server address for the phones: `http://192.168.1.4:8000`. Allow Python through the firewall for **private** networks.
Check from a phone's browser: `http://192.168.1.4:8000/docs` must load.

## 3. Run the teacher screen (laptop)
```
cd frontend
npm install
```
Create a file named `.env.local` inside `frontend` (Notepad, save as plain text; avoid `echo >` in PowerShell, it saves
in an encoding Vite can't read) containing one line, with your own IP:
```
VITE_API_BASE_URL=http://192.168.1.4:8000
```
Then:
```
npm run dev
```
Open the printed address and enter the teacher token `dev-teacher-token`.

## 4. Install on the phones
**Android:** copy the APK to the phone, open it, allow "Install unknown apps", install, allow Bluetooth / Nearby devices.
Android 11 and older: also switch **Location** on in system settings.

**iPhone (no Mac):** Apple only allows signed apps, so use a free sideloading tool:
1. Install iTunes and iCloud **from apple.com** (not the Microsoft Store versions) and Sideloadly (sideloadly.io).
2. Plug in the iPhone, tap Trust, drag the `.ipa` into Sideloadly, sign in with an Apple ID, press Start.
3. iPhone: Settings -> General -> VPN & Device Management -> trust your Apple ID; Settings -> Privacy & Security -> turn on **Developer Mode**.
4. A free Apple ID expires the app after 7 days (reinstall to renew). Keep Auto-Lock off while testing.

## 5. First use
1. Open the app. Enter roll number, name and the server address, then **Get started**. (Once per phone.)
2. Check **BLE lab** on two phones 1 m apart: each should list the other with rising sample counts.
3. Teacher screen: for 2-3 phones type `1` in **Witnesses k** (the default needs at least two independent supporters per student), then **Start roll call**.
4. On the phones tap **Mark me present** within 20 s; keep the app open until the countdown ends (~25 s in total).
5. Teacher screen: tick the verified seed students, optionally enter a headcount, **Close**. Review anything flagged.

## 6. Troubleshooting
| Symptom | Fix |
|---|---|
| "Can't reach http://..." in the app | Open the same address + `/docs` in the phone's browser. If that fails: same Wi-Fi? firewall (allow Python on private networks)? server started with `--host 0.0.0.0`? Try a phone hotspot. |
| iPhone says nothing / never connects | Settings -> NetPresence -> allow **Local Network** and **Bluetooth**. |
| Nobody shows up as nearby | Both screens on, 1-2 m apart, Bluetooth on; Android 11- needs Location on. |
| Registration says already enrolled | Teacher resets the device (`DELETE /api/devices/{id}`). |

## 7. Check everything without phones
```
cd backend
python -m tools.check          # tests, 93-student room study, Android+iOS fleet study, phone code vs live server (~2.5 min)
python -m tools.check --full   # + the teacher console in headless Chromium
```
GitHub runs the same command on every push (`.github/workflows/tests.yml`).

## 8. Real deployment (later)
Use MongoDB (Atlas free tier) instead of the in-memory database, set a long random `TEACHER_TOKEN`, put the API behind HTTPS
(Render/Railway/Fly), restrict CORS in `backend/app/main.py`, and remove `usesCleartextTraffic` from the Android manifest.
Free hosts sleep when idle: open the API's `/docs` a minute before class.

## 9. Publishing this repo (maintainers)
```
git remote set-url origin https://github.com/<you>/netpresence.git
git push -u origin v2-proximity-graph
git tag v0.1.0 && git push origin v0.1.0        # builds both apps and creates the Release page
```
Every push to a branch also refreshes a rolling **"Latest build"** pre-release (tag `latest`) with the newest APK and IPA,
so testers can always grab the newest build from the Releases page. If publishing is refused ("Resource not accessible by
integration"), set Settings -> Actions -> General -> **Workflow permissions** to "Read and write".
Add a LICENSE of your choice; without one, others have no permission to reuse the code.
