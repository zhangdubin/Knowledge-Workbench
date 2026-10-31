#!/usr/bin/env python3
"""备份「导出到本地 / 从本地导入」的离线自测

跑法（仓库根目录，依赖装在容器里时用这条）：
    docker run --rm -i -v "$PWD/backend/app:/app/app:ro" \
      --entrypoint python kb-workbench-backend - < scripts/verify-backup-export-import.py

也可以在装了依赖的机器上直接跑：
    python3 scripts/verify-backup-export-import.py

验六件事：
  1. 导出的 .tar.gz 里确实有 kb.db / files/ / meta.json；
  2. 把这个包导回去，备份列表里会多出一条 snap-…-imported，
     它的 kb.db 通过 quick_check，files/ 里的原文也在；
  3. 导入**不动线上数据**（导入前后线上库的行数不变）；
  4. 恶意归档一律被拒：路径穿越 ../evil、绝对路径、符号链接、
     没有 kb.db、解压炸弹；
  5. 导出接口的名字校验：../ 之类的名字拿不到任何文件；
  6. 导入的快照能走现有的还原流程（这里连真正的还原都跑一遍）。

**全程只碰临时目录**：库、文件目录、备份目录都由脚本建在 tempfile 下，
线上的 data/ 与 backups/ 一个字节都不会被读到或写到。
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import os
import shutil
import sys
import tarfile
import tempfile

# ---- 先把运行环境钉死在临时目录，再 import 应用模块 ----
# 应用模块在 import 时就会读 config（数据库 URL、备份目录、文件目录…），
# 所以环境变量必须先设好，否则会连到线上库、往线上备份目录里写东西。
TMP = tempfile.mkdtemp(prefix="kb-verify-backup-")
DATA_DIR = os.path.join(TMP, "data")
FILES_DIR = os.path.join(TMP, "files")
BACKUP_DIR = os.path.join(TMP, "backups")
for _d in (DATA_DIR, FILES_DIR, BACKUP_DIR):
    os.makedirs(_d, exist_ok=True)

os.environ["DATA_DIR"] = DATA_DIR
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DATA_DIR}/kb.db"
os.environ["FILE_STORE_DIR"] = FILES_DIR
os.environ["BACKUP_DIR"] = BACKUP_DIR
os.environ["FILE_STORE"] = "fs"
os.environ["UPLOAD_MAX_MB"] = "64"
# 关掉鉴权：HTTP 层自测不想先登录（关掉后是等价管理员身份，见 auth.py）
os.environ["AUTH_ENABLED"] = "false"
# 定时任务在自测里没有意义，关掉免得后台噪声干扰断言
os.environ["MAINTENANCE_ENABLED"] = "false"

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.join(os.path.dirname(_HERE), "backend")
if os.path.isdir(_BACKEND):
    sys.path.insert(0, _BACKEND)

from app.services import maintenance as maint            # noqa: E402

FAILURES: list[str] = []
CHECKS = 0


def check(cond: bool, label: str) -> bool:
    global CHECKS
    CHECKS += 1
    if cond:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}")
        FAILURES.append(label)
    return bool(cond)


def section(title: str) -> None:
    print(f"\n== {title} ==")


# ------------------------------------------------------------ 造测试数据

async def _init_db() -> None:
    """在临时目录里建一份真实的库

    用应用自己的模型建表，字段与线上一致 —— 还原流程要读
    document.storage / document.path 等列，字段不对就没法验。
    """
    from app import models  # noqa: F401  让 Base.metadata 认识所有模型
    from app.database import Base, engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _seed() -> str:
    """塞一条外置原文的文档（这样 files/ 目录里真的有东西可备）"""
    from app.database import SessionLocal
    from app.models import Document
    from app.services import filestore

    blob = "备份导出导入自测用的原文内容。\n".encode("utf-8")
    sha = hashlib.sha256(blob).hexdigest()
    rel = filestore.put(blob, sha, ".txt")
    async with SessionLocal() as db:
        db.add(Document(title="自测文档", filename="verify.txt", ext=".txt",
                        mime="text/plain", size=len(blob), sha256=sha,
                        storage=filestore.MODE_FS, path=rel, data=None,
                        kind="other", tags=[], app="default"))
        await db.commit()
    return rel


async def _doc_count() -> int:
    from app.database import SessionLocal
    from app.models import Document
    from sqlalchemy import select
    async with SessionLocal() as db:
        return len((await db.execute(select(Document.id))).all())


# ------------------------------------------------------------ 造归档

def _make_tar(path: str, entries: list[tuple[str, bytes]], *, symlink: str = "") -> str:
    """做一个测试用归档

    entries = [(归档内路径, 内容)]；symlink 非空时再加一个指向外部的链接成员。
    """
    with tarfile.open(path, "w:gz") as tf:
        for name, data in entries:
            ti = tarfile.TarInfo(name=name)
            ti.size = len(data)
            ti.mtime = 0
            tf.addfile(ti, io.BytesIO(data))
        if symlink:
            ti = tarfile.TarInfo(name=symlink)
            ti.type = tarfile.SYMTYPE
            ti.linkname = "/etc/passwd"
            ti.mtime = 0
            tf.addfile(ti)
    return path


# ------------------------------------------------------------ 主流程

async def run() -> None:
    section("准备临时环境")
    print(f"  临时目录：{TMP}")
    print(f"  库：{DATA_DIR}/kb.db")
    print(f"  备份目录：{BACKUP_DIR}")
    check(os.path.isdir(BACKUP_DIR), "备份目录建在临时目录里（不碰线上 backups/）")

    await _init_db()
    rel = await _seed()
    check(os.path.isfile(os.path.join(FILES_DIR, rel)), "测试原文已落到临时文件目录")
    before_docs = await _doc_count()

    # ---- 1. 做一份快照 ----
    section("1. 做快照并导出")
    snap = await maint.make_backup()
    check(snap.get("ok"), f"make_backup 成功：{snap.get('name')}")
    snap_dir = snap["path"]
    check(os.path.isfile(os.path.join(snap_dir, "kb.db")), "快照里有 kb.db")
    check(os.path.isdir(os.path.join(snap_dir, "files")), "快照里有 files/ 目录")
    check(os.path.isfile(os.path.join(snap_dir, "meta.json")), "快照里有 meta.json")

    exp = await maint.export_backup(snap["name"])
    check(exp.get("ok"), f"export_backup 成功：{exp.get('filename')}")
    archive = exp.get("path") or ""
    check(os.path.isfile(archive), "导出的 .tar.gz 落在临时文件里")
    check((exp.get("bytes") or 0) > 0, f"归档非空（{exp.get('bytes')} 字节）")

    with tarfile.open(archive, "r:gz") as tf:
        members = tf.getnames()
    check("kb.db" in members, "归档里有 kb.db")
    check("meta.json" in members, "归档里有 meta.json")
    check(any(m.startswith("files/") for m in members),
          f"归档里有 files/（共 {len(members)} 个成员）")
    check(not any(m.startswith("/") or ".." in m for m in members),
          "归档里没有绝对路径或 .. 成员")

    # ---- 2. 导入刚导出的包 ----
    section("2. 导入刚导出的包")
    imp = await maint.import_backup(archive, original_name="kb-backup-test.tar.gz")
    check(imp.get("ok"), f"import_backup 成功：{(imp.get('entry') or {}).get('name')}")
    entry = imp.get("entry") or {}
    imported_name = entry.get("name") or ""
    check("-imported" in imported_name, f"导入的快照名字带 -imported：{imported_name}")
    check(imp.get("complete") is True, "导入的快照被标为完整（含 files/）")
    check((imp.get("verify") or {}).get("quick_check") == "ok",
          f"导入时 quick_check 通过：{(imp.get('verify') or {}).get('quick_check')}")

    items = await maint.list_backups()
    names = [i["name"] for i in items]
    check(imported_name in names, "导入的快照出现在备份列表里")
    imp_item = next((i for i in items if i["name"] == imported_name), None)
    check(imp_item is not None and imp_item["kind"] == "snapshot",
          "导入的条目是 snapshot 类型（可以用「还原」）")
    check(imp_item is not None and imp_item.get("imported") is True,
          "导入的条目带 imported 标记")

    imp_dir = os.path.join(BACKUP_DIR, imported_name)
    report = maint._verify_snapshot_db(os.path.join(imp_dir, "kb.db"))
    check(report.get("ok"), f"导入快照的 kb.db 再次 quick_check 通过（{report.get('quick_check')}）")
    check(os.path.isdir(os.path.join(imp_dir, "files")), "导入快照里有 files/ 目录")
    check(any(os.path.isfile(os.path.join(dp, f))
              for dp, _d, fs in os.walk(os.path.join(imp_dir, "files")) for f in fs),
          "导入快照的 files/ 里确实有原文")

    # ---- 3. 导入不动线上数据 ----
    section("3. 导入只登记、不动数据")
    after_docs = await _doc_count()
    check(after_docs == before_docs,
          f"导入前后线上文档数不变（{before_docs} → {after_docs}）")

    # ---- 3b. 别人手工打的包：库文件被多包了一层目录 ----
    section("3b. 多包一层目录的包")
    nested_dir = os.path.join(TMP, "nested")
    os.makedirs(os.path.join(nested_dir, "snap-x"), exist_ok=True)
    shutil.copy2(os.path.join(snap_dir, "kb.db"),
                 os.path.join(nested_dir, "snap-x", "kb.db"))
    shutil.copytree(os.path.join(snap_dir, "files"),
                    os.path.join(nested_dir, "files"))
    nested_tar = os.path.join(TMP, "nested.tar.gz")
    with tarfile.open(nested_tar, "w:gz") as tf:
        tf.add(nested_dir, arcname=".")
    r = await maint.import_backup(nested_tar, original_name="nested.tar.gz")
    check(bool(r.get("ok")),
          f"多包一层目录的包也能导入：{(r.get('entry') or {}).get('name')}（{r.get('error')}）")
    check(r.get("complete") is True,
          "这种情况下 files/ 也能被找到（标为完整，而不是不完整）")

    # ---- 4. 恶意归档必须被拒 ----
    section("4. 恶意归档被拒绝")
    hostile_dir = os.path.join(TMP, "hostile")
    os.makedirs(hostile_dir, exist_ok=True)

    # 4a 路径穿越
    p = _make_tar(os.path.join(hostile_dir, "traversal.tar.gz"),
                  [("../evil.txt", b"pwned"), ("kb.db", b"not-a-db")])
    r = await maint.import_backup(p, original_name="traversal.tar.gz")
    check(not r.get("ok") and "越界路径" in str(r.get("error")),
          f"路径穿越（../evil）被拒：{r.get('error')}")
    check(not os.path.exists(os.path.join(TMP, "evil.txt"))
          and not os.path.exists("/tmp/evil.txt"),
          "穿越目标没有被创建")

    # 4b 绝对路径
    p = _make_tar(os.path.join(hostile_dir, "absolute.tar.gz"),
                  [("/tmp/kb-verify-abs.txt", b"pwned")])
    r = await maint.import_backup(p, original_name="absolute.tar.gz")
    check(not r.get("ok") and "绝对路径" in str(r.get("error")),
          f"绝对路径成员被拒：{r.get('error')}")
    check(not os.path.exists("/tmp/kb-verify-abs.txt"), "绝对路径目标没有被创建")

    # 4c 符号链接
    p = _make_tar(os.path.join(hostile_dir, "symlink.tar.gz"),
                  [("kb.db", b"x")], symlink="passwd")
    r = await maint.import_backup(p, original_name="symlink.tar.gz")
    check(not r.get("ok") and "非普通文件" in str(r.get("error")),
          f"符号链接成员被拒：{r.get('error')}")

    # 4d 没有 kb.db
    p = _make_tar(os.path.join(hostile_dir, "nodb.tar.gz"),
                  [("readme.txt", b"hello")])
    r = await maint.import_backup(p, original_name="nodb.tar.gz")
    check(not r.get("ok") and "没有找到 kb.db" in str(r.get("error")),
          f"没有 kb.db 的包被拒：{r.get('error')}")

    # 4e 解压炸弹：把展开下限临时调小，造一个「很小但撑得很大」的包
    old_floor = maint.IMPORT_MIN_EXPANDED
    maint.IMPORT_MIN_EXPANDED = 1 * maint.MB
    try:
        p = _make_tar(os.path.join(hostile_dir, "bomb.tar.gz"),
                      [("kb.db", b"\0" * (16 * 1024 * 1024))])
        r = await maint.import_backup(p, original_name="bomb.tar.gz")
        check(not r.get("ok") and "解压炸弹" in str(r.get("error")),
              f"解压炸弹被拒：{r.get('error')}")
    finally:
        maint.IMPORT_MIN_EXPANDED = old_floor

    # 4f 生产配置下的上限本身也是有限的（不能因为 bomb 测试调过就忘了）
    lim = maint._import_limits(1024)
    check(0 < lim["expanded"] <= maint.IMPORT_MIN_EXPANDED,
          f"小包的展开上限被膨胀比卡住（{lim['expanded'] // maint.MB} MB ≤ "
          f"{maint.IMPORT_MIN_EXPANDED // maint.MB} MB）")
    lim2 = maint._import_limits(50 * 1024 * 1024)
    check(lim2["expanded"] <= lim2["absolute"],
          f"上限不会超过绝对上限（{lim2['expanded'] // maint.MB} MB ≤ "
          f"{lim2['absolute'] // maint.MB} MB）")

    # ---- 5. 导出时的名字校验 ----
    section("5. 导出的名字校验")
    for bad in ("../../etc/passwd", "..", "snap-不存在", "a/b", "a\\b"):
        r = await maint.export_backup(bad)
        check(not r.get("ok"), f"名字「{bad}」被拒：{r.get('error')}")
    r = await maint.export_backup(snap["name"])
    check(bool(r.get("ok")), "合法名字仍然可以导出")

    # ---- 6. 旧格式（v0.2 的 kb-<时间>.db）也能导出与导入 ----
    section("6. 旧格式备份")
    legacy_name = "kb-20240101-000000.db"
    shutil.copy2(os.path.join(snap_dir, "kb.db"), os.path.join(BACKUP_DIR, legacy_name))
    items = await maint.list_backups()
    legacy = next((i for i in items if i["name"] == legacy_name), None)
    check(legacy is not None and legacy["kind"] == "legacy",
          "旧格式备份被标成 legacy")
    lexp = await maint.export_backup(legacy_name)
    check(bool(lexp.get("ok")), f"旧格式备份可以导出：{lexp.get('filename')}")
    with tarfile.open(lexp["path"], "r:gz") as tf:
        legacy_members = tf.getnames()
    check(legacy_name in legacy_members,
          f"旧格式归档里就是那个 .db（{legacy_members}）")
    limp = await maint.import_backup(lexp["path"], original_name=lexp["filename"])
    check(bool(limp.get("ok")),
          f"旧格式的包也能导入：{(limp.get('entry') or {}).get('name')}（{limp.get('error')}）")
    check(limp.get("complete") is False,
          "只有库、没有 files/ 的导入被标成「不完整」")
    legacy_items = await maint.list_backups()
    legacy_imp = next((i for i in legacy_items
                        if i["name"] == (limp.get("entry") or {}).get("name")), None)
    check(legacy_imp is not None and legacy_imp.get("complete") is False,
          "列表里这条也标着不完整（别让人误以为它能恢复附件）")

    # ---- 7. 导入的快照能走现有的还原流程 ----
    section("7. 导入的快照可以还原")
    res = await maint.restore_snapshot(imported_name, who="verify")
    check(res.get("ok"), f"restore_snapshot 成功：{res.get('error')}")
    check((res.get("restored") or {}).get("document") == before_docs,
          f"还原后文档数与快照一致（{before_docs}）")
    check(bool(res.get("safety_snapshot")), "还原前留了退路快照")
    after_restore = await _doc_count()
    check(after_restore == before_docs,
          f"还原后线上文档数不变（{after_restore}）")
    check(os.path.isfile(os.path.join(FILES_DIR, rel)),
          "还原后原文仍在文件目录里")

    # 还原会再补一份退路快照，最后再核一次列表仍然正常
    items = await maint.list_backups()
    check(imported_name in [i["name"] for i in items],
          "还原之后导入的快照仍在列表里")

    # ---- 8. HTTP 接口层 ----
    await _http_checks()


async def _http_checks() -> None:
    """HTTP 层：两个新接口真的能用（路由、下载、上传、错误码）"""
    section("8. HTTP 接口")
    from fastapi.testclient import TestClient

    from app.database import engine
    from app.main import app

    # 引擎的连接池是**绑在事件循环上**的：换循环前必须 dispose，
    # 否则 TestClient 的请求会拿到「另一个 loop 建的连接」而报奇怪的错
    await engine.dispose()

    with TestClient(app) as client:
        r = client.post("/api/system/storage/backup")
        check(r.status_code == 200, f"POST /storage/backup 返回 {r.status_code}")
        name = (r.json() or {}).get("name") or ""
        check(name.startswith("snap-"), f"备份接口返回了快照名：{name}")

        r = client.get(f"/api/system/storage/backups/{name}/export")
        check(r.status_code == 200, f"GET 导出接口返回 {r.status_code}")
        disp = r.headers.get("content-disposition") or ""
        check("attachment" in disp and f"kb-backup-{name}.tar.gz" in disp,
              f"Content-Disposition 正确：{disp}")
        body = r.content
        check(body[:2] == b"\x1f\x8b", "下载到的确实是 gzip 数据")
        with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as tf:
            http_members = tf.getnames()
        check("kb.db" in http_members,
              f"下载到的归档里有 kb.db（共 {len(http_members)} 个成员）")

        r = client.post("/api/system/storage/import",
                        files={"file": ("kb-backup.tar.gz", body, "application/gzip")})
        check(r.status_code == 200,
              f"POST 导入接口返回 {r.status_code}：{r.text[:160]}")
        imported = (r.json() or {}).get("entry") or {}
        check("-imported" in str(imported.get("name") or ""),
              f"导入接口返回了新快照：{imported.get('name')}")

        r = client.get("/api/system/storage/backups")
        names = [i["name"] for i in (r.json() or {}).get("items", [])]
        check(imported.get("name") in names, "导入的快照出现在备份列表接口里")

        # 非法的名字必须被挡下来（400；有些路径穿越会先被路由层挡成 404，
        # 两种都算「没把文件发出去」）
        r = client.get("/api/system/storage/backups/..%2F%2Fetc%2Fpasswd/export")
        check(r.status_code in (400, 404),
              f"穿越式名字被挡下（{r.status_code}）")
        check(b"root:" not in r.content, "响应里没有 /etc/passwd 的内容")
        r = client.get("/api/system/storage/backups/不存在的快照/export")
        check(r.status_code == 400,
              f"不存在的快照返回 400（实际 {r.status_code}）")
        check("没有这个备份" in (r.json() or {}).get("detail", ""),
              f"错误提示是人话：{(r.json() or {}).get('detail')}")

        # 恶意包：接口层也要挡下来
        hostile = _make_tar(os.path.join(TMP, "http-hostile.tar.gz"),
                            [("../evil.txt", b"pwned")])
        with open(hostile, "rb") as fh:
            r = client.post("/api/system/storage/import",
                            files={"file": ("evil.tar.gz", fh, "application/gzip")})
        check(r.status_code == 400, f"恶意包返回 400（实际 {r.status_code}）")
        check("越界路径" in (r.json() or {}).get("detail", ""),
              f"错误提示是人话：{(r.json() or {}).get('detail')}")

    await engine.dispose()


async def main() -> int:
    try:
        await run()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{'=' * 56}")
    if FAILURES:
        print(f"✗ {len(FAILURES)}/{CHECKS} 项未通过：")
        for f in FAILURES:
            print(f"    - {f}")
        return 1
    print(f"✓ 全部 {CHECKS} 项通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
