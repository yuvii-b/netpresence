# NetPresence

An audible-tone attendance system: a teacher's browser emits a short encoded tone sequence, students' devices decode it via the microphone and submit it back to confirm attendance.

## Architecture

- **`backend/`** — FastAPI service backed by MongoDB (via Motor). Exposes REST endpoints for starting/stopping attendance sessions and submitting attendance, plus a `/ws` WebSocket that broadcasts live submission events to the teacher dashboard. Session/token/nonce state is kept in-process (see `app/services/token_service.py`) and is intentionally not persisted — it resets on every backend restart.
- **`frontend/`** — React 19 + Vite single-page app with two components: `TeacherDashboard` (starts a session and plays the tone) and `StudentScanner` (listens via the mic, decodes the tone, and submits attendance). Tone encoding/decoding lives under `frontend/src/audio/` (Goertzel-algorithm based).

See `STATUS.md` for a detailed, up-to-date gap analysis against the project's 12-week plan.

## Backend setup

```bash
cd backend
python -m venv venv
./venv/Scripts/activate   # or `source venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
cp .env.example .env      # adjust MONGO_URL/DB_NAME if needed
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Requires a running MongoDB instance reachable at `MONGO_URL`.

## Frontend setup

```bash
cd frontend
npm install
npm run dev
```

By default the frontend points at whatever backend URL is set in `frontend/src/services/api.js`. To point it at a different backend (e.g. a local one) without editing source, create `frontend/.env.local` with:

```
VITE_API_BASE_URL=http://localhost:8000
VITE_WS_BASE_URL=ws://localhost:8000/ws
```

## Known limitations

No authentication, in-memory-only session state, fixed (non-rolling) session expiry, and other deliberate deferrals for the current phase of the plan are tracked in `STATUS.md`.
