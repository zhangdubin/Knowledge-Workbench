"""JSON 解析、序列化与树形结构服务

取代原先的 Jevko 语法：Jevko 是自定义的极简树形语法，需要自己写解析器、
自己定义转义规则，AI/前端/第三方工具都不认识它。
JSON 是通用标准 —— 标准库直接支持、大模型天然会写、复制粘贴到任何工具都能用。

对外提供四件事：
- parse / dumps：文本 ↔ 对象
- get_summary：统计（字数、节点数、深度、直接子节点）
- to_tree：把任意 JSON 值展开成**前端可直接渲染**的节点数组
  （前端不再需要自己写树遍历，也不怕数据结构千奇百怪）
"""
from __future__ import annotations

import json
from typing import Any

# 防御性上限：避免用户贴进一个巨大 JSON 把响应撑爆
MAX_NODES = 5000
MAX_DEPTH = 24
MAX_PREVIEW = 400


def parse(text: str) -> Any:
    """解析 JSON 文本。

    失败时抛出 ValueError，并把原始报错（行/列）带上，
    方便前端把「第 12 行第 5 列」这种信息直接展示给用户。
    """
    if text is None or not text.strip():
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"JSON 解析失败：第 {e.lineno} 行第 {e.colno} 列 —— {e.msg}"
        ) from e


def dumps(value: Any, indent: int = 2) -> str:
    """序列化为 JSON 文本（中文不转义，方便直接阅读）"""
    return json.dumps(value, ensure_ascii=False, indent=indent)


def kind_of(value: Any) -> str:
    """归一化类型名，供前端着色使用"""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    return "string"


def _scalar_text(value: Any) -> str:
    """非字符串标量 → 展示文本"""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def to_tree(value: Any) -> list[dict]:
    """把任意 JSON 值展开成节点数组，前端直接递归渲染。

    节点结构：
    {
      "key": "字段名（数组元素为下标字符串）",
      "isIndex": false,          # 数组元素为 true，前端显示为 [0] 而非 "key":
      "kind": "object|array|string|number|boolean|null",
      "value": "标量文本；容器为 null（长字符串已截断 + 省略号）",
      "chars": 123,              # 字符串原文长度（未截断前），其余为 null
      "count": 3,                # 容器的子元素个数
      "truncated": false,        # 超过 MAX_NODES/MAX_DEPTH 被截断
      "children": [...]          # 仅容器有
    }
    """
    budget = {"n": MAX_NODES}

    def build(val: Any, key: str | None, is_index: bool, depth: int) -> dict:
        k = kind_of(val)
        node: dict = {
            "key": key,
            "isIndex": is_index,
            "kind": k,
            "value": None,
            "chars": None,
            "count": 0,
            "truncated": False,
            "children": [],
        }
        if k in ("object", "array"):
            items = list(val.items()) if k == "object" else list(enumerate(val))
            node["count"] = len(items)
            if depth >= MAX_DEPTH:
                node["truncated"] = True
                return node
            for kk, vv in items:
                if budget["n"] <= 0:
                    node["truncated"] = True
                    break
                budget["n"] -= 1
                node["children"].append(
                    build(vv, str(kk), k == "array", depth + 1)
                )
        elif k == "string":
            node["chars"] = len(val)
            node["value"] = val[:MAX_PREVIEW] + "…" if len(val) > MAX_PREVIEW else val
        else:
            node["value"] = _scalar_text(val)
        return node

    budget["n"] -= 1
    root = build(value, None, False, 0)
    return [root]


def get_summary(value: Any) -> dict:
    """统计 JSON 结构信息（与前端 utils/jsonview.js 的口径保持一致）"""
    stat = {
        "node_count": 0,
        "text_length": 0,
        "max_depth": 0,
        "direct_children": 0,
    }

    def walk(val: Any, depth: int) -> None:
        stat["node_count"] += 1
        k = kind_of(val)
        if k == "string":
            stat["text_length"] += len(val)
        elif k in ("object", "array"):
            if depth > stat["max_depth"]:
                stat["max_depth"] = depth
            children = val.values() if k == "object" else val
            for child in children:
                walk(child, depth + 1)

    walk(value, 0)
    if kind_of(value) in ("object", "array"):
        stat["direct_children"] = len(value)
    stat["root_type"] = kind_of(value)
    return stat
