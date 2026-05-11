from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolIntent:
    kind: str
    name: str = ''
    arguments: Dict[str, Any] = field(default_factory=dict)
    code: str = ''
    lang: str = ''
    source: str = ''
    conversation_id: str = ''
    raw_block: str = ''
    tool_call_id: Optional[str] = None
    block_key: Optional[str] = None


@dataclass
class ToolExecutionResult:
    success: bool
    kind: str
    name: str
    output: str = ''
    error: str = ''
    conversation_id: str = ''
    display_text: str = ''
    tool_call_id: Optional[str] = None
    block_key: Optional[str] = None

@dataclass
class ToolRoundResult:
    intents: List[ToolIntent] = field(default_factory=list)
    results: List[ToolExecutionResult] = field(default_factory=list)
    has_any_tool: bool = False
    combined_feedback: str = ''
    source_protocol: str = ''
