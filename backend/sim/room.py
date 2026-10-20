"""Compatibility wrapper: the room model now lives in the `netsim` package (docs/SIM_PLAN.md).

Existing studies and tests import from here; new code should import from netsim.* directly. Nothing is defined in this
file, so there is exactly one implementation of the model.
"""
from netsim.ble_fast import synth_reports            # noqa: F401
from netsim.config import RoomConfig                 # noqa: F401
from netsim.scenario import build_scene, link_budget, platforms, seat_of   # noqa: F401
from netsim.server import collusion_trial, trial     # noqa: F401
