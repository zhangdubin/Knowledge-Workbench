#!/usr/bin/env python3
"""按《笔记 UI 排版规范》排版的接口断言（打真实后端）

覆盖三件事，缺一不可：
  1. 规则接口本身 —— 一段散乱正文进来，规范笔记出去（含凭证遮盖）
  2. 幂等 —— 已经排好的笔记再排一次，返回「无改动」
  3. 落库 —— 已存在的笔记走 /api/notes/{id}/format 后，库里内容确实变了

用法：
    # 有会话 token（推荐，最省事）
    KB_TOKEN=xxxx python3 scripts/verify-note-autofmt-api.py

    # 或者给账号口令（会走登录接口）
    KB_USER=admin KB_PASS='你的口令' python3 scripts/verify-note-autofmt-api.py

    # 后端不在默认地址
    KB_BASE=http://127.0.0.1:8001 KB_TOKEN=xxxx python3 scripts/verify-note-autofmt-api.py

注意：这个脚本会**临时建一篇笔记再删掉**（软删除 → 进回收站）。
在正式库里跑完记得清回收站；不确定就用测试库。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("KB_BASE", "http://127.0.0.1:8001").rstrip("/")
TOKEN = os.environ.get("KB_TOKEN", "")
USER = os.environ.get("KB_USER", "admin")
PASS = os.environ.get("KB_PASS", "") or os.environ.get("KB_ADMIN_PASSWORD", "")

FAILED = 0
PASSED = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global FAILED, PASSED
    if cond:
        PASSED += 1
        print(f"✅ {name}")
    else:
        FAILED += 1
        print(f"❌ {name}  {detail}")


def call(method: str, path: str, body: dict | None = None, token: str = "") -> tuple[int, dict]:
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    tok = token or TOKEN
    if tok:
        # 会话既认 Cookie 也认 Bearer，这里用 Cookie（和后端 _set_cookie 一致）
        req.add_header("Cookie", f"kb_session={tok}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"detail": raw}


def login() -> str:
    if TOKEN:
        return TOKEN
    code, data = call("POST", "/api/auth/login", {"username": USER, "password": PASS})
    if code != 200:
        print(f"登录失败（{code}）：{data.get('detail')}")
        print("提示：用 KB_TOKEN=… 或 KB_USER/KB_PASS=… 再试；口令不对就先 "
              "./scripts/reset-admin-password.sh")
        sys.exit(2)
    # 登录接口同时下发 Cookie；这里从响应里取 token（不同版本字段名可能不同）
    tok = data.get("token") or data.get("session") or ""
    if not tok:
        print("登录成功但没拿到 token 字段，请直接用 KB_TOKEN 传会话")
        sys.exit(2)
    return tok


RAW = """已成功登录 18001 的 session
数据库 密码: YunHai@2026
$ nmap -sV -p 18001 120.224.7.251
$ curl -s http://120.224.7.251:18001/admin/login
| 项 | 值 | 状态 |
|---|---|---|
| 端口 | 18001 | 已完成 |
"""


def main() -> int:
    tok = login()

    code, health = call("GET", "/api/health", token=tok)
    check("后端在线", code == 200 and bool(health), f"{code} {health}")
    print(f"   版本：{health.get('version') or health.get('app_version') or '?'}")

    # ---------- 1. 规则排版 ----------
    code, r = call("POST", "/api/notes/format", {
        "content": RAW,
        "title": "登录记录",
        "tags": ["security"],
    }, token=tok)
    check("POST /api/notes/format 返回 200", code == 200, f"{code} {r}")
    text = r.get("text", "") if isinstance(r, dict) else ""
    check("补上了 front-matter", text.startswith("---\ntitle: 登录记录"), text[:60])
    check("H1 带语义 emoji", "# ✅ 登录记录" in text or "# 📌 登录记录" in text, text[:200])
    check("密码被遮成 secret-toggle", "secret-toggle" in text and "YunHai@2026</span>" in text,
          text[:400])
    check("命令行围栏成 bash", "```bash" in text, text[:400])
    check("表格表头加粗", "**项**" in text, text[:400])
    check("返回了改动清单", isinstance(r.get("changes"), list) and len(r["changes"]) > 0,
          str(r.get("changes"))[:200])
    check("改动清单标了规范章节",
          all(str(c.get("section", "")).startswith("§") for c in r.get("changes", [])), "")

    # ---------- 2. 幂等 ----------
    code2, r2 = call("POST", "/api/notes/format", {"content": text, "title": "登录记录"}, token=tok)
    check("再排一次不再有改动", code2 == 200 and r2.get("changes") == [],
          str(r2.get("changes"))[:200])
    check("再排一次内容一字不差", (r2.get("text") or "").rstrip() == text.rstrip(), "")

    # ---------- 2.5 要素体检 ----------
    check("返回要素体检清单", isinstance(r.get("elements"), list) and len(r["elements"]) >= 15,
          str(len(r.get("elements") or [])))
    check("要素体检标出了缺失项", any(not e["present"] for e in r.get("elements", [])), "")

    # ---------- 2.6 笔记类型骨架 ----------
    code, profs = call("GET", "/api/notes/profiles", token=tok)
    check("笔记类型清单可取", code == 200 and len(profs.get("profiles", [])) >= 4, str(profs)[:200])
    code, tpl_p = call("POST", "/api/notes/template",
                       {"title": "渗透骨架", "profile": "pentest-record"}, token=tok)
    ptxt = tpl_p.get("text") or ""
    check("渗透骨架含最高机密横幅与目标表",
          "最高机密" in ptxt and "🎯 资产" in ptxt, ptxt[:200])
    check("渗透骨架的要素基本齐全",
          sum(1 for e in tpl_p.get("elements", []) if e["present"]) >= 12,
          str([e["id"] for e in tpl_p.get("elements", []) if not e["present"]]))

    # ---------- 3. 规则清单 ----------
    code, rules = call("GET", "/api/notes/format/rules", token=tok)
    check("规则清单可取", code == 200 and len(rules.get("rules", [])) >= 10, str(rules)[:200])

    # ---------- 4. 模板（不依赖 AI） ----------
    code, tpl = call("POST", "/api/notes/template", {"title": "测试模板", "tags": ["a"]}, token=tok)
    check("模板接口不要求 AI 授权", code == 200, f"{code} {tpl}")
    check("模板含 front-matter 与 H1",
          (tpl.get("text") or "").startswith("---") and "\n# " in (tpl.get("text") or ""),
          (tpl.get("text") or "")[:80])

    # ---------- 5. 落库：已存在的笔记 ----------
    code, types = call("GET", "/api/entity-types", token=tok)
    note_type = next((t for t in (types if isinstance(types, list) else [])
                      if t.get("key") == "note"), None)
    check("拿得到 note 模型", code == 200 and note_type is not None, f"{code} {str(types)[:120]}")

    record_id = None
    try:
        code, rec = call("POST", f"/api/records/type/{note_type['id']}", {
            "data": {"title": "排版接口自测", "content": RAW, "tags": []},
        }, token=tok)
        check("临时笔记建好了", code == 200 and rec.get("id"), f"{code} {rec}")
        record_id = rec.get("id")

        code, fmt = call("POST", f"/api/notes/{record_id}/format", {}, token=tok)
        check("落库排版返回 changed=true", code == 200 and fmt.get("changed") is True,
              f"{code} {str(fmt)[:200]}")

        code, back = call("GET", f"/api/records/{record_id}", token=tok)
        content = (back.get("data") or {}).get("content", "")
        check("库里的正文确实变了", "secret-toggle" in content and "```bash" in content,
              content[:200])

        # ---------- 6. 保存时维护：版本 + 变更日志 ----------
        code, back2 = call("GET", f"/api/records/{record_id}", token=tok)
        base = dict(back2.get("data") or {})
        base["content"] = str(base.get("content") or "").replace("已成功登录", "已成功登录（人工补一句）", 1)
        code, _ = call("PUT", f"/api/records/{record_id}", {"data": base}, token=tok)
        check("PUT 保存成功", code == 200, str(code))
        code, back3 = call("GET", f"/api/records/{record_id}", token=tok)
        c3 = (back3.get("data") or {}).get("content", "")
        check("保存后 version 自动升到 1.1", "version: 1.1" in c3, c3[:200])
        check("保存后变更日志写清了改了什么（章节 + 片段，不是只写 +N 字符）",
              "人工编辑 · " in c3 and "v1.1" in c3
              and any(k in c3 for k in ("改「", "新增「", "删除「", "改正文开头")), c3[-300:])

        code, fmt2 = call("POST", f"/api/notes/{record_id}/format", {}, token=tok)
        check("再排一次返回无改动", code == 200 and fmt2.get("changed") is False,
              str(fmt2)[:160])
    finally:
        if record_id:
            call("DELETE", f"/api/records/{record_id}", token=tok)
            print(f"   （已把自测笔记 #{record_id} 移进回收站）")

    print()
    print(f"{PASSED} 项通过，{FAILED} 项失败")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
