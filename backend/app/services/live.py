"""In-process hub for live roll calls: debounced re-evaluation, revision counters and long-poll wake-ups.

One process, one event loop (state is rebuilt from the database after a restart). Phones and the teacher phone long-poll
(`?since=<rev>&wait=25`); an upload schedules at most one evaluation per LIVE_EVAL_DEBOUNCE_MS, and a status change wakes
exactly the waiters that care."""
import asyncio
import time

from app.config import settings

LIVE_STATUSES = ("PRESENT", "PENDING", "FLAGGED", "ABSENT")   # what a student phone is told (NOT_JOINED has no phone to tell)


class _State:
    def __init__(self):
        self.rev = 0
        self.cond = asyncio.Condition()
        self.task = None
        self.dirty = False
        self.last_eval = 0.0
        self.last_change = time.time()
        self.snap = None                    # {"rows": [...], "counts": {...}}
        self.stat: dict[str, list] = {}     # student -> [per-student rev, status, at]
        self.result: dict[str, str] = {}
        self.closed = False
        self.latched: set[str] = set()      # students shown PRESENT: they stay PRESENT (see Hub._latch)


class Hub:
    def __init__(self):
        self._loop = None
        self._reset()

    def _reset(self):
        self.states: dict[str, _State] = {}
        self.open_rev = 0
        self._open_cond = asyncio.Condition()
        self._tasks: set = set()

    def _ensure(self):
        loop = asyncio.get_running_loop()
        if loop is not self._loop:     # tests run one loop per test; production has exactly one
            self._loop = loop
            self._reset()

    def state(self, sid: str) -> _State:
        self._ensure()
        return self.states.setdefault(sid, _State())

    def current_open_rev(self) -> int:
        self._ensure()
        return self.open_rev

    def _spawn(self, coro):
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return t

    async def _wake(self, st: _State):
        async with st.cond:
            st.cond.notify_all()

    async def bump_open(self):
        self._ensure()
        async with self._open_cond:
            self.open_rev += 1
            self._open_cond.notify_all()

    async def wait_open(self, last_rev: int, timeout: float) -> int:
        """Block until a session is opened/closed after `last_rev` (or timeout). Returns the current revision."""
        self._ensure()
        async with self._open_cond:
            try:
                await asyncio.wait_for(self._open_cond.wait_for(lambda: self.open_rev > last_rev), max(0.0, timeout))
            except asyncio.TimeoutError:
                pass
            return self.open_rev

    async def wait(self, sid: str, pred, timeout: float):
        st = self.state(sid)
        async with st.cond:
            try:
                await asyncio.wait_for(st.cond.wait_for(pred), max(0.0, timeout))
            except asyncio.TimeoutError:
                pass

    # ---- lifecycle -------------------------------------------------------------------------------------------------
    async def created(self, db, s: dict):
        self.state(s["session_id"])
        self._spawn(self._watchdog(db, s["session_id"], settings.LIVE_MAX_SECONDS))
        await self.bump_open()

    async def _watchdog(self, db, sid: str, delay: float):
        await asyncio.sleep(delay)
        from app.services import rollcall
        s = await db.sessions.find_one({"session_id": sid}, {"_id": 0})
        if s and s["status"] == "open":
            await rollcall.finish(db, s)

    async def checked_in(self, db, sid: str, student_id: str):
        st = self.state(sid)
        if student_id not in st.stat:
            st.stat[student_id] = [1, "PENDING", time.time()]
            st.rev += 1
            st.last_change = time.time()
            await self._wake(st)
        self.schedule(db, sid)

    async def touched(self, db, sid: str):
        """Seeds / adjudication / a report changed something: re-evaluate soon."""
        self.state(sid)
        self.schedule(db, sid)

    def schedule(self, db, sid: str):
        st = self.state(sid)
        if st.task and not st.task.done():
            st.dirty = True
            return
        st.task = self._spawn(self._run(db, sid, st))

    async def _run(self, db, sid: str, st: _State):
        while True:
            wait = st.last_eval + settings.LIVE_EVAL_DEBOUNCE_MS / 1000 - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            st.dirty = False
            st.last_eval = time.monotonic()
            try:
                await self.evaluate(db, sid)
            except Exception:   # never let one bad evaluation kill the loop
                import logging
                logging.getLogger("netpresence.live").exception("live evaluation failed for %s", sid)
            if not st.dirty:
                return

    async def evaluate(self, db, sid: str):
        from app.services import rollcall
        s = await db.sessions.find_one({"session_id": sid}, {"_id": 0})
        if not s or s["status"] != "open":
            return
        out = await rollcall.compute(db, s)
        await self.apply(sid, out["rows"])

    async def prepare(self, db, s: dict):
        """Make sure there is a snapshot (first look, or after a server restart)."""
        st = self.state(s["session_id"])
        if st.snap is None and not st.closed:
            await self.evaluate(db, s["session_id"])

    @staticmethod
    def _latch(st: _State, rows: list[dict]) -> list[dict]:
        """Once a student is shown PRESENT they stay PRESENT for the rest of the roll call: their phone just keeps relaying for the
        others and is never "checked" again (borderline links used to flicker Present -> Checking -> Present). Two things still apply
        at once: FLAGGED (co-location = a relayed phone, which is often admitted before its readings are sharp enough to catch it)
        and the teacher's own decision."""
        out = []
        for r in rows:
            sid = r["student_id"]
            if r["status"] == "PRESENT":
                st.latched.add(sid)
            elif sid in st.latched and r["status"] in ("PENDING", "ABSENT", "NOT_JOINED") and r.get("decided_by") != "teacher":
                r = {**r, "status": "PRESENT", "latched": True}
            elif sid in st.latched:                       # FLAGGED or a teacher decision: the latch is released
                st.latched.discard(sid)
            out.append(r)
        return out

    def latch_final(self, sid: str, rows: list[dict]) -> list[dict]:
        """Finish: the final verdict keeps everyone the phones and the teacher screen showed as Present."""
        st = self.state(sid)
        return [({**r, "status": "PRESENT", "latched": True} if r["status"] == "ABSENT" and r["student_id"] in st.latched
                 and r.get("decided_by") != "teacher" else r) for r in rows]

    async def apply(self, sid: str, rows: list[dict]):
        st = self.state(sid)
        now = time.time()
        rows = self._latch(st, rows)
        changed = st.snap is None
        counts = {"PRESENT": 0, "PENDING": 0, "FLAGGED": 0, "NOT_JOINED": 0, "ABSENT": 0}
        prev = {r["student_id"]: r["status"] for r in st.snap["rows"]} if st.snap else {}
        for r in rows:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
            if prev.get(r["student_id"]) != r["status"]:
                changed = True
            if r["status"] in LIVE_STATUSES:
                cur = st.stat.get(r["student_id"])
                if cur is None or cur[1] != r["status"]:
                    st.stat[r["student_id"]] = [(cur[0] if cur else 0) + 1, r["status"], now]
        st.snap = {"rows": rows, "counts": counts}
        if changed:
            st.rev += 1
            st.last_change = now
            await self._wake(st)

    async def publish_close(self, sid: str, rows: list[dict]):
        st = self.state(sid)
        now = time.time()
        st.closed = True
        for r in rows:
            cur = st.stat.get(r["student_id"], [0])
            st.stat[r["student_id"]] = [cur[0] + 1, "CLOSED", now]
            st.result[r["student_id"]] = r["status"]
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        st.snap = {"rows": rows, "counts": counts}
        st.rev += 1
        st.last_change = now
        await self._wake(st)
        await self.bump_open()
        asyncio.get_running_loop().call_later(600, self.states.pop, sid, None)


hub = Hub()
