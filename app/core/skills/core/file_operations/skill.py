# filename: app/core/skills/core/file_operations/skill.py
from typing import Any
from app.core.skills.base import BaseSkill, SkillMetadata, SkillParameter
from .path_utils import sanitize_path, resolve_legacy_path, is_path_allowed, path_exists
from .read_ops import read_file as read_file_op, read_lines as read_lines_op, read_file_tail as read_file_tail_op, list_files as list_files_op, file_exists as file_exists_op, stat_file as stat_file_op
from .symbol_search import search_symbols as search_symbols_op
from .write_ops import write_file as write_file_op, append_file as append_file_op
from .edit_ops import replace_in_file as replace_in_file_op, insert_after as insert_after_op, insert_before as insert_before_op
from .delete_ops import delete_text as delete_text_op, delete_between as delete_between_op, remove_section as remove_section_op
from .block_ops import replace_between as replace_between_op, replace_section as replace_section_op
from .line_ops import delete_lines as delete_lines_op, replace_lines as replace_lines_op, insert_at_line as insert_at_line_op


class FileOperationsSkill(BaseSkill):
    """文件操作 Skill"""

    def __init__(self, file_service=None):
        super().__init__()
        self.file_service = file_service
        self.path_redirects = {
            "app/ui/worker.py": "app/core/worker.py",
            "app/ui/error_reporter.py": "app/core/utils/error_reporter.py",
        }

    @property
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="file_operations",
            display_name="文件操作",
            category="file",
            description="读取、写入、列出文件和目录",
            scenario="需要查看文件内容、列出目录结构、检查文件是否存在、写入或编辑文件时",
            version="2.2.1",
            author="System",
            parameters=[
                SkillParameter(name="operation", type="str", required=True, description="操作类型"),
                SkillParameter(name="path", type="str", required=False, description="文件或目录路径"),
                SkillParameter(name="max_lines", type="int", required=False, description="最大读取行数", default=1000),
                SkillParameter(name="content", type="str", required=False, description="写入、追加、替换或插入内容"),
                SkillParameter(name="old_text", type="str", required=False, description="待替换旧文本"),
                SkillParameter(name="new_text", type="str", required=False, description="替换后新文本"),
                SkillParameter(name="target_text", type="str", required=False, description="待删除目标文本"),
                SkillParameter(name="anchor_text", type="str", required=False, description="插入锚点文本"),
                SkillParameter(name="start_anchor", type="str", required=False, description="起始锚点"),
                SkillParameter(name="end_anchor", type="str", required=False, description="结束锚点"),
                SkillParameter(name="section_header", type="str", required=False, description="Markdown 节标题"),
                SkillParameter(name="header_level", type="int", required=False, description="标题级别", default=None),
                SkillParameter(name="start_line", type="int", required=False, description="起始行号", default=1),
                SkillParameter(name="end_line", type="int", required=False, description="结束行号", default=1),
                SkillParameter(name="line_number", type="int", required=False, description="目标行号", default=1),
                SkillParameter(name="position", type="str", required=False, description="插入位置 before 或 after", default="before"),
                SkillParameter(name="count", type="int", required=False, description="替换或删除次数", default=1),
                SkillParameter(name="overwrite", type="bool", required=False, description="是否覆盖已存在文件", default=True),
                SkillParameter(name="create_dirs", type="bool", required=False, description="是否自动创建父目录", default=True),
                SkillParameter(name="ensure_newline", type="bool", required=False, description="追加前是否补换行", default=True),
                SkillParameter(name="occurrence", type="int", required=False, description="锚点命中序号", default=1),
                SkillParameter(name="strict_anchor", type="bool", required=False, description="锚点多次命中时是否要求显式指定 occurrence", default=False),
                SkillParameter(name="include_anchors", type="bool", required=False, description="区间操作时是否包含锚点", default=False),
                SkillParameter(name="atomic", type="bool", required=False, description="是否采用原子写入", default=True),
                SkillParameter(name="output_format", type="str", required=False, description="返回格式 text 或 json", default="text"),
                SkillParameter(name="confirm_large_delete", type="bool", required=False, description="是否确认高风险大删除", default=False),
                SkillParameter(name="allow_near_empty_result", type="bool", required=False, description="是否允许接近空文件结果", default=False),
                SkillParameter(name="validate_code", type="bool", required=False, description="代码和结构化配置文件编辑后是否做语法验证", default=True),
                SkillParameter(name="allow_duplicate_append", type="bool", required=False, description="是否允许追加重复内容", default=False),
            ],
            examples=[
                "file_operations(operation='read_lines', path='app/core/agent_manager.py', start_line=60, end_line=80)",
                "file_operations(operation='read_file_tail', path='AI_JOURNAL.md', max_lines=40)",
                "file_operations(operation='delete_text', path='docs/x.md', target_text='obsolete')",
                "file_operations(operation='delete_between', path='docs/x.md', start_anchor='## A', end_anchor='## B')",
                "file_operations(operation='remove_section', path='docs/x.md', section_header='## Phase C')",
                "file_operations(operation='replace_between', path='docs/x.md', start_anchor='## A', end_anchor='## B', content='new')",
                "file_operations(operation='delete_lines', path='app/core/x.py', start_line=10, end_line=20)",
                "file_operations(operation='replace_lines', path='app/core/x.py', start_line=10, end_line=12, content='x=1')",
                "file_operations(operation='insert_at_line', path='app/core/x.py', line_number=1, content='# header')",
            ],
            dangerous=False,
        )

    def _get_parameters_schema(self) -> dict:
        return {
            "operation": {
                "type": "string",
                "description": "操作类型",
                "enum": [
                    "read_file", "read_lines", "read_file_tail", "list_files", "write_file", "append_file", "replace_in_file",
                    "insert_after", "insert_before", "file_exists", "stat_file", "search_symbols",
                    "delete_text", "delete_between", "remove_section",
                    "replace_between", "replace_section",
                    "delete_lines", "replace_lines", "insert_at_line"
                ],
            },
            "path": {"type": "string", "description": "文件或目录路径"},
            "max_lines": {"type": "integer", "description": "读取文件时的最大行数", "default": 1000},
            "content": {"type": "string", "description": "写入、追加、替换或插入内容"},
            "old_text": {"type": "string", "description": "待替换旧文本"},
            "new_text": {"type": "string", "description": "替换后新文本"},
            "target_text": {"type": "string", "description": "待删除目标文本"},
            "anchor_text": {"type": "string", "description": "插入锚点文本"},
            "start_anchor": {"type": "string", "description": "起始锚点"},
            "end_anchor": {"type": "string", "description": "结束锚点"},
            "section_header": {"type": "string", "description": "Markdown 节标题"},
            "header_level": {"type": "integer", "description": "标题级别"},
            "start_line": {"type": "integer", "description": "起始行号", "default": 1},
            "end_line": {"type": "integer", "description": "结束行号", "default": 1},
            "line_number": {"type": "integer", "description": "目标行号", "default": 1},
            "position": {"type": "string", "description": "插入位置 before 或 after", "default": "before"},
            "count": {"type": "integer", "description": "替换或删除次数", "default": 1},
            "overwrite": {"type": "boolean", "description": "是否覆盖已存在文件", "default": True},
            "create_dirs": {"type": "boolean", "description": "是否自动创建父目录", "default": True},
            "ensure_newline": {"type": "boolean", "description": "追加前是否补换行", "default": True},
            "occurrence": {"type": "integer", "description": "锚点命中序号", "default": 1},
            "strict_anchor": {"type": "boolean", "description": "锚点多次命中时是否要求显式指定 occurrence", "default": False},
            "include_anchors": {"type": "boolean", "description": "区间操作时是否包含锚点", "default": False},
            "atomic": {"type": "boolean", "description": "是否采用原子写入", "default": True},
            "output_format": {"type": "string", "description": "返回格式 text 或 json", "default": "text"},
            "confirm_large_delete": {"type": "boolean", "description": "是否确认高风险大删除", "default": False},
            "allow_near_empty_result": {"type": "boolean", "description": "是否允许接近空文件结果", "default": False},
            "validate_code": {"type": "boolean", "description": "代码和结构化配置文件编辑后是否做语法验证", "default": True},
            "allow_duplicate_append": {"type": "boolean", "description": "是否允许追加重复内容", "default": False},
        }

    def _get_required_parameters(self) -> list:
        return ["operation"]

    def execute(
        self,
        operation: str,
        path: str = None,
        max_lines: int = 1000,
        content: str = None,
        old_text: str = None,
        new_text: str = None,
        target_text: str = None,
        anchor_text: str = None,
        start_anchor: str = None,
        end_anchor: str = None,
        section_header: str = None,
        header_level: int = None,
        start_line: int = 1,
        end_line: int = 1,
        line_number: int = 1,
        position: str = "before",
        count: int = 1,
        overwrite: bool = True,
        create_dirs: bool = True,
        ensure_newline: bool = True,
        occurrence: int = 1,
        strict_anchor: bool = False,
        include_anchors: bool = False,
        atomic: bool = True,
        output_format: str = "text",
        confirm_large_delete: bool = False,
        allow_near_empty_result: bool = False,
        validate_code: bool = True,
        allow_duplicate_append: bool = False,
        **kwargs,
    ) -> Any:
        path = sanitize_path(path) if path is not None else path
        if path:
            path = resolve_legacy_path(path, self.path_redirects)

        if operation == "read_file":
            if not path:
                return "❌ Error: read_file 需要 path 参数"
            if not is_path_allowed(path, self.file_service):
                return f"❌ Error: Access denied to '{path}'. Security Violation."
            if not path_exists(path):
                return f"❌ Error: File '{path}' not found."
            return read_file_op(path, max_lines)

        if operation == "read_lines":
            if not path:
                return "❌ Error: read_lines 需要 path 参数"
            if not is_path_allowed(path, self.file_service):
                return f"❌ Error: Access denied to '{path}'. Security Violation."
            if not path_exists(path):
                return f"❌ Error: File '{path}' not found."
            return read_lines_op(path, start_line=start_line, end_line=end_line)

        if operation == "read_file_tail":
            if not path:
                return "❌ Error: read_file_tail 需要 path 参数"
            if not is_path_allowed(path, self.file_service):
                return f"❌ Error: Access denied to '{path}'. Security Violation."
            if not path_exists(path):
                return f"❌ Error: File '{path}' not found."
            return read_file_tail_op(path, max_lines)

        if operation == "list_files":
            directory = path or "."
            if not is_path_allowed(directory, self.file_service):
                return f"❌ Error: Access denied to '{directory}'."
            if not path_exists(directory):
                return f"❌ Error: Directory '{directory}' not found."
            return list_files_op(directory)

        if operation == "file_exists":
            if not path:
                return "❌ Error: file_exists 需要 path 参数"
            if not is_path_allowed(path, self.file_service):
                return f"❌ Error: Access denied to '{path}'. Security Violation."
            return file_exists_op(path, output_format=output_format)

        if operation == "stat_file":
            if not path:
                return "❌ Error: stat_file 需要 path 参数"
            if not is_path_allowed(path, self.file_service):
                return f"❌ Error: Access denied to '{path}'. Security Violation."
            return stat_file_op(path, output_format=output_format)


        if operation == "search_symbols":
            if not path:
                return "❌ Error: search_symbols 需要 path 参数"
            if not is_path_allowed(path, self.file_service):
                return f"❌ Error: Access denied to '{path}'. Security Violation."
            if not path_exists(path):
                return f"❌ Error: File '{path}' not found."
            return search_symbols_op(path, output_format=output_format)
        if operation == "write_file":
            if not path or content is None:
                return "❌ Error: write_file 需要 path 和 content 参数"
            if not is_path_allowed(path, self.file_service):
                return f"❌ Error: Access denied to '{path}'. Security Violation."
            return write_file_op(path, content, create_dirs=create_dirs, overwrite=overwrite, atomic=atomic, output_format=output_format, validate_code=validate_code)

        if operation == "append_file":
            if not path or content is None:
                return "❌ Error: append_file 需要 path 和 content 参数"
            if not is_path_allowed(path, self.file_service):
                return f"❌ Error: Access denied to '{path}'. Security Violation."
            return append_file_op(path, content, ensure_newline=ensure_newline, create_dirs=create_dirs, output_format=output_format, allow_duplicate_append=allow_duplicate_append, atomic=atomic, validate_code=validate_code)

        if operation == "replace_in_file":
            if not path or old_text is None or new_text is None:
                return "❌ Error: replace_in_file 需要 path、old_text 和 new_text 参数"
            if not is_path_allowed(path, self.file_service):
                return f"❌ Error: Access denied to '{path}'. Security Violation."
            return replace_in_file_op(path, old_text, new_text, count=count, atomic=atomic, output_format=output_format, validate_code=validate_code)

        if operation == "insert_after":
            if not path or anchor_text is None or content is None:
                return "❌ Error: insert_after 需要 path、anchor_text 和 content 参数"
            if not is_path_allowed(path, self.file_service):
                return f"❌ Error: Access denied to '{path}'. Security Violation."
            return insert_after_op(path, anchor_text, content, occurrence=occurrence, strict_anchor=strict_anchor, atomic=atomic, output_format=output_format, validate_code=validate_code)

        if operation == "insert_before":
            if not path or anchor_text is None or content is None:
                return "❌ Error: insert_before 需要 path、anchor_text 和 content 参数"
            if not is_path_allowed(path, self.file_service):
                return f"❌ Error: Access denied to '{path}'. Security Violation."
            return insert_before_op(path, anchor_text, content, occurrence=occurrence, strict_anchor=strict_anchor, atomic=atomic, output_format=output_format, validate_code=validate_code)

        if operation == "delete_text":
            if not path or target_text is None:
                return "❌ Error: delete_text 需要 path 和 target_text 参数"
            if not is_path_allowed(path, self.file_service):
                return f"❌ Error: Access denied to '{path}'. Security Violation."
            return delete_text_op(path, target_text, count=count, atomic=atomic, output_format=output_format, confirm_large_delete=confirm_large_delete, allow_near_empty_result=allow_near_empty_result, validate_code=validate_code)

        if operation == "delete_between":
            if not path or start_anchor is None or end_anchor is None:
                return "❌ Error: delete_between 需要 path、start_anchor 和 end_anchor 参数"
            if not is_path_allowed(path, self.file_service):
                return f"❌ Error: Access denied to '{path}'. Security Violation."
            return delete_between_op(path, start_anchor, end_anchor, include_anchors=include_anchors, occurrence=occurrence, atomic=atomic, output_format=output_format, confirm_large_delete=confirm_large_delete, allow_near_empty_result=allow_near_empty_result, validate_code=validate_code)

        if operation == "remove_section":
            if not path or section_header is None:
                return "❌ Error: remove_section 需要 path 和 section_header 参数"
            if not is_path_allowed(path, self.file_service):
                return f"❌ Error: Access denied to '{path}'. Security Violation."
            return remove_section_op(path, section_header, header_level=header_level, atomic=atomic, output_format=output_format, confirm_large_delete=confirm_large_delete, allow_near_empty_result=allow_near_empty_result)

        if operation == "replace_between":
            if not path or start_anchor is None or end_anchor is None or content is None:
                return "❌ Error: replace_between 需要 path、start_anchor、end_anchor 和 content 参数"
            if not is_path_allowed(path, self.file_service):
                return f"❌ Error: Access denied to '{path}'. Security Violation."
            return replace_between_op(path, start_anchor, end_anchor, content, include_anchors=include_anchors, occurrence=occurrence, atomic=atomic, output_format=output_format, confirm_large_delete=confirm_large_delete, allow_near_empty_result=allow_near_empty_result, validate_code=validate_code)

        if operation == "replace_section":
            if not path or section_header is None or content is None:
                return "❌ Error: replace_section 需要 path、section_header 和 content 参数"
            if not is_path_allowed(path, self.file_service):
                return f"❌ Error: Access denied to '{path}'. Security Violation."
            return replace_section_op(path, section_header, content, header_level=header_level, atomic=atomic, output_format=output_format, confirm_large_delete=confirm_large_delete, allow_near_empty_result=allow_near_empty_result)

        if operation == "delete_lines":
            if not path:
                return "❌ Error: delete_lines 需要 path 参数"
            if not is_path_allowed(path, self.file_service):
                return f"❌ Error: Access denied to '{path}'. Security Violation."
            return delete_lines_op(path, start_line=start_line, end_line=end_line, atomic=atomic, output_format=output_format, confirm_large_delete=confirm_large_delete, allow_near_empty_result=allow_near_empty_result, validate_code=validate_code)

        if operation == "replace_lines":
            if not path or content is None:
                return "❌ Error: replace_lines 需要 path 和 content 参数"
            if not is_path_allowed(path, self.file_service):
                return f"❌ Error: Access denied to '{path}'. Security Violation."
            return replace_lines_op(path, start_line=start_line, end_line=end_line, content=content, atomic=atomic, output_format=output_format, confirm_large_delete=confirm_large_delete, allow_near_empty_result=allow_near_empty_result, validate_code=validate_code)

        if operation == "insert_at_line":
            if not path or content is None:
                return "❌ Error: insert_at_line 需要 path 和 content 参数"
            if not is_path_allowed(path, self.file_service):
                return f"❌ Error: Access denied to '{path}'. Security Violation."
            return insert_at_line_op(path, line_number=line_number, content=content, position=position, atomic=atomic, output_format=output_format, validate_code=validate_code)

        return f"❌ Error: 未知操作 '{operation}'"


__skill__ = FileOperationsSkill
