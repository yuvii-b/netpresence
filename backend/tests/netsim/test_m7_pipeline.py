"""M7: statistics, cache, deterministic hashes and the paper pipeline."""
import json

import numpy as np
import pytest

from netsim import metrics, runner
from netsim.experiments import IDS, Ctx, load
from paper import make


def _sq(j):
    return {"v": j * j}


def test_ratio_ci_contains_estimate_and_narrows():
    num, den = [1, 0, 2, 0, 1, 0, 0, 1], [90] * 8
    a = metrics.ratio_ci(num, den, seed=1)
    assert a["lo"] <= a["est"] <= a["hi"] and a["est"] == pytest.approx(5 / 720)
    b = metrics.ratio_ci(num * 10, den * 10, seed=1)
    assert (b["hi"] - b["lo"]) < (a["hi"] - a["lo"])


def test_ratio_ci_is_deterministic_and_handles_zero():
    assert metrics.ratio_ci([0, 0], [10, 10], seed=3) == metrics.ratio_ci([0, 0], [10, 10], seed=3)
    z = metrics.ratio_ci([0, 0, 0], [5, 5, 5])
    assert z["est"] == 0 and z["lo"] == 0 and z["hi"] == 0


def test_paired_difference_detects_a_real_gap_only():
    n, d = [5] * 30, [100] * 30
    assert metrics.paired_diff_ci(n, d, [1] * 30, d, seed=1)["significant"]
    assert not metrics.paired_diff_ci(n, d, n, d, seed=1)["significant"]


def test_mean_ci_and_quantiles():
    m = metrics.mean_ci(np.arange(100.0), seed=1)
    assert m["lo"] < 49.5 < m["hi"]
    assert metrics.quantiles(range(101), (0.5, 0.95)) == [50.0, 95.0]


def test_cache_hit_miss_and_code_invalidation(tmp_path):
    c = runner.Cache(tmp_path)
    r1 = runner.cached_map("t", _sq, [1, 2, 3], c)
    assert r1 == [{"v": 1}, {"v": 4}, {"v": 9}] and (c.hits, c.misses) == (0, 1)
    assert runner.cached_map("t", _sq, [1, 2, 3], c) == r1 and c.hits == 1
    runner.cached_map("t", _sq, [1, 2, 4], c)
    assert c.misses == 2                                  # different jobs: different key
    assert runner.cached_map("t", _sq, [1, 2, 3], runner.Cache(None)) == r1   # cache disabled still works


def test_map_jobs_parallel_equals_serial():
    assert runner.map_jobs(_sq, list(range(8)), 2) == runner.map_jobs(_sq, list(range(8)), 1)


def test_digest_ignores_float_noise_and_key_order():
    a = runner.digest(runner.round_floats({"x": 0.1 + 0.2, "y": [1, 2]}))
    b = runner.digest(runner.round_floats({"y": [1, 2], "x": 0.3}))
    assert a == b


def test_every_experiment_is_declared_completely():
    exps = load()
    assert [e["id"] for e in exps] == [f"E{i:02d}" for i in range(1, 17)] and len(IDS) == 16
    for e in exps:
        for k in ("title", "question", "trials_quick", "trials_full", "run", "plot", "table"):
            assert k in e, (e["id"], k)
        assert e["trials_quick"] <= e["trials_full"]


def _hashes(tmp_path, only, workers):
    out = tmp_path / f"o{workers}"
    assert make.main(["--quick", "--only", only, "--workers", str(workers), "--out", str(out), "--no-figures", "--no-cache",
                      "--real", str(tmp_path / "none")]) == 0
    return json.loads((out / "results" / "hashes.json").read_text())["hashes"], out


def test_pipeline_is_deterministic_across_worker_counts(tmp_path):
    h1, out = _hashes(tmp_path, "E01,E12,E14", 1)
    h2, _ = _hashes(tmp_path, "E01,E12,E14", 2)
    assert h1 == h2 and set(h1) == {"E01", "E12", "E14"}
    for sub, ext in (("results", "json"), ("tables", "md"), ("tables", "tex")):
        assert (out / sub / f"E01.{ext}").stat().st_size > 0
    assert (out / "summary.md").read_text(encoding="utf-8").count("## E") == 3


def test_missing_real_data_is_labelled_not_invented(tmp_path):
    _, out = _hashes(tmp_path, "E12", 1)
    r = json.loads((out / "results" / "E12.json").read_text())
    assert r["status"].startswith("NO REAL DATA") and "real_far" not in r["rows"][0]
    assert "NO REAL DATA" in (out / "tables" / "E12.md").read_text()


