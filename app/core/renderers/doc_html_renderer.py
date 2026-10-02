import re
import html as html_mod
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path


@dataclass
class MdSection:
    id: str = ""
    title: str = ""
    level: int = 0
    icon: str = ""
    accent: str = "accent1"
    raw_lines: list = field(default_factory=list)
    children: list = field(default_factory=list)
    parent: Optional["MdSection"] = None


@dataclass
class ParsedDoc:
    title: str = ""
    subtitle: str = ""
    badge_text: str = ""
    badge_date: str = ""
    sections: list = field(default_factory=list)
    nav_items: list = field(default_factory=list)
    progress_pills: list = field(default_factory=list)
    conclusion_items: list = field(default_factory=list)


SECTION_ICONS = {
    "背景": "📋", "目标": "🎯", "原则": "🎯", "核心原则": "🎯",
    "范围": "📐", "第一版范围": "📐",
    "技术": "🔗", "链路": "🔗", "技术链路": "🔗",
    "页面": "🏗️", "页面结构": "🏗️", "结构": "🏗️",
    "触发": "⚡", "触发方式": "⚡",
    "模块": "🧩", "模块拆分": "🧩",
    "实现": "⚙️", "关键实现": "⚙️",
    "风险": "⚠️", "风险与约束": "⚠️",
    "约束": "🚫",
    "实施": "🗓️", "实施顺序": "🗓️", "顺序": "🗓️",
    "验收": "✅", "验收标准": "✅",
    "结论": "💡",
    "架构": "🏗️",
    "流程": "🔢",
    "优先": "🔢", "优先级": "🔢",
    "路线": "🗓️", "路线图": "🗓️",
    "方案": "📖", "阶段": "📖",
    "设计": "📐",
    "任务": "📝",
    "配置": "⚙️",
    "测试": "🧪",
    "总结": "📊",
    "报告": "📊",
    "分析": "🔍",
    "问题": "❓",
    "修复": "🔧",
    "改进": "🚀",
    "优化": "🚀",
    "计划": "📋",
    "概述": "📋",
    "简介": "📋",
    "说明": "📋",
}

ACCENT_CYCLE = ["accent1", "accent2", "accent3", "accent4", "accent5"]

SECTION_KEYWORDS_PATTERNS = [
    (r"^背景$", "background"),
    (r"^目标$", "goals"),
    (r"背景.*目标", "background"),
    (r"^原则$|^核心原则$", "principles"),
    (r"^范围$|^第一版范围$", "scope"),
    (r"^技术$|^链路$|^技术链路$|^推荐技术链路$", "techchain"),
    (r"^页面结构$|^页面.*结构$", "pagestruct"),
    (r"^触发$|^触发方式$|^触发方式设计$", "trigger"),
    (r"^模块$|^模块拆分$|^模块拆分建议$", "modules"),
    (r"^实现$|^关键实现$|^关键实现点$", "implementation"),
    (r"^风险$|^风险.*约束$", "risks"),
    (r"^实施$|^实施顺序$|^路线$|^路线图$", "roadmap"),
    (r"^验收$|^验收标准$", "acceptance"),
    (r"^结论$", "conclusion"),
    (r"^架构$|^目标架构$", "architecture"),
    (r"^阶段$|^落地阶段$|^阶段详情$", "phases"),
    (r"^优先$|^优先级$", "priority"),
    (r"^任务$|^主力$", "tasks"),
    (r"^配置$|^配置建议$", "config"),
    (r"^设计$|^方案设计$", "design"),
    (r"^测试$|^回归$", "testing"),
    (r"^总结$|^报告$", "summary"),
    (r"^分析$", "analysis"),
    (r"^问题$|^修复$", "fix"),
    (r"^改进$|^优化$", "improvement"),
    (r"^计划$|^概述$|^简介$|^说明$", "overview"),
]


def _slugify(text: str) -> str:
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "-", text).strip("-")
    return text.lower()[:60] if text else "section"


def _detect_section_id(title: str) -> str:
    for pattern, sid in SECTION_KEYWORDS_PATTERNS:
        if re.search(pattern, title):
            return sid
    return _slugify(title)


def _detect_icon(title: str) -> str:
    for keyword, icon in SECTION_ICONS.items():
        if keyword in title:
            return icon
    return "📄"


