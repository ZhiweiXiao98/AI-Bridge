import os
import threading
from pathlib import Path

from app.core.logging import get_logger
from app.core.app_constants import PROJECT_ROOT as APP_PROJECT_ROOT
from app.core.services.doc_organizer_service import DocOrganizerService
from app.core.services.doc_status_tracker import DocStatusTracker
from app.core.services.doc_analyzer_service import DocAnalyzerService
from app.core.renderers.doc_html_renderer import parse_markdown, render_html

logger = get_logger("app.ui.panels.doc_organizer_panel_logic", side="ui")

PROJECT_ROOT = Path(APP_PROJECT_ROOT)
DEFAULT_DOCS_DIR = PROJECT_ROOT / "docs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "docs" / "导出HTML"


class DocOrganizerPanelLogic:
    def __init__(self, panel, llm_router=None, html_opener=None):
        self._panel = panel
        self._llm = llm_router
        self._html_opener = html_opener
        self._tracker = DocStatusTracker()
        self._service = DocOrganizerService()
        self._analyzer = DocAnalyzerService(llm_router)
        self._generating = False

    def bind(self):
        self._panel.refresh_requested.connect(self.refresh)
        self._panel.generate_requested.connect(self.generate_single)
        self._panel.generate_all_requested.connect(self.generate_all)
        self._panel.open_html_requested.connect(self.open_html)
        self.refresh()

    def refresh(self):
        statuses = self._tracker.scan_all()
        self._panel.update_doc_list(statuses)
        logger.info("DocOrganizer: 刷新完成, %d 篇文档", len(statuses))

    def generate_single(self, filename: str):
        if self._generating:
            logger.info("DocOrganizer: 正在生成中，跳过")
            return
        self._generating = True
        self._panel.show_progress(0, 1)

        def _work():
            try:
                md_path = DEFAULT_DOCS_DIR / filename
                if not md_path.exists():
                    logger.warning("DocOrganizer: 文件不存在 %s", filename)
                    return

                md_text = md_path.read_text(encoding="utf-8")
                llm_data = self._analyzer.analyze(md_text, filename)

                if llm_data:
                    html_content = render_html_from_analysis(llm_data, md_text)
                else:
                    doc = parse_markdown(md_text)
                    html_content = render_html(doc)

                DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                html_path = DEFAULT_OUTPUT_DIR / (md_path.stem + ".html")
                html_path.write_text(html_content, encoding="utf-8")

                self._tracker.mark_generated(filename, html_path)
                self._panel.update_card_status(filename, "up_to_date", self._tracker.get_status(filename).last_generated)
                logger.info("DocOrganizer: 生成完成 %s (llm=%s)", filename, llm_data is not None)
            except Exception as e:
                logger.warning("DocOrganizer: 生成失败 %s | %s", filename, e)
            finally:
                self._generating = False
                self._panel.hide_progress()

        threading.Thread(target=_work, daemon=True).start()

    def generate_all(self):
        if self._generating:
            return
        outdated = self._tracker.get_outdated()
        if not outdated:
            logger.info("DocOrganizer: 无需更新")
            return

        self._generating = True
        total = len(outdated)
        self._panel.show_progress(0, total)

        def _work():
            for idx, status in enumerate(outdated):
                try:
                    md_path = DEFAULT_DOCS_DIR / status.filename
                    if not md_path.exists():
                        continue

                    md_text = md_path.read_text(encoding="utf-8")
                    llm_data = self._analyzer.analyze(md_text, status.filename)

                    if llm_data:
                        html_content = render_html_from_analysis(llm_data, md_text)
                    else:
                        doc = parse_markdown(md_text)
                        html_content = render_html(doc)

                    DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                    html_path = DEFAULT_OUTPUT_DIR / (md_path.stem + ".html")
                    html_path.write_text(html_content, encoding="utf-8")

                    self._tracker.mark_generated(status.filename, html_path)
                    self._panel.update_card_status(status.filename, "up_to_date", self._tracker.get_status(status.filename).last_generated)
                except Exception as e:
                    logger.warning("DocOrganizer: 批量生成失败 %s | %s", status.filename, e)

                self._panel.show_progress(idx + 1, total)

            self._generating = False
            self._panel.hide_progress()
            self._service.generate_index()
            logger.info("DocOrganizer: 批量生成完成, %d 篇", total)

        threading.Thread(target=_work, daemon=True).start()

    def open_html(self, filename: str):
        stem = Path(filename).stem
        html_path = DEFAULT_OUTPUT_DIR / (stem + ".html")
        if html_path.exists():
            if self._html_opener:
                self._html_opener(html_path, filename)
            else:
                logger.warning("DocOrganizer: 未配置内置浏览器预览入口 %s", html_path)
        else:
            logger.warning("DocOrganizer: HTML 不存在 %s", html_path)


