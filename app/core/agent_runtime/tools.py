"""One execution boundary for native agent tools; approvals happen before entry."""
from pathlib import Path
import json

from app.core.tool_runtime.models import ToolIntent


def normalize_tools(tools):
    result = []
    for item in tools or []:
        fn = item.get("function", item)
        if not isinstance(fn, dict) or not fn.get("name"):
            continue
        result.append({"name": fn["name"], "description": fn.get("description", ""),
                       "parameters": fn.get("parameters") or {"type": "object", "properties": {}}})
    return result


class SafeToolBridge:
    def __init__(self, executor, tools, project_root, conversation_id, project_root_getter=None):
        self.executor = executor
        self.names = frozenset(tool["name"] for tool in normalize_tools(tools))
        self.project_root = Path(project_root).resolve(strict=True)
        self.conversation_id = conversation_id
        self.project_root_getter = project_root_getter
        self._results = {}

    def __call__(self, name, arguments, call_id):
        signature = json.dumps([name, arguments], sort_keys=True, ensure_ascii=False)
        if call_id in self._results:
            prior_signature, result = self._results[call_id]
            if prior_signature != signature:
                raise RuntimeError("Tool call ID reused with different arguments")
            return result
        def denied(reason):
            return {"content": [{"type": "text", "text": reason}], "isError": True}
        if not call_id or name not in self.names or not isinstance(arguments, dict):
            return denied("Tool is not in this request's enabled catalog")
        if self.project_root_getter and Path(self.project_root_getter()).resolve() != self.project_root:
            return denied("Project changed; tool execution rejected")
        # Metadata is server-owned. Models must not spoof audit IDs or private kwargs.
        if any(str(key).startswith("_") for key in arguments):
            return denied("Private tool arguments are not accepted")
        if self.executor is None:
            return denied("Data-Bridge tool executor unavailable")
        intent = ToolIntent(kind="skill_call", name=name, arguments=dict(arguments),
                            source="pi", conversation_id=self.conversation_id,
                            tool_call_id=call_id)
        result = self.executor.execute_intent(intent)
        converted = {"content": [{"type": "text", "text": str(result.output if result.success else result.error)}],
                     "isError": not result.success,
                     "details": {"tool_call_id": call_id, "conversation_id": self.conversation_id}}
        self._results[call_id] = (signature, converted)
        return converted
