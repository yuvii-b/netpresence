"""The full-stack simulation as regression tests: real API, real signatures, virtual phones on benches."""
from sim.ble import SCAN_MODES, discovery_completeness
from sim.e2e import run_scenario
from sim.room import RoomConfig

CLOSED = RoomConfig(door_open=False)
OPEN = RoomConfig(door_open=True)


async def test_honest_class_with_remote_cheaters_door_closed():
    runs = [await run_scenario(CLOSED, seed=s, remote=4) for s in (1, 2, 3)]
    assert sum(r["false_absent"] for r in runs) / sum(r["inside"] for r in runs) < 0.03
    assert sum(r["remote_present"] for r in runs) == 0          # one-sided claims never admitted
    assert sum(r["corridor_present"] for r in runs) == 0
    assert all(r["teacher_workload"] >= r["remote"] for r in runs)   # every remote cheater lands in the review list


async def test_collusion_succeeds_exactly_at_k():
    assert (await run_scenario(CLOSED, seed=2, remote=0, accomplices=1))["friend_present"] == 0
    assert (await run_scenario(CLOSED, seed=2, remote=0, accomplices=2))["friend_present"] == 1
    assert (await run_scenario(CLOSED, seed=2, remote=0, accomplices=2, params={"k": 3}))["friend_present"] == 0


async def test_headcount_check_catches_leaks_when_the_cascade_rule_is_off():
    # force leaks (independent=False + open door), then let the teacher's headcount surface them
    runs = [await run_scenario(OPEN, seed=s, remote=0, params={"independent": False}, headcount=True) for s in range(100, 106)]
    leaked = sum(r["corridor_present"] for r in runs)
    caught = sum(r["corridor_caught"] for r in runs)
    assert leaked > 0 and caught / leaked >= 0.5                # measured ~74%


async def test_api_pipeline_reproduces_graph_engine_exactly():
    """Signed reports -> eph-id mapping -> per-model calibration -> flood: the server must give the same verdicts
    as running the graph engine directly on the same synthetic radio data."""
    from app.services.graph import Params
    from sim.room import trial
    for seed in (100, 101, 105):
        api = await run_scenario(OPEN, seed=seed, remote=0)
        ref = trial(OPEN, Params(), seed)
        assert (api["false_absent"], api["corridor_present"]) == (ref["false_absent"], ref["false_present"])


def test_ble_discovery_is_complete_with_continuous_scan_but_not_duty_cycled():
    assert discovery_completeness(40, 15, 250, airtime_ms=1.0) > 0.99
    win, per = SCAN_MODES["LOW_POWER"]
    assert discovery_completeness(40, 5, 250, airtime_ms=1.0, scan_window_ms=win, scan_interval_ms=per) < 0.95