def render_html_from_analysis(analysis: dict, fallback_md: str) -> str:
    from app.core.renderers.doc_html_renderer import (
        _escape_html, _process_inline, _accent_rgb,
        ACCENT_CYCLE, _CSS, _JS,
    )

    title = analysis.get("title", "文档")
    subtitle = analysis.get("subtitle", "")
    badge = analysis.get("badge", {})
    phases = analysis.get("phases", [])
    sections = analysis.get("sections", [])
    flow_diagrams = analysis.get("flow_diagrams", [])
    acceptance = analysis.get("acceptance_criteria", [])
    conclusion = analysis.get("conclusion_highlights", [])
    risks = analysis.get("risks", [])

    badge_display = ""
    if badge:
        status = badge.get("status", "进行中")
        date = badge.get("date", "")
        date_part = f" · {date}" if date else ""
        badge_display = f'<div class="hero-badge">🚧 {status}{date_part}</div>'

    subtitle_display = f"<p>{_process_inline(subtitle)}</p>" if subtitle else ""

    pills_html = ""
    if phases:
        for ph in phases:
            st = "doing" if ph.get("status") == "doing" else ("done" if ph.get("status") == "done" else "todo")
            pills_html += f'<div class="pill {st}"><div class="pill-dot"></div>{ph.get("label", "")}</div>'
        pills_html = f'<div class="progress-pills" style="justify-content:center;margin-top:24px;">{pills_html}</div>'

    nav_html = ""
    for sec in sections:
        nav_html += f'<a href="#{sec.get("id", "")}">{sec.get("icon", "📄")} {sec.get("title", "")}</a>'

    sections_html = ""
    for idx, sec in enumerate(sections):
        sec_id = sec.get("id", f"section_{idx}")
        sec_title = sec.get("title", "")
        sec_icon = sec.get("icon", "📄")
        accent = ACCENT_CYCLE[idx % len(ACCENT_CYCLE)]
        summary = sec.get("summary", "")
        key_points = sec.get("key_points", [])
        display_hint = sec.get("display_hint", "cards")

        content_parts = ""
        if summary:
            content_parts += f'<p style="color:var(--text2);font-size:14px;line-height:1.8;margin-bottom:12px;">{_process_inline(summary)}</p>'

        if key_points:
            items_html = ""
            for kp in key_points:
                items_html += (
                    f'<li style="position:relative;padding:6px 0 6px 20px;font-size:14px;color:var(--text);line-height:1.5;">'
                    f'<span style="position:absolute;left:0;font-size:8px;top:10px;color:var(--{accent});">◆</span>'
                    f'{_process_inline(kp)}</li>'
                )
            content_parts += f'<ul style="list-style:none;padding:0;">{items_html}</ul>'

        flow = next((f for f in flow_diagrams if f.get("section_id") == sec_id), None)
        if flow:
            nodes = flow.get("nodes", [])
            nodes_html = ""
            for ni, node in enumerate(nodes):
                step_class = f"step{(ni % 5) + 1}"
                nodes_html += f'<div class="arch-box {step_class}"><div class="arch-label">{_process_inline(node)}</div></div>'
                if ni < len(nodes) - 1:
                    nodes_html += '<div class="arch-arrow">→</div>'
            content_parts += f'<div class="arch-diagram"><h3>{_process_inline(flow.get("title", "流程图"))}</h3><div class="arch-flow">{nodes_html}</div></div>'

        if not content_parts.strip():
            content_parts = f'<p style="color:var(--text2);font-size:14px;">（本节内容待补充）</p>'

        sections_html += (
            f'<div class="section reveal" id="{sec_id}">'
            f'<div class="section-title">'
            f'<div class="icon" style="background:rgba({_accent_rgb(accent)},0.15);color:var(--{accent});">{sec_icon}</div>'
            f'{sec_title}</div>'
            f'<div class="content-card">{content_parts}</div></div>'
        )

    acceptance_html = ""
    if acceptance:
        items_html = "".join(f'<div class="accept-item">{_process_inline(a)}</div>' for a in acceptance)
        acceptance_html = f'<div class="acceptance reveal" id="acceptance"><h2>✅ 验收标准</h2><div class="acceptance-grid">{items_html}</div></div>'

    conclusion_html = ""
    if conclusion:
        highlights_html = ""
        highlight_icons = ["📖", "🎙️", "📦", "🎯"]
        for hi, item in enumerate(conclusion[:4]):
            h_accent = ACCENT_CYCLE[hi % len(ACCENT_CYCLE)]
            h_icon = highlight_icons[hi % len(highlight_icons)]
            highlights_html += (
                f'<div class="conclusion-highlight" style="background:rgba({_accent_rgb(h_accent)},0.1);border:1px solid rgba({_accent_rgb(h_accent)},0.2);">'
                f'<div class="ch-icon">{h_icon}</div>'
                f'<div class="ch-text" style="color:var(--{h_accent});">{_process_inline(item)}</div></div>'
            )
        conclusion_html = (
            f'<div class="section reveal" id="conclusion">'
            f'<div class="section-title"><div class="icon" style="background:rgba(0,212,170,0.15);color:var(--accent2);">💡</div>结论</div>'
            f'<div class="conclusion-box"><div class="conclusion-highlights">{highlights_html}</div></div></div>'
        )

    title_escaped = _escape_html(title)
    footer_text = f"{title_escaped} · 内部文档"

    return (
        f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1.0">'
        f"<title>{title_escaped}</title>"
        f"<style>{_CSS}</style></head><body>"
        f'<div class="hero"><div class="hero-content">{badge_display}'
        f"<h1>{title_escaped}</h1>{subtitle_display}{pills_html}</div></div>"
        f'<div class="container"><nav aria-label="目录">{nav_html}</nav>'
        f"{sections_html}{acceptance_html}{conclusion_html}</div>"
        f'<div class="footer">{footer_text}</div>'
        f"{_JS}</body></html>"
    )
