"""
WebSocket 连接管理器（含心跳保活 + 工作空间隔离）

心跳机制：
  - 服务端每 PING_INTERVAL 秒向所有客户端发送 {"type":"ping"}
  - 客户端回复 {"type":"pong"} 以表示存活
  - 超过 PING_TIMEOUT 秒未收到 pong 的连接视为断开，主动清理

工作空间隔离：
  - 客户端连接后发送 {"type":"subscribe_workspace","workspace_id":N}
  - 广播时携带 workspace_id → 只推送给订阅了该空间的连接
  - workspace_id=0 的连接（admin/未订阅）收到所有广播
"""
import asyncio
from typing import Dict, Set
from fastapi import WebSocket
from loguru import logger

PING_INTERVAL = 30   # 每30秒发一次 ping
PING_TIMEOUT  = 90   # 等待 pong 最多90秒（LLM 调用可能需要60+秒）


class WebSocketManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self._last_pong: Dict[WebSocket, float] = {}
        self._conn_workspace: Dict[WebSocket, int] = {}  # 0=未订阅/管理员
        self._heartbeat_task: asyncio.Task | None = None

    # ── 连接管理 ──────────────────────────────────────────────────────────

    async def connect(self, websocket: WebSocket, client_id: str = "default"):
        await websocket.accept()
        if client_id not in self.active_connections:
            self.active_connections[client_id] = set()
        self.active_connections[client_id].add(websocket)
        self._last_pong[websocket] = asyncio.get_event_loop().time()
        self._conn_workspace[websocket] = 0   # 默认未订阅
        logger.info(f"WebSocket connected: {client_id}")
        self._ensure_heartbeat()

    def disconnect(self, websocket: WebSocket, client_id: str = "default"):
        if client_id in self.active_connections:
            self.active_connections[client_id].discard(websocket)
            if not self.active_connections[client_id]:
                del self.active_connections[client_id]
        self._last_pong.pop(websocket, None)
        self._conn_workspace.pop(websocket, None)
        logger.info(f"WebSocket disconnected: {client_id}")

    def subscribe_workspace(self, websocket: WebSocket, workspace_id: int):
        """将连接绑定到指定工作空间。0 表示管理员/看全部。"""
        self._conn_workspace[websocket] = workspace_id or 0

    def record_pong(self, websocket: WebSocket):
        self._last_pong[websocket] = asyncio.get_event_loop().time()

    # ── 消息发送 ──────────────────────────────────────────────────────────

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Failed to send personal message: {e}")

    async def broadcast(self, message: dict, client_id: str = "default"):
        if client_id not in self.active_connections:
            return
        dead = []
        for conn in self.active_connections[client_id]:
            try:
                await conn.send_json(message)
            except Exception as e:
                logger.error(f"Failed to broadcast to {client_id}: {e}")
                dead.append(conn)
        for conn in dead:
            self.active_connections[client_id].discard(conn)
            self._last_pong.pop(conn, None)
            self._conn_workspace.pop(conn, None)

    async def broadcast_all(self, message: dict):
        """广播给所有已连接的客户端（不区分工作空间）。兼容旧逻辑。"""
        for client_id, connections in list(self.active_connections.items()):
            dead = []
            for conn in connections:
                try:
                    await conn.send_json(message)
                except Exception as e:
                    logger.error(f"Failed to broadcast_all to {client_id}: {e}")
                    dead.append(conn)
            for conn in dead:
                self.active_connections[client_id].discard(conn)
                self._last_pong.pop(conn, None)
                self._conn_workspace.pop(conn, None)

    async def broadcast_to_workspace(self, message: dict, workspace_id: int = None):
        """
        按工作空间广播。
        - workspace_id=None/0: 广播给所有连接
        - workspace_id>0: 只发给订阅了该空间的连接，或 ws=0 的管理员
        """
        ws = workspace_id or 0
        for client_id, connections in list(self.active_connections.items()):
            dead = []
            for conn in connections:
                conn_ws = self._conn_workspace.get(conn, 0)
                if ws == 0 or conn_ws == 0 or conn_ws == ws:
                    try:
                        await conn.send_json(message)
                    except Exception as e:
                        logger.error(f"Failed to broadcast_to_workspace to {client_id}: {e}")
                        dead.append(conn)
            for conn in dead:
                self.active_connections[client_id].discard(conn)
                self._last_pong.pop(conn, None)
                self._conn_workspace.pop(conn, None)

    # ── 心跳 ──────────────────────────────────────────────────────────────

    def _ensure_heartbeat(self):
        if self._heartbeat_task is None or self._heartbeat_task.done():
            try:
                loop = asyncio.get_event_loop()
                self._heartbeat_task = loop.create_task(self._heartbeat_loop())
            except RuntimeError:
                pass

    async def _heartbeat_loop(self):
        while True:
            await asyncio.sleep(PING_INTERVAL)
            if not self.active_connections:
                continue
            now = asyncio.get_event_loop().time()
            dead: list[tuple[str, WebSocket]] = []

            for client_id, connections in list(self.active_connections.items()):
                for conn in list(connections):
                    try:
                        await conn.send_json({"type": "ping"})
                    except Exception:
                        dead.append((client_id, conn))
                        continue
                    last = self._last_pong.get(conn, now)
                    if now - last > PING_INTERVAL + PING_TIMEOUT:
                        logger.warning(f"WebSocket pong timeout, closing: {client_id}")
                        dead.append((client_id, conn))

            for client_id, conn in dead:
                if client_id in self.active_connections:
                    self.active_connections[client_id].discard(conn)
                    if not self.active_connections[client_id]:
                        del self.active_connections[client_id]
                self._last_pong.pop(conn, None)
                self._conn_workspace.pop(conn, None)
                try:
                    await conn.close()
                except Exception:
                    pass


ws_manager = WebSocketManager()
