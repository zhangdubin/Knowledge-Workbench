#!/usr/bin/env python3
"""打印一条还没过期的会话 token（只读）。

用途：截图脚本用它直接带上 kb_session Cookie，
免得为了截图去改管理员口令。

**必须通过正在运行的容器去读库** —— 这一点不是讲究，是必须的：
后端容器以 WAL 模式打开着 data/kb.db，WAL 的索引（-shm）是**按打开它的
那一组进程共享的**。宿主机上再开一个 sqlite3 连接去读同一个库，
在 Docker Desktop 的 bind mount 下会拿到**另一份 -shm**，
于是两边各自维护 WAL 索引、各自回放 WAL ——
轻则报 "disk I/O error"，重则报 "file is not a database"，
把线上库搞得读不出来。

所以这里的顺序是：
  1) 容器在跑 → docker exec 进去读（同一个挂载、同一份 -shm，安全）
  2) 容器没跑 → 宿主机直接读（这时没人写，安全）

用法：python3 scripts/kb-session-token.py [数据库路径]
"""
import datetime
import os
import shutil
import sqlite3
import subprocess
import sys

# 容器里读库的那段代码：只查一条还没过期的 token
_IN_CONTAINER = r"""
import datetime, sqlite3, sys
con = sqlite3.connect('/app/data/kb.db')
now = datetime.datetime.now()
for token, expires in con.execute(
    'select token, expires_at from user_session order by expires_at desc'
):
    try:
        if datetime.datetime.fromisoformat(expires) > now:
            print(token)
            sys.exit(0)
    except (TypeError, ValueError):
        continue
sys.exit(1)
"""


def _token_from_container() -> str:
    """从正在运行的容器里读（容器名可猜：kb-backend / kb-workbench-backend-1）"""
    candidates = ["kb-backend"]
    # compose 项目名可能是 kb-workbench，服务名 backend
    for name in ("kb-workbench-backend-1", "kb-workbench_backend_1", "backend"):
        candidates.append(name)
    for name in candidates:
        if shutil.which("docker") is None:
            return ""
        probe = subprocess.run(
            ["docker", "exec", name, "python", "-c", "print(1)"],
            capture_output=True, text=True, timeout=10)
        if probe.returncode != 0:
            continue
        out = subprocess.run(
            ["docker", "exec", name, "python", "-c", _IN_CONTAINER],
            capture_output=True, text=True, timeout=20)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    return ""


def _token_from_host(db: str) -> str:
    """容器没跑时，才在宿主机上直接读

    不能用 mode=ro：WAL 模式下只读连接遇到需要回放的 WAL 会报
    "unable to open database file"。这里只读不写，够用。
    """
    con = sqlite3.connect(db)
    now = datetime.datetime.now()
    for token, expires in con.execute(
        "select token, expires_at from user_session order by expires_at desc"
    ):
        try:
            if datetime.datetime.fromisoformat(expires) > now:
                return token
        except (TypeError, ValueError):
            continue
    return ""


def main() -> int:
    db = sys.argv[1] if len(sys.argv) > 1 else "data/kb.db"
    token = _token_from_container()
    if token:
        print(token)
        return 0
    if not os.path.exists(db):
        return 1
    print(_token_from_host(db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
