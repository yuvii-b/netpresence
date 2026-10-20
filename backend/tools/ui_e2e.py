"""Browser end-to-end test of the web teacher console.

Starts a REAL server process (in-memory DB) and the BUILT frontend, then drives the console in headless Chromium
while 100+ virtual phones (from a sim.export_scene fixture, real P-256 signatures) enrol, check in and report over HTTP.

    python -m tools.ui_e2e --fixture ../mobile/core/test/fixtures/scene93.json [--shots DIR]

Needs: pip install playwright (Chromium: the preinstalled /opt/pw-browsers/chromium is used if present), npm deps in ../frontend.
"""
import argparse
import asyncio
import json
import os
import tempfile
import re
import socket
import statistics
import subprocess
import sys
import time

import httpx
from playwright.async_api import async_playwright

from sim.phone import Device

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(os.path.dirname(BACKEND), "frontend")
TOKEN = "ui-e2e-token"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def chunks(items, n, fn):
    for i in range(0, len(items), n):
        await asyncio.gather(*[fn(x) for x in items[i:i + n]])


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        raise AssertionError(msg)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", required=True)
    ap.add_argument("--shots", default=os.path.join(tempfile.gettempdir(), "np-shots"))
    ap.add_argument("--short-by", type=int, default=3, help="teacher 'counts' this many fewer heads than are marked present")
    a = ap.parse_args()
    os.makedirs(a.shots, exist_ok=True)
    fx = json.load(open(a.fixture))
    api_port, ui_port = free_port(), free_port()
    api_url, ui_url = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{ui_port}"

    print("building frontend against", api_url)
    dist = os.path.join(tempfile.gettempdir(), f"np-ui-dist-{api_port}")
    subprocess.run(["npx", "vite", "build", "--outDir", dist, "--emptyOutDir", "--logLevel", "error"], cwd=FRONTEND, check=True,
                   env={**os.environ, "VITE_API_BASE_URL": api_url})
    procs = [
        subprocess.Popen([sys.executable, "-m", "tools.dev_server", "--port", str(api_port), "--token", TOKEN], cwd=BACKEND,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
        subprocess.Popen([sys.executable, "-m", "http.server", str(ui_port), "--bind", "127.0.0.1", "-d", dist],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
    ]
    try:
        async with httpx.AsyncClient(base_url=api_url, timeout=30) as http:
            for _ in range(100):
                try:
                    if (await http.get("/api/health")).status_code == 200:
                        break
                except httpx.TransportError:
                    await asyncio.sleep(0.2)
            else:
                raise RuntimeError("server did not start")

            T = {"X-Teacher-Token": TOKEN}
            ids = list(fx["people"])
            phones = {i: Device(i, model=fx["people"][i]["model"]) for i in ids}
            inside = [i for i in fx["expected_present"]]

            async def enrol(i):
                r = await http.post("/api/devices/register", json=phones[i].register_body())
                assert r.status_code == 201, r.text
            await chunks(ids, 25, enrol)
            for m, off in fx["calibration_offsets"].items():
                await http.put("/api/devices/calibration", json={"model": m, "rssi_offset_db": off}, headers=T)

            async with async_playwright() as p:
                exe = "/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None
                browser = await p.chromium.launch(executable_path=exe) if exe else await p.chromium.launch()
                page = await browser.new_page(viewport={"width": 1000, "height": 1400})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

                print("1) teacher starts the roll call")
                await page.goto(ui_url)
                await page.fill("input[type=password]", TOKEN)
                await page.get_by_role("button", name="Start roll call").click()
                await page.wait_for_selector("text=/Session S-/")
                check(True, "session started from the UI")

                print("2) phones check in; the console updates live over the websocket")
                o = (await http.get("/api/sessions/open")).json()
                from app.services import crypto
                async def join(i):
                    r = await http.post(f"/api/sessions/{o['session_id']}/checkin", json={
                        "student_id": i, "signature": phones[i].sign(crypto.checkin_message(o["session_id"], o["nonce"]))})
                    assert r.status_code == 200, r.text
                    phones[i].eph = r.json()["eph_id"]
                await chunks(ids, 25, join)
                await page.wait_for_selector(f"text=Checked in ({len(ids)})", timeout=20000)
                check(True, f"console shows all {len(ids)} check-ins")

                print("3) teacher ticks the front bench and confirms")
                for s in fx["seeds"]:
                    await page.locator("label", has_text=re.compile(rf"\({re.escape(s)}\)")).locator("input").check()
                await page.get_by_role("button", name=re.compile(r"Confirm \d+ verified")).click()
                await page.wait_for_selector("text=verified", timeout=10000)
                check(await page.locator("text=✓ verified").count() == len(fx["seeds"]), f"{len(fx['seeds'])} seeds shown as verified")

                print("4) phones send signed neighbour reports")
                def neighbours(i):
                    rows = []
                    for peer, rs in fx["people"][i]["samples"].items():
                        rows.append({"peer_id": phones[peer].eph, "rssi_median": int(statistics.median(rs)), "sample_count": len(rs)})
                    return rows
                async def report(i):
                    r = await http.post(f"/api/sessions/{o['session_id']}/report", json=phones[i].report_body(o["session_id"], neighbours(i)))
                    assert r.status_code == 200, r.text
                await chunks(ids, 25, report)
                await page.wait_for_selector(f"text=reports received: {len(ids)}", timeout=20000)
                check(True, f"console counts {len(ids)} reports")

                print("5) teacher counts heads (a few fewer than the system says) and closes")
                headcount = len(inside) - a.short_by
                await page.locator("input[type=number]").fill(str(headcount))
                await page.get_by_role("button", name="Close & compute attendance").click()
                await page.wait_for_selector("h3:has-text('Result')", timeout=20000)
                counts = await page.get_by_test_id("counts").inner_text()
                m = re.search(r"(\d+)\s*PRESENT\s*(\d+)\s*FLAGGED\s*(\d+)\s*ABSENT", counts)
                present, flagged, absent = map(int, m.groups())
                expected = len(inside)
                check(present == expected, f"PRESENT = {present} (engine expected {expected})")
                remote = [i for i in ids if fx["people"][i].get("remote")]
                statuses = {}
                for i in ids:
                    row = page.locator("tr", has_text=re.compile(rf"\({re.escape(i)}\)"))
                    statuses[i] = (await row.locator("td").nth(1).inner_text()).split(" ")[0]
                check(all(statuses[r] == "FLAGGED" for r in remote), f"all {len(remote)} remote cheaters FLAGGED, none present")
                check({i for i, s in statuses.items() if s == "PRESENT"} == set(inside), "the PRESENT rows are exactly the expected students")
                await page.screenshot(path=os.path.join(a.shots, "result.png"), full_page=False)

                print("6) headcount mismatch -> least-corroborated students are highlighted for review")
                warn = await page.locator(".warn").inner_text()
                check(f"You counted {headcount}" in warn and f"{expected} are marked present" in warn, "warning explains the mismatch")
                check(await page.locator("tr.review").count() == a.short_by, f"{a.short_by} rows highlighted")
                first = page.locator("tr.review").first
                who = re.search(r"\(([^)]+)\)", await first.locator("td").first.inner_text()).group(1)
                await first.get_by_role("button", name="Absent").click()
                await page.wait_for_function(f"document.querySelectorAll('tr.review').length === {a.short_by - 1}", timeout=10000)
                row = page.locator("tr", has_text=re.compile(rf"\({re.escape(who)}\)"))
                check((await row.locator("td").nth(1).inner_text()).startswith("ABSENT"), f"adjudicating {who} as ABSENT updates the row live")
                check((await row.locator("td").nth(4).inner_text()) == "teacher", "decision is attributed to the teacher")
                await page.screenshot(path=os.path.join(a.shots, "review.png"))

                srv = (await http.get(f"/api/sessions/{o['session_id']}/result", headers=T)).json()
                check({r["student_id"]: r["status"] for r in srv["rows"]}[who] == "ABSENT", "server state matches the UI")
                check(not [e for e in errors if "favicon" not in e], f"no browser console errors {errors[:2] if errors else ''}")
                await browser.close()
        print("\nUI end-to-end: ALL CHECKS PASSED")
    finally:
        for pr in procs:
            pr.terminate()


if __name__ == "__main__":
    asyncio.run(main())
