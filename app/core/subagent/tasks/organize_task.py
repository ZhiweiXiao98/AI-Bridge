from typing import List, Optional

from app.core.subagent.subagent_config import OrganizeTaskConfig
from app.core.subagent.subagent_llm import SubagentLLMRouter
from app.core.logging import get_logger
from app.core.prompt_runtime.prompt_file_loader import load_subagent_prompt
from app.core.services.doc_organizer_service import DocOrganizerService

logger = get_logger("app.core.subagent.tasks.organize_task", side="worker")


class OrganizeTask:
    def __init__(self, config: OrganizeTaskConfig, llm: SubagentLLMRouter):
        self._config = config
        self._llm = llm
        self._system_prompt = ""
        self._service = DocOrganizerService()

    def _load_system_prompt(self) -> str:
        content = load_subagent_prompt("organize")
        if content:
            self._system_prompt = content
        return self._system_prompt

    def handle(self, payload: dict = None) -> Optional[dict]:
        trigger = payload.get("trigger", "polling") if payload else "polling"

        if trigger == "convert":
            return self._handle_convert(payload or {})
        elif trigger == "scan":
            return self._handle_scan()
        else:
            return self._handle_polling()

    def _handle_convert(self, payload: dict) -> Optional[dict]:
        filename = payload.get("filename", "")
        if not filename:
            logger.warning("资料整理: convert 缺少 filename")
            return None

        output_path = self._service.convert_single(filename)
        if output_path:
            self._service.generate_index()
            return {"action": "converted", "filename": filename, "output": str(output_path)}
        return None

    def _handle_scan(self) -> Optional[dict]:
        changed = self._service.scan_changed()
        if not changed:
            return {"action": "scan", "changed_count": 0, "changed_files": []}

        filenames = [f.name for f in changed]
        return {"action": "scan", "changed_count": len(changed), "changed_files": filenames}

    def _handle_polling(self) -> Optional[dict]:
        changed = self._service.scan_changed()
        if not changed:
            return None

        converted = []
        for md_file in changed:
            try:
                out = self._service.convert_file(md_file)
                if out:
                    converted.append(out)
            except Exception as e:
                logger.warning("资料整理: 转换失败 %s | %s", md_file.name, e)

        if converted:
            self._service.generate_index()

        if not converted:
            return None

        filenames = [f.name for f in converted]
        return {"action": "polling_convert", "converted_count": len(converted), "converted_files": filenames}

    def handle_llm_analysis(self, doc_inventory: str) -> Optional[List[str]]:
        system_prompt = self._load_system_prompt()
        if not system_prompt:
            logger.warning("资料整理任务: 提示词为空，跳过 LLM 分析")
            return None

        user_prompt = (
            f"以下是项目文档清单：\n{doc_inventory}\n\n"
            f"请分析这些文档，指出过时、缺失或需要整理的问题。"
            f"最多给出 {self._config.max_findings} 条建议。"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        raw = self._llm.chat(messages, tier=self._config.model_tier)
        if not raw:
            return None

        findings = []
        for line in str(raw).strip().splitlines():
            line = line.strip().lstrip("-*0123456789. )")
            if line:
                findings.append(line)
            if len(findings) >= self._config.max_findings:
                break

        return findings if findings else None

