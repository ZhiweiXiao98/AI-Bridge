"""AI_JOURNAL.md 轻量机械索引与检索。

基于主标题行 (## date | title | status) 和标签 (**标签**: `tag`) 构建索引，
支持标签精确匹配 + 标题子串匹配，供长期记忆注入与按需详情读取。
"""

import re
import logging
from pathlib import Path
from typing import List, Dict, Optional
from app.core.logging import get_logger

logger = get_logger("app.core.journal_index", side="worker")

JOURNAL_PATH = Path('AI_JOURNAL.md')

HEADER_PATTERN = re.compile(
    r'^##\s+(\d{4}-\d{2}-\d{2})\s*\|\s*(.+?)\s*\|\s*(.+?)\s*$'
)
TAG_LINE_PATTERN = re.compile(
    r'^\s*-\s*\*\*标签\*\*\s*[:：]\s*(.+)$'
)
TAG_EXTRACT = re.compile(r'`([^`]+)`')


class JournalEntry:
    """单条日志的索引信息。"""

    __slots__ = ('date', 'title', 'status', 'tags', 'line_start', 'line_end')

    def __init__(self, date: str, title: str, status: str,
                 tags: List[str], line_start: int, line_end: int):
        self.date = date
        self.title = title
        self.status = status
        self.tags = tags
        self.line_start = line_start  # 1-based
        self.line_end = line_end      # 1-based, inclusive

    @property
    def header(self) -> str:
        return f"## {self.date} | {self.title} | {self.status}"

    def matches(self, keywords: List[str]) -> bool:
        """标签精确匹配 + 标题子串匹配。"""
        lower_title = self.title.lower()
        lower_tags = [t.lower() for t in self.tags]
        for kw in keywords:
            kw_lower = kw.lower().strip()
            if not kw_lower:
                continue
            if kw_lower in lower_tags:
                return True
            if kw_lower in lower_title:
                return True
        return False

    def to_dict(self) -> dict:
        return {
            'date': self.date, 'title': self.title, 'status': self.status,
            'tags': self.tags, 'line_start': self.line_start,
            'line_end': self.line_end, 'header': self.header,
        }


class JournalIndex:
    """AI_JOURNAL.md 的轻量机械索引。"""

    def __init__(self, journal_path: Optional[str] = None):
        self._path = Path(journal_path) if journal_path else JOURNAL_PATH
        self._entries: List[JournalEntry] = []
        self._tag_index: Dict[str, List[int]] = {}
        self._built = False

    def build(self) -> bool:
        """解析 AI_JOURNAL.md，构建索引。"""
        self._entries = []
        self._tag_index = {}
        self._built = False

        if not self._path.exists():
            logger.warning('AI_JOURNAL.md 不存在: %s', self._path)
            return False

        try:
            lines = self._path.read_text(encoding='utf-8', errors='replace').splitlines()
        except Exception as e:
            logger.warning('读取 AI_JOURNAL.md 失败: %s', e)
            return False

        header_positions = []
        for i, line in enumerate(lines):
            m = HEADER_PATTERN.match(line.strip())
            if m:
                header_positions.append((i, m.group(1), m.group(2).strip(), m.group(3).strip()))

        for idx, (line_num, date, title, status) in enumerate(header_positions):
            line_end = (header_positions[idx + 1][0] - 1) if idx + 1 < len(header_positions) else len(lines) - 1

            tags = []
            search_end = min(line_num + 10, line_end + 1)
            for j in range(line_num + 1, search_end):
                tag_match = TAG_LINE_PATTERN.match(lines[j])
                if tag_match:
                    tags = TAG_EXTRACT.findall(tag_match.group(1))
                    break

            entry = JournalEntry(
                date=date, title=title, status=status, tags=tags,
                line_start=line_num + 1, line_end=line_end + 1,
            )
            self._entries.append(entry)

            entry_idx = len(self._entries) - 1
            for tag in tags:
                tag_lower = tag.lower()
                self._tag_index.setdefault(tag_lower, []).append(entry_idx)

        self._built = True
        logger.info('AI_JOURNAL 索引构建完成: %d 条记录, %d 个标签', len(self._entries), len(self._tag_index))
        return True

    def _ensure_built(self):
        if not self._built:
            self.build()

    def search(self, keywords: List[str], max_results: int = 10) -> List[JournalEntry]:
        """按关键词搜索，返回匹配条目。"""
        self._ensure_built()
        results = []
        for entry in self._entries:
            if entry.matches(keywords):
                results.append(entry)
                if len(results) >= max_results:
                    break
        return results

    def search_headers(self, keywords: List[str], max_results: int = 10) -> List[str]:
        """搜索并返回匹配的主标题列表（用于注入长期记忆）。"""
        return [e.header for e in self.search(keywords, max_results=max_results)]

    def get_entry_by_date(self, date: str) -> Optional[JournalEntry]:
        """按日期查找条目。"""
        self._ensure_built()
        for entry in self._entries:
            if entry.date == date:
                return entry
        return None

    def get_all_headers(self) -> List[str]:
        self._ensure_built()
        return [e.header for e in self._entries]

    def get_recent_headers(self, count: int = 5) -> List[str]:
        self._ensure_built()
        return [e.header for e in self._entries[-count:]]

    def get_all_tags(self) -> List[str]:
        self._ensure_built()
        return sorted(self._tag_index.keys())

    def read_entry_content(self, entry: JournalEntry) -> str:
        """读取指定条目的完整内容。"""
        try:
            lines = self._path.read_text(encoding='utf-8', errors='replace').splitlines()
            start = max(0, entry.line_start - 1)
            end = min(len(lines), entry.line_end)
            return '\n'.join(lines[start:end])
        except Exception as e:
            logger.warning('读取日志条目失败: %s', e)
            return ''

    def read_entry_by_date(self, date: str) -> str:
        """按日期读取条目全文。"""
        entry = self.get_entry_by_date(date)
        return self.read_entry_content(entry) if entry else ''


