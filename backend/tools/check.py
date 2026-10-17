"""One command for every check that does not need a real phone.

    python -m tools.check            # ~2.5 min: tests, both acceptance studies, phone protocol vs live server
    python -m tools.check --full     # + the teacher console driven in headless Chromium (needs Playwright)

The studies always run at their declared trial counts: leaks are bursty, so fewer trials fail on noise.

Exit code is non-zero if anything fails, so it works as a pre-push hook or in CI.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
ROOT = os.path.dirname(BACKEND)
CORE = os.path.join(ROOT, "mobile", "core")


def run(name: str, cmd: list[str], cwd: str, env: dict | None = None) -> bool:
    t = time.time()
    print(f"\n=== {name}\n$ {' '.join(cmd)}", flush=True)
    rc = subprocess.call(cmd, cwd=cwd, env={**os.environ, **(env or {})})
    print(f"--- {name}: {'ok' if rc == 0 else f'FAILED (exit {rc})'} in {time.time() - t:.0f} s", flush=True)
    return rc == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="also drive the teacher console in headless Chromium")
    a = ap.parse_args()
    py = sys.executable
    steps = [
        ("server + engine + simulator tests", [py, "-m", "pytest", "-q"], BACKEND, None),
        ("93-student room study", [py, "-m", "sim.orientation"], BACKEND, None),
        ("Android + iOS fleet study", [py, "-m", "sim.platforms"], BACKEND, None),
    ]
    npx = shutil.which("npx")
    if npx and os.path.isdir(os.path.join(CORE, "node_modules")):
        steps += [
            ("phone protocol unit tests", [npx, "vitest", "run", "--exclude", "test/live.test.ts"], CORE, None),
            ("phone protocol vs live server", [npx, "vitest", "run", "test/live.test.ts"], CORE, {"NP_PYTHON": py}),
        ]
    else:
        print("(skipping phone protocol tests: run `npm install` in mobile/core)")
    if a.full:
        steps.append(("teacher console in Chromium", [py, "-m", "tools.ui_e2e", "--fixture",
                                                      os.path.join(CORE, "test", "fixtures", "scene93.json")], BACKEND, None))
    t0 = time.time()
    results = [(name, run(name, cmd, cwd, env)) for name, cmd, cwd, env in steps]
    print(f"\nSummary ({time.time() - t0:.0f} s):")
    for name, ok in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(main())
