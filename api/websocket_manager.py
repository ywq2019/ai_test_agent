"""
WebSocket 连接管理器（含心跳保活）

心跳机制：
  - 服务端每 PING_INTERVAL 秒向所有客户端发送 {"type":"ping"}
  - 客户端回复 {"type":"pong"} 以表示存活
  - 超过 PING_TIMEOUT 秒未收到 pong 的连接视为断开，主动清理
"""
import asyncio
from typing import Dict, Set
from fastapi import WebSocket
from loguru import logger

PING_INTERVAL = 30   # 每30秒发一次 ping
PING_TIMEOUT  = 10   # 等待 pong 最多10秒


class WebSocketManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        # 记录每条连接最后一次收到 pong 的时间戳（asyncio.get_event_loop().time()）
        self._last_pong: Dict[WebSocket, float] = {}
        self._heartbeat_task: asyncio.Task | None = None

    # ── 连接管理 ──────────────────────────────────────────────────────────

    async def connect(self, websocket: WebSocket, client_id: str = "default"):
        await websocket.accept()
        if client_id not in self.active_connections:
            self.active_connections[client_id] = set()
        self.active_connections[client_id].add(websocket)
        self._last_pong[websocket] = asyncio.get_event_loop().time()
        logger.info(f"WebSocket connected: {client_id}")
        # 确保心跳任务在运行
        self._ensure_heartbeat()

    def disconnect(self, websocket: WebSocket, client_id: str = "default"):
        if client_id in self.active_connections:
            self.active_connections[client_id].discard(websocket)
            if not self.active_connections[client_id]:
                del self.active_connections[client_id]
        self._last_pong.pop(websocket, None)
        logger.info(f"WebSocket disconnected: {client_id}")

    def record_pong(self, websocket: WebSocket):
        """收到客户端 pong 时调用，更新存活时间。"""
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

    async def broadcast_all(self, message: dict):
        """广播给所有已连接的客户端。"""
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

    # ── 心跳 ──────────────────────────────────────────────────────────────

    def _ensure_heartbeat(self):
        """确保心跳任务在运行，避免重复启动。"""
        if self._heartbeat_task is None or self._heartbeat_task.done():
            try:
                loop = asyncio.get_event_loop()
                self._heartbeat_task = loop.create_task(self._heartbeat_loop())
            except RuntimeError:
                pass  # 事件循环未运行时忽略

    async def _heartbeat_loop(self):
        """周期性心跳：发 ping → 等 PING_TIMEOUT → 清理超时连接。"""
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
                    # 检查上次 pong 是否超时
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
                try:
                    await conn.close()
                except Exception:
                    pass


ws_manager = WebSocketManager()
