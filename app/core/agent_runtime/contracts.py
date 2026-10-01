"""Provider-independent agent lifecycle. No provider's history is replayed by the UI."""
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Protocol


@dataclass(frozen=True)
class AgentRequest:
    conversation_id: str
    request_id: str
    project_root: str
    session_dir: str
    provider: str
    model: str
    system_prompt: str = ""
    api_key: str = field(default="", repr=False)
    base_url: str = ""
    tools: list[dict] = field(default_factory=list)
    session_path: str = ""
    session_pending: bool = False
    api: str = "openai-completions"
    message: str = ""
    reasoning: bool = False
    thinking_level: str = "off"
    context_window: int = 128000
    max_tokens: int = 4096


@dataclass(frozen=True)
class AgentEvent:
    kind: str
    conversation_id: str
    request_id: str
    payload: dict[str, Any] = field(default_factory=dict)


ToolHandler = Callable[[str, dict, str], dict]


class AgentRuntime(Protocol):
    @property
    def is_running(self) -> bool: ...
    def run(self, request: AgentRequest, tool_handler: ToolHandler) -> Iterator[AgentEvent]: ...
    def approve(self, call_id: str, approved: bool) -> bool: ...
    def cancel(self) -> None: ...
    def close(self) -> None: ...
