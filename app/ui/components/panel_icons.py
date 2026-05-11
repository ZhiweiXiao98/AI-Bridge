# filename: app/ui/components/panel_icons.py
"""
面板图标管理
用于生成和管理面板的占位图标
"""
from PySide6.QtGui import QPixmap, QColor, QPainter
from PySide6.QtCore import Qt, QRect

class PanelIcons:
    """面板图标生成器"""
    
    @staticmethod
    def create_placeholder_icon(color_hex, size=48):
        """
        创建占位图标（彩色方块）
        
        Args:
            color_hex: 颜色（如 "#6366F1"）
            size: 图标大小（默认 48x48）
        
        Returns:
            QPixmap: 图标
        """
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 绘制圆角矩形
        color = QColor(color_hex)
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRect(4, 4, size-8, size-8), 8, 8)
        
        painter.end()
        return pixmap
    
    @staticmethod
    def get_icon(panel_name):
        """
        根据面板名称获取图标
        
        Args:
            panel_name: 面板名称
        
        Returns:
            QPixmap: 图标
        """
        # 预定义颜色方案
        colors = {
            "沙盒监控": "#6366F1",  # 蓝色
            "AI日志": "#10B981",    # 绿色
            "文件浏览器": "#F59E0B", # 橙色
            "终端输出": "#8B5CF6",  # 紫色
            "属性面板": "#EC4899",  # 粉色
            "原型面板": "#06B6D4",  # 青色
        }
        
        color = colors.get(panel_name, "#6B7280")  # 默认灰色
        return PanelIcons.create_placeholder_icon(color)
