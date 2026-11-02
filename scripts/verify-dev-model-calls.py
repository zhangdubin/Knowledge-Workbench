#!/usr/bin/env python3
"""软件开发模块「模型调用链路」自检

为什么要有这个脚本：
    开发流程的失败，八成不是模型笨，而是**调用方式**出了问题：
      · 输出被 max_tokens 截断 → JSON 解析不出来
      · 模型给了对象而不是字符串 → 字段取不到
      · 模型不照 schema 来 → 产出跟用户要的不是一回事
    这三样在界面上都长成同一句「生成失败」，用户无从下手。
    这个脚本把「调用方式」这一层单独钉住：改了 max_tokens、重试、抢救、
    归一化，都得从这里过一遍。

用法：python3 scripts/verify-dev-model-calls.py
退出码 0 = 全部通过
"""
import ast
import asyncio
import json
import re
import sys

FAILS = []
CHECKS = 0


def ok(name, cond, detail=""):
    global CHECKS
    CHECKS += 1
    if cond:
        print("  \u2714 %s" % name)
    else:
        print("  \u2718 %s %s" % (name, detail))
        FAILS.append(name)


def load_funcs(path, names):
    """只抽取要测的函数，不 import 整个模块。

    为什么不直接 import：
        这个模块 import 时会拉起 config/数据库/ai_config 一堆依赖，
        自检脚本只想验几个纯函数，不该被那些副作用绊倒。
    """
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    ns = {"json": json, "re": re,
          "_FENCE_RE": re.compile(re.escape(chr(96) * 3) + r"(?:json)?\s*(.*?)"
                                 + re.escape(chr(96) * 3), re.S)}
    pre = "from __future__ import annotations" + chr(10)
    got = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            exec(compile(pre + ast.get_source_segment(src, node), "<x>", "exec"), ns)
            got.add(node.name)
    return ns, got


def main() -> int:
    root = __import__("os").path.dirname(__import__("os").path.dirname(
        __import__("os").path.abspath(__file__)))
    path = root + "/backend/app/services/dev.py"

    print("\u25b6\ufe0f  抢救被截断的 JSON")
    ns, got = load_funcs(path, {"_salvage_json", "parse_json_block",
                                "_flatten_to_text", "_normalize_plan_payload",
                                "_validate_plan_payload"})
    ok("抽出了要测的函数", got == {"_salvage_json", "parse_json_block",
                                  "_flatten_to_text", "_normalize_plan_payload",
                                  "_validate_plan_payload"},
       "实际 %s" % sorted(got))
    pb = ns.get("parse_json_block")
    norm = ns.get("_normalize_plan_payload")
    flat = ns.get("_flatten_to_text")
    valid = ns.get("_validate_plan_payload")
    if not all([pb, norm, flat, valid]):
        print("\n\u2717  函数没抽出来，后面没法测")
        return 1

    # 完整 JSON：不能被抢救逻辑改坏
    ok("完整 JSON 原样解析", pb('{"a": 1, "b": [1,2]}') == {"a": 1, "b": [1, 2]})
    ok("围栏 JSON 能抠出来",
       pb("```json\n{\"a\": 1}\n```") == {"a": 1})
    ok("末尾多逗号能修", pb('{"a":1,}') == {"a": 1})
    ok("非 JSON 不乱认", pb("抱歉，我不能完成这个请求") is None)

    # 截断：严格解析必须失败，抢救必须拿回一部分
    truncated = [
        ('{"summary": "abc', "summary"),
        ('{"a": {"b": [1, 2,', "a"),
        ('{"summary": "abc", "tasks": [{"title": "x", "desc": "被截断', "summary"),
        ('{"a":1,"b":2,"c":{"d":3,"e":"没写完', "a"),
    ]
    for text, key in truncated:
        strict = pb(text)
        salv = pb(text, salvage=True)
        ok("截断的 JSON 严格解析会失败：%s…" % text[:16], strict is None)
        ok("截断的 JSON 能抢救回来：%s…" % text[:16],
           isinstance(salv, dict) and key in salv, "抢救结果 %s" % salv)

    print("\n\u25b6\ufe0f  把模型随手给的形状掰直")
    ok("对象 summary 压成文本",
       flat({"goal": "做报表", "scope": {"in": ["a"]}}) != "")
    ok("字符串原样返回", flat(" 就是一句话 ") == "就是一句话")
    ok("列表压成分号串", "；" in flat(["a", "b"]))
    p = norm({"summary": {"project": "X", "goal": "G"},
              "architecture": ["第一层", "第二层"],
              "tech_stack": "Python",
              "risks": [{"risk": "慢"}],
              "tasks": {"title": "T1", "description": "D", "acceptance": "A",
                        "depends_on": 0}})
    ok("summary 被掰成字符串", isinstance(p["summary"], str) and p["summary"])
    ok("architecture 被掰成字符串", isinstance(p["architecture"], str))
    ok("tech_stack 变成数组", p["tech_stack"] == ["Python"])
    ok("risks 变成字符串数组",
       isinstance(p["risks"], list) and all(isinstance(x, str) for x in p["risks"]))
    ok("tasks 对象被掰成数组", isinstance(p["tasks"], list) and len(p["tasks"]) == 1)
    ok("depends_on 变成整数数组", p["tasks"][0]["depends_on"] == [0])

    print("\n\u25b6\ufe0f  校验器只在该失败时失败")
    ok("有 summary 就通过",
       (lambda: (valid({"summary": "s"}), True)[1])())
    try:
        valid({})
        ok("空对象会报错", False, "应该抛异常")
    except ValueError:
        ok("空对象会报错", True)

    print("")
    if FAILS:
        print("\u2717 %d 项不通过（共 %d 项）" % (len(FAILS), CHECKS))
        return 1
    print("\u2713 全部 %d 项检查通过" % CHECKS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
