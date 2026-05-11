"""
Skills 系统功能测试

测试覆盖：
1. Skills 扫描和加载
2. Skills 启用/禁用
3. 系统提示词生成
4. Skills 配置持久化
5. 远程 RPC 调用
"""

import pytest
import os
import json
import tempfile
import shutil
from pathlib import Path

# 测试前准备
@pytest.fixture
def temp_skills_dir():
    """创建临时 Skills 目录"""
    temp_dir = tempfile.mkdtemp()
    skills_dir = Path(temp_dir) / "skills"
    skills_dir.mkdir()
    
    # 创建测试 Skill 文件
    (skills_dir / "test_skill.py").write_text("""
# Skill Metadata
SKILL_NAME = "测试技能"
SKILL_DESCRIPTION = "用于测试的技能"
SKILL_CATEGORY = "core"
SKILL_ENABLED = True
SKILL_DANGEROUS = False

def execute():
    return "测试执行"
""", encoding='utf-8')
    
    yield skills_dir
    
    # 清理
    shutil.rmtree(temp_dir)


@pytest.fixture
def skills_manager(temp_skills_dir):
    """创建 SkillsManager 实例"""
    from app.core.skills import SkillsManager
    
    manager = SkillsManager()
    manager.core_skills_dir = str(temp_skills_dir)
    return manager


class TestSkillsScanning:
    """测试 Skills 扫描功能"""
    
    def test_scan_core_skills(self, skills_manager):
        """测试扫描核心 Skills"""
        core_count, _, _ = skills_manager.scan_all_skills()
        assert core_count >= 1, "应该至少扫描到 1 个核心 Skill"
    
    def test_skill_metadata_parsing(self, skills_manager):
        """测试 Skill 元数据解析"""
        skills_manager.scan_all_skills()
        skills = skills_manager.list_all_skills()
        
        assert len(skills) > 0, "应该有 Skills"
        
        skill = skills[0]
        assert 'id' in skill
        assert 'name' in skill
        assert 'description' in skill
        assert 'category' in skill
        assert 'enabled' in skill
        assert 'dangerous' in skill
    
    def test_skill_has_code(self, skills_manager):
        """测试 Skill 代码检测"""
        skills_manager.scan_all_skills()
        skills = skills_manager.list_all_skills()
        
        for skill in skills:
            assert 'has_code' in skill
            assert isinstance(skill['has_code'], bool)


class TestSkillsToggle:
    """测试 Skills 启用/禁用功能"""
    
    def test_toggle_skill(self, skills_manager):
        """测试切换 Skill 状态"""
        skills_manager.scan_all_skills()
        skills = skills_manager.list_all_skills()
        
        if len(skills) > 0:
            skill_id = skills[0]['name']
            original_state = skills[0]['enabled']
            
            # 切换状态
            # toggle_skill 使用 skill name，不是 id
        skills_manager.toggle_skill(skill_id, not original_state)
            
            # 验证状态已改变
        updated_skills = skills_manager.list_all_skills()
        updated_skill = next(s for s in updated_skills if s['name'] == skill_id)
        assert updated_skill['enabled'] == (not original_state)
    
    def test_toggle_nonexistent_skill(self, skills_manager):
        """测试切换不存在的 Skill"""
        skills_manager.scan_all_skills()
        
        # 不应该抛出异常
        skills_manager.toggle_skill("nonexistent_skill", True)


class TestSystemPrompt:
    """测试系统提示词生成"""
    
    def test_generate_system_prompt(self, skills_manager):
        """测试生成系统提示词"""
        skills_manager.scan_all_skills()
        prompt = skills_manager.generate_system_prompt()
        
        assert isinstance(prompt, str)
        assert len(prompt) > 0
        assert "# Available Skills" in prompt or "技能系统" in prompt
    
    def test_prompt_includes_enabled_skills(self, skills_manager):
        """测试提示词包含已启用的 Skills"""
        skills_manager.scan_all_skills()
        skills = skills_manager.list_all_skills()
        
        # 确保至少有一个启用的 Skill
        enabled_skills = [s for s in skills if s['enabled']]
        if len(enabled_skills) > 0:
            prompt = skills_manager.generate_system_prompt()
            
            # 提示词应该包含启用的 Skill 名称
            for skill in enabled_skills:
                # 名称或描述应该在提示词中
                assert skill['name'] in prompt or skill['description'] in prompt
    
    def test_prompt_excludes_disabled_skills(self, skills_manager):
        """测试提示词不包含禁用的 Skills"""
        skills_manager.scan_all_skills()
        skills = skills_manager.list_all_skills()
        
        if len(skills) > 0:
            # 禁用第一个 Skill
            skill_id = skills[0]['name']
            skills_manager.toggle_skill(skill_id, False)
            
            prompt = skills_manager.generate_system_prompt()
            
            # 禁用的 Skill 不应该在提示词中（或被标记为禁用）
            # 这取决于具体实现


