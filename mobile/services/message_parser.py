"""消息解析 — 服务端 JSON → 结构化对象"""

from dataclasses import dataclass, field


@dataclass
class TextSegment:
    type: str = "text"
    content: str = ""


@dataclass
class CodeSegment:
    type: str = "code"
    content: str = ""
    language: str = "text"
    raw_content: str = ""
    block_key: str = ""
    code_fingerprint: str = ""
    message_id: str = ""
    block_index: int = 0


@dataclass
class ImageSegment:
    type: str = "image"
    content: str = ""


@dataclass
class ToolResultSegment:
    type: str = "tool_result"
    tool_name: str = ""
    content: str = ""
    success: bool = True
    block_key: str = ""


Segment = TextSegment | CodeSegment | ImageSegment | ToolResultSegment


@dataclass
class ParsedMessage:
    role: str  # "AI" | "User"
    segments: list[Segment] = field(default_factory=list)
    raw_len: int = 0
    msg_id: str = ""
    source: str = ""  # "api" | "browser"


def parse_segment(seg: dict) -> Segment:
    """解析单个 segment 字典"""
    seg_type = seg.get("type", "text")

    if seg_type == "code":
        return CodeSegment(
            type="code",
            content=seg.get("code", seg.get("content", "")),
            language=seg.get("language", "text"),
            raw_content=seg.get("raw_content", ""),
            block_key=seg.get("block_key", ""),
            code_fingerprint=seg.get("code_fingerprint", ""),
            message_id=seg.get("message_id", ""),
            block_index=seg.get("block_index", 0),
        )
    elif seg_type == "image":
        return ImageSegment(
            type="image",
            content=seg.get("content", ""),
        )
    elif seg_type == "tool_result":
        return ToolResultSegment(
            type="tool_result",
            tool_name=seg.get("tool_name", ""),
            content=seg.get("content", ""),
            success=seg.get("success", True),
            block_key=seg.get("block_key", ""),
        )
    else:
        return TextSegment(
            type="text",
            content=seg.get("content", ""),
        )


def parse_messages(raw_list: list[dict]) -> list[ParsedMessage]:
    """解析 GET /api/sync/messages 的返回"""
    messages = []
    for i, raw in enumerate(raw_list):
        segments = [parse_segment(s) for s in raw.get("segments", [])]
        messages.append(ParsedMessage(
            role=raw.get("role", "AI"),
            segments=segments,
            raw_len=raw.get("raw_len", 0),
            msg_id=raw.get("id", f"msg_{i}"),
            source=raw.get("source", "browser"),
        ))
    return messages