# ---- 关键词提取 ----

_CN_STOPWORDS = frozenset({
    '的', '是', '在', '了', '和', '或', '不', '有', '这', '那', '我', '你',
    '他', '她', '它', '们', '也', '都', '就', '会', '要', '能', '可以',
    '一个', '什么', '怎么', '如何', '请', '帮', '看', '做', '用', '把',
    '被', '让', '给', '到', '从', '对', '为', '吗', '呢', '吧', '啊',
    '好', '行', '没有', '已经', '然后', '但是', '如果', '因为', '所以',
    '现在', '需要', '应该', '可能', '问题', '代码', '文件', '修改',
})

_EN_STOPWORDS = frozenset({
    'the', 'is', 'at', 'in', 'on', 'of', 'and', 'or', 'to', 'for', 'a', 'an',
    'it', 'this', 'that', 'with', 'as', 'by', 'be', 'are', 'was', 'were',
    'def', 'class', 'import', 'from', 'return', 'self', 'none', 'true', 'false',
    'if', 'else', 'elif', 'try', 'except', 'while', 'not', 'print', 'str',
    'int', 'list', 'dict', 'set', 'can', 'will', 'should', 'would', 'could',
    'have', 'has', 'had', 'do', 'does', 'did', 'but', 'so', 'then', 'than',
    'just', 'also', 'how', 'what', 'when', 'where', 'which', 'who', 'why',
    'all', 'each', 'every', 'some', 'any', 'no', 'yes', 'get', 'got',
})

_BACKTICK_RE = re.compile(r'`([^`]+)`')
_PATH_RE = re.compile(r'[\w./]+\.(?:py|js|ts|md|json|toml|yaml|yml)')
_EN_WORD_RE = re.compile(r'[a-zA-Z_]\w{2,}')
_CN_TERM_RE = re.compile(r'[\u4e00-\u9fff]{2,6}')


def extract_search_keywords(history: list, max_keywords: int = 20) -> List[str]:
    """从对话历史中提取关键词，用于 journal 索引搜索。

    优先从最后一条 user message 提取，同时参考近期 user messages。
    提取策略：反引号标识符 > 文件路径 > 英文标识符 > 中文关键词。
    """
    if not history:
        return []

    user_texts = []
    for msg in history:
        if msg.get('role') == 'user':
            content = msg.get('content', '')
            if content:
                user_texts.append(content)

    if not user_texts:
        return []

    primary = user_texts[-1]
    recent = ' '.join(user_texts[-5:])

    keywords = set()

    # 1. 反引号中的标识符（最可能匹配标签）
    for term in _BACKTICK_RE.findall(recent):
        t = term.strip()
        if t and len(t) > 1:
            keywords.add(t)

    # 2. 文件路径 → 提取文件名（不含扩展名）
    for path in _PATH_RE.findall(recent):
        basename = path.rsplit('/', 1)[-1].rsplit('.', 1)[0]
        if basename and len(basename) > 1:
            keywords.add(basename)

    # 3. 英文标识符（主要从最新消息）
    for word in _EN_WORD_RE.findall(primary):
        if word.lower() not in _EN_STOPWORDS:
            keywords.add(word.lower())

    # 4. 中文关键词（主要从最新消息）
    for term in _CN_TERM_RE.findall(primary):
        if term not in _CN_STOPWORDS:
            keywords.add(term)

    return list(keywords)[:max_keywords]