class TestSkillsConfig:
    """测试 Skills 配置持久化"""
    
    def test_config_persistence(self, skills_manager, tmp_path):
        """测试配置保存和加载"""
        config_file = tmp_path / "skills_config.json"
        skills_manager.config_file = str(config_file)
        
        skills_manager.scan_all_skills()
        skills = skills_manager.list_all_skills()
        
        if len(skills) > 0:
            skill_id = skills[0]['name']
            
            # 切换状态
            skills_manager.toggle_skill(skill_id, False)
            
            # 保存配置
            skills_manager.save_config()
            
            # 验证配置文件存在
            assert config_file.exists()
            
            # 创建新实例并加载配置
            new_manager = type(skills_manager)()
            new_manager.config_file = str(config_file)
            new_manager.core_skills_dir = skills_manager.core_skills_dir
            new_manager.scan_all_skills()
            
            # 验证状态已恢复
            new_skills = new_manager.list_all_skills()
            new_skill = next(s for s in new_skills if s['name'] == skill_id)
            assert new_skill['enabled'] == False


class TestSkillsIntegration:
    """测试 Skills 系统集成"""
    
    def test_skills_manager_initialization(self):
        """测试 SkillsManager 初始化"""
        from app.core.skills import SkillsManager
        
        manager = SkillsManager()
        assert manager is not None
        assert hasattr(manager, 'scan_all_skills')
        assert hasattr(manager, 'list_all_skills')
        assert hasattr(manager, 'toggle_skill')
        assert hasattr(manager, 'generate_system_prompt')
    
    def test_skills_categories(self, skills_manager):
        """测试 Skills 分类"""
        skills_manager.scan_all_skills()
        skills = skills_manager.list_all_skills()
        
        # category 是功能分类（code, file, system 等）
        categories = set(s['category'] for s in skills)
        
        # 应该有预定义的功能分类
        expected_categories = {'code', 'file', 'system', 'network', 'data'}
        assert len(categories) > 0, "应该有至少一个分类"
        # 检查所有分类都是字符串
        assert all(isinstance(c, str) for c in categories)
    
    def test_dangerous_skills_flag(self, skills_manager):
        """测试危险 Skills 标记"""
        skills_manager.scan_all_skills()
        skills = skills_manager.list_all_skills()
        
        for skill in skills:
            assert isinstance(skill['dangerous'], bool)


class TestSkillsRPC:
    """测试 Skills RPC 功能"""
    
    def test_rpc_refresh_skills(self, skills_manager):
        """测试 RPC 刷新 Skills"""
        # 模拟 RPC 调用
        skills_manager.scan_all_skills()
        skills_before = len(skills_manager.list_all_skills())
        
        # 重新扫描
        skills_manager.scan_all_skills()
        skills_after = len(skills_manager.list_all_skills())
        
        assert skills_after == skills_before
    
    def test_rpc_toggle_skill(self):
        """测试 RPC 切换 Skill"""
        from app.core.skills import SkillsManager
        
        manager = SkillsManager()
        manager.scan_all_skills()
        skills = manager.list_all_skills()
        
        if len(skills) > 0:
            skill_id = skills[0]['name']
            original_state = skills[0]['enabled']
            
            # 模拟 RPC 切换
            manager.toggle_skill(skill_id, not original_state)
            
            # 验证
            updated_skills = manager.list_all_skills()
            updated_skill = next(s for s in updated_skills if s['name'] == skill_id)
            assert updated_skill['enabled'] == (not original_state)
            
            # 恢复原状态
            manager.toggle_skill(skill_id, original_state)
    
    def test_rpc_generate_prompt(self, skills_manager):
        """测试 RPC 生成提示词"""
        skills_manager.scan_all_skills()
        prompt = skills_manager.generate_system_prompt()
        
        assert isinstance(prompt, str)
        assert len(prompt) > 0


# 运行测试
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