def _escape_html(text: str) -> str:
    return html_mod.escape(text)


def _process_inline(text: str) -> str:
    result = _escape_html(text)
    result = re.sub(
        r"`([^`]+)`",
        r'<code style="background:var(--surface2);padding:2px 8px;border-radius:4px;color:var(--accent2);font-size:13px;">\1</code>',
        result,
    )
    result = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", result)
    result = re.sub(r"\*(.+?)\*", r"<em>\1</em>", result)
    result = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2" style="color:var(--accent2);text-decoration:underline;">\1</a>',
        result,
    )
    return result


def parse_markdown(md_text: str) -> ParsedDoc:
    doc = ParsedDoc()
    lines = md_text.split("\n")

    title_match = re.match(r"^#\s+(.+)$", lines[0]) if lines else None
    if title_match:
        doc.title = title_match.group(1).strip()

    for line in lines[:5]:
        m = re.match(r"^##\s+\d{4}-\d{2}-\d{2}\s*\|\s*(.+)$", line)
        if m:
            meta = m.group(1).strip()
            date_m = re.search(r"(\d{4}-\d{2}-\d{2})", line)
            doc.badge_date = date_m.group(1) if date_m else ""
            status_m = re.search(r"([\u4e00-\u9fff]+)\s*·", meta)
            if not status_m:
                status_m = re.search(r"🚧\s*([\u4e00-\u9fff]+)", meta)
            doc.badge_text = status_m.group(1) if status_m else "进行中"
            break

    if not doc.badge_text:
        for line in lines[:10]:
            if "🚧" in line:
                doc.badge_text = "进行中"
                break
            if "✅" in line:
                doc.badge_text = "已完成"
                break

    accent_idx = 0
    section_stack: list[MdSection] = []
    current_section: Optional[MdSection] = None
    meta_line_idx = -1
    for idx, line in enumerate(lines[:5]):
        if re.match(r"^##\s+\d{4}-\d{2}-\d{2}\s*\|", line):
            meta_line_idx = idx
            break

    i = 1
    while i < len(lines):
        line = lines[i]

        if i == meta_line_idx:
            i += 1
            continue

        heading_match = re.match(r"^(#{2,4})\s+(.+)$", line)
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            title = re.sub(r"^\d+\.\s*", "", title)

            section_id = _detect_section_id(title)
            icon = _detect_icon(title)
            accent = ACCENT_CYCLE[accent_idx % len(ACCENT_CYCLE)]
            accent_idx += 1

            new_section = MdSection(
                id=section_id,
                title=title,
                level=level,
                icon=icon,
                accent=accent,
            )

            while section_stack and section_stack[-1].level >= level:
                section_stack.pop()

            if section_stack:
                section_stack[-1].children.append(new_section)
                new_section.parent = section_stack[-1]
            else:
                doc.sections.append(new_section)

            section_stack.append(new_section)
            current_section = new_section
            i += 1
            continue

        if current_section is not None:
            current_section.raw_lines.append(line)
        else:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not doc.subtitle:
                clean = re.sub(r"^[*\-]\s*", "", stripped)
                if len(clean) > 10:
                    doc.subtitle = clean

        i += 1

    for sec in doc.sections:
        doc.nav_items.append({"id": sec.id, "title": sec.title, "icon": sec.icon})

    _extract_progress_pills(doc)
    _extract_conclusion_items(doc)

    return doc


def _extract_progress_pills(doc: ParsedDoc):
    pills = []
    seen_labels = set()
    pill_patterns = [
        (r"手动生成|第一阶段", "第一阶段 · 手动生成", "doing"),
        (r"自动监听|第二阶段", "第二阶段 · 自动监听", "todo"),
        (r"批量整理|第三阶段", "第三阶段 · 批量整理", "todo"),
    ]
    for sec in doc.sections:
        text = "\n".join(sec.raw_lines)
        for pattern, label, status in pill_patterns:
            if label not in seen_labels and (re.search(pattern, sec.title) or re.search(pattern, text)):
                pills.append({"label": label, "status": status})
                seen_labels.add(label)
    if pills:
        doc.progress_pills = pills
    else:
        doc.progress_pills = [
            {"label": "进行中", "status": "doing"},
        ]


