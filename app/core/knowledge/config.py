# filename: app/core/knowledge/config.py
"""KnowledgeService V2 配置"""

import os
from app.core.project_context import ProjectContext

# Embedding 模型
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"  # 384维，快速，代码检索够用
EMBEDDING_DIM = 384

# 向量库
def _default_db_dir():
    return ProjectContext.get().get_knowledge_db_path()

DB_DIR = _default_db_dir()
COLLECTION_NAME = "codebase_v2"

# 分块
MAX_CHUNK_LINES = 80      # 单个 chunk 最大行数
MIN_CHUNK_LINES = 3       # 太短的 chunk 丢弃
FALLBACK_CHUNK_SIZE = 50  # AST 失败时的 fallback 行数

# 检索
DEFAULT_TOP_K = 5
RECALL_MULTIPLIER = 3     # 粗排召回倍数（top_k * 3）

# 重排序
RERANK_ENABLED = True
RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"  # 轻量 cross-encoder

# 缓存
CACHE_MAX_SIZE = 128
CACHE_TTL_SECONDS = 300   # 5 分钟过期

# 索引
SUPPORTED_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".yaml", ".yml", ".md"}
IGNORED_DIRS = {
    ".git", "__pycache__", "venv", ".venv", "env",
    "node_modules", "_knowledge_base", "_knowledge_base_v2",
    "_docker_env", "backup", "htmlcov", ".pytest_cache",
    "export", "dist", "build", ".tox", ".eggs",
    "Chrome_143_Clean_Data", "chrome_user_data"
}