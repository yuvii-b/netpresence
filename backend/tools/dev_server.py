"""Run the API with an in-memory database (no MongoDB needed) - for demos, UI work and cross-language tests.

    python -m tools.dev_server [--port 8000] [--token dev-teacher-token]
A demo teacher (code DEMO-TEACH) with subjects CS301 and NW204 is seeded unless --no-demo.
State is lost on restart. Never use this in production.
"""
import argparse
import os

import uvicorn

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--token", default="dev-teacher-token")
    ap.add_argument("--no-demo", action="store_true", help="do not seed the demo teacher / subjects")
    a = ap.parse_args()
    os.environ["NP_INMEMORY_DB"] = "1"
    os.environ["TEACHER_TOKEN"] = a.token
    os.environ["NP_SEED_DEMO"] = "0" if a.no_demo else "1"
    uvicorn.run("app.main:app", host=a.host, port=a.port, log_level="warning")
