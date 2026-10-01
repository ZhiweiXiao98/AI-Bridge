import json
import hashlib
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict

from app.core.app_constants import PROJECT_ROOT as APP_PROJECT_ROOT
from app.core.logging import get_logger

logger = get_logger("app.core.services.doc_status_tracker", side="worker")

PROJECT_ROOT = Path(APP_PROJECT_ROOT)
DEFAULT_DOCS_DIR = PROJECT_ROOT / "docs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "docs" / "导出HTML"
STATUS_FILE = DEFAULT_OUTPUT_DIR / ".doc_status.json"


@dataclass
class DocStatus:
    filename: str = ""
    md_hash: str = ""
    md_size: int = 0
    md_mtime: float = 0
    html_exists: bool = False
    html_hash: str = ""
    html_mtime: float = 0
    last_generated: float = 0
    status: str = "missing"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DocStatus":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class DocStatusTracker:
    def __init__(self, docs_dir: Path = None, output_dir: Path = None):
        self._docs_dir = docs_dir or DEFAULT_DOCS_DIR
        self._output_dir = output_dir or DEFAULT_OUTPUT_DIR
        self._status_file = self._output_dir / ".doc_status.json"
        self._statuses: dict[str, DocStatus] = {}
        self._load()

    def scan_all(self) -> list[DocStatus]:
        results = []
        seen_filenames = set()
        for md_file in sorted(self._docs_dir.glob("*.md")):
            status = self._compute_status(md_file)
            self._statuses[md_file.name] = status
            seen_filenames.add(md_file.name)
            results.append(status)
        for filename in list(self._statuses):
            if filename not in seen_filenames:
                self._statuses.pop(filename, None)
        self._save()
        return results

    def get_status(self, filename: str) -> DocStatus:
        if filename in self._statuses:
            return self._statuses[filename]
        md_path = self._docs_dir / filename
        if md_path.exists():
            status = self._compute_status(md_path)
            self._statuses[filename] = status
            return status
        return DocStatus(filename=filename, status="missing")

    def mark_generated(self, filename: str, html_path: Path):
        if filename in self._statuses:
            s = self._statuses[filename]
            s.html_exists = True
            s.html_hash = self._file_hash(html_path)
            s.html_mtime = html_path.stat().st_mtime if html_path.exists() else 0
            s.last_generated = time.time()
            s.status = "up_to_date"
        else:
            md_path = self._docs_dir / filename
            s = self._compute_status(md_path)
            s.html_exists = True
            s.html_hash = self._file_hash(html_path)
            s.html_mtime = html_path.stat().st_mtime if html_path.exists() else 0
            s.last_generated = time.time()
            s.status = "up_to_date"
            self._statuses[filename] = s
        self._save()

    def get_outdated(self) -> list[DocStatus]:
        return [s for s in self._statuses.values() if s.status in ("outdated", "missing")]

    def get_summary(self) -> dict:
        all_statuses = list(self._statuses.values())
        return {
            "total": len(all_statuses),
            "up_to_date": sum(1 for s in all_statuses if s.status == "up_to_date"),
            "outdated": sum(1 for s in all_statuses if s.status == "outdated"),
            "missing": sum(1 for s in all_statuses if s.status == "missing"),
        }

    def _compute_status(self, md_path: Path) -> DocStatus:
        filename = md_path.name
        md_stat = md_path.stat()
        md_hash = self._file_hash(md_path)
        html_path = self._output_dir / (md_path.stem + ".html")

        html_exists = html_path.exists()
        html_hash = self._file_hash(html_path) if html_exists else ""
        html_mtime = html_path.stat().st_mtime if html_exists else 0

        prev = self._statuses.get(filename)

        if not html_exists:
            status = "missing"
        elif prev and prev.md_hash == md_hash and prev.html_hash == html_hash:
            status = "up_to_date"
        elif prev and prev.md_hash != md_hash:
            status = "outdated"
        elif html_exists and md_stat.st_mtime > html_mtime:
            status = "outdated"
        else:
            status = "up_to_date"

        return DocStatus(
            filename=filename,
            md_hash=md_hash,
            md_size=md_stat.st_size,
            md_mtime=md_stat.st_mtime,
            html_exists=html_exists,
            html_hash=html_hash,
            html_mtime=html_mtime,
            last_generated=prev.last_generated if prev else 0,
            status=status,
        )

    def _file_hash(self, path: Path) -> str:
        if not path.exists():
            return ""
        content = path.read_bytes()
        return hashlib.md5(content).hexdigest()

    def _load(self):
        if self._status_file.exists():
            try:
                data = json.loads(self._status_file.read_text(encoding="utf-8"))
                for k, v in data.items():
                    self._statuses[k] = DocStatus.from_dict(v)
            except Exception as e:
                logger.warning("DocStatusTracker: 加载状态文件失败: %s", e)

    def _save(self):
        try:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            data = {k: v.to_dict() for k, v in self._statuses.items()}
            self._status_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("DocStatusTracker: 保存状态文件失败: %s", e)
