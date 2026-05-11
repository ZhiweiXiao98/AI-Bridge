from dataclasses import dataclass
from typing import List, Dict, Tuple


@dataclass
class WindowConfig:
    default_turns: int = 20
    step_turns: int = 10


class MessageWindowService:
    """聊天消息展示窗口服务。

    职责：
    - 管理 browser/api 两个模式当前可见轮数
    - 切换会话时恢复默认轮数
    - 按“轮数 x 2”裁剪显示消息
    - 判断是否还有更多历史可加载
    """

    def __init__(self, default_turns: int = 20, step_turns: int = 10):
        self.config = WindowConfig(
            default_turns=max(1, int(default_turns or 20)),
            step_turns=max(1, int(step_turns or 10)),
        )
        self._visible_turns = {
            'browser': self.config.default_turns,
            'api': self.config.default_turns,
        }

    def reset_for_mode(self, mode: str) -> int:
        mode = self._normalize_mode(mode)
        self._visible_turns[mode] = self.config.default_turns
        return self._visible_turns[mode]

    def expand_for_mode(self, mode: str) -> int:
        mode = self._normalize_mode(mode)
        self._visible_turns[mode] += self.config.step_turns
        return self._visible_turns[mode]

    def get_visible_turns(self, mode: str) -> int:
        mode = self._normalize_mode(mode)
        return int(self._visible_turns.get(mode, self.config.default_turns))

    def slice_messages(self, mode: str, messages: List[Dict]) -> Tuple[List[Dict], bool]:
        mode = self._normalize_mode(mode)
        all_messages = list(messages or [])
        visible_turns = self.get_visible_turns(mode)
        visible_count = max(1, visible_turns * 2)
        if len(all_messages) <= visible_count:
            return all_messages, False
        return all_messages[-visible_count:], True

    def update_config(self, default_turns: int, step_turns: int):
        self.config = WindowConfig(
            default_turns=max(1, int(default_turns or 20)),
            step_turns=max(1, int(step_turns or 10)),
        )
        for mode in ('browser', 'api'):
            self._visible_turns[mode] = self.config.default_turns

    def _normalize_mode(self, mode: str) -> str:
        return 'api' if str(mode).lower() == 'api' else 'browser'
