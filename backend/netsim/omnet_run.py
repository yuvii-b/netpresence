"""Run the NetPresence OMNeT++ model on one classroom (headless, or with the animated Qtenv window).

    python -m netsim.omnet_run --preset class93 --seed 1                  # headless: prints the verdict
    python -m netsim.omnet_run --preset class93 --seed 1 --gui            # opens OMNeT++ Qtenv: watch the roll call run
    python -m netsim.omnet_run --preset class93 --relays 2 --gui          # a relay attack and its detection
    python -m netsim.omnet_run --compare --seeds 12                       # OMNeT++ vs the Python simulator, same rooms

Needs OMNeT++ 6.x and the model built once (omnet/README.md). Finds the executable via $NETPRESENCE_BIN or omnet/netpresence(.exe).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from netsim import config, omnet_export

ROOT = Path(__file__).resolve().parents[2]
OMNET = ROOT / "omnet"
BACKEND = ROOT / "backend"


def find_binary() -> Path | None:
    env = os.environ.get("NETPRESENCE_BIN")
    for c in ([Path(env)] if env else []) + [OMNET / "netpresence", OMNET / "netpresence.exe"]:
        if c.is_file():
            return c
    return None


def available() -> bool:
    return find_binary() is not None


def parse_sca(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"scalar\s+(\S+)\s+(\S+)\s+(\S+)$", line)
        if m:
            out[m.group(2)] = out.get(m.group(2), 0.0) + float(m.group(3))
    return out


def run_one(cfg, seed: int, workdir: Path, relays: int = 0, gui: bool = False, engine_args: str = "") -> dict:
    exe = find_binary()
    if exe is None:
        raise RuntimeError("NetPresence OMNeT++ model not built: see omnet/README.md (or set NETPRESENCE_BIN)")
    scene = workdir / "scene"
    omnet_export.export(cfg, seed, scene, relays)
    n = sum(1 for _ in open(scene / "phones.csv")) - 1
    posix = lambda p: str(Path(p).resolve()).replace("\\", "/")
    ev = f'"{sys.executable}" -m netsim.omnet_eval {engine_args}'.replace("\\", "/").replace('"', '\\"')
    ini = workdir / "run.ini"
    ini.write_text(f'include {posix(OMNET / "omnetpp.ini")}\n[General]\nrepeat = 1\nseed-set = {seed}\n'
                   f'*.numPhones = {n}\n**.sceneDir = "{posix(scene)}"\n**.outDir = "{posix(scene)}"\n'
                   f'**.evalCommand = "{ev}"\nresult-dir = "{posix(workdir / "results")}"\n'
                   f'sim-time-limit = {cfg.window_s + cfg.tail_s + 15 + 20}s\n', encoding="ascii")
    cmd = [str(exe), "-u", "Qtenv" if gui else "Cmdenv", "-n", posix(OMNET / "src"), "-f", posix(ini), "-c", "General"]
    p = subprocess.run(cmd, cwd=str(BACKEND), capture_output=not gui, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"OMNeT++ run failed ({p.returncode}):\n{(p.stdout or '')[-1500:]}\n{(p.stderr or '')[-1500:]}")
    sca = sorted((workdir / "results").glob("*.sca"))
    return parse_sca(sca[-1]) if sca else {}


def compare(preset: str, seeds: int, overrides: dict | None, workers: int = 1) -> dict:
    """Same classrooms through both simulators: the Python fast/DES link layer and the OMNeT++ event-driven model."""
    import tempfile
    from app.services.graph import Params, adaptive_edge_m
    from netsim.server import trial
    cfg = config.load(preset, overrides=overrides)
    p = Params(max_edge_m=adaptive_edge_m(cfg.students or cfg.capacity))
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for s in range(seeds):
            py = trial(cfg, p, s)
            om = run_one(cfg, s, Path(tmp) / f"s{s}")
            rows.append({"seed": s, "py_far": py["false_absent"], "py_fpr": py["false_present"], "inside": py["inside"], "outside": py["outside"],
                         "om_far": int(om["falseAbsent"]), "om_fpr": int(om["falsePresent"]), "om_inside": int(om["inside"]),
                         "om_outside": int(om["outside"]), "om_pdus": int(om["pdus"]), "om_delivered": int(om["delivered"])})
    return {"preset": preset, "rows": rows}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", default="class93")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--seeds", type=int, default=10, help="with --compare: number of classrooms")
    ap.add_argument("--relays", type=int, default=0)
    ap.add_argument("--gui", action="store_true", help="open the OMNeT++ Qtenv window")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--keep", default=None, help="keep the run folder here (default: omnet/generated/last)")
    a = ap.parse_args(argv)
    ov = dict(s.split("=", 1) for s in a.set) or None
    if a.compare:
        res = compare(a.preset, a.seeds, ov)
        r = res["rows"]
        sums = {k: sum(x[k] for x in r) for k in ("inside", "py_far", "om_far", "outside", "py_fpr", "om_fpr", "om_pdus", "om_delivered")}
        print(f"{a.preset}: {len(r)} identical classrooms")
        print(f"  false-absent   python {100 * sums['py_far'] / sums['inside']:.2f}%   omnet {100 * sums['om_far'] / sums['inside']:.2f}%")
        if sums["outside"]:
            print(f"  corridor in    python {100 * sums['py_fpr'] / sums['outside']:.2f}%   omnet {100 * sums['om_fpr'] / sums['outside']:.2f}%")
        print(f"  omnet link layer: {sums['om_pdus']} PDUs, {sums['om_delivered']} deliveries")
        return 0
    work = Path(a.keep) if a.keep else OMNET / "generated" / "last"
    work.mkdir(parents=True, exist_ok=True)
    cfg = config.load(a.preset, overrides=ov)
    sc = run_one(cfg, a.seed, work, a.relays, a.gui)
    if sc:
        print(f"{a.preset} seed {a.seed}: inside {int(sc['inside'])}, marked absent {int(sc['falseAbsent'])}; outside {int(sc['outside'])}, "
              f"admitted {int(sc['falsePresent'])}; reports {int(sc['reportsDelivered'])}; PDUs {int(sc['pdus'])}, delivered {int(sc['delivered'])}, "
              f"collided {int(sc['collided'])}; last report at {sc['lastReportAt']:.2f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
