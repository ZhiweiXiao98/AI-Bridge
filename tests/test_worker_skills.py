from types import SimpleNamespace

from app.core.worker_modules.worker_skills import WorkerSkillsBridge
from tests.helpers import RecordingSignal


class FakeSkillsManager:
    def __init__(self):
        self.skills = [{"id": "code_execution", "enabled": True}]
        self.toggled = []
        self.prompt = "system prompt text"

    def list_all_skills(self):
        return list(self.skills)

    def toggle_skill(self, skill_name, enabled):
        self.toggled.append((skill_name, enabled))
        return skill_name == "code_execution"

    def generate_system_prompt(self):
        return self.prompt


class FakeAgent:
    def __init__(self, skills_manager):
        self.skills_manager = skills_manager
        self.reloads = []

    def reload_skill(self, skill_name):
        self.reloads.append(skill_name)
        return skill_name == "code_execution", f"reload {skill_name}"


class FakeWorker:
    def __init__(self):
        self.skills_manager = FakeSkillsManager()
        self.agent = FakeAgent(self.skills_manager)
        self.tool_router = SimpleNamespace(skills_manager=self.skills_manager)
        self.skills_data_signal = RecordingSignal()
        self.system_prompt_signal = RecordingSignal()
        self.statuses = []

    def safe_emit_status(self, text):
        self.statuses.append(text)


def test_get_skills_list_emits_payload_and_status():
    worker = FakeWorker()
    bridge = WorkerSkillsBridge(worker)

    result = bridge.get_skills_list(client_id="client_1")

    assert result == [{"id": "code_execution", "enabled": True}]
    assert worker.skills_data_signal.payloads == [
        {
            "target_client_id": "client_1",
            "skills": [{"id": "code_execution", "enabled": True}],
        }
    ]
    assert any("已获取 1 个 Skills" in status for status in worker.statuses)


def test_toggle_skill_uses_tool_router_manager_and_refreshes_list():
    worker = FakeWorker()
    bridge = WorkerSkillsBridge(worker)

    ok = bridge.toggle_skill("code_execution", False, client_id="client_1")

    assert ok is True
    assert worker.skills_manager.toggled == [("code_execution", False)]
    assert worker.skills_data_signal.payloads[-1]["target_client_id"] == "client_1"
    assert any("已禁用 Skill: code_execution" in status for status in worker.statuses)


def test_reload_skill_uses_agent_and_refreshes_list():
    worker = FakeWorker()
    bridge = WorkerSkillsBridge(worker)

    ok = bridge.reload_skill("code_execution", client_id="client_1")

    assert ok is True
    assert worker.agent.reloads == ["code_execution"]
    assert worker.skills_data_signal.payloads[-1]["skills"] == worker.skills_manager.skills
    assert any("reload code_execution" in status for status in worker.statuses)


def test_get_system_prompt_emits_prompt_payload_and_status():
    worker = FakeWorker()
    bridge = WorkerSkillsBridge(worker)

    prompt = bridge.get_system_prompt(client_id="client_1")

    assert prompt == "system prompt text"
    assert worker.system_prompt_signal.payloads == [
        {
            "target_client_id": "client_1",
            "prompt": "system prompt text",
        }
    ]
    assert any("已生成系统提示词" in status for status in worker.statuses)
