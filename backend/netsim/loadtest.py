"""Load test: N virtual phones (real P-256 keys, real signatures) drive a REAL NetPresence server over the REAL network.

    python -m netsim.loadtest --server http://192.168.1.20:8000 --token <TEACHER_TOKEN> --phones 93
    python -m netsim.loadtest --local --phones 93          # in-process server on mock Mongo: a dry run / the self-test

What it measures: the server, its database and the network path (registration, check-in, report burst, latency, errors,
retries with the app's exact retry ladder and request timeout, close). The radio is SIMULATED (netsim.ble_fast), so the verdict
accuracy is not a measurement of real phones. Do NOT put its output into paper/real/sessions.csv.
Every phone enrols as `lt<run>-<n>`; enrolments are permanent (delete them in the teacher console / database afterwards).
Plain Python 3.11+, httpx, numpy, cryptography.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import secrets
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path

import httpx

from app.services import crypto
from app.services.graph import adaptive_edge_m, evaluate, Params
from netsim import config
from netsim.ble_fast import synth_reports
from netsim.scenario import build_scene, platforms
from sim import protocol
from sim.phone import Device


logging.getLogger("httpx").setLevel(logging.WARNING)      # one INFO line per request would drown the report


def pctl(xs: list[float], q: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    return s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))]


async def _post(c: httpx.AsyncClient, url: str, body: dict, timeout_s: float, headers: dict | None = None):
    try:
        return await c.post(url, json=body, headers=headers, timeout=timeout_s)
    except (httpx.TimeoutException, httpx.TransportError):
        return None


async def upload_report(c, url, body, stats, deadline_t: float) -> bool:
    """submitReport as the app does it: 5 s request timeout, first retry after RETRY_START_MS, doubling up to RETRY_MAX_MS,
    stop once the server's deadline has passed or the server answers 4xx (not retried)."""
    delay = protocol.RETRY_START_MS / 1000.0
    while True:
        t0 = time.perf_counter()
        r = await _post(c, url, body, protocol.REQUEST_TIMEOUT_MS / 1000.0)
        stats["attempts"] += 1
        lat = time.perf_counter() - t0
        code = "timeout/transport" if r is None else str(r.status_code)
        stats["codes"][code] = stats["codes"].get(code, 0) + 1
        if r is not None and r.status_code == 200:
            stats["lat"].append(lat)
            return True
        if r is not None and 400 <= r.status_code < 500:
            return False
        if time.time() + delay > deadline_t:
            return False
        await asyncio.sleep(delay)
        delay = min(delay * 2, protocol.RETRY_MAX_MS / 1000.0)


async def run(base: str, token: str, phones: int, seed: int, preset: str, ios_share: float, enrol_code: str, window_s: int,
              realtime: bool, client_factory, calibrated: bool = False) -> dict:
    cfg = replace(config.load(preset, overrides=None), students=phones, capacity=max(phones, 1), ios_share=ios_share, n_outside=0)
    rng = random.Random(seed)
    nodes, seeds, wall = build_scene(cfg, rng)
    plat = platforms(cfg, nodes)
    reports = synth_reports(cfg, nodes, wall, rng, calibrate=calibrated)       # {node: {peer_node: rssi}}; raw unless --calibrated: a fresh server has no offset table
    run_id = secrets.token_hex(3)
    sid_of = {k: f"lt{run_id}-{i}" for i, k in enumerate(nodes)}
    dev = {k: Device(sid_of[k], "iPhone 13" if plat[k] == "ios" else "Pixel 6") for k in nodes}
    T = {"X-Teacher-Token": token}
    out: dict = {"phones": len(nodes), "seed": seed, "preset": preset, "server": base, "run_id": run_id,
                 "radio": "SIMULATED (netsim.ble_fast); only the server and the network are real"}
    async with client_factory() as c:
        t = time.perf_counter()
        sem = asyncio.Semaphore(32)

        async def reg(k):
            async with sem:
                body = dev[k].register_body()
                if enrol_code:
                    body["enrol_code"] = enrol_code
                r = await _post(c, f"{base}/api/devices/register", body, 15.0)
                return r is not None and r.status_code == 201
        ok = await asyncio.gather(*(reg(k) for k in nodes))
        out["register"] = {"ok": sum(ok), "seconds": round(time.perf_counter() - t, 2)}
        if not all(ok):
            out["error"] = "some enrolments failed (wrong class code? duplicate ids?)"
            return out

        r = await _post(c, f"{base}/api/sessions/start", {"window_seconds": window_s}, 15.0, T)
        if r is None or r.status_code != 200:
            out["error"] = f"could not start a session: {None if r is None else (r.status_code, r.text[:200])}"
            return out
        s = r.json(); sess = s["session_id"]

        stats = {"attempts": 0, "codes": {}, "lat": []}
        t = time.perf_counter()
        joined = [k for k in nodes if k in reports]
        eph: dict[str, str] = {}

        async def chk(k):
            async with sem:
                rr = await _post(c, f"{base}/api/sessions/{sess}/checkin",
                                 {"student_id": sid_of[k], "signature": dev[k].sign(crypto.checkin_message(sess, s["nonce"]))}, 15.0)
                if rr is not None and rr.status_code == 200:
                    eph[k] = rr.json()["eph_id"]
        await asyncio.gather(*(chk(k) for k in joined))
        out["checkin"] = {"ok": len(eph), "seconds": round(time.perf_counter() - t, 2)}

        if realtime:
            await asyncio.sleep(max(0.0, s["discovery_ends_at"] - time.time()))

        def body_for(k):
            nb = [{"peer_id": eph[p], "rssi_median": int(v), "sample_count": 20} for p, v in reports[k].items() if p in eph]
            return dev[k].report_body(sess, nb)
        bodies = {k: body_for(k) for k in eph}                                   # signing outside the timed burst
        t = time.perf_counter()
        sent = await asyncio.gather(*(upload_report(c, f"{base}/api/sessions/{sess}/report", bodies[k], stats, s["report_deadline"]) for k in eph))
        burst = time.perf_counter() - t
        lat = stats["lat"]
        out["report_burst"] = {"delivered": sum(sent), "of": len(sent), "seconds_all_in": round(burst, 2), "attempts": stats["attempts"],
                               "status_codes": stats["codes"], "latency_s": {"p50": round(pctl(lat, .5), 3), "p95": round(pctl(lat, .95), 3),
                                                                             "max": round(max(lat, default=float('nan')), 3),
                                                                             "mean": round(statistics.fmean(lat), 3) if lat else None}}

        r = await _post(c, f"{base}/api/sessions/{sess}/verify-seeds", {"student_ids": [sid_of[k] for k in seeds]}, 15.0, T)
        out["verify_seeds"] = None if r is None else r.status_code
        t = time.perf_counter()
        r = await _post(c, f"{base}/api/sessions/{sess}/close", {}, 60.0, T)
        out["close"] = {"status": None if r is None else r.status_code, "seconds": round(time.perf_counter() - t, 2)}
        if r is not None and r.status_code == 200:
            rows = {x["student_id"]: x["status"] for x in r.json()["rows"] if x["student_id"].startswith(f"lt{run_id}-")}
            present = {k for k in nodes if rows.get(sid_of[k]) == "PRESENT"}
            # the same reports through the engine in-process: the server must reach the same verdict
            expect = set(evaluate([k for k in seeds if k in reports], {k: v for k, v in reports.items() if k in eph},
                                  Params(max_edge_m=adaptive_edge_m(len(eph))), {k: plat[k] for k in nodes})["present"])
            inside = [k for k, v in nodes.items() if v["inside"] and k not in seeds]
            out["verdict"] = {"present": len(present), "marked_absent_inside": sum(1 for k in inside if k not in present),
                              "inside": len(inside), "server_equals_engine": present == expect or present == (expect | set(seeds))}
    return out


