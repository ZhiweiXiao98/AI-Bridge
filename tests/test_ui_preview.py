# filename: tests/test_ui_preview.py
import pytest
from unittest.mock import MagicMock, patch
import sys
import importlib

class TestCodePreview:
    
    @pytest.fixture(autouse=True)
    def setup_env(self):
        """
        白板重载 + 全量 Mock 环境配置
        """
        # 1. 清除模块缓存，防止污染
        if 'app.ui.components.preview_dialog' in sys.modules:
            del sys.modules['app.ui.components.preview_dialog']
            
        # 2. 准备 DummyQDialog 基类
        class DummyQDialog:
            def __init__(self, parent=None, **kwargs):
                pass
            def setWindowFlags(self, flags): pass
            def setWindowTitle(self, title): pass
            def resize(self, w, h): pass
            def accept(self): pass
            def setStyleSheet(self, s): pass
            def exec(self): pass

        # 3. 准备 PySide6.QtWidgets Mock
        # 关键：使用 MagicMock() 实例，支持静态属性访问 (如 LineWrapMode)
        mock_widgets = MagicMock()
        mock_widgets.QDialog = DummyQDialog
        mock_widgets.QTextEdit = MagicMock() 
        mock_widgets.QProgressBar = MagicMock()
        mock_widgets.QLabel = MagicMock()
        mock_widgets.QPushButton = MagicMock()
        mock_widgets.QVBoxLayout = MagicMock()
        mock_widgets.QHBoxLayout = MagicMock()
        
        # 4. 准备 PySide6.QtGui Mock
        mock_gui = MagicMock()
        mock_gui.QFont = MagicMock()
        mock_gui.QColor = MagicMock()
        
        # 5. 准备 PySide6.QtCore Mock
        mock_core = MagicMock()
        mock_core.Qt = MagicMock()
        
        # 6. 注入所有 Mock 模块
        with patch.dict(sys.modules, {
            'PySide6.QtWidgets': mock_widgets,
            'PySide6.QtGui': mock_gui,
            'PySide6.QtCore': mock_core
        }):
            import app.ui.components.preview_dialog
            importlib.reload(app.ui.components.preview_dialog)
            self.module = app.ui.components.preview_dialog
            
            # 7. Patch theme_manager
            mock_tm = MagicMock()
            mock_palette = MagicMock()
            mock_palette.BG_PRIMARY = "#FFFFFF"
            for attr in ['TEXT_PRIMARY', 'ACCENT_PRIMARY', 'BTN_WARNING', 
                         'BG_SECONDARY', 'BORDER', 'TEXT_DANGER', 'TEXT_SECONDARY']:
                setattr(mock_palette, attr, "#000000")
            mock_tm.get_palette.return_value = mock_palette
            
            with patch.object(self.module, 'theme_manager', mock_tm):
                yield

    def test_diff_mode_instantiation(self):
        CodePreviewDialog = self.module.CodePreviewDialog
        new_code = "def foo():\n    return 2"
        old_code = "def foo():\n    return 1"
        
        # 实例化
        dialog = CodePreviewDialog("test.py")
        
        # 注入 Mock Editors (捕获操作对象)
        mock_diff_editor = MagicMock()
        mock_pseudo_editor = MagicMock()
        dialog.diff_editor = mock_diff_editor
        dialog.pseudo_editor = mock_pseudo_editor
        
        # 执行逻辑
        dialog.update_content(new_code, old_code)
        
        # 验证 diff_editor 被调用
        mock_diff_editor.setHtml.assert_called()
        args, _ = mock_diff_editor.setHtml.call_args
        assert "<table" in args[0] or "background-color" in args[0]

    def test_source_mode_instantiation(self):
        CodePreviewDialog = self.module.CodePreviewDialog
        new_code = "print('hello')"
        
        dialog = CodePreviewDialog("test.py")
        
        mock_diff_editor = MagicMock()
        mock_pseudo_editor = MagicMock()
        dialog.diff_editor = mock_diff_editor
        dialog.pseudo_editor = mock_pseudo_editor
        
        dialog.update_content(new_code, None)
        
        # 验证 diff_editor 被调用
        mock_diff_editor.setHtml.assert_called()
        args, _ = mock_diff_editor.setHtml.call_args
        # 简单的内容验证
        assert "print" in args[0] or len(args[0]) > 0

if __name__ == "__main__":
    pytest.main([__file__, "-v"])