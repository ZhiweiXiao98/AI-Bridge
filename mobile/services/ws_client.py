"""WebSocket 客户端 — 连接、心跳、RPC 调用、通知分发"""

import asyncio
import json
import logging
import time

import websockets

logger = logging.getLogger("mobile.ws")

# 桌面客户端使用的 CSS selector（来自 app/core/driver/config.py）
DEFAULT_INPUT_SELECTOR = "div.aa-chat-input textarea"


class WSClient:
    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self._ws = None
        self._handlers: dict[str, list] = {}
        self.latency_ms: int = 0
        self.connected: bool = False
        self._running = False
        self._missed_pong = 0

    def on(self, msg_type: str, handler):
        """注册通知处理器"""
        self._handlers.setdefault(msg_type, []).append(handler)

    async def connect(self):
        """建立连接 + 启动心跳循环 + 消息接收循环"""
        self._running = True
        try:
            self._ws = await websockets.connect(
                self.ws_url,
                ping_interval=None,
                close_timeout=10,
            )
            self.connected = True
            self._missed_pong = 0
            logger.info("WebSocket 已连接: %s", self.ws_url)
        except Exception as e:
            self.connected = False
            logger.error("WebSocket 连接失败: %s", e)
            raise

    async def start_loops(self, page=None):
        """启动接收和心跳循环（非阻塞）"""
        asyncio.create_task(self._receive_loop(page))
        asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self):
        """每 5 秒发 ping"""
        while self._running and self.connected:
            try:
                ts = int(time.time() * 1000)
                await self._send({"action": "ping", "timestamp": ts})
                self._missed_pong += 1
                if self._missed_pong > 12:
                    logger.warning("超过 12 次未收到 pong，断开重连")
                    self.connected = False
                    break
            except Exception:
                self.connected = False
                break
            await asyncio.sleep(5)

    async def _receive_loop(self, page=None):
        """持续接收服务端消息"""
        while self._running and self.connected:
            try:
                raw = await self._ws.recv()
                data = json.loads(raw)
                msg_type = data.get("type")
                payload = data.get("payload")

                # 处理 pong
                if msg_type == "pong":
                    self._missed_pong = 0
                    self.latency_ms = int(time.time() * 1000) - payload if isinstance(payload, (int, float)) else 0
                    continue

                # 分发到注册的处理器（并发执行，不阻塞接收循环）
                handlers = self._handlers.get(msg_type, [])
                for handler in handlers:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            asyncio.create_task(handler(payload, page))
                        else:
                            handler(payload, page)
                    except Exception as e:
                        logger.warning("处理 %s 回调异常: %s", msg_type, e)

            except websockets.ConnectionClosed:
                logger.info("WebSocket 连接关闭")
                self.connected = False
                break
            except Exception as e:
                logger.warning("接收消息异常: %s", e)

    async def _send(self, data: dict):
        """发送原始 JSON"""
        if self._ws and self.connected:
            await self._ws.send(json.dumps(data))

    async def rpc(self, method: str, args: list = None, kwargs: dict = None):
        """RPC 调用"""
        await self._send({
            "action": "rpc_call",
            "method": method,
            "args": args or [],
            "kwargs": kwargs or {},
        })

    async def send_text_browser(self, text: str, selector: str = DEFAULT_INPUT_SELECTOR):
        """浏览器模式：发送文本到 Chrome 聊天输入框"""
        await self.rpc("send_text", [selector, text])

    async def send_text_api(self, text: str):
        """API 模式：直接调用 LLM API"""
        await self.rpc("api_send", [], {"text": text})

    async def new_chat(self):
        """新建对话"""
        await self.rpc("new_chat")

    async def switch_session(self, index: int):
        """切换会话"""
        await self.rpc("request_switch_session", [index])

    async def request_sync(self):
        """触发同步"""
        await self.rpc("handle_sync_request")

    async def disconnect(self):
        """断开连接"""
        self._running = False
        self.connected = False
        if self._ws:
            await self._ws.close()
