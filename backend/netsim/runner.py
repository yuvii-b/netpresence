"""Run many classrooms in parallel and cache results by configuration hash.

* Workers are top-level functions (Windows 'spawn' safe); entry points must sit under `if __name__ == "__main__":`.
* Results are cached in <cache_dir>/<hash>.json. The hash covers the experiment name, every job (config, params, seeds) AND a
  fingerprint of the simulator/engine source, so changing the code invalidates the cache automatically.
* Results are plain JSON, floats rounded to 6 digits, so two runs (and Windows vs Linux) can be compared by hash.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
FINGERPRINT_FILES = ["netsim", "app/services/graph.py", "sim/protocol.py"]


def _enc(o):
    if dataclasses.is_dataclass(o) and not isinstance(o, type):
        return {"__dc__": type(o).__name__, **dataclasses.asdict(o)}
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    if isinstance(o, Path):
        return str(o)
    if hasattr(o, "item"):                    # numpy scalars
        return o.item()
    raise TypeError(f"cannot hash {type(o).__name__}")


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, default=_enc, separators=(",", ":"))


def digest(obj) -> str:
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()[:20]


_fp: str | None = None


def code_fingerprint() -> str:
    """Hash of the source that determines simulation results (line endings normalised so Windows == Linux)."""
    global _fp
    if _fp is None:
        h = hashlib.sha256()
        files = []
        for rel in FINGERPRINT_FILES:
            p = BACKEND / rel
            files += sorted(p.rglob("*.py")) if p.is_dir() else [p]
        for f in sorted(files):
            if "__pycache__" in f.parts or "experiments" in f.parts:
                continue
            h.update(f.relative_to(BACKEND).as_posix().encode())
            h.update(f.read_bytes().replace(b"\r\n", b"\n"))
        _fp = h.hexdigest()[:16]
    return _fp


def round_floats(o, nd: int = 6):
    if isinstance(o, float):
        return round(o, nd)
    if isinstance(o, dict):
        return {k: round_floats(v, nd) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [round_floats(v, nd) for v in o]
    if hasattr(o, "item"):
        return round_floats(o.item(), nd)
    return o


class Cache:
    def __init__(self, directory: str | Path | None):
        self.dir = Path(directory) if directory else None
        if self.dir:
            self.dir.mkdir(parents=True, exist_ok=True)
        self.hits = self.misses = 0

    def get(self, key: str):
        if self.dir and (self.dir / f"{key}.json").is_file():
            try:
                v = json.loads((self.dir / f"{key}.json").read_text(encoding="utf-8"))
                self.hits += 1
                return v
            except (OSError, ValueError):
                pass
        self.misses += 1
        return None

    def put(self, key: str, value) -> None:
        if self.dir:
            tmp = self.dir / f"{key}.json.tmp"
            tmp.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
            os.replace(tmp, self.dir / f"{key}.json")


def map_jobs(fn, jobs: list, workers: int = 1) -> list:
    """fn(job) for every job, in order. `fn` must be a module-level function; jobs must be picklable."""
    if workers <= 1 or len(jobs) < 2:
        return [fn(j) for j in jobs]
    with ProcessPoolExecutor(workers) as pool:
        return list(pool.map(fn, jobs, chunksize=max(1, len(jobs) // (workers * 8))))


def cached_map(name: str, fn, jobs: list, cache: Cache, workers: int = 1) -> list:
    """Like map_jobs but remembers the answer. The key is (name, code fingerprint, canonical jobs)."""
    key = digest([name, code_fingerprint(), jobs])
    hit = cache.get(key)
    if hit is not None:
        return hit
    out = round_floats(map_jobs(fn, jobs, workers))
    cache.put(key, out)
    return out
