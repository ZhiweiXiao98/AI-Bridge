# filename: app/core/conversation_store.py
"""多对话持久化管理

职责：
- 创建/切换/删除/列出对话
- 每个对话独立 JSON 文件存储
- 与 ContextManager 联动：切换时加载/保存上下文
- 统一对话格式，兼容现有 SessionList
"""
import json
import os
import time
import uuid
from pathlib import Path
from typing import Optional

from app.core.context_manager import ContextManager, ContextConfig
from app.core.context_compaction_state import create_default_compact_state, normalize_compact_state
from app.core.project_context import ProjectContext
from app.core.logging import get_logger

logger = get_logger("app.core.conversation_store", side="worker")


class ConversationStore:
    """多对话管理器"""

    def __init__(self, storage_dir: str = None, config: Optional[ContextConfig] = None):
        if storage_dir:
            self.storage_dir = Path(storage_dir)
        else:
            self.storage_dir = Path(ProjectContext.get().get_project_root()) / "conversations"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.config = config or ContextConfig()
        self.active_id: Optional[str] = None
        self.context_manager: Optional[ContextManager] = None
        self._index: dict = {}  # {id: metadata}
        self._load_index()

    def on_project_switched(self, new_root: str, new_db_path: str):
        old_dir = self.storage_dir
        if self.active_id:
            logger.info("[ConversationStore] 保存当前对话: %s", self.active_id)
            self.save_current()
        self.storage_dir = Path(new_root) / "conversations"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.active_id = None
        self.context_manager = None
        self._index = {}
        self._load_index()
        convs = self.list_conversations()
        if convs:
            self.switch(convs[0]["id"])
        logger.info("[ConversationStore] 对话目录已切换: %s → %s (共 %d 个对话, active=%s)", old_dir, self.storage_dir, len(self._index), self.active_id)

    #============================================================
    # 索引管理
    # ============================================================

    def _index_path(self) -> Path:
        return self.storage_dir / "_index.json"

    def _load_index(self):
        """加载对话索引"""
        path = self._index_path()
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._index = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._index = {}
        # 校验：清理孤立索引（文件不存在的）
        orphans = [cid for cid in self._index if not self._conv_path(cid).exists()]
        for cid in orphans:
            del self._index[cid]
        if orphans:
            self._save_index()

    def _save_index(self):
        """保存对话索引"""
        with open(self._index_path(), "w", encoding="utf-8") as f:
            json.dump(self._index, f, indent=2, ensure_ascii=False)

    # ============================================================
    # 对话文件
    # ============================================================

    def _conv_path(self, conv_id: str) -> Path:
        return self.storage_dir / f"{conv_id}.json"

    def _save_conversation(self, conv_id: str):
        """保存单个对话的完整数据"""
        if conv_id not in self._index:
            return
        # 如果是当前活跃对话，从context_manager 提取最新状态
        data = {"meta": self._index[conv_id]}
        if conv_id == self.active_id and self.context_manager:
            data["conversation_system_prompt"] = self.get_conversation_system_prompt(conv_id)
            data["system_prompt"] = self.context_manager._system_content or ""
            data["history"] = self.context_manager.get_history()
            data["long_term"] = self.context_manager._long_term_fragments
            data["working"] = self.context_manager._working_memory
            data["token_usage"] = self.context_manager.get_token_usage()
            data["compact_state"] = self.get_compact_state(conv_id)