def _extract_conclusion_items(doc: ParsedDoc):
    for sec in doc.sections:
        if "结论" in sec.title:
            items = []
            for line in sec.raw_lines:
                stripped = line.strip()
                if stripped.startswith("- ") or stripped.startswith("* "):
                    clean = re.sub(r"^[-*]\s*", "", stripped)
                    clean = re.sub(r"\*\*(.+?)\*\*", r"\1", clean)
                    if clean:
                        items.append(clean)
            if items:
                doc.conclusion_items = items[:4]
            break


def _render_code_block(code: str, lang: str = "") -> str:
    escaped = _escape_html(code.rstrip())
    lang_label = f'<div style="font-size:11px;color:var(--text3);margin-bottom:8px;text-transform:uppercase;letter-spacing:0.5px;">{lang}</div>' if lang else ""
    return f'<pre style="overflow-x:auto;margin:14px 0;padding:18px 20px;border-radius:8px;background:#1e293b;color:#e2e8f0;line-height:1.6;border:1px solid #334155;font-size:13px;">{lang_label}<code>{escaped}</code></pre>'


def _render_table(rows: list) -> str:
    if len(rows) < 2:
        return ""
    header_cells = rows[0]
    body_rows = rows[1:]

    th_html = "".join(f"<th>{_process_inline(c.strip())}</th>" for c in header_cells)
    tr_html_parts = []
    for row in body_rows:
        td_html = "".join(f"<td>{_process_inline(c.strip())}</td>" for c in row)
        tr_html_parts.append(f"<tr>{td_html}</tr>")

    return f'<table style="width:100%;border-collapse:separate;border-spacing:0;margin:16px 0;font-size:14px;border:1px solid var(--border);border-radius:8px;overflow:hidden;"><thead><tr style="background:var(--surface2);">{th_html}</tr></thead><tbody>{"".join(tr_html_parts)}</tbody></table>'


def _render_mermaid(code: str) -> str:
    escaped = _escape_html(code.strip())
    return f'<div class="mermaid-container" style="background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:24px;margin:16px 0;text-align:center;"><pre class="mermaid">{escaped}</pre></div>'


def _render_flow_diagram(code: str) -> str:
    nodes = []
    for line in code.strip().split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("↓") or stripped.startswith("→"):
            continue
        clean = stripped.strip("→↓↘↗↙↖").strip()
        if clean:
            nodes.append(clean)

    if not nodes:
        return _render_code_block(code, "text")

    nodes_html = ""
    for idx, node in enumerate(nodes):
        step_class = f"step{(idx % 5) + 1}"
        nodes_html += f'<div class="arch-box {step_class}"><div class="arch-label">{_process_inline(node)}</div></div>'
        if idx < len(nodes) - 1:
            nodes_html += '<div class="arch-arrow">→</div>'

    return f'<div class="arch-diagram"><h3>流程图</h3><div class="arch-flow">{nodes_html}</div></div>'


def _render_checklist(items: list, accent: str = "accent2") -> str:
    html_parts = []
    for item in items:
        checked = item.get("checked", False)
        text = item.get("text", "")
        check_icon = "✅" if checked else "○"
        opacity = "1" if checked else "0.7"
        html_parts.append(
            f'<div style="display:flex;align-items:center;gap:10px;padding:8px 0;font-size:14px;color:var(--text);opacity:{opacity};">'
            f'<span style="color:var(--{accent});font-size:14px;">{check_icon}</span>'
            f'<span>{_process_inline(text)}</span></div>'
        )
    return "".join(html_parts)


def _render_list_items(lines: list, accent: str = "accent1") -> str:
    items = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- [ ] ") or stripped.startswith("- [x] "):
            checked = stripped.startswith("- [x] ")
            text = re.sub(r"^-\s*\[[ x]\]\s*", "", stripped)
            items.append({"checked": checked, "text": text})
        elif stripped.startswith("- ") or stripped.startswith("* "):
            text = re.sub(r"^[-*]\s+", "", stripped)
            items.append({"checked": None, "text": text})
        elif re.match(r"^\d+\.\s+", stripped):
            text = re.sub(r"^\d+\.\s+", "", stripped)
            items.append({"checked": None, "text": text})

    if not items:
        return ""

    has_checklist = any(item["checked"] is not None for item in items)
    if has_checklist:
        return _render_checklist(items, accent)

    html_parts = []
    for item in items:
        html_parts.append(
            f'<li style="position:relative;padding:6px 0 6px 20px;font-size:14px;color:var(--text);line-height:1.5;">'
            f'<span style="position:absolute;left:0;font-size:8px;top:10px;color:var(--{accent});">◆</span>'
            f'{_process_inline(item["text"])}</li>'
        )
    return f'<ul style="list-style:none;padding:0;">{"".join(html_parts)}</ul>'


