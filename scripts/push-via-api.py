#!/usr/bin/env python3
"""用 GitHub 的 Git Data API 推送提交（git push 连不上 github.com 时的兜底）

为什么需要它：
    github.com 的 443 在某些网络里连不通（连接超时 / HTTP2 帧错误），
    但 api.github.com 往往是通的 —— 两者是不同的主机、不同的 CDN。
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
from datetime import datetime, timezone

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


def git_bytes(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args], capture_output=True, check=True
    ).stdout


def git_show(commit: str, path: str) -> bytes:
    """取某个提交里某个文件的原始内容（二进制安全）。

    为什么不用 open(path)：对齐远端时会 reset --hard，
    工作区那时已经是父提交的内容了 —— 读磁盘拿到的是旧内容。
    """
    return git_bytes("show", f"{commit}:{path}")


def git_has_path(commit: str, path: str) -> bool:
    """这个提交里有没有这个路径。"""
    r = subprocess.run(["git", "ls-tree", commit, "--", path],
                       capture_output=True, text=True)
    return bool(r.stdout.strip())


def align_local_to(remote_sha: str) -> bool:
    """把远端 commit 在本地复刻出来，并把本地分支指过去。

    为什么需要：API 建的 commit 和本地 commit 的 sha 不一样
    （committer 的时间戳不同），但内容完全一致。远端那个 commit 对象本地又没有 ——
    下次推送时 `git diff <远端sha>..<本地sha>` 会因为不认识父提交而直接失败。

    复刻有两个坑（都踩过）：
      1. `git commit-tree` 会给消息补一个尾换行，而远端存的**没有**尾换行
         → 手工拼 commit 原文，用 `git hash-object -t commit -w` 落对象
      2. API 返回的日期是 UTC（"...Z"），但**原文里保留的是提交时的本地时区**
         （这里 +0800）—— 用 UTC 拼出来 sha 对不上

    ⚠️ 工作区有未提交改动时**不** reset --hard：
       reset --hard 会把没提交的活儿一起冲掉（踩过一次：
       改推送脚本 → 跑推送 → 脚本把自己的改动冲没了 → 白改一场）。
    """
    try:
        c = api("GET", f"/repos/{REPO}/git/commits/{remote_sha}")
        tree_sha = c["tree"]["sha"]
        parents = [p["sha"] for p in c["parents"]]
        message = c["message"]

        def ident(who) -> str:
            epoch = int(datetime.strptime(who["date"], "%Y-%m-%dT%H:%M:%SZ")
                        .replace(tzinfo=timezone.utc).timestamp())
            off = int(time.localtime(epoch).tm_gmtoff)
            sign = "+" if off >= 0 else "-"
            off = abs(off)
            return (f"{who['name']} <{who['email']}> {epoch} "
                    f"{sign}{off // 3600:02d}{(off % 3600) // 60:02d}")

        raw = f"tree {tree_sha}\n"
        for p_ in parents:
            raw += f"parent {p_}\n"
        raw += f"author {ident(c['author'])}\n"
        raw += f"committer {ident(c['committer'])}\n\n"
        raw += message
        local = subprocess.run(
            ["git", "hash-object", "-t", "commit", "-w", "--stdin"],
            input=raw, capture_output=True, text=True, check=True).stdout.strip()
        if local != remote_sha:
            print(f"  ! 本地复刻出的 sha 与远端不一致（{local[:12]} ≠ {remote_sha[:12]}）")
            return False
        # 远端那个 tree 本地不一定存在（文件模式不一致的历史遗留）。
        # 不存在就别去 checkout 它 —— 本地 HEAD 会指向一个 tree 缺失的提交，
        # 之后所有 git 命令都会报 "bad tree object"。
        have_tree = subprocess.run(["git", "cat-file", "-e", f"{tree_sha}^{{tree}}"],
                                   capture_output=True, text=True).returncode == 0
        if not have_tree:
            print(f"  ! 远端那个 tree 本地没有（{tree_sha[:10]}），本地分支保持不动；"
                  f"推送功能不受影响（清单比对走 API）")
            return True
        dirty = subprocess.run(["git", "status", "--porcelain"],
                               capture_output=True, text=True).stdout.strip()
        if dirty:
            # 有未提交的活儿 —— 只挪分支指针，不碰工作区
            subprocess.run(["git", "update-ref", "refs/heads/main", remote_sha], check=True)
            subprocess.run(["git", "reset", "--soft", remote_sha], check=True,
                           capture_output=True, text=True)
            print(f"  本地分支已指向 {remote_sha[:12]}（工作区有未提交改动，保留原样）")
        else:
            subprocess.run(["git", "update-ref", "refs/heads/main", remote_sha], check=True)
            r = subprocess.run(["git", "reset", "--hard", remote_sha],
                               capture_output=True, text=True)
            if r.returncode == 0:
                print(f"  本地分支已对齐到 {remote_sha[:12]}（内容相同，工作区未变）")
            else:
                print(f"  ! 本地无法 checkout 远端那个提交（{remote_sha[:12]}），"
                      f"分支指针已更新，下次推送会走 API 比对清单")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  ! 本地对齐失败（不影响远端）：{e}")
        return False


def changed_files_against_remote(parent: str, local_sha: str):
    """算出「远端 → 本地」需要动的文件清单。

    为什么不用 `git diff <远端sha>..<本地sha>`：
    远端那个 commit 的 tree 在本地可能压根不存在
    （tree 里记录的文件模式跟本地不一致时，本地没有那个 tree 对象，
    diff 直接报 "not a valid object name"）。
    跟远端比文件清单不依赖本地有那些对象 —— 直接问 API 要远端的清单，
    两边按「路径 + 模式 + blob sha」对齐即可。
    """
    parent_tree = api("GET", f"/repos/{REPO}/git/commits/{parent}")["tree"]["sha"]
    remote = api("GET", f"/repos/{REPO}/git/trees/{parent_tree}?recursive=1")
    remote_map = {}
    for e in remote.get("tree", []):
        if e.get("type") == "blob":
            remote_map[e["path"]] = (e.get("mode", "100644"), e["sha"])

    local_map = {}
    # core.quotePath=false：默认 git 会把中文路径转义成 \345\256\211...
    # 那样本地清单里是转义串、远端清单里是原文 → 两边对不上，
    # 远端会多出一个乱码路径的文件
    for line in git("-c", "core.quotePath=false", "ls-tree", "-r", "--full-tree",
                    local_sha).splitlines():
        meta, path = line.split("\t", 1)
        mode, typ, sha = meta.split()
        if typ == "blob":
            local_map[path] = (mode, sha)

    changed = []
    for path, val in local_map.items():
        if remote_map.get(path) != val:
            changed.append(path)
    for path in remote_map:
        if path not in local_map:
            changed.append(path)      # 本地删了的
    return changed, parent_tree


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
        # ---- 0. 先把远端提交复刻到本地 ----
        # 不对齐的话，`git diff <远端sha>..` 会因为不认识这个父提交而失败
        align_local_to(parent)

        # ---- 1. 收集要改的文件 ----
        names, base_tree = changed_files_against_remote(parent, local_sha)
        if not names:
            print("没有差异，退出")
            return 0
        print(f"要推送 {len(names)} 个文件")

        # ---- 2. 逐个建 blob ----
        entries = []
        for name in names:
            # 本地已经删掉的文件（git diff 会列出来，但提交里没有了）：
            # tree 里要写 sha=null 才会真的删掉，不能跳过 —— 跳过了远端还留着旧文件
            if not git_has_path(local_sha, name):
                entries.append({
                    "path": name,
                    "mode": "100644",
                    "type": "blob",
                    "sha": None,          # null = 删除
                })
                print(f"  del  {name[:46]:<48} (已删除)")
                continue
            # ⚠️ 内容必须从**提交对象**里取，不能读磁盘。
            # 上面对齐远端时会 reset --hard，工作区就变成了父提交的内容 ——
            # 这时候读磁盘拿到的是**旧内容**，推上去的也是旧的
            # （踩过一次：改完 UI 提交了、推送了，
            #   远端却还是改之前的代码，本地也被 reset 掉了）。
            content = base64.b64encode(git_show(local_sha, name)).decode("ascii")
            blob = api("POST", f"/repos/{REPO}/git/blobs",
                       {"content": content, "encoding": "base64"})
            # mode 要按本地实际的来（100755 可执行 / 100644 普通）。
            # 写死 100644 的话，脚本文件推上去就没了执行位 ——
            # tree 的 sha 也会跟着和本地对不上。
            mode = "100644"
            ls = git("ls-tree", local_sha, "--", name).split()
            if len(ls) >= 2 and ls[0] in ("100644", "100755", "120000"):
                mode = ls[0]
            entries.append({
                "path": name,
                "mode": mode,
                "type": "blob",
                "sha": blob["sha"],
            })
            print(f"  blob {name[:46]:<48} {blob['sha'][:10]}")

        # ---- 3. 建 tree（基于远端 main 的 tree，只提交变了的文件）----
        # 注意别改成全量：文件一多，GitHub 的 tree 接口会超时（422）
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

    # ---- 7. 本地对齐 ----
    align_local_to(head_sha)

    print(f"完成：main 与 {tag} 都在 {head_sha[:12]}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"失败：{e}", file=sys.stderr)
        sys.exit(1)