def test_real_sessions_file_is_used_when_present(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "sessions.csv").write_text("session,preset,students_inside,marked_absent_inside,outside,marked_present_outside,ios_share\n"
                                       "a,lab6,6,1,2,0,0.5\nb,lab6,6,0,2,0,0.5\n", encoding="utf-8")
    out = tmp_path / "o"
    make.main(["--quick", "--only", "E12", "--out", str(out), "--no-figures", "--no-cache", "--real", str(real)])
    r = json.loads((out / "results" / "E12.json").read_text())
    assert r["status"] == "compared" and r["rows"][0]["sessions_real"] == 2
    assert r["rows"][0]["real_far"]["est"] == pytest.approx(1 / 12, abs=1e-5)


def test_bad_real_file_fails_loudly(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "sessions.csv").write_text("session,preset\nx,lab6\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing columns"):
        make.main(["--quick", "--only", "E12", "--out", str(tmp_path / "o"), "--no-figures", "--real", str(real)])


def test_timing_is_not_part_of_the_hash():
    assert make.deterministic_part({"a": 1, "timing": {"seconds": 3}}) == {"a": 1}


def test_compare_hashes_flags_any_difference(tmp_path):
    from paper import compare_hashes as ch
    a = {"quick": True, "code": "x", "hashes": {"E01": "aa", "E02": "bb"}}
    assert ch.compare(a, {**a, "code": "y"}) == []
    assert len(ch.compare(a, {"quick": True, "hashes": {"E01": "aa", "E02": "zz"}})) == 1
    assert len(ch.compare(a, {"quick": True, "hashes": {"E01": "aa"}})) == 1
    assert len(ch.compare(a, {**a, "quick": False})) == 1
    pa, pb = tmp_path / "a.json", tmp_path / "b.json"
    pa.write_text(json.dumps(a)); pb.write_text(json.dumps(a))
    assert ch.main([str(pa), str(pb)]) == 0


# ----------------------------------------------------------------------------------------------- M9 loadtest
def test_loadtest_local_end_to_end(tmp_path, capsys):
    from netsim import loadtest
    out = tmp_path / "lt.json"
    assert loadtest.main(["--local", "--phones", "93", "--out", str(out)]) == 0
    r = json.loads(out.read_text())
    assert r["report_burst"]["delivered"] == r["report_burst"]["of"] == 93
    assert r["verdict"]["server_equals_engine"] is True and r["verdict"]["marked_absent_inside"] <= 5
    assert "SIMULATED" in r["radio"]
    assert "server == engine" in capsys.readouterr().out


def test_loadtest_requires_exactly_one_target():
    from netsim import loadtest
    with pytest.raises(SystemExit):
        loadtest.main(["--phones", "3"])


def _mock_client(handler):
    import httpx
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_upload_retries_5xx_then_succeeds(monkeypatch):
    import asyncio, time
    import httpx
    from netsim import loadtest
    monkeypatch.setattr(loadtest.protocol, "RETRY_START_MS", 5)
    monkeypatch.setattr(loadtest.protocol, "RETRY_MAX_MS", 20)
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(503 if len(calls) < 3 else 200, json={})

    async def go():
        st = {"attempts": 0, "codes": {}, "lat": []}
        async with _mock_client(handler) as c:
            ok = await loadtest.upload_report(c, "http://x/r", {}, st, time.time() + 5)
        return ok, st
    ok, st = asyncio.run(go())
    assert ok and st["attempts"] == 3 and st["codes"] == {"503": 2, "200": 1} and len(st["lat"]) == 1


def test_upload_does_not_retry_4xx_and_stops_at_deadline(monkeypatch):
    import asyncio, time
    import httpx
    from netsim import loadtest
    monkeypatch.setattr(loadtest.protocol, "RETRY_START_MS", 5)
    monkeypatch.setattr(loadtest.protocol, "RETRY_MAX_MS", 20)

    async def go(status, deadline):
        st = {"attempts": 0, "codes": {}, "lat": []}
        async with _mock_client(lambda req: httpx.Response(status, json={})) as c:
            return await loadtest.upload_report(c, "http://x/r", {}, st, deadline), st
    ok, st = asyncio.run(go(400, time.time() + 5))
    assert not ok and st["attempts"] == 1                                # "report window closed" is final
    ok, st = asyncio.run(go(503, time.time() + 0.05))
    assert not ok and 1 < st["attempts"] < 20                            # keeps trying until the deadline, then stops
