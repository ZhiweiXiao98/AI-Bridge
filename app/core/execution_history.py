# filename: app/core/execution_history.py
"""
代码执行历史记录模块
记录所有代码执行的历史，用于调试和审计
"""
import json
import os
import time
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
import logging
from app.core.logging import get_logger

logger = get_logger("app.core.execution_history", side="worker")

@dataclass
class ExecutionRecord:
    """执行记录"""
    timestamp: float
    code: str
    exit_code: int
    output: str
    duration: float
    validation_warnings: List[str]
    validation_errors: List[str]
    timeout: int
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'timestamp': self.timestamp,
            'datetime': datetime.fromtimestamp(self.timestamp).strftime('%Y-%m-%d %H:%M:%S'),
            'code': self.code[:200] + '...' if len(self.code) > 200 else self.code,  # 截断长代码
            'exit_code': self.exit_code,
            'output': self.output[:500] + '...' if len(self.output) > 500 else self.output,  # 截断长输出
            'duration': round(self.duration, 2),
            'validation_warnings': self.validation_warnings,
            'validation_errors': self.validation_errors,
            'timeout': self.timeout,
            'success': self.exit_code == 0
        }

class ExecutionHistory:
    """执行历史管理器"""
    
    def __init__(self, max_records: int = 100, history_file: str = ".sandbox_history.json"):
        self.max_records = max_records
        self.history_file = history_file
        self.records: List[ExecutionRecord] = []
        self._load_history()
    
    def _load_history(self):
        """从文件加载历史记录"""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 只加载最近的记录
                    for record_dict in data[-self.max_records:]:
                        record = ExecutionRecord(
                            timestamp=record_dict['timestamp'],
                            code=record_dict.get('code', ''),
                            exit_code=record_dict['exit_code'],
                            output=record_dict['output'],
                            duration=record_dict['duration'],
                            validation_warnings=record_dict.get('validation_warnings', []),
                            validation_errors=record_dict.get('validation_errors', []),
                            timeout=record_dict.get('timeout', 60)
                        )
                        self.records.append(record)
                logger.info(f"✅ 加载了 {len(self.records)} 条历史记录")
            except Exception as e:
                logger.warning(f"⚠️ 加载历史记录失败: {e}")
    
    def _save_history(self):
        """保存历史记录到文件"""
        try:
            data = [record.to_dict() for record in self.records[-self.max_records:]]
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"⚠️ 保存历史记录失败: {e}")
    
    def add_record(self, record: ExecutionRecord):
        """添加执行记录"""
        self.records.append(record)
        
        # 限制记录数量
        if len(self.records) > self.max_records:
            self.records = self.records[-self.max_records:]
        
        # 异步保存（避免阻塞）
        try:
            self._save_history()
        except Exception as e:
            logger.warning(f"⚠️ 保存记录失败: {e}")
    
    def get_recent(self, count: int = 10) -> List[Dict]:
        """获取最近的执行记录"""
        return [record.to_dict() for record in self.records[-count:]]
    
    def get_failed(self, count: int = 10) -> List[Dict]:
        """获取最近的失败记录"""
        failed = [record for record in self.records if record.exit_code != 0]
        return [record.to_dict() for record in failed[-count:]]
    
    def get_statistics(self) -> Dict:
        """获取统计信息"""
        if not self.records:
            return {
                'total': 0,
                'success': 0,
                'failed': 0,
                'success_rate': 0,
                'avg_duration': 0
            }
        
        total = len(self.records)
        success = sum(1 for r in self.records if r.exit_code == 0)
        failed = total - success
        avg_duration = sum(r.duration for r in self.records) / total
        
        return {
            'total': total,
            'success': success,
            'failed': failed,
            'success_rate': round(success / total * 100, 1),
            'avg_duration': round(avg_duration, 2)
        }
    
    def clear(self):
        """清空历史记录"""
        self.records.clear()
        try:
            if os.path.exists(self.history_file):
                os.remove(self.history_file)
            logger.info("✅ 已清空历史记录")
        except Exception as e:
            logger.warning(f"⚠️ 清空历史记录失败: {e}")
