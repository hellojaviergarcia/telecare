# Copyright (C) 2026 Javier Garcia
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import asyncio

from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        self._connections: dict[int, list[WebSocket]] = {}

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.setdefault(user_id, []).append(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        connections = self._connections.get(user_id, [])
        if websocket in connections:
            connections.remove(websocket)
        if not connections and user_id in self._connections:
            self._connections.pop(user_id, None)

    async def send(self, user_id: int, payload: dict) -> None:
        connections = list(self._connections.get(user_id, []))
        for websocket in connections:
            try:
                await websocket.send_json(payload)
            except Exception:
                self.disconnect(user_id, websocket)

    async def send_many(self, user_ids: list[int | None], payload: dict) -> None:
        tasks = [self.send(user_id, payload) for user_id in dict.fromkeys([uid for uid in user_ids if uid is not None])]
        if tasks:
            await asyncio.gather(*tasks)

manager = ConnectionManager()

def refresh_payload(reason: str) -> dict:
    return {"event": "dashboard_refresh", "reason": reason}
