"""HTTP REST 封装 — 对接 AI Bridge 服务端 API"""

import os
import httpx
import logging

_DEFAULT_PORT = int(os.environ.get("BRIDGE_SERVER_PORT", "8765"))

logger = logging.getLogger("mobile.api")


class BridgeAPI:
    def __init__(self, host: str, port: int = _DEFAULT_PORT):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.token: str | None = None
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(5.0, connect=3.0),
                http2=False,
            )
        return self._client

    @property
    def ws_url(self) -> str:
        if not hasattr(self, '_device_id'):
            from utils.device_id import generate_device_id
            self._device_id = generate_device_id()
        return f"ws://{self.host}:{self.port}/ws/{self.token}/{self._device_id}"

    @property
    def device_id(self) -> str:
        if not hasattr(self, '_device_id'):
            from utils.device_id import generate_device_id
            self._device_id = generate_device_id()
        return self._device_id

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    async def login(self, username: str, password: str) -> dict:
        """POST /api/login → {'status','token','role','display_name'}"""
        client = self._get_client()
        logger.info("尝试登录: username=%r, password_len=%d, url=%s", username, len(password), f"{self.base_url}/api/login")
        resp = await client.post(
            f"{self.base_url}/api/login",
            json={"username": username, "password": password},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "ok":
            self.token = data["token"]
            logger.info("登录成功: %s (role=%s)", data.get("display_name"), data.get("role"))
        return data

    async def sync_messages(self) -> list[dict]:
        """GET /api/sync/messages → 消息数组"""
        client = self._get_client()
        resp = await client.get(
            f"{self.base_url}/api/sync/messages",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    async def sync_sessions(self) -> list[dict]:
        """GET /api/sync/sessions → 会话列表"""
        client = self._get_client()
        resp = await client.get(
            f"{self.base_url}/api/sync/sessions",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
