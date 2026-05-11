# filename: rhino_plugin/AIBridge/__init__.py
# -*- coding: utf-8 -*-
"""
AI Bridge Connector for Rhino
"""
import Rhino
from . import listener

__plugin_id__ = "97799564-9040-42c2-801e-727803023210"
__plugin_version__ = "1.0.0"
__plugin_name__ = "AI Bridge Connector"
__command_name__ = "AIBridgeStart"

def OnLoad(is_interactive):
    Rhino.RhinoApp.WriteLine("🔌 AI Bridge 插件正在加载...")
    listener.start_polling()

def OnShutdown():
    pass