def _render_section_content(section: MdSection) -> str:
    content_parts = []
    raw = section.raw_lines

    i = 0
    in_code_block = False
    code_buffer = []
    code_lang = ""
    in_table = False
    table_rows = []
    table_col_count = 0

    while i < len(raw):
        line = raw[i]

        if line.strip().startswith("```"):
            if in_code_block:
                code_text = "\n".join(code_buffer)
                if code_lang == "mermaid":
                    content_parts.append(_render_mermaid(code_text))
                elif code_lang == "text" and ("→" in code_text or "↓" in code_text):
                    content_parts.append(_render_flow_diagram(code_text))
                else:
                    content_parts.append(_render_code_block(code_text, code_lang))
                code_buffer = []
                code_lang = ""
                in_code_block = False
            else:
                in_code_block = True
                code_lang = line.strip()[3:].strip()
            i += 1
            continue

        if in_code_block:
            code_buffer.append(line)
            i += 1
            continue

        stripped = line.strip()

        if stripped.startswith("|") and "|" in stripped[1:]:
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            if not in_table:
                in_table = True
                table_col_count = len(cells)
                table_rows = [cells]
            else:
                if all(re.match(r"^[-:]+$", c) for c in cells):
                    pass
                else:
                    while len(cells) < table_col_count:
                        cells.append("")
                    table_rows.append(cells[:table_col_count])
            i += 1
            continue
        elif in_table:
            content_parts.append(_render_table(table_rows))
            in_table = False
            table_rows = []

        if stripped == "---":
            content_parts.append('<hr style="border:none;border-top:1px solid var(--border);margin:24px 0;">')
            i += 1
            continue

        if stripped.startswith("#### ") or stripped.startswith("##### "):
            h_text = re.sub(r"^#+\s*", "", stripped)
            content_parts.append(
                f'<h4 style="font-size:14px;font-weight:600;color:var(--text2);'
                f'text-transform:uppercase;letter-spacing:1px;margin:20px 0 10px;">'
                f'{_process_inline(h_text)}</h4>'
            )
            i += 1
            continue

        if stripped.startswith("### "):
            h_text = re.sub(r"^###\s*", "", stripped)
            content_parts.append(
                f'<h3 style="font-size:16px;font-weight:700;color:var(--text);margin:20px 0 12px;">'
                f'{_process_inline(h_text)}</h3>'
            )
            i += 1
            continue

        list_lines = []
        while i < len(raw):
            sl = raw[i].strip()
            if sl.startswith("- [ ] ") or sl.startswith("- [x] ") or sl.startswith("- ") or sl.startswith("* ") or re.match(r"^\d+\.\s+", sl):
                list_lines.append(sl)
                i += 1
            else:
                break
        if list_lines:
            content_parts.append(_render_list_items(list_lines, section.accent))
            continue

        if stripped:
            content_parts.append(
                f'<p style="color:var(--text2);font-size:14px;line-height:1.8;margin-bottom:12px;">'
                f'{_process_inline(stripped)}</p>'
            )

        i += 1

    if in_table and table_rows:
        content_parts.append(_render_table(table_rows))

    return "".join(content_parts)


def _accent_rgb(accent: str) -> str:
    mapping = {
        "accent1": "108,99,255",
        "accent2": "0,212,170",
        "accent3": "255,107,157",
        "accent4": "255,217,61",
        "accent5": "107,140,255",
    }
    return mapping.get(accent, "108,99,255")


def _render_section_as_card(section: MdSection, idx: int) -> str:
    content = _render_section_content(section)
    if not content.strip():
        return ""

    accent = section.accent
    icon = section.icon

    return f'<div class="section reveal" id="{section.id}"><div class="section-title"><div class="icon" style="background:rgba({_accent_rgb(accent)},0.15);color:var(--{accent});">{icon}</div>{section.title}</div><div class="content-card">{content}</div></div>'


