#!/usr/bin/env python3
"""Agent Framework Result Cache - 工具结果缓存系统

支持工具结果的引用传递：
- 工具执行结果自动存储到缓存
- 返回引用格式 [RESULT:ref_N]...[/RESULT]
- 后续工具可以使用 $ref_N 引用结果
- 框架自动解析引用并注入实际内容

解决长结果在工具间传递的 token 消耗问题
"""

import re
from typing import Any, Dict, List, Optional


class ToolResultCache:
    """工具结果缓存 - 存储工具执行结果供引用
    
    特性：
    - 轻量级，无锁（单线程使用）
    - 支持引用解析
    """
    
    def __init__(self, max_size: int = 50):
        """
        Args:
            max_size: 最大缓存条目数
        """
        self._cache: Dict[str, Any] = {}
        self._metadata: Dict[str, Dict[str, Any]] = {}
        self._order: List[str] = []
        self._counter = 0
        self._max_size = max_size
    
    def put(self, result: Any, metadata: Dict[str, Any] = None) -> str:
        """存储结果，返回引用ID"""
        self._counter += 1
        ref_id = f"ref_{self._counter}"
        
        # LRU 驱逐
        if len(self._cache) >= self._max_size and self._order:
            oldest = self._order.pop(0)
            self._cache.pop(oldest, None)
            self._metadata.pop(oldest, None)
        
        self._cache[ref_id] = result
        self._metadata[ref_id] = metadata or {}
        self._order.append(ref_id)
        
        return ref_id
    
    def get(self, ref_id: str) -> Any:
        """获取引用结果"""
        return self._cache.get(ref_id)
    
    def get_current(self) -> Any:
        """获取最新结果"""
        if self._order:
            return self._cache.get(self._order[-1])
        return None
    
    def get_previous(self) -> Any:
        """获取上一个结果"""
        if len(self._order) >= 2:
            return self._cache.get(self._order[-2])
        return None
    
    def resolve_reference(self, value: Any) -> Any:
        """解析值中的引用
        
        支持: $ref_N, $latest, $prev
        """
        if not isinstance(value, str):
            return value
        
        # 简单替换
        result = value
        
        # $latest
        if "$latest" in result:
            latest = self.get_current()
            result = result.replace("$latest", str(latest) if latest else "")
        
        # $prev
        if "$prev" in result:
            prev = self.get_previous()
            result = result.replace("$prev", str(prev) if prev else "")
        
        # $ref_N
        def replace_ref(m):
            ref_id = m.group(1)
            val = self.get(f"ref_{ref_id}")
            return str(val) if val is not None else ""
        
        result = re.sub(r'\$ref_(\d+)', replace_ref, result)
        
        return result
    
    def format_with_reference(self, result: Any, metadata: Dict[str, Any] = None) -> str:
        """格式化结果，包含引用标签"""
        ref_id = self.put(result, metadata)
        return f"[RESULT:{ref_id}]{result}[/RESULT]"
    
    def clear(self):
        """清空缓存"""
        self._cache.clear()
        self._metadata.clear()
        self._order.clear()
    
    def __len__(self) -> int:
        return len(self._cache)
    
    def __repr__(self) -> str:
        return f"ToolResultCache(size={len(self)}, refs={self._order[-5:] if self._order else []})"


def create_result_cache(max_size: int = 50) -> ToolResultCache:
    """创建新的结果缓存实例"""
    return ToolResultCache(max_size=max_size)
