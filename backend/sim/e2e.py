"""Full-stack simulation: virtual phones with REAL P-256 keys drive the REAL FastAPI app
(enrol -> check-in -> signed neighbour reports -> teacher seeds -> close), then the server's
verdicts are scored against ground truth.

    python -m sim.e2e                    # in-process app + mongomock (no services needed)
    python -m sim.e2e --seeds 5 --p-detect 0.9

Populations in each run
  * inside students (ground truth present) incl. 4 teacher-verified front-bench seeds
  * corridor phones just past the wall (checked in, genuinely close but NOT in the room)
  * remote cheaters (check in from home, claim strong links to random students; nobody confirms)
  * colluder ring (a remote friend + N in-room accomplices who fabricate mutual links)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import random
import time

import httpx
from mongomock_motor import AsyncMongoMockClient

from app.config import settings
from app.db.mongo import db_instance, ensure_indexes
from app.main import app
from app.services import crypto
from sim.room import RoomConfig, build_scene, synth_reports
from tests.conftest import Device

TEACHER = {"X-Teacher-Token": settings.TEACHER_TOKEN}
for _n in ("httpx", "httpcore", "netpresence"):
    logging.getLogger(_n).setLevel(logging.WARNING)


async def run_scenario(cfg: RoomConfig, seed: int, remote: int = 5, accomplices: int = 0, params: dict | None = None,
                       client: httpx.AsyncClient | None = None, headcount: bool = False) -> dict:
    rng = random.Random(seed)
    own = client is None
    if own:
        db_instance.db = AsyncMongoMockClient()["sim"]
        await ensure_indexes(db_instance.db)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://sim")
    try:
        nodes, seeds, wall = build_scene(cfg, rng)
        reports = synth_reports(cfg, nodes, wall, rng, calibrate=False)   # raw readings incl. per-model bias
        inside = [k for k, v in nodes.items() if v["inside"]]

        devices = {k: Device(k, model=v["model"]) for k, v in nodes.items()}
        away = [f"away{i}" for i in range(remote)]
        for k in away:
            devices[k] = Device(k, model="ref")
        if accomplices:
            devices["friend"] = Device("friend", model="ref")
        reqs = 0

        async def post(path, **kw):
            nonlocal reqs
            reqs += 1
            r = await client.post(path, **kw)
            assert r.status_code < 400, (path, r.status_code, r.text)
            return r.json()

        # server-side per-model calibration (what the lab measurement would produce)
        for m, bias in cfg.models.items():
            await client.put("/api/devices/calibration", json={"model": m, "rssi_offset_db": -bias}, headers=TEACHER)
        await asyncio.gather(*[post("/api/devices/register", json=d.register_body()) for d in devices.values()])

        t0 = time.perf_counter()
        sess = await post("/api/sessions/start", json=params or {}, headers=TEACHER)
        sid = sess["session_id"]
        sig = lambda d: d.sign(crypto.checkin_message(sid, sess["nonce"]))   # noqa: E731
        for d in devices.values():   # sequential: ephemeral-id allocation is per request
            d.eph = (await post(f"/api/sessions/{sid}/checkin", json={"student_id": d.student_id, "signature": sig(d)}))["eph_id"]

        def rows_for(k):
            return [{"peer_id": devices[p].eph, "rssi_median": int(r), "sample_count": 20} for p, r in reports[k].items()]

        claims = {k: rows_for(k) for k in nodes}
        if accomplices:
            for c in rng.sample([k for k in inside if k not in seeds], accomplices):
                # worst case: the attacker knows the server's calibration and pre-compensates their phone's bias
                fake = int(-60 + cfg.models[nodes[c]["model"]])
                claims[c].append({"peer_id": devices["friend"].eph, "rssi_median": fake, "sample_count": 20})
                claims.setdefault("friend", []).append({"peer_id": devices[c].eph, "rssi_median": -60, "sample_count": 20})
        for k in away:   # one-sided lies: strong links to random in-room students nobody confirms
            claims[k] = [{"peer_id": devices[p].eph, "rssi_median": -55, "sample_count": 20} for p in rng.sample(inside, 6)]

        await asyncio.gather(*[post(f"/api/sessions/{sid}/report", json=devices[k].report_body(sid, nb)) for k, nb in claims.items()])
        await post(f"/api/sessions/{sid}/verify-seeds", json={"student_ids": seeds}, headers=TEACHER)
        out = await post(f"/api/sessions/{sid}/close", headers=TEACHER,
                         json={"headcount": len(inside)} if headcount else None)   # teacher counts heads in the room
        elapsed = time.perf_counter() - t0
    finally:
        if own:
            await client.aclose()
            db_instance.db = None

    st = {r["student_id"]: r["status"] for r in out["rows"]}
    reviewed = {r["student_id"] for r in out["rows"] if r.get("review")}
    ins = [k for k in inside if k not in seeds]
    outs = [k for k, v in nodes.items() if not v["inside"]]
    return {
        "inside": len(ins), "false_absent": sum(st[k] != "PRESENT" for k in ins),
        "flagged_inside": sum(st[k] == "FLAGGED" for k in ins),
        "corridor": len(outs), "corridor_present": sum(st[k] == "PRESENT" for k in outs),
        "corridor_caught": sum(st[k] == "PRESENT" and k in reviewed for k in outs),
        "review_total": len(reviewed), "review_inside": sum(k in reviewed for k in ins),
        "remote": len(away), "remote_present": sum(st[k] == "PRESENT" for k in away),
        "friend_present": int(st.get("friend") == "PRESENT"),
        "teacher_workload": sum(v == "FLAGGED" for v in st.values()),
        "phones": len(devices), "requests": reqs, "seconds": round(elapsed, 2),
    }


def _agg(runs, key, over):
    d = sum(r[over] for r in runs)
    return sum(r[key] for r in runs) / d if d else 0.0


async def amain():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--p-detect", type=float, default=0.97)
    a = ap.parse_args()
    base = RoomConfig(p_detect=a.p_detect, students=93)       # a full class
    closed = RoomConfig(p_detect=a.p_detect, students=93, door_open=False)
    scenarios = [
        ("door closed: honest + corridor + 5 remote", closed, dict(), {}, False),
        ("door OPEN: same class", base, dict(), {}, False),
        ("door OPEN + teacher headcount check", base, dict(), {}, True),
        ("door open, 1 colluder for a remote friend", base, dict(accomplices=1), {}, True),
        ("door open, 2 colluders (== k)", base, dict(accomplices=2), {}, True),
        ("door open, 2 colluders, server k=3", base, dict(accomplices=2), {"k": 3}, True),
        ("door open, looser edge 3.0 m", base, dict(), {"max_edge_m": 3.0}, True),
    ]
    cfg = base
    print(f"bench-column room: {cfg.bench_cols} columns x {cfg.bench_rows} benches x {cfg.seats_per_bench} seats = "
          f"{cfg.bench_cols * cfg.bench_rows * cfg.seats_per_bench} seats, {cfg.students} students (capacity {cfg.capacity}), p_detect={a.p_detect}, {a.seeds} seeds each")
    print("teacher verifies the whole FRONT BENCH of the middle column\n")
    print(f"{'scenario':<44}{'false-abs':>10}{'corr✓':>7}{'caught':>7}{'remote✓':>8}{'friend✓':>8}{'to-review':>10}")
    for name, c, kw, params, hc in scenarios:
        runs = [await run_scenario(c, 100 + s, params=params, headcount=hc, **kw) for s in range(a.seeds)]
        friend = sum(r["friend_present"] for r in runs) / len(runs)
        leaked = sum(r["corridor_present"] for r in runs)
        caught = sum(r["corridor_caught"] for r in runs)
        print(f"{name:<44}{_agg(runs, 'false_absent', 'inside'):>10.1%}{_agg(runs, 'corridor_present', 'corridor'):>7.0%}"
              f"{(caught / leaked if leaked else 0):>7.0%}{_agg(runs, 'remote_present', 'remote'):>8.1%}{friend:>8.0%}"
              f"{sum(r['teacher_workload'] + r['review_total'] for r in runs) / len(runs):>10.1f}")
    r = runs[-1]
    print(f"\nlast run: {r['phones']} phones, {r['requests']} API requests, {r['seconds']} s in-process")
    print("corr✓ / remote✓ / friend✓ = share wrongly marked PRESENT (lower is better). caught = share of those leaked corridor phones the headcount\n"
          "check put on the teacher's review list. to-review = avg students the teacher must look at (FLAGGED + headcount review).")


if __name__ == "__main__":
    asyncio.run(amain())
