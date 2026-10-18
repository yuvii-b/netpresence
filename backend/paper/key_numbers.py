"""Write the headline numbers of a results folder as one Markdown page, ready to copy into a paper.

    python -m paper.key_numbers [--results paper/out] [--out paper/out/KEY_NUMBERS.md]

Every number is read from results/*.json (nothing typed by hand). A missing experiment is listed, not guessed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def pct(ci, d=2):
    return f"{100 * ci['est']:.{d}f}% (95% CI {100 * ci['lo']:.{d}f}-{100 * ci['hi']:.{d}f})"


def pick(rows, **kw):
    return next(r for r in rows if all(r.get(k) == v for k, v in kw.items()))


def build(res: Path) -> str:
    def load(i):
        f = res / "results" / f"E{i:02d}.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
    e = {i: load(i) for i in range(1, 15)}
    hashes = res / "results" / "hashes.json"
    quick = json.loads(hashes.read_text()).get("quick") if hashes.is_file() else None
    out = ["# Key numbers", "",
           f"Run kind: **{'QUICK (few classrooms; do not quote)' if quick else 'full' if quick is False else 'unknown'}**. "
           "All radio/phone/human parameters are *assumed* unless a measured trace is in `paper/real/` (see E12/E13).", ""]
    missing = []

    def line(label, fn):
        try:
            out.append(f"* **{label}:** {fn()}")
        except Exception:                          # noqa: BLE001 - listed as missing
            missing.append(label)

    line("E01 false-absent, 93 students, door closed", lambda: pct(pick(e[1]["rows"], students=93, door="closed")["far"]))
    line("E01 corridor admitted, 93 students, door open", lambda: pct(pick(e[1]["rows"], students=93, door="open")["fpr"]))
    line("E01 false-absent, 20 students (stated limit)", lambda: pct(pick(e[1]["rows"], students=20, door="closed")["far"]))
    for k in (1, 2, 3):
        line(f"E03 collusion, k={k}: friend admitted with 1 / 2 / 3 accomplices",
             lambda k=k: " / ".join(pct(pick(e[3]["collusion"], k=k, accomplices=a)["success"], 0) for a in (1, 2, 3)))
    for d in (False, True):
        line(f"E03 relay (3 relays), co-location {'ON' if d else 'OFF'}: admitted / flagged / honest flagged",
             lambda d=d: (lambda r: f"{pct(r['admitted'], 1)} / {pct(r['flagged'], 1)} / {pct(r['honest_flagged'], 2)}")(pick(e[3]["relay"], defence=d, relays=3)))
    line("E04 12 dB iPhone TX asymmetry, 50% iOS: self-cal OFF -> ON",
         lambda: f"{pct(pick(e[4]['rows'], ios_share=0.5, asym_db=12.0, selfcal=False)['far'], 1)} -> {pct(pick(e[4]['rows'], ios_share=0.5, asym_db=12.0, selfcal=True)['far'])}")
    line("E04 fresh server (no per-model offset table), 20 students: with table -> without",
         lambda: f"{pct(pick(e[4]['table_rows'], students=20, model_table=True)['far'], 1)} -> {pct(pick(e[4]['table_rows'], students=20, model_table=False)['far'], 1)}")
    line("E05 wait for the verdict, window 20 s, tap median 4 s: p50 / p95 (s); manual roll call total (s)",
         lambda: (lambda r: f"{r['wait_p50_s']:.0f} / {r['wait_p95_s']:.0f}; manual {e[5]['manual']['total_s']:.0f}")(pick(e[5]["rows"], window_s=20, tap_median_s=4.0)))
    for m in ("B0 manual roll call", "B1 teacher beacon", "B2 acoustic (v1)", "B5 rotating QR", "NetPresence", "NetPresence, no co-location"):
        line(f"E09 {m} (door open, 30% iOS): false-absent / corridor admitted / proxy succeeds / time s",
             lambda m=m: (lambda r: f"{pct(r['far'], 1)} / {pct(r['fpr'], 1)} / {pct(r['proxy'], 0)} / {r['time_s']['est']:.0f}")(pick(e[9]["rows"], door="open", method=m)))
    line("E11 200 students false-absent, ttl 8 -> ttl 12", lambda: f"{pct(pick(e[11]['rows'], students=200)['far'], 1)} -> {pct(pick(e[11]['rows'], students=200)['far_ttl12'], 1)}")
    line("E14 energy per roll call (assumed currents)", lambda: (lambda r: f"{r['mAh']} mAh = {r['pct_day']}% of a 4000 mAh battery per day (6 lectures)")(pick(e[14]["rows"], method="NetPresence")))
    out += ["", "## Not measured on real phones", "E12 (simulator vs real sessions) and E13 (trace-driven channel) need data in `paper/real/`;"
            " until then they are labelled NO REAL DATA / SYNTHETIC.", ""]
    if missing:
        out += ["## Missing in this results folder", *[f"* {m}" for m in missing], ""]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default=str(HERE / "out"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    text = build(Path(a.results))
    out = Path(a.out) if a.out else Path(a.results) / "KEY_NUMBERS.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