_CSS = """\
:root{--bg:#0f1117;--surface:#1a1d2e;--surface2:#232740;--border:#2e3350;--accent1:#6c63ff;--accent2:#00d4aa;--accent3:#ff6b9d;--accent4:#ffd93d;--accent5:#6b8cff;--text:#e8eaf6;--text2:#9ea4c1;--text3:#6b7199;--radius:12px}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text);line-height:1.7;overflow-x:hidden}
.hero{position:relative;padding:80px 40px 60px;text-align:center;overflow:hidden}
.hero::before{content:'';position:absolute;top:-50%;left:-50%;width:200%;height:200%;background:radial-gradient(ellipse at 30% 20%,rgba(108,99,255,0.15) 0%,transparent 50%),radial-gradient(ellipse at 70% 80%,rgba(0,212,170,0.1) 0%,transparent 50%);animation:heroBg 20s ease-in-out infinite alternate}
@keyframes heroBg{0%{transform:translate(0,0) rotate(0deg)}100%{transform:translate(-5%,-5%) rotate(3deg)}}
.hero-content{position:relative;z-index:1;max-width:800px;margin:0 auto}
.hero-badge{display:inline-block;padding:6px 18px;background:rgba(108,99,255,0.2);border:1px solid rgba(108,99,255,0.4);border-radius:20px;font-size:13px;color:var(--accent1);margin-bottom:24px;animation:fadeInUp .6s ease-out}
.hero h1{font-size:42px;font-weight:800;background:linear-gradient(135deg,#fff 0%,var(--accent1) 50%,var(--accent2) 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:16px;animation:fadeInUp .6s ease-out .1s both}
.hero p{font-size:16px;color:var(--text2);max-width:600px;margin:0 auto;animation:fadeInUp .6s ease-out .2s both}
@keyframes fadeInUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
.progress-pills{display:flex;gap:12px;margin:20px 0;flex-wrap:wrap}
.pill{display:flex;align-items:center;gap:8px;padding:8px 16px;border-radius:20px;font-size:13px;font-weight:500}
.pill.doing{background:rgba(255,217,61,0.15);color:var(--accent4);border:1px solid rgba(255,217,61,0.3)}
.pill.todo{background:var(--surface2);color:var(--text3);border:1px solid var(--border)}
.pill-dot{width:8px;height:8px;border-radius:50%}
.pill.doing .pill-dot{background:var(--accent4);animation:pulse 1.5s infinite}
.pill.todo .pill-dot{background:var(--text3)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.container{max-width:1100px;margin:0 auto;padding:0 24px}
nav{position:sticky;top:12px;z-index:50;display:flex;flex-wrap:wrap;gap:6px;margin:20px 0;padding:10px 14px;background:rgba(26,29,46,0.92);backdrop-filter:blur(16px) saturate(1.8);border:1px solid var(--border);border-radius:var(--radius);animation:fadeInUp .5s ease-out .3s both}
nav a{display:inline-flex;align-items:center;min-height:34px;padding:5px 14px;border:1px solid transparent;border-radius:6px;background:transparent;color:var(--text2);text-decoration:none;font-size:13px;font-weight:600;transition:all .2s}
nav a:hover{background:var(--surface2);color:var(--accent1);border-color:var(--border)}
nav a.active{background:var(--accent1);color:#fff;border-color:var(--accent1)}
.section{margin:60px 0}
.section-title{font-size:22px;font-weight:700;margin-bottom:32px;display:flex;align-items:center;gap:12px}
.section-title .icon{width:36px;height:36px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:18px}
.content-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:28px;transition:all .3s ease}
.content-card:hover{transform:translateY(-2px);box-shadow:0 8px 30px rgba(0,0,0,0.3);border-color:rgba(108,99,255,0.3)}
.arch-diagram{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:32px;margin:16px 0;overflow-x:auto}
.arch-diagram h3{font-size:16px;font-weight:700;margin-bottom:24px;color:var(--text)}
.arch-flow{display:flex;align-items:center;justify-content:center;gap:16px;flex-wrap:wrap}
.arch-box{padding:16px 20px;border-radius:10px;text-align:center;min-width:120px;transition:all .3s ease;cursor:default}
.arch-box:hover{transform:scale(1.05)}
.arch-box.step1{background:rgba(108,99,255,0.15);border:1px solid rgba(108,99,255,0.3)}
.arch-box.step2{background:rgba(0,212,170,0.15);border:1px solid rgba(0,212,170,0.3)}
.arch-box.step3{background:rgba(255,107,157,0.15);border:1px solid rgba(255,107,157,0.3)}
.arch-box.step4{background:rgba(255,217,61,0.15);border:1px solid rgba(255,217,61,0.3)}
.arch-box.step5{background:rgba(107,140,255,0.15);border:1px solid rgba(107,140,255,0.3)}
.arch-box .arch-label{font-size:14px;font-weight:600;margin-bottom:4px}
.arch-box.step1 .arch-label{color:var(--accent1)}
.arch-box.step2 .arch-label{color:var(--accent2)}
.arch-box.step3 .arch-label{color:var(--accent3)}
.arch-box.step4 .arch-label{color:var(--accent4)}
.arch-box.step5 .arch-label{color:var(--accent5)}
.arch-arrow{font-size:24px;color:var(--text3);user-select:none}
.acceptance{background:linear-gradient(135deg,rgba(108,99,255,0.1),rgba(0,212,170,0.05));border:1px solid rgba(108,99,255,0.2);border-radius:var(--radius);padding:32px;margin:60px 0}
.acceptance h2{font-size:20px;font-weight:700;margin-bottom:20px;color:var(--accent1)}
.acceptance-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}
.accept-item{background:rgba(255,255,255,0.03);border-radius:8px;padding:16px;font-size:14px;color:var(--text);line-height:1.5;border-left:3px solid var(--accent2);transition:all .3s ease}
.accept-item:hover{background:rgba(255,255,255,0.06);transform:translateX(4px)}
.conclusion-box{background:linear-gradient(135deg,rgba(108,99,255,0.12),rgba(0,212,170,0.08));border:1px solid rgba(108,99,255,0.2);border-radius:var(--radius);padding:28px}
.conclusion-highlights{display:flex;gap:12px;flex-wrap:wrap;margin-top:16px}
.conclusion-highlight{flex:1;min-width:140px;padding:14px 18px;border-radius:8px;text-align:center;transition:all .3s ease}
.conclusion-highlight:hover{transform:translateY(-2px);box-shadow:0 4px 15px rgba(108,99,255,0.2)}
.conclusion-highlight .ch-icon{font-size:24px;margin-bottom:6px}
.conclusion-highlight .ch-text{font-size:14px;font-weight:600}
.mermaid-container{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:24px;margin:16px 0}
.footer{text-align:center;padding:40px 24px;color:var(--text3);font-size:13px;border-top:1px solid var(--border);margin-top:60px}
.reveal{opacity:0;transform:translateY(20px);transition:opacity .55s cubic-bezier(.22,1,.36,1),transform .55s cubic-bezier(.22,1,.36,1)}
.reveal.visible{opacity:1;transform:translateY(0)}
@media(max-width:768px){.hero h1{font-size:28px}nav{position:static}}
"""

