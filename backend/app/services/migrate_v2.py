"""v0.1 → v0.2 存量迁移

要解决三件事：

1. **把磁盘上的旧附件搬进 document**
   v0.1 的文件落在 data/uploads/{record_id}/{uuid}.扩展名，
   数据库里只有路径。这里读出来写成 document 记录
   （v0.3 起原文外置到文件目录，故走 doc_svc.store_bytes 统一落盘）。

2. **保持 id 一一对应**
   前端把整个附件对象（含 `/api/attachments/3/preview` 这类绝对路径）
   存进了记录 JSON。给 Document 分配新 id 会让老数据的附件全部死链，
   所以这里显式沿用 attachment.id 作为 document.id。

3. **清理"伪造笔记"**
   v0.1 的数据中心上传要先造一条 `_upload_*` 的伪笔记当文件容器，
   污染了知识库列表。文档现在可以独立存在（link.record_id 可空），
   所以把这类伪笔记删掉，文件自动变成独立文档。

整个过程幂等：用 sys_meta 打标记，重复启动不会重复搬运。
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import (
    Attachment,
    Document,
    DocumentLink,
    EntityRecord,
    EntityType,
    RelationRecord,
)
from . import docindex
from . import document as doc_svc
from . import filepreview as fp

log = logging.getLogger("kb.migrate")

MIGRATED_FLAG = "migrated_v2"
ORPHAN_FLAG = "orphans_imported_v2"
EXTRACT_VER_FLAG = "extract_engine_version"
DEDUP_FLAG = "dedup_v2"

# 抽取器版本：新增 PDF 支持后 +1，启动时会据此回补此前抽不出正文的文件
EXTRACT_ENGINE_VERSION = 2



async def migrate_legacy_files(db: AsyncSession) -> dict:
    """迁移旧附件并清理伪笔记。返回统计信息。"""
    if await docindex.get_meta(db, MIGRATED_FLAG) == "done":
        return {"skipped": True}

    legacy = (await db.execute(select(Attachment).order_by(Attachment.id))).scalars().all()
    root = Path(settings.legacy_upload_dir)

    moved, missing, no_data = 0, 0, 0
    pending_embed: list[int] = []

    for att in legacy:
        existing = await db.get(Document, att.id)
        if existing is not None:
            continue

        path = root / str(att.record_id) / att.stored_name
        if not path.exists():
            missing += 1
            continue
        try:
            data = path.read_bytes()
        except Exception as e:
            log.warning("读取旧文件失败 %s：%s", path, e)
            missing += 1
            continue
        if not data:
            no_data += 1
            continue

        mime = fp.resolve_mime(att.filename, att.content_type or "")
        # 必须算 sha256：否则后续的孤儿扫描无法识别「这个文件已经进过库」，
        # 会把同一份文件重复导入成新记录
        digest = hashlib.sha256(data).hexdigest()
        _ext = Path(att.filename).suffix.lower()
        _storage, _rel = doc_svc.store_bytes(data, sha=digest, ext=_ext)
        doc = Document(
            id=att.id,                      # 关键：沿用旧 id，保证历史链接不失效
            title=att.filename,
            filename=att.filename,
            ext=_ext,
            mime=mime,
            size=len(data),
            sha256=digest,
            storage=_storage,
            path=_rel,
            data=data if _storage == "db" else None,
            kind=fp.doc_kind(att.filename, mime),
            tags=[],
            source="migrated",
            extract_status="pending",
            embed_status="pending",
            created_at=att.created_at,
        )
        db.add(doc)

        # 抽取正文
        try:
            body = fp.plain_text(data, att.filename)
            if body:
                doc.extracted_text = body[:400_000]
                doc.extract_status = "ok"
            else:
                doc.extract_status = "skipped"
        except Exception as e:
            doc.extract_status = "failed"
            doc.extract_error = f"{type(e).__name__}: {e}"[:500]

        await db.flush()

        db.add(DocumentLink(document_id=doc.id, record_id=att.record_id,
                            field_key=att.field_key))
        await db.flush()

        await docindex.index_document(
            db, doc.id, doc.title, doc.filename, doc.tags, "", doc.extracted_text or ""
        )
        moved += 1
        if (doc.extracted_text or "").strip():
            pending_embed.append(doc.id)

    # 清理伪笔记（tags 里带 _auto 的容器笔记）
    removed_notes = await _cleanup_fake_notes(db)

    await docindex.set_meta(db, MIGRATED_FLAG, "done")
    await db.commit()

    log.info("存量迁移完成：搬入 %s 个文件，缺失 %s，空文件 %s，清理伪笔记 %s",
             moved, missing, no_data, removed_notes)

    # 向量化放后台，不阻塞启动（首次启动时可能要走网络）
    if pending_embed:
        asyncio.create_task(_embed_later(pending_embed))

    return {
        "skipped": False, "moved": moved, "missing": missing,
        "empty": no_data, "removed_notes": removed_notes,
        "pending_embed": len(pending_embed),
    }


async def _cleanup_fake_notes(db: AsyncSession) -> int:
    """删除 v0.1 数据中心为上传文件而伪造的笔记

    识别方式：笔记的 tags 里含 `_auto`（Upload 时写入的标记）。
    删除后 document_link 会因外键级联一并消失，而 document 本身
    保留下来 —— 正是我们想要的「文件独立于记录存在」。
    """
    from ..models import EntityType

    note_type = (await db.execute(
        select(EntityType).where(EntityType.key == "note")
    )).scalar_one_or_none()
    if not note_type:
        return 0

    rows = (await db.execute(
        text(
            "select id from entity_record "
            "where entity_type_id = :nt and data like '%\"_auto\"%'"
        ),
        {"nt": note_type.id},
    )).scalars().all()

    if not rows:
        return 0

    for rid in rows:
        # 先断开关系记录（不依赖级联，避免 SQLite 外键未开时残留）
        rels = (await db.execute(
            select(RelationRecord).where(
                (RelationRecord.source_record_id == rid)
                | (RelationRecord.target_record_id == rid)
            )
        )).scalars().all()
        for r in rels:
            await db.delete(r)
        rec = await db.get(EntityRecord, rid)
        if rec:
            await db.delete(rec)
    await db.flush()
    return len(rows)


async def _embed_later(doc_ids: list[int]) -> None:
    """后台补向量（失败只记日志，不影响服务可用）"""
    from ..database import SessionLocal

    await asyncio.sleep(3)   # 等服务完全起来，避免与启动期抢资源
    for did in doc_ids:
        try:
            async with SessionLocal() as db:
                doc = await db.get(Document, did)
                if doc and doc.embed_status in ("pending", "failed"):
                    await doc_svc.embed_document(db, doc)
        except Exception as e:
            log.warning("后台向量化失败 doc=%s：%s", did, e)


# ============ 启动期修补 ============

async def run_startup_repairs(db: AsyncSession) -> dict:
    """幂等的启动期修补：去重回填 + 导入孤儿文件 + 回补正文抽取"""
    deduped = await repair_hashes_and_dedup(db)
    imported = await import_orphan_files(db)
    refilled = await refill_extracted_text(db)
    return {"deduped": deduped, "orphans_imported": imported, "text_refilled": refilled}


async def repair_hashes_and_dedup(db: AsyncSession) -> int:
    """回填 sha256，并清理因缺少指纹而重复导入的迁移记录

    背景：早期版本的迁移没写 sha256，导致孤儿扫描把同一份文件又当成
    『新文件』导入了一次。这里按内容指纹把重复项软删除（保留 id 最小的一条），
    并把缺失的指纹补齐，避免问题复现。

    作用范围严格限定在 source='migrated' 的记录上 —— 用户自己上传的
    文件从创建时就带指纹，绝不能被这次修补误删。
    """
    if await docindex.get_meta(db, DEDUP_FLAG) == "done":
        return 0

    rows = (await db.execute(
        select(Document).where(Document.source == "migrated").order_by(Document.id)
    )).scalars().all()

    seen: dict[str, int] = {}
    for doc in rows:
        digest = doc.sha256 or ""
        if not digest:
            # 指纹可能来自 BLOB，也可能来自外置文件，统一走读取入口取
            try:
                digest = hashlib.sha256(doc_svc.load_bytes(doc)).hexdigest()
                doc.sha256 = digest
            except Exception:
                digest = ""
        if not digest:
            continue
        if digest in seen:
            # 与更早的记录内容完全相同 → 是重复导入，软删除
            doc.deleted_at = datetime.utcnow()
        else:
            seen[digest] = doc.id

    await docindex.set_meta(db, DEDUP_FLAG, "done")
    await db.commit()

    # 重新统计（软删除后剩下的才是唯一集合）
    dupes = (await db.execute(
        select(func.count(Document.id)).where(Document.deleted_at.is_not(None))
    )).scalar() or 0
    if dupes:
        log.info("清理迁移重复记录：当前回收站共 %s 条", dupes)
    return dupes


async def import_orphan_files(db: AsyncSession) -> int:
    """把磁盘上「有文件、没有数据库记录」的孤儿文件也收进数据库

    v0.1 删附件时只删了数据库行、没删磁盘文件，于是 uploads 目录里
    留下了若干没有任何记录指向的文件。既然目标是「数据都在数据库里」，
    这些文件也应该被收编 —— 只是原始文件名已经不可考（磁盘上是 uuid），
    只能给出一个可辨识的临时标题，用户可以自行改名。
    """
    if await docindex.get_meta(db, ORPHAN_FLAG) == "done":
        return 0

    root = Path(settings.legacy_upload_dir)
    if not root.exists():
        await docindex.set_meta(db, ORPHAN_FLAG, "done")
        await db.commit()
        return 0

    known = set((await db.execute(select(Document.sha256))).scalars().all())
    imported = 0

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except Exception:
            continue
        if not data:
            continue

        digest = hashlib.sha256(data).hexdigest()
        if digest in known:
            continue

        ext = path.suffix.lower()
        mime = fp.resolve_mime(f"x{ext}", "")
        title = f"恢复文件_{path.stem[:8]}{ext}"
        # 走统一落盘入口：file_store=fs 时原文进文件目录，
        # 否则这次「收编历史文件」会把一堆 BLOB 又塞回库里，
        # 把刚刚做完的外迁工作原地抵消
        storage, rel = doc_svc.store_bytes(data, sha=digest, ext=ext)
        doc = Document(
            title=title,
            filename=title,
            ext=ext,
            mime=mime,
            size=len(data),
            sha256=digest,
            storage=storage,
            path=rel,
            data=data if storage == "db" else None,
            kind=fp.doc_kind(title, mime),
            tags=["_recovered"],
            source="migrated",
            extract_status="pending",
            embed_status="pending",
        )
        db.add(doc)
        await db.flush()
        try:
            body = fp.plain_text(data, title)
            if body:
                doc.extracted_text = body[:400_000]
                doc.extract_status = "ok"
            else:
                doc.extract_status = "skipped"
        except Exception:
            doc.extract_status = "failed"
        await docindex.index_document(
            db, doc.id, doc.title, doc.filename, doc.tags, "", doc.extracted_text or ""
        )
        known.add(digest)
        imported += 1

    await docindex.set_meta(db, ORPHAN_FLAG, "done")
    await db.commit()
    if imported:
        log.info("收编 %s 个孤儿文件（原文件名已不可考，标题为临时值）", imported)
    return imported


async def refill_extracted_text(db: AsyncSession) -> int:
    """用新版本抽取器回补正文

    extraction 能力是会演进的（例如本次新增了 PDF 文本抽取）。用版本号
    记录抽取器版本，升级后自动把此前「抽不出正文」的文件重跑一遍，
    否则那些文件会永远停留在 skipped 状态、AI 检索不到。
    """
    cur = await docindex.get_meta(db, EXTRACT_VER_FLAG)
    if cur and int(cur) >= EXTRACT_ENGINE_VERSION:
        return 0

    rows = (await db.execute(
        select(Document).where(Document.extract_status.in_(("skipped", "failed", "pending")))
    )).scalars().all()

    refilled = 0
    for doc in rows:
        try:
            # 用统一读取入口：原文可能在外置文件里，也可能还在 BLOB 列
            body = fp.plain_text(doc_svc.load_bytes(doc), doc.filename)
        except FileNotFoundError:
            continue
        except Exception:
            continue
        if not body:
            continue
        doc.extracted_text = body[:400_000]
        doc.extract_status = "ok"
        doc.extract_error = ""
        await docindex.index_document(
            db, doc.id, doc.title, doc.filename, doc.tags, doc.summary, body
        )
        refilled += 1
        if doc.embed_status in ("failed", "pending", "skipped"):
            asyncio.create_task(_embed_later([doc.id]))

    await docindex.set_meta(db, EXTRACT_VER_FLAG, str(EXTRACT_ENGINE_VERSION))
    await db.commit()
    if refilled:
        log.info("正文抽取器升级，回补 %s 个文件的内容", refilled)
    return refilled

