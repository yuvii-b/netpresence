"""netsim: layered network simulator for NetPresence (see docs/SIM_PLAN.md and docs/NETSIM.md).

Layers, bottom to top: channel (PHY) -> ble_fast / ble_des (link layer) -> phone (app/OS) -> uplink -> server (the REAL
engine in app.services.graph). Protocol constants are never copied here: they come from sim.protocol, which reads them
from the real server, TypeScript, Kotlin and Objective-C sources.
"""
