# filename: app/core/driver/browser_js.py
"""
浏览器端 JS 脚本集合 —— 用于批量 DOM 提取，替代逐元素 Selenium IPC。

设计目标：
- 全量提取：1 次 execute_script 替代 ~2090 次逐元素 IPC
- 轻量探测：只返回 id + ai（角色），用于结构变化判定（~2KB）
- 定向提取：只返回指定索引的元素 HTML

所有脚本兼容 WebAI 平台的 DOM 结构，选择器由 config.py SELECTORS["chat_items"] 统一管理。
"""

from .config import SELECTORS

# 聊天消息的 CSS 选择器，由 config.py 统一管理，此处不再硬编码
_CHAT_SELECTOR = SELECTORS["chat_items"]

# ── 全量批量提取 ──────────────────────────────────────────────
# 一次 IPC 返回所有可见消息的 id / ai / html
# 返回 ~10.5MB JSON（418 条消息时）
BATCH_CHAT_CONTENT = """
return (function() {
  var items = document.querySelectorAll('""" + _CHAT_SELECTOR + """');
  var result = [];
  for (var i = 0; i < items.length; i++) {
    var el = items[i];
    if (el.offsetHeight === 0) continue;
    result.push({
      id: el.dataset.messageId || el.dataset.id || el.id || '',
      ai: el.dataset.messageAi || '',
      html: el.outerHTML
    });
  }
  return result;
})();
"""

# ── 轻量探测 ──────────────────────────────────────────────────
# 一次 IPC 返回所有可见消息的 id + ai（~2KB）
# 用于结构变化判定：(id, ai) 有序列表 vs 上轮对比，不等则结构有变化
CHAT_CONTENT_PROBE = """
return (function() {
  var items = document.querySelectorAll('""" + _CHAT_SELECTOR + """');
  var result = [];
  for (var i = 0; i < items.length; i++) {
    var el = items[i];
    if (el.offsetHeight === 0) continue;
    var codeBlocks = el.querySelectorAll('pre code, .code-block, [class*="code-"]');
    result.push({
      id: el.dataset.messageId || el.dataset.id || el.id || '',
      ai: el.dataset.messageAi || '',
      text_len: (el.textContent || '').length,
      html_len: (el.outerHTML || '').length,
      code_count: codeBlocks.length
    });
  }
  return result;
})();
"""

# ── 定向提取 ──────────────────────────────────────────────────
# 参数：arguments[0] = indexes 数组（需要提取的可见元素索引）
# 只返回指定索引的元素完整信息
CHAT_CONTENT_BY_INDEX = """
return (function(indexes) {
  var items = document.querySelectorAll('""" + _CHAT_SELECTOR + """');
  var visible = [];
  for (var i = 0; i < items.length; i++) {
    if (items[i].offsetHeight > 0) visible.push(items[i]);
  }
  var result = [];
  for (var j = 0; j < indexes.length; j++) {
    var idx = indexes[j];
    if (idx >= 0 && idx < visible.length) {
      var el = visible[idx];
      result.push({
        idx: idx,
        id: el.dataset.messageId || el.dataset.id || el.id || '',
        ai: el.dataset.messageAi || '',
        html: el.outerHTML
      });
    }
  }
  return result;
})(arguments[0]);
"""