def table(o: dict) -> str:
    if "error" in o:
        return f"ERROR: {o['error']}"
    b, v = o["report_burst"], o.get("verdict", {})
    lines = [f"phones {o['phones']}  server {o['server']}  run lt{o['run_id']}", f"  {o['radio']}",
             f"  register  {o['register']['ok']}/{o['phones']} in {o['register']['seconds']} s",
             f"  check-in  {o['checkin']['ok']} in {o['checkin']['seconds']} s",
             f"  reports   {b['delivered']}/{b['of']} delivered, all in {b['seconds_all_in']} s, {b['attempts']} attempts, codes {b['status_codes']}",
             f"  latency   p50 {b['latency_s']['p50']} s  p95 {b['latency_s']['p95']} s  max {b['latency_s']['max']} s",
             f"  close     HTTP {o['close']['status']} in {o['close']['seconds']} s"]
    if v:
        lines.append(f"  verdict   {v['present']} present, {v['marked_absent_inside']}/{v['inside']} inside marked absent; "
                     f"server == engine on the same reports: {v['server_equals_engine']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", help="base URL of a running server, e.g. http://192.168.1.20:8000")
    ap.add_argument("--local", action="store_true", help="in-process server on mock Mongo (dry run / self-test)")
    ap.add_argument("--token", default=None, help="teacher token (default: env TEACHER_TOKEN or the server default)")
    ap.add_argument("--phones", type=int, default=93)
    ap.add_argument("--preset", default="class93")
    ap.add_argument("--ios-share", type=float, default=0.3)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--enrol-code", default="", help="class code, if the server has ENROL_CODE set")
    ap.add_argument("--calibrated", action="store_true", help="apply ideal per-model offsets (a server with a full device_calibration table)")
    ap.add_argument("--window", type=int, default=20)
    ap.add_argument("--realtime", action="store_true", help="wait for the discovery tail before the report burst")
    ap.add_argument("--out", default=None, help="write the JSON result here (default: paper/real/loadtest-<time>.json)")
    a = ap.parse_args(argv)
    if bool(a.server) == bool(a.local):
        ap.error("give exactly one of --server URL or --local")

    import os
    token = a.token or os.getenv("TEACHER_TOKEN")
    if a.local:
        from mongomock_motor import AsyncMongoMockClient
        from app.config import settings
        from app.db.mongo import db_instance, ensure_indexes
        from app.main import app
        token = token or settings.TEACHER_TOKEN
        base = "http://local"

        def factory():
            return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="")

        async def go():
            db_instance.db = AsyncMongoMockClient()["loadtest"]
            await ensure_indexes(db_instance.db)
            return await run(base, token, a.phones, a.seed, a.preset, a.ios_share, a.enrol_code, a.window, a.realtime, factory, a.calibrated)
    else:
        from app.config import settings
        token = token or settings.TEACHER_TOKEN
        base = a.server.rstrip("/")

        def factory():
            return httpx.AsyncClient(limits=httpx.Limits(max_connections=200))

        async def go():
            return await run(base, token, a.phones, a.seed, a.preset, a.ios_share, a.enrol_code, a.window, a.realtime, factory, a.calibrated)
    res = asyncio.run(go())
    print(table(res))
    path = Path(a.out) if a.out else Path(__file__).resolve().parents[1] / "paper" / "real" / f"loadtest-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"  saved {path}")
    return 1 if "error" in res or res.get("report_burst", {}).get("delivered", 0) < res.get("report_burst", {}).get("of", 0) else 0


if __name__ == "__main__":
    sys.exit(main())
