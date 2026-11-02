#!/usr/bin/env python3
"""从 CHANGELOG.md 的某一节生成 GitHub Release

为什么从 CHANGELOG 取，而不是另写一份 Release 说明：
    两份说明必然会走偏 —— CHANGELOG 改了、Release 没改，
    用户在 GitHub 上看到的和仓库里记的不一样。
    从同一份文本生成，只有一种可能：对不上。
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

TOKEN_FILE = "/tmp/.gh_token"
API = "https://api.github.com"
REPO = "zhangdubin/Knowledge-Workbench"


def token() -> str:
    with open(TOKEN_FILE, encoding="utf-8") as f:
        return f.read().strip()


def api(method: str, path: str, payload=None, allow_404: bool = False):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        API + path, data=data, method=method,
        headers={
            "Authorization": "Bearer " + token(),
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "kb-workbench-release",
        })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode()
    except urllib.error.HTTPError as e:
        # 查「这个 tag 的 Release 存不存在」时 404 是正常答案，不是错误
        if e.code == 404 and allow_404:
            return {}
        raise
    return json.loads(body) if body else {}


def section(version: str) -> str:
    text = Path("CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(r"^## " + re.escape(version) + r".*?$", text, re.M)
    if not m:
        raise SystemExit(f"CHANGELOG 里找不到 {version} 那一节")
    start = m.start()
    nxt = re.search(r"^## ", text[m.end():], re.M)
    end = m.end() + nxt.start() if nxt else len(text)
    body = text[start:end].rstrip()
    # 第一行是标题，Release 页自己也有标题，去掉免得重复
    lines = body.split("\n")
    title, rest = lines[0], lines[1:]
    return "\n".join(rest).strip()


def main() -> int:
    version = sys.argv[1] if len(sys.argv) > 1 else "1.1.0"
    tag = f"v{version}"
    notes = section(version)
    body = {
        "tag_name": tag,
        "target_commitish": "main",
        "name": f"KB Workbench v{version}",
        "body": notes,
        "draft": False,
        "prerelease": False,
    }
    existing = api("GET", f"/repos/{REPO}/releases/tags/{tag}", allow_404=True)
    if existing.get("id"):
        res = api("PATCH", f"/repos/{REPO}/releases/{existing['id']}", body)
        print("updated:", res.get("html_url"))
    else:
        res = api("POST", f"/repos/{REPO}/releases", body)
        print("created:", res.get("html_url"))
    print("assets:", len(res.get("assets", [])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