# 更新 meta
            meta = self._index[conv_id]
            meta["updated_at"] = time.time()
            meta["turns"] = data["token_usage"].get("history_turns", 0)
            meta["tokens_used"] = data["token_usage"].get("total_used", 0)
        else:
            # 从文件加载已有数据
            existing = self._load_conversation_data(conv_id)
            if existing:
                data = existing

        with open(self._conv_path(conv_id), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _load_conversation_data(self, conv_id: str) -> Optional[dict]:
        """读取对话文件"""
        path = self._conv_path(conv_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    def load_conversation_snapshot(self, conv_id: str) -> Optional[dict]:
        """无副作用读取指定对话快照，不修改 active_id/context_manager。"""
        if conv_id not in self._index:
            return None
        return self._load_conversation_data(conv_id)

    def get_conversation_system_prompt(self, conv_id: str) -> str:
        """读取指定对话的原始 conversation system prompt。"""
        if conv_id not in self._index:
            return ""
        data = self._load_conversation_data(conv_id) or {}
        return (
            data.get("conversation_system_prompt")
            or data.get("meta", {}).get("conversation_system_prompt")
            or ""
        )

    def set_conversation_system_prompt(self, conv_id: str, content: str) -> bool:
        """设置指定对话的原始 conversation system prompt，并持久化。"""
        if conv_id not in self._index:
            return False
        data = self._load_conversation_data(conv_id) or {"meta": self._index[conv_id]}
        data["conversation_system_prompt"] = (content or "").strip()
        if "meta" not in data or not isinstance(data["meta"], dict):
            data["meta"] = self._index[conv_id]
        with open(self._conv_path(conv_id), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True

    def get_compact_state(self, conv_id: str) -> dict:
        """读取指定对话的 compact_state。"""
        if conv_id not in self._index:
            return create_default_compact_state()
        data = self._load_conversation_data(conv_id) or {}
        return normalize_compact_state(data.get("compact_state", {}))

    def set_compact_state(self, conv_id: str, compact_state: dict) -> bool:
        """设置指定对话的 compact_state，并持久化。"""
        if conv_id not in self._index:
            return False
        data = self._load_conversation_data(conv_id) or {"meta": self._index[conv_id]}
        data["compact_state"] = normalize_compact_state(compact_state or {})
        if "meta" not in data or not isinstance(data["meta"], dict):
            data["meta"] = self._index[conv_id]
        with open(self._conv_path(conv_id), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True

    def build_context_manager_for(self, conv_id: str) -> Optional[ContextManager]:
        """为指定对话临时构建 ContextManager，不修改 active 状态。"""
        if conv_id not in self._index:
            return None
        data = self._load_conversation_data(conv_id)
        if not data:
            return None
        cm = ContextManager(self.config)
        runtime_system_prompt = data.get("system_prompt") or ""
        if runtime_system_prompt:
            cm.set_system_prompt(runtime_system_prompt)
        for frag in data.get("long_term", []):
            cm.inject_long_term([frag])
        for key, val in data.get("working", {}).items():
            cm.update_working_memory(key, val)
        for msg in data.get("history", []):
            cm.load_history_message(msg)
        return cm

    def save_context_manager_for(self, conv_id: str, cm: ContextManager) -> bool:
        """将指定 ContextManager 状态写回指定对话，不修改 active 状态。"""
        if conv_id not in self._index or not cm:
            return False
        meta = self._index[conv_id]
        token_usage = cm.get_token_usage() if hasattr(cm, 'get_token_usage') else {}
        data = {
            "meta": meta,
            "conversation_system_prompt": self.get_conversation_system_prompt(conv_id),
            "system_prompt": cm.get_system_prompt() if hasattr(cm, 'get_system_prompt') else '',
            "history": cm.get_history() if hasattr(cm, 'get_history') else [],
            "long_term": cm.get_long_term_fragments() if hasattr(cm, 'get_long_term_fragments') else [],
            "working": cm.get_working_memory() if hasattr(cm, 'get_working_memory') else {},
            "token_usage": token_usage,
            "compact_state": self.get_compact_state(conv_id),
        }
        meta["updated_at"] = time.time()
        meta["turns"] = token_usage.get("history_turns", 0)
        meta["tokens_used"] = token_usage.get("total_used", 0)
        with open(self._conv_path(conv_id), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self._save_index()
        return True

    # ============================================================
    # 公开接口
    # ============================================================

    def create(self, title: str = "新对话", system_prompt: str = "") -> str:
        """新建对话，返回 conv_id"""
        conv_id = uuid.uuid4().hex[:12]
        now = time.time()
        self._index[conv_id] = {
            "id": conv_id,
            "title": title,
            "source": "api",
            "icon": "🤖",
            "created_at": now,
            "updated_at": now,
            "last_message_at": now,
            "turns": 0,
            "tokens_used": 0,
            "manual_title": False,
            "pinned": False,
            "model_usage": None,
        }
        # 初始化空对话文件
        data = {
            "meta": self._index[conv_id],
            "conversation_system_prompt": system_prompt,
            "system_prompt": "",
            "history": [],
            "long_term": [],
            "working": {},
            "compact_state": create_default_compact_state(),
        }
        with open(self._conv_path(conv_id), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self._save_index()
        # 自动切换到新对话
        self.switch(conv_id)
        return conv_id

    def switch(self, conv_id: str) -> bool:
        """切换到指定对话"""
        if conv_id not in self._index:
            return False
        # 保存当前对话
        if self.active_id and self.context_manager:
            self.save_current()
        # 加载目标对话
        data = self._load_conversation_data(conv_id)
        if not data:
            return False
        # 重建ContextManager
        cm = ContextManager(self.config)
        runtime_system_prompt = data.get("system_prompt") or ""
        if runtime_system_prompt:
            cm.set_system_prompt(runtime_system_prompt)
        #恢复长期记忆
        for frag in data.get("long_term", []):
            cm.inject_long_term([frag])
        # 恢复工作记忆
        for key, val in data.get("working", {}).items():
            cm.update_working_memory(key, val)
        # 恢复对话历史
        for msg in data.get("history", []):
            cm.load_history_message(msg)
        self.context_manager = cm
        self.active_id = conv_id
        return True

    def delete(self, conv_id: str) -> bool:
        """删除对话。

        规则：
        - 删除非当前对话：当前 active 保持不变
        - 删除当前对话：若仍有剩余对话，自动切到排序后的第一项；否则进入空状态
        """
        if conv_id not in self._index:
            return False

        deleting_active = (conv_id == self.active_id)

        path = self._conv_path(conv_id)
        if path.exists():
            os.remove(path)
        del self._index[conv_id]
        self._save_index()

        if deleting_active:
            self.active_id = None
            self.context_manager = None
            remaining = self.list_conversations()
            if remaining:
                self.switch(remaining[0]["id"])

        return True

    def rename(self, conv_id: str, new_title: str) -> bool:
        """重命名对话"""
        if conv_id not in self._index:
            return False
        self._index[conv_id]["title"] = new_title
        self._index[conv_id]["manual_title"] = True
        self._index[conv_id]["updated_at"] = time.time()
        self._save_index()
        return True

    def get_meta(self, conv_id: str) -> Optional[dict]:
        """获取对话元数据（只读视角）"""
        return self._index.get(conv_id)

    def get_model_usage(self, conv_id: str) -> Optional[dict]:
        """读取指定对话的模型来源配置。None 表示使用全局默认。"""
        meta = self._index.get(conv_id) or {}
        usage = meta.get("model_usage")
        return usage if isinstance(usage, dict) else None

    def set_model_usage(self, conv_id: str, usage: Optional[dict]) -> bool:
        """设置指定对话使用的 Profile/Chain。传 None 表示回退全局默认。"""
        if conv_id not in self._index:
            return False
        normalized = None
        if isinstance(usage, dict):
            ref_type = str(usage.get("type") or "profile").strip()
            ref = str(usage.get("ref") or "").strip()
            if ref_type in ("profile", "chain") and ref:
                normalized = {"type": ref_type, "ref": ref}
        self._index[conv_id]["model_usage"] = normalized
        self._index[conv_id]["updated_at"] = time.time()
        data = self._load_conversation_data(conv_id) or {"meta": self._index[conv_id]}
        data["meta"] = self._index[conv_id]
        with open(self._conv_path(conv_id), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self._save_index()
        return True

    def set_pinned(self, conv_id: str, pinned: bool) -> bool:
        """设置/取消置顶。

        注意：置顶状态不应污染“最后活跃时间”排序，因此这里不修改 updated_at。
        """
        if conv_id not in self._index:
            return False
        self._index[conv_id]["pinned"] = bool(pinned)
        self._save_index()
        return True

    def touch_last_message_at(self, conv_id: str, ts: Optional[float] = None) -> bool:
        """更新最后一次真实对话时间。仅用于真实消息收发，不用于切换/重命名/置顶。"""
        if conv_id not in self._index:
            return False
        self._index[conv_id]["last_message_at"] = float(ts or time.time())
        self._save_index()
        return True

    def save_current(self):
        """保存当前活跃对话"""
        if self.active_id:
            self._save_conversation(self.active_id)
            self._save_index()

    def list_conversations(self) -> list:
        """列出所有对话，统一格式（兼容 SessionList）。

        排序规则：
        1. 置顶优先
        2. 同组内按最后一次真实对话时间（last_message_at）倒序
        """
        result = []
        for conv_id, meta in self._index.items():
            from datetime import datetime
            last_msg_ts = meta.get("last_message_at", meta.get("created_at", 0))
            last_msg_dt = datetime.fromtimestamp(last_msg_ts)
            result.append({
                "id": conv_id,
                "title": meta.get("title", "未命名"),
                "date": last_msg_dt.strftime("%m-%d %H:%M"),
                "source": "api",
                "icon": meta.get("icon", "🤖"),
                "active": conv_id == self.active_id,
                "turns": meta.get("turns", 0),
                "tokens_used": meta.get("tokens_used", 0),
                "pinned": bool(meta.get("pinned", False)),
                "model_usage": meta.get("model_usage"),
            })
        result.sort(
            key=lambda x: (
                0 if x.get("pinned", False) else 1,
                -self._index.get(x["id"], {}).get("last_message_at", self._index.get(x["id"], {}).get("created_at", 0)),
            )
        )
        return result

    def auto_title(self, conv_id: str, first_message: str):
        """根据首条消息自动生成标题。

        若用户已手动命名（manual_title=True），则禁止自动覆盖。
        """
        if conv_id not in self._index:
            return
        meta = self._index[conv_id]
        if meta.get("manual_title", False):
            return
        title = first_message.strip()[:30]
        if len(first_message.strip()) > 30:
            title += "..."
        meta["title"] = title
        meta["manual_title"] = False
        meta["updated_at"] = time.time()
        self._save_index()
