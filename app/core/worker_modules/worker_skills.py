# filename: app/core/worker_modules/worker_skills.py
from __future__ import annotations


class WorkerSkillsBridge:
    """RPC/UI bridge for Skills management and system prompt preview."""

    def __init__(self, worker):
        self.worker = worker

    def get_skills_list(self, client_id="Host", **kwargs):
        worker = self.worker
        try:
            skills_list = worker.agent.skills_manager.list_all_skills()
            if hasattr(worker, "skills_data_signal"):
                worker.skills_data_signal.emit(
                    {
                        "target_client_id": client_id,
                        "skills": skills_list,
                    }
                )

            worker.safe_emit_status(f"📋 已获取 {len(skills_list)} 个 Skills")
            return skills_list
        except Exception as exc:
            worker.safe_emit_status(f"❌ 获取 Skills 列表失败: {exc}")
            return None

    def toggle_skill(self, skill_name, enabled, client_id="Host", **kwargs):
        worker = self.worker
        try:
            skills_manager = getattr(getattr(worker, "tool_router", None), "skills_manager", None)
            if not skills_manager:
                worker.safe_emit_status("❌ SkillsManager 未初始化，无法切换 Skill")
                return False

            success = skills_manager.toggle_skill(skill_name, enabled)
            if success:
                status = "启用" if enabled else "禁用"
                worker.safe_emit_status(f"✅ 已{status} Skill: {skill_name}")
            else:
                worker.safe_emit_status(f"❌ Skill '{skill_name}' 不存在")

            self.get_skills_list(client_id=client_id)
            return success
        except Exception as exc:
            worker.safe_emit_status(f"❌ 切换 Skill 状态失败: {exc}")
            return False

    def reload_skill(self, skill_name, client_id="Host", **kwargs):
        worker = self.worker
        try:
            success, message = worker.agent.reload_skill(skill_name)
            if success:
                worker.safe_emit_status(f"🔄 {message}")
            else:
                worker.safe_emit_status(f"❌ {message}")
            self.get_skills_list(client_id=client_id)
            return success
        except Exception as exc:
            worker.safe_emit_status(f"❌ 重载 Skill 失败: {exc}")
            return False

    def get_system_prompt(self, client_id="Host", **kwargs):
        worker = self.worker
        try:
            skills_manager = worker.agent.skills_manager
            full_prompt = skills_manager.generate_system_prompt()
            try:
                summary_prompt = skills_manager.generate_system_prompt(summary_only=True)
            except TypeError:
                summary_prompt = None

            if summary_prompt is None:
                prompt_payload = full_prompt
            else:
                prompt_payload = {
                    "content": full_prompt,
                    "summary": summary_prompt,
                }

            if hasattr(worker, "system_prompt_signal"):
                worker.system_prompt_signal.emit(
                    {
                        "target_client_id": client_id,
                        "prompt": prompt_payload,
                    }
                )

            worker.safe_emit_status(f"📝 已生成系统提示词 (~{len(full_prompt) // 4} tokens)")
            return full_prompt
        except Exception as exc:
            worker.safe_emit_status(f"❌ 生成系统提示词失败: {exc}")
            return None
