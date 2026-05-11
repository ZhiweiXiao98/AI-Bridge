"""SkillsPanel 插件 - Skills 管理面板"""

import logging
from app.ui.plugins.base_panel_plugin import BasePanelPlugin
from plugins.panels.skills_panel.panel import SkillsPanelWidget
from app.core.skills import SkillsManager
from PySide6.QtWidgets import QFileDialog

logger = logging.getLogger(__name__)


class SkillsPanelPlugin(BasePanelPlugin):
    """Skills 管理面板插件"""
    
    def __init__(self):
        super().__init__()
        
        # 插件元数据
        self.plugin_id = "skills_panel"
        self.plugin_name = "Skills 管理面板"
        self.plugin_version = "1.0.0"
        self.plugin_author = "Kiro Team"
        self.plugin_description = "管理和配置 AI Skills"
        self.plugin_icon = "🎯"
        self.default_area = "right"
        
        # 运行时状态
        self.skills_manager = None
        self.worker = None
        self.is_remote = False
        self._cached_skills = []
    
    def on_load(self):
        """插件加载时初始化"""
        logger.info("[SkillsPanel] 插件加载中...")
    
    def on_enable(self):
        """插件启用时"""
        logger.info("[SkillsPanel] 插件已启用")
    
    def create_panel(self):
        """创建面板实例"""
        if not self.panel_instance:
            panel = SkillsPanelWidget()
            panel.rpc_request.connect(self.handle_skills_rpc)
            self._set_panel_instance(panel)
            logger.info("[SkillsPanel] 面板已创建")
        return self.panel_instance
    
    def on_panel_created(self, panel):
        """面板创建后的回调"""
        main_window = panel.parent()
        if main_window and hasattr(main_window, 'worker'):
            self.worker = main_window.worker
            self._initialize_skills_system()
        logger.info("[SkillsPanel] 面板初始化完成")

    
    def _initialize_skills_system(self):
        """初始化 Skills 系统（本地或远程模式）"""
        self.is_remote = hasattr(self.worker, '_request_send')
        
        if self.is_remote:
            self.skills_manager = None
            logger.info("🌐 远程模式：Skills 将从服务端获取")
            
            # 连接远程信号
            if hasattr(self.worker, 'skills_list_signal'):
                self.worker.skills_list_signal.connect(self._on_skills_list)
            if hasattr(self.worker, 'skills_toggle_result_signal'):
                self.worker.skills_toggle_result_signal.connect(self._on_skills_toggle_result)
            if hasattr(self.worker, 'skills_prompt_signal'):
                self.worker.skills_prompt_signal.connect(self._on_skills_prompt)
            if hasattr(self.worker, 'system_prompt_signal'):
                self.worker.system_prompt_signal.connect(self._on_system_prompt)
            
            # 请求初始数据
            if hasattr(self.worker, 'skills_list'):
                self.worker.skills_list()
        else:
            self.skills_manager = SkillsManager()
            self.skills_manager.config_file = 'config/skills_config.json'
            self.skills_manager.scan_all_skills()
            logger.info("💻 本地模式：使用本地 Skills")
            
            initial_skills = self.skills_manager.list_all_skills()
            if self.panel_instance:
                self.panel_instance.update_skills_data(initial_skills)
    
    def handle_skills_rpc(self, method, kwargs):
        """处理 Skills 面板的 RPC 请求"""
        if method == 'refresh_skills' or method == 'skills_refresh':
            logger.info("🔄 刷新 Skills...")
            if self.is_remote:
                if hasattr(self.worker, 'skills_refresh'):
                    self.worker.skills_refresh()
            else:
                self.skills_manager.scan_all_skills()
                skills_data = self.skills_manager.list_all_skills()
                if self.panel_instance:
                    self.panel_instance.update_skills_data(skills_data)
        
        elif method == 'toggle_skill' or method == 'skills_toggle':
            skill_id = kwargs.get('skill_name') or kwargs.get('skill_id')
            requested_enabled = kwargs.get('enabled')
            logger.info(f"🔄 切换 Skill: {skill_id} -> {requested_enabled}")

            if not skill_id:
                logger.error("❌ 切换 Skill 失败: 未提供 skill_name/skill_id")
                return

            if self.is_remote:
                all_skills = self._cached_skills
                current_skill = next(
                    (s for s in all_skills if s.get('id') == skill_id or s.get('name') == skill_id),
                    None
                )
                if current_skill:
                    new_state = requested_enabled if requested_enabled is not None else (not current_skill.get('enabled', True))
                    if hasattr(self.worker, 'skills_toggle'):
                        self.worker.skills_toggle(skill_id, new_state)
                else:
                    logger.error(f"❌ 远程切换失败，未找到 Skill: {skill_id}")
            else:
                all_skills = self.skills_manager.list_all_skills()
                current_skill = next(
                    (s for s in all_skills if s.get('id') == skill_id or s.get('name') == skill_id),
                    None
                )
                if current_skill:
                    new_state = requested_enabled if requested_enabled is not None else (not current_skill.get('enabled', True))
                    self.skills_manager.toggle_skill(skill_id, new_state)
                    self.skills_manager.save_config()
                    
                    # 即时更新卡片
                    if self.panel_instance and skill_id in self.panel_instance.skill_cards:
                        self.panel_instance.skill_cards[skill_id].update_status(new_state)
                    
                    # 刷新列表
                    skills_data = self.skills_manager.list_all_skills()
                    if self.panel_instance:
                        self.panel_instance.update_skills_data(skills_data)
                else:
                    logger.error(f"❌ 本地切换失败，未找到 Skill: {skill_id}")
        
        elif method == 'reload_skill' or method == 'skills_reload':
            skill_id = kwargs.get('skill_name') or kwargs.get('skill_id')
            logger.info(f"🔄 重载 Skill: {skill_id}")

            if not skill_id:
                logger.error("❌ 重载 Skill 失败: 未提供 skill_name/skill_id")
                return

            if self.is_remote:
                if hasattr(self.worker, 'skills_reload'):
                    self.worker.skills_reload(skill_id)
                else:
                    logger.error("❌ 远程 Worker 不支持 skills_reload")
            else:
                success = False
                message = ''
                if self.worker and hasattr(self.worker, 'reload_skill'):
                    self.worker.reload_skill(skill_id)
                    success = True
                    message = f"已请求通过 Worker 重载 Skill: {skill_id}"
                elif self.skills_manager:
                    success, message = self.skills_manager.reload_skill(skill_id)
                else:
                    message = 'SkillsManager 未初始化'

                if success:
                    logger.info(f"✅ {message}")
                    if self.skills_manager:
                        skills_data = self.skills_manager.list_all_skills()
                        if self.panel_instance:
                            self.panel_instance.update_skills_data(skills_data)
                else:
                    logger.error(f"❌ {message}")

        elif method == 'import_skill':
            logger.info("📥 导入 Skill...")
            if self.is_remote:
                logger.warning("远程模式暂不支持导入")
            else:
                logger.info("请将 Skill 文件放入 app/core/skills/ 目录")
        
        elif method == 'generate_prompt' or method == 'skills_generate_prompt':
            logger.info("📝 生成系统提示词...")
            if self.is_remote:
                if hasattr(self.worker, 'skills_generate_prompt'):
                    self.worker.skills_generate_prompt()
            else:
                prompt = self.skills_manager.generate_system_prompt()
                if self.panel_instance:
                    self.panel_instance.display_system_prompt({'content': prompt})
        
        else:
            logger.warning(f"未知的 Skills RPC 方法: {method}")
    
    def _on_skills_list(self, skills_data):
        """处理服务端返回的 Skills 列表"""
        logger.info(f"📊 收到服务端 Skills 列表: {len(skills_data)} 个")
        self._cached_skills = skills_data
        if self.panel_instance:
            self.panel_instance.update_skills_data(skills_data)
    
    def _on_skills_toggle_result(self, result):
        """处理服务端返回的切换结果"""
        if result.get('success'):
            logger.info(f"✅ Skill 切换成功: {result.get('skill_name')}")
            if hasattr(self.worker, 'skills_list'):
                self.worker.skills_list()
        else:
            logger.error(f"❌ Skill 切换失败: {result.get('skill_name')}")
    
    def _on_skills_prompt(self, data):
        """处理服务端返回的系统提示词"""
        logger.info("📝 收到系统提示词")
        if self.panel_instance:
            self.panel_instance.display_system_prompt(data)
    
    def _on_system_prompt(self, data):
        """处理系统提示词信号"""
        if data.get('target_client_id') == 'Host':
            if self.panel_instance:
                self.panel_instance.display_system_prompt(data['prompt'])
    
    def on_panel_closed(self, panel):
        """面板关闭时"""
        logger.info("[SkillsPanel] 面板已关闭")
    
    def on_disable(self):
        """插件禁用时"""
        logger.info("[SkillsPanel] 插件已禁用")
    
    def on_unload(self):
        """插件卸载时"""
        # 断开信号连接
        if self.worker and self.is_remote:
            if hasattr(self.worker, 'skills_list_signal'):
                try:
                    self.worker.skills_list_signal.disconnect(self._on_skills_list)
                except:
                    pass
        logger.info("[SkillsPanel] 插件已卸载")