_JS = """\
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<script>
mermaid.initialize({startOnLoad:true,theme:'dark',themeVariables:{primaryColor:'#6c63ff',primaryTextColor:'#e8eaf6',primaryBorderColor:'#2e3350',lineColor:'#6b7199',secondaryColor:'#232740',tertiaryColor:'#1a1d2e',fontFamily:'-apple-system,BlinkMacSystemFont,Segoe UI,PingFang SC,Microsoft YaHei,sans-serif',fontSize:'14px'}});
var revealElements=document.querySelectorAll('.reveal');
var observer=new IntersectionObserver(function(entries){entries.forEach(function(entry){if(entry.isIntersecting){entry.target.classList.add('visible')}})},{threshold:0.1});
revealElements.forEach(function(el){observer.observe(el)});
var navLinks=document.querySelectorAll('nav a');
var allSections=document.querySelectorAll('.section,.acceptance');
var navObserver=new IntersectionObserver(function(entries){entries.forEach(function(entry){if(entry.isIntersecting){var id=entry.target.id;navLinks.forEach(function(link){link.classList.toggle('active',link.getAttribute('href')==='#'+id)})}})},{threshold:0.3,rootMargin:'-80px 0px -50% 0px'});
allSections.forEach(function(section){if(section.id)navObserver.observe(section)});
</script>
"""


