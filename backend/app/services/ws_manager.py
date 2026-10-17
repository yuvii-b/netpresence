import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger("netpresence.ws")

ACOUSTIC_ROOM = "__acoustic__"


class WebSocketManager:
    """Room-scoped broadcast: a v2 teacher only receives events for their session."""

    def __init__(self):
        self.rooms: dict[str, list[WebSocket]] = defaultdict(list)

    async def connect(self, room: str, websocket: WebSocket):
        await websocket.accept()
        self.rooms[room].append(websocket)

    def disconnect(self, room: str, websocket: WebSocket):
        conns = self.rooms.get(room, [])
        if websocket in conns:
            conns.remove(websocket)
        if not conns:
            self.rooms.pop(room, None)

    async def broadcast(self, room: str, message: dict):
        for connection in list(self.rooms.get(room, [])):
            try:
                await connection.send_json(message)
            except Exception:
                logger.warning("Dropping WebSocket connection after send failure.", exc_info=True)
                self.disconnect(room, connection)


ws_manager = WebSocketManager()
