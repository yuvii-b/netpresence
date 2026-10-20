"""Compare the result hashes of two `paper.make` runs (e.g. Linux vs Windows CI): python -m paper.compare_hashes a.json b.json
Exit 0 only if every experiment's hash is identical. Compares `hashes` only (the code fingerprint may differ by line endings)."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def compare(a: dict, b: dict) -> list[str]:
    ha, hb = a["hashes"], b["hashes"]
    bad = [f"{k}: {ha.get(k)} != {hb.get(k)}" for k in sorted(set(ha) | set(hb)) if ha.get(k) != hb.get(k)]
    if a.get("quick") != b.get("quick"):
        bad.append(f"quick flag differs: {a.get('quick')} vs {b.get('quick')}")
    return bad


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print("usage: python -m paper.compare_hashes A/hashes.json B/hashes.json")
        return 2
    a, b = (json.loads(Path(p).read_text(encoding="utf-8")) for p in argv)
    bad = compare(a, b)
    for line in bad:
        print("MISMATCH", line)
    print(f"{len(a['hashes'])} experiments compared: " + ("IDENTICAL" if not bad else f"{len(bad)} differences"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