def render_html(doc: ParsedDoc) -> str:
    nav_html = ""
    for item in doc.nav_items:
        nav_html += f'<a href="#{item["id"]}">{item["title"]}</a>'

    pills_html = ""
    for pill in doc.progress_pills:
        status = pill["status"]
        pills_html += f'<div class="pill {status}"><div class="pill-dot"></div>{pill["label"]}</div>'

    sections_html = ""
    skip_ids = set()
    for sec in doc.sections:
        if "验收" in sec.title:
            skip_ids.add(sec.id)
        if "结论" in sec.title:
            skip_ids.add(sec.id)

    for idx, sec in enumerate(doc.sections):
        if sec.id in skip_ids:
            continue
        sections_html += _render_section_as_card(sec, idx)

    acceptance_html = ""
    for sec in doc.sections:
        if "验收" in sec.title:
            items = []
            for line in sec.raw_lines:
                stripped = line.strip()
                if stripped.startswith("- [ ] ") or stripped.startswith("- [x] "):
                    text = re.sub(r"^-\s*\[[ x]\]\s*", "", stripped)
                    items.append(text)
                elif stripped.startswith("- ") or stripped.startswith("* "):
                    text = re.sub(r"^[-*]\s+", "", stripped)
                    items.append(text)
            if items:
                accept_items_html = ""
                for item in items:
                    accept_items_html += f'<div class="accept-item">{_process_inline(item)}</div>'
                acceptance_html = f'<div class="acceptance reveal" id="acceptance"><h2>✅ 验收标准</h2><div class="acceptance-grid">{accept_items_html}</div></div>'
            break

    conclusion_html = ""
    for sec in doc.sections:
        if "结论" in sec.title:
            content = _render_section_content(sec)
            highlights = ""
            highlight_items = doc.conclusion_items if doc.conclusion_items else ["更易读", "更易讲解", "更像成品", "更适合展示"]
            highlight_icons = ["📖", "🎙️", "📦", "🎯"]
            for hi, item in enumerate(highlight_items[:4]):
                h_accent = ACCENT_CYCLE[hi % len(ACCENT_CYCLE)]
                h_icon = highlight_icons[hi % len(highlight_icons)]
                highlights += f'<div class="conclusion-highlight" style="background:rgba({_accent_rgb(h_accent)},0.1);border:1px solid rgba({_accent_rgb(h_accent)},0.2);"><div class="ch-icon">{h_icon}</div><div class="ch-text" style="color:var(--{h_accent});">{_process_inline(item)}</div></div>'
            conclusion_html = f'<div class="section reveal" id="conclusion"><div class="section-title"><div class="icon" style="background:rgba(0,212,170,0.15);color:var(--accent2);">💡</div>结论</div><div class="conclusion-box">{content}<div class="conclusion-highlights">{highlights}</div></div></div>'
            break

    badge_display = ""
    if doc.badge_text:
        date_part = f" · {doc.badge_date}" if doc.badge_date else ""
        badge_display = f'<div class="hero-badge">🚧 {doc.badge_text}{date_part}</div>'

    subtitle_display = ""
    if doc.subtitle:
        subtitle_display = f"<p>{_process_inline(doc.subtitle)}</p>"

    pills_section = ""
    if pills_html:
        pills_section = f'<div class="progress-pills" style="justify-content:center;margin-top:24px;">{pills_html}</div>'

    title_escaped = _escape_html(doc.title)
    footer_text = f"{title_escaped} · {doc.badge_date or '内部文档'} · 内部文档"

    return (
        f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1.0">'
        f"<title>{title_escaped}</title>"
        f"<style>{_CSS}</style></head><body>"
        f'<div class="hero"><div class="hero-content">{badge_display}'
        f"<h1>{title_escaped}</h1>{subtitle_display}{pills_section}</div></div>"
        f'<div class="container"><nav aria-label="目录">{nav_html}</nav>'
        f"{sections_html}{acceptance_html}{conclusion_html}</div>"
        f'<div class="footer">{footer_text}</div>'
        f"{_JS}</body></html>"
    )
