# providers/base.py - 搜索提供商基类
from dataclasses import dataclass
from typing import List, Optional
from abc import ABC, abstractmethod


@dataclass
class SearchResult:
    '''搜索结果数据类'''
    title: str
    url: str
    snippet: str
    content: Optional[str] = None


class SearchProvider(ABC):
    '''搜索提供商基类'''

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.name = self.__class__.__name__

    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        '''执行搜索，返回结果列表'''
        pass

    def is_available(self) -> bool:
        '''检查提供商是否可用'''
        return True

    def get_status(self) -> str:
        '''获取提供商状态'''
        avail = "Available" if self.is_available() else "Unavailable"
        return f"{self.name}: {avail}"
