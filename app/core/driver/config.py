# filename: app/core/driver/config.py
import os

# [Fix] 恢复强制离线模式！
# 既然之前已经成功启动过，说明驱动已就绪。
# 开启此选项可避免 Selenium 每次启动都因联网检查更新而卡死。
# 如果网络环境允许连接 Google 服务器，建议开启此选项（注释掉或设为 'false'）。
# 如果在纯内网环境且已手动放置了正确的 chromedriver.exe，可以取消注释以加快启动速度。
os.environ['SE_OFFLINE'] = 'true' 

SELECTORS = {
    # 聊天消息气泡 (核心内容)
    # 注意：这些类名可能会随网页更新而变化，需定期检查
    "chat_items": ".chat-item",
    
    # 消息内的具体内容块 (用于解析)
    # 包含文本、Markdown、图片等不同类型的容器类名
    "content_blocks": ["chat-text", "aa-html", "aa-html-content", "markdown-renderer", "aa-image", "n-image"],
    
    # 输入框
    # 这是一个 CSS 选择器，定位到聊天输入框的 textarea 元素
    "input_area": "div.aa-chat-input textarea.n-input__textarea-el, div.aa-chat-input textarea",
    
    # 上传相关
    # 使用 XPath 定位上传按钮和文件输入框
    "upload_trigger": "//button[contains(@class, 'n-button') and .//span[contains(text(), '附件')]]",
    "file_input": "input.n-upload-file-input", 
    "upload_confirm": "//button[contains(@class, 'n-button--primary-type') and .//span[contains(text(), '确认')]]",
    
    # 发送按钮 (多重保障)
    # 提供多个 XPath 作为备选，因为网页可能会根据状态显示不同的发送按钮
    "send_buttons_xpath": [
        "//div[contains(@class, 'aa-chat-input') or contains(@class, 'chat-input-box')]//button[.//span[contains(text(), '发送')] or contains(normalize-space(.), '发送')]",
        "//button[ancestor::*[contains(@class, 'aa-chat-input') or contains(@class, 'chat-input-box')] and (.//span[contains(text(), '发送')] or contains(normalize-space(.), '发送'))]",
        "//button[.//span[contains(text(), '发送')]]",
        "//button[contains(@class, 'send')]",
        "//div[contains(@class, 'send')]"
    ],
    
    # === [重点检查这里] 会话列表 ===
    # 用于定位左侧会话列表中的每一项。
    # 如果你的网页版改了 class，这里必须更新！
    # 常见备选: ".session", "div[class*='session']", "div[role='button']"
    "session_item": ".aa-sidebar-list-item", 
    "session_active": ".aa-sidebar-list-item.active",
    
    # 滚动容器
    # 用于判断是否到达底部，以及执行滚动操作的容器元素
    "scroll_container_xpath": "//div[contains(@class, 'n-scrollbar-container')][.//div[contains(@class, 'chat-item')]]"
}

SCRIPTS = {
    # 滚动检查脚本
    # 返回 true 表示已经接近底部 (距离底部小于 150px)
    "scroll_check": """
        var container = document.evaluate("//div[contains(@class, 'n-scrollbar-container')][.//div[contains(@class, 'chat-item')]]", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
        if (!container) return false;
        return (container.scrollTop + container.clientHeight) >= (container.scrollHeight - 150);
    """,

    # React 输入框注入脚本
    # 绕过 React 的虚拟 DOM 机制，直接设置 value 并触发 input 事件
    "react_input": """
        var element = arguments[0];
        var text = arguments[1];
        var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
        element.focus();
        nativeInputValueSetter.call(element, text);
        element.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text }));
        element.dispatchEvent(new Event('change', { bubbles: true }));
    """
}

# 代码块操作按钮选择器 (双兼容: FontAwesome 旧版 + Lucide SVG 新版)
CODE_BLOCK_SELECTORS = {
    # FontAwesome (旧版) — <i> 元素的 class 片段
    "fa_copy_class": "fa-copy",
    "fa_collapsed_class": "down-left-and-up-right-to-center",
    "fa_expanded_class": "up-right-and-down-left-from-center",

    # Lucide SVG (新版) — <svg> 元素的 class 片段
    "lucide_copy_class": "lucide-copy",
    "lucide_collapsed_class": "lucide-maximize-2",
    "lucide_expanded_class": "lucide-minimize-2",

    # aria-label (新版按钮的语义标签，最可靠)
    "lucide_expand_aria": "展开",
    "lucide_collapse_aria": "退出全屏",
    "lucide_copy_aria": "复制",

    # 通用
    "action_btn_class": "chat-md-action-btn",
}
