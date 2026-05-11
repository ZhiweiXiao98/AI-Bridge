# filename: app/core/services/knowledge_service.py
"""
KnowledgeService V1 兼容层。
所有调用转发到 V2 实现，调用方无需修改。
"""

import logging
from app.core.knowledge.service import KnowledgeServiceV2
from app.core.logging import get_logger

logger = get_logger("app.core.services.knowledge_service", side="worker")


class KnowledgeService:
    """V1 兼容层，转发到 KnowledgeServiceV2"""

    def __init__(self):
        self._v2 = KnowledgeServiceV2()
        self._v2.start_executor()

    def search_context(self, query, top_k=3, task_meta=None):
        """检索（V1 接口）"""
        return self._v2.search(query, top_k, task_meta=task_meta)

    def update_file_index(self, file_path, content):
        """索引文件（V1 接口）"""
        return self._v2.index_file(file_path, content)

    def rebuild_index(self, root_dir="."):
        """全量重建（新接口）"""
        return self._v2.rebuild_index(root_dir)

    def get_stats(self):
        """状态查询（新接口）"""
        return self._v2.get_stats()

    def list_indexed_paths(self):
        """列出当前知识库中所有已索引路径"""
        return self._v2.list_indexed_paths()

    def delete_paths(self, paths):
        """批量删除指定路径对应的索引"""
        return self._v2.delete_paths(paths)

    def on_project_switched(self, new_root: str, new_db_path: str):
        self._v2.on_project_switched(new_root, new_db_path)


# 保持单例导出（兼容所有调用方）
knowledge_engine = KnowledgeService()