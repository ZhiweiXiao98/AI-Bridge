# filename: app/core/connection_manager.py
import logging
from fastapi import WebSocket
from typing import Dict, List
import json
import time
import datetime

from app.core.logging import get_logger

logger = get_logger("app.core.connection_manager", side="server")

class ConnectionManager:
    def __init__(self):
        # { "group_id": { "client_id": WebSocket } }
        self.active_groups: Dict[str, Dict[str, WebSocket]] = {}

        # [New] 在线用户注册表 (用于存储元数据)
        # { "client_id": { "username": str, "ip": str, "login_at": str,         "device": str } }
        self.online_registry: Dict[str, dict] = {}

    async def connect(self, websocket: WebSocket, group_id: str, client_id:     str, username: str = "Unknown", ip: str = "Unknown", verified_login: bool = False):
        await websocket.accept()

        if group_id not in self.active_groups: self.active_groups[group_id] = {}

        # 踢掉旧连接 (同 Device ID)
        if client_id in self.active_groups[group_id]:
            await self.active_groups[group_id][client_id].close()

        self.active_groups[group_id][client_id] = websocket

        # [New] 登记在线信息
        self.online_registry[client_id] = {
            "username": username,
            "verified_login": verified_login,
            "ip": ip,
            "device": client_id,
            "group": group_id,
            "login_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        print(f"🔌 [{group_id}] 客户端上线: {username} ({client_id}) @ {ip}")

    async def disconnect(self, group_id: str, client_id: str, websocket: WebSocket = None):
        if websocket is not None and self.active_groups.get(group_id, {}).get(client_id) is not websocket:
            return
        if group_id in self.active_groups:
            if client_id in self.active_groups[group_id]:
                del self.active_groups[group_id][client_id]
            if not self.active_groups[group_id]: del self.active_groups            [group_id]

        # [New] 移除登记
        if client_id in self.online_registry:
            del self.online_registry[client_id]

        print(f"❌ [{group_id}] 客户端下线: {client_id}")

    async def send_personal_message(self, message: dict, group_id: str,     client_id: str, expected_username: str = None, expected_verified_login: bool = False):
        if expected_verified_login and not self.online_registry.get(client_id, {}).get("verified_login"):
            return
        if expected_username is not None and self.online_registry.get(client_id, {}).get("username") != expected_username:
            return
        if group_id in self.active_groups and client_id in self.active_groups        [group_id]:
            await self.active_groups[group_id][client_id].send_text(json.dumps            (message))

    async def broadcast_to_group(self, message: str, target_group: str = None):
        """
        广播消息
        :param target_group: 如果为 None，广播给所有组 (Global Broadcast)；否则        只发给指定组
        """
        groups_to_send = [target_group] if target_group else self.active_groups.        keys()

        for gid in groups_to_send:
            if gid not in self.active_groups: continue
            targets = list(self.active_groups[gid].items())
            for c_id, ws in targets:
                try:
                    await ws.send_text(message)
                except Exception as e:
                    logger.warning(f"发送消息到 {c_id} 失败: {e}")

    # [New] 获取在线列表 API 接口
    def get_online_users(self):
        return list(self.online_registry.values())

manager = ConnectionManager()
