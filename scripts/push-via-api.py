#!/usr/bin/env python3
"""用 GitHub 的 Git Data API 推送提交（git push 连不上 github.com 时的兜底）

为什么需要它：
    github.com 的 443 在某些网络里连不通（连接超时 / HTTP2 帧错误），
    但 api.github.com 往往是通的 —— 两者是不同��主机、不同 CDN。
    这时 git push 用不了，但 REST API 照样能建提交：
    blob → tree → commit → ref，一条链走完。

用法：
    python3 scripts/push-via-api.py <版本号>

前提：
    - 本地已 commit 干净（工作区无未提交改动）
    - /tmp/.gh_token 里有 token（600 权限）
    - 远端 main 是要推送的父提交

安全：
    token 只从文件读，不进命令行参数、不打印。
"""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

TOKEN_FILE = "/tmp/.gh_token"
API = "https://api.github.com"
REPO = "zhangdubin/Knowledge-Workbench"


def token() -> str:
    with open(TOKEN_FILE, encoding="utf-8") as f:
        return f.read().strip()


def api(method: str, path: str, body=None):
    """调一次 API。失败就重试 —— 这条链路本身也会抖。"""
    url = path if path.startswith("http") else API + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    last = None
    for attempt in range(1, 6):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {token()}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            last = f"HTTP {e.code}: {detail}"
            if e.code in (401, 403, 404, 422):
                break  # 这些重试也没用
        except Exception as e:  # noqa: BLE001 - 网络异常统一重试
            last = f"{type(e).__name__}: {e}"
        time.sleep(3 * attempt)
    raise RuntimeError(f"{method} {path} 失败：{last}")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def main() -> int:
    tag = sys.argv[1] if len(sys.argv) > 1 else ""
    if not tag:
        print("用法：push-via-api.py <版本号>", file=sys.stderr)
        return 2

    local_sha = git("rev-parse", "HEAD")
    parent = api("GET", f"/repos/{REPO}/git/ref/heads/main")["object"]["sha"]
    print(f"远端 main: {parent[:12]}   本地 HEAD: {local_sha[:12]}")

    if parent == local_sha:
        print("远端已经是这个提交了")
    else:
        # ---- 1. 收集要改的文件 ----
        names = git("diff", "--name-only", f"{parent}..{local_sha}").splitlines()
        if not names:
            print("没有差异，退出")
            return 0
        print(f"要推送 {len(names)} 个文件")

        # ---- 2. 逐个建 blob ----
        entries = []
        for name in names:
            with open(name, "rb") as f:
                content = base64.b64encode(f.read()).decode("ascii")
            blob = api("POST", f"/repos/{REPO}/git/blobs",
                       {"content": content, "encoding": "base64"})
            entries.append({
                "path": name,
                "mode": "100644",
                "type": "blob",
                "sha": blob["sha"],
            })
            print(f"  blob {name[:46]:<48} {blob['sha'][:10]}")

        # ---- 3. 建 tree（基于远端 main 的 tree）----
        base_tree = api("GET", f"/repos/{REPO}/git/commits/{parent}")["tree"]["sha"]
        tree = api("POST", f"/repos/{REPO}/git/trees",
                   {"base_tree": base_tree, "tree": entries})
        print(f"  tree {tree['sha'][:10]}")

        # ---- 4. 建 commit（沿用本地的提交信息）----
        message = git("log", "-1", "--pretty=%B", local_sha)
        commit = api("POST", f"/repos/{REPO}/git/commits", {
            "message": message,
            "tree": tree["sha"],
            "parents": [parent],
        })
        print(f"  commit {commit['sha'][:12]}")

        # ---- 5. 推 ref ----
        api("PATCH", f"/repos/{REPO}/git/refs/heads/main",
            {"sha": commit["sha"], "force": False})
        print(f"  main 已更新到 {commit['sha'][:12]}")

    # ---- 6. 打标签 ----
    head_sha = api("GET", f"/repos/{REPO}/git/ref/heads/main")["object"]["sha"]
    try:
        api("GET", f"/repos/{REPO}/git/ref/tags/{tag}")
        api("PATCH", f"/repos/{REPO}/git/refs/tags/{tag}",
            {"sha": head_sha, "force": True})
        print(f"  标签 {tag} 已指到 {head_sha[:12]}")
    except RuntimeError:
        api("POST", f"/repos/{REPO}/git/refs",
            {"ref": f"refs/tags/{tag}", "sha": head_sha})
        print(f"  标签 {tag} 已创建 → {head_sha[:12]}")

    print(f"完成：main 与 {tag} 都在 {head_sha[:12]}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"失败：{e}", file=sys.stderr)
        sys.exit(1)
