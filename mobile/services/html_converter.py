"""HTML → 纯文本/Markdown 转换 — 浏览器模式消息解析用"""

import re


def html_to_markdown(html: str) -> str:
    """将 HTML 片段转为 Markdown 风格纯文本

    浏览器模式下服务端返回的消息内容是网页 HTML，
    需要转为 Markdown 才能被 ft.Markdown 正确渲染。
    """
    if not html:
        return ""

    text = html

    # 块级元素 → 换行
    text = re.sub(r'<br\s*/?>', '\n', text)
    text = re.sub(r'</p>', '\n', text)
    text = re.sub(r'</div>', '\n', text)
    text = re.sub(r'</li>', '\n', text)
    text = re.sub(r'</h[1-6]>', '\n', text)
    text = re.sub(r'<li[^>]*>', '- ', text)

    # 粗体
    text = re.sub(r'<b>', '**', text)
    text = re.sub(r'</b>', '**', text)
    text = re.sub(r'<strong>', '**', text)
    text = re.sub(r'</strong>', '**', text)

    # 斜体
    text = re.sub(r'<i>', '*', text)
    text = re.sub(r'</i>', '*', text)
    text = re.sub(r'<em>', '*', text)
    text = re.sub(r'</em>', '*', text)

    # 代码
    text = re.sub(r'<code>', '`', text)
    text = re.sub(r'</code>', '`', text)
    text = re.sub(r'<pre>', '```\n', text)
    text = re.sub(r'</pre>', '\n```', text)

    # 删除其余 HTML 标签
    text = re.sub(r'<[^>]+>', '', text)

    # HTML 实体
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&quot;', '"')
    text = text.replace('&#39;', "'")
    text = text.replace('&hellip;', '…')
    text = text.replace('&mdash;', '—')
    text = text.replace('&ndash;', '–')

    # 清理多余空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()

    return text
