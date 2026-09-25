"""文件在线预览服务

职责：
1. guess_mime()  —— 按扩展名推断 MIME，修正浏览器上传时给出的
   空值 / application/octet-stream（否则 PDF 无法内联渲染）
2. extract_document() —— 纯标准库（zipfile + xml.etree）抽取
   docx / xlsx / pptx / csv / 文本类 的内容，转成可渲染结构，
   避免依赖公网 Office Online（内网部署根本访问不到）
"""
from __future__ import annotations

import csv
import io
import json
import mimetypes
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

# ---------- MIME 推断 ----------

# mimetypes 在部分系统上不认识这些新格式，显式登记
EXTRA_MIME = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".yml": "text/yaml",
    ".yaml": "text/yaml",
    ".log": "text/plain",
    ".ini": "text/plain",
    ".conf": "text/plain",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".xml": "application/xml",
    ".js": "text/javascript",
    ".ts": "text/plain",
    ".py": "text/x-python",
    ".sh": "text/x-shellscript",
    ".sql": "text/plain",
    ".css": "text/css",
    ".html": "text/html",
    ".htm": "text/html",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".doc": "application/msword",
    ".xls": "application/vnd.ms-excel",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pdf": "application/pdf",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".mkv": "video/x-matroska",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".7z": "application/x-7z-compressed",
    ".rar": "application/vnd.rar",
}

# 浏览器经常给这些"说不清"的类型，需要按扩展名纠正
VAGUE_TYPES = {"", "application/octet-stream", "binary/octet-stream",
               "application/unknown", "text/plain"}


def guess_mime(filename: str, fallback: str = "") -> str:
    """按扩展名推断 MIME；扩展名无法识别时回退到上传时的 content_type"""
    ext = Path(filename or "").suffix.lower()
    if ext in EXTRA_MIME:
        return EXTRA_MIME[ext]
    guessed, _ = mimetypes.guess_type(filename or "")
    if guessed:
        return guessed
    fb = (fallback or "").strip()
    if fb and fb not in VAGUE_TYPES:
        return fb
    return "application/octet-stream"


def resolve_mime(filename: str, stored_type: str = "") -> str:
    """综合扩展名与存储类型，得出可信 MIME

    扩展名能给出明确类型时以扩展名为准（浏览器上传的 content_type 常不可靠）；
    否则退回存储类型。
    """
    ext = Path(filename or "").suffix.lower()
    if ext in EXTRA_MIME:
        return EXTRA_MIME[ext]
    stored = (stored_type or "").strip()
    if stored and stored not in VAGUE_TYPES:
        return stored
    return guess_mime(filename, stored)


# ---------- 预览能力判定 ----------

TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".log", ".csv", ".tsv", ".json", ".xml",
    ".yml", ".yaml", ".ini", ".conf", ".py", ".js", ".ts", ".sh", ".sql",
    ".css", ".html", ".htm", ".java", ".go", ".rs", ".c", ".cpp", ".rb", ".php",
}
OFFICE_EXTS = {".docx", ".xlsx", ".pptx"}
LEGACY_OFFICE_EXTS = {".doc", ".xls", ".ppt"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg",
              ".ico", ".avif", ".heic", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".webm", ".ogv", ".mov", ".m4v", ".mkv", ".avi"}
AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac", ".weba"}



def preview_mode(filename: str, mime: str = "") -> str:
    """返回前端可用的预览模式"""
    ext = Path(filename or "").suffix.lower()
    m = (mime or "").lower()
    if ext in (".csv", ".tsv"):
        return "csv"
    if m.startswith("image/"):
        return "image"
    if m.startswith("video/"):
        return "video"
    if m.startswith("audio/"):
        return "audio"
    if m == "application/pdf" or ext == ".pdf":
        return "pdf"
    if ext in OFFICE_EXTS:
        return "office"
    if ext in LEGACY_OFFICE_EXTS:
        return "legacy-office"
    if ext in TEXT_EXTS or m.startswith("text/") or "json" in m or "xml" in m:
        return "text"
    return "other"


# ---------- Office / 文本抽取 ----------

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

MAX_DOCX_BLOCKS = 4000
MAX_SHEET_ROWS = 800
MAX_SHEET_COLS = 40
MAX_SLIDES = 300
MAX_TEXT_CHARS = 400_000


def _sheet_sort_key(name: str) -> int:
    m = re.search(r"(\d+)", name)
    return int(m.group(1)) if m else 0


def _docx_to_blocks(zf: zipfile.ZipFile) -> list[dict]:
    xml = zf.read("word/document.xml")
    root = ET.fromstring(xml)
    body = root.find(f"{W}body")
    if body is None:
        return []
    blocks: list[dict] = []
    for el in body:
        if el.tag == f"{W}p":
            text = "".join(t.text or "" for t in el.iter(f"{W}t")).strip()
            if not text:
                continue
            style = ""
            ppr = el.find(f"{W}pPr")
            if ppr is not None:
                st = ppr.find(f"{W}pStyle")
                if st is not None:
                    style = (st.get(f"{W}val") or "").lower()
            level = 0
            if style:
                if "heading" in style or "标题" in style:
                    m = re.search(r"(\d+)", style)
                    level = int(m.group(1)) if m else 1
                    level = max(1, min(level, 4))
                elif style in ("1", "2", "3", "4"):
                    level = int(style)
            blocks.append({"type": "heading" if level else "p",
                           "level": level, "text": text})
        elif el.tag == f"{W}tbl":
            rows = []
            for tr in el.iter(f"{W}tr"):
                row = []
                for tc in tr.findall(f"{W}tc"):
                    cell = "".join(t.text or "" for t in tc.iter(f"{W}t")).strip()
                    row.append(cell)
                if any(row):
                    rows.append(row)
            if rows:
                blocks.append({"type": "table", "rows": rows})
        if len(blocks) >= MAX_DOCX_BLOCKS:
            break
    return blocks


def _xlsx_to_sheets(zf: zipfile.ZipFile) -> list[dict]:
    shared: list[str] = []
    if "xl/sharedStrings.xml" in zf.namelist():
        sroot = ET.fromstring(zf.read("xl/sharedStrings.xml"))
        for si in sroot.findall(f"{S}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{S}t")))

    names: list[str] = []
    if "xl/workbook.xml" in zf.namelist():
        try:
            wb = ET.fromstring(zf.read("xl/workbook.xml"))
            for sh in wb.iter(f"{S}sheet"):
                names.append(sh.get("name") or "")
        except ET.ParseError:
            pass

    sheets_xml = sorted(
        (n for n in zf.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n)),
        key=_sheet_sort_key,
    )
    out = []
    for i, name in enumerate(sheets_xml):
        try:
            root = ET.fromstring(zf.read(name))
        except ET.ParseError:
            continue
        rows: list[list[str]] = []
        for row_el in root.iter(f"{S}row"):
            cells: list[str] = []
            for c in row_el.findall(f"{S}c"):
                t = c.get("t")
                v = c.find(f"{S}v")
                is_el = c.find(f"{S}is")
                val = ""
                if t == "s" and v is not None and v.text is not None:
                    idx = int(v.text)
                    val = shared[idx] if 0 <= idx < len(shared) else ""
                elif t == "inlineStr" and is_el is not None:
                    val = "".join(x.text or "" for x in is_el.iter(f"{S}t"))
                elif v is not None:
                    val = v.text or ""
                cells.append(val)
                if len(cells) >= MAX_SHEET_COLS:
                    break
            if any(x.strip() for x in cells):
                rows.append(cells)
            if len(rows) >= MAX_SHEET_ROWS:
                break
        out.append({
            "name": names[i] if i < len(names) and names[i] else f"Sheet{i + 1}",
            "rows": rows,
            "truncated": len(rows) >= MAX_SHEET_ROWS,
        })
    return out


def _pptx_to_slides(zf: zipfile.ZipFile) -> list[dict]:
    slides = sorted(
        (n for n in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
        key=_sheet_sort_key,
    )
    out = []
    for i, name in enumerate(slides[:MAX_SLIDES]):
        try:
            root = ET.fromstring(zf.read(name))
        except ET.ParseError:
            continue
        lines = [(t.text or "").strip() for t in root.iter(f"{A}t")]
        lines = [x for x in lines if x]
        out.append({"index": i + 1, "lines": lines})
    return out


def _csv_to_table(text: str, delimiter: str = ",") -> list[list[str]]:
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = []
    for i, row in enumerate(reader):
        rows.append([c for c in row[:MAX_SHEET_COLS]])
        if i >= MAX_SHEET_ROWS:
            break
    return rows


def doc_kind(filename: str, mime: str = "") -> str:
    """归一化的文件大类，用于列表筛选"""
    m = (mime or "").lower()
    ext = Path(filename or "").suffix.lower()
    if m.startswith("image/") or ext in IMAGE_EXTS:
        return "image"
    if m.startswith("video/") or ext in VIDEO_EXTS:
        return "video"
    if m.startswith("audio/") or ext in AUDIO_EXTS:
        return "audio"
    if ext in TEXT_EXTS or ext in OFFICE_EXTS or ext == ".pdf" or m.startswith("text/"):
        return "doc"
    return "other"


def extract_document(path: Path, filename: str) -> dict | None:
    """从磁盘文件抽取（保留旧签名，内部转调 extract_bytes）"""
    try:
        return extract_bytes(path.read_bytes(), filename or path.name)
    except Exception:
        return None


def extract_bytes(data: bytes, filename: str) -> dict | None:
    """从字节流抽取文档内容，返回可渲染结构；不支持的格式返回 None

    v0.2 起文件存在数据库 BLOB 里，不再有磁盘路径，所以抽取逻辑
    必须在内存中完成 —— 这也是本函数存在的原因。
    """
    if not data:
        return None
    ext = Path(filename or "").suffix.lower()

    # PDF：纯文本抽取（pypdf 是纯 Python，不依赖系统库）
    if ext == ".pdf":
        return _pdf_extract(data)

    if ext in OFFICE_EXTS:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                if ext == ".docx":
                    blocks = _docx_to_blocks(zf)
                    return {"kind": "docx", "blocks": blocks,
                            "blockCount": len(blocks)}
                if ext == ".xlsx":
                    sheets = _xlsx_to_sheets(zf)
                    return {"kind": "xlsx", "sheets": sheets,
                            "sheetCount": len(sheets)}
                if ext == ".pptx":
                    slides = _pptx_to_slides(zf)
                    return {"kind": "pptx", "slides": slides,
                            "slideCount": len(slides)}
        except zipfile.BadZipFile:
            return None

    if ext in TEXT_EXTS:
        text = _decode(data[: MAX_TEXT_CHARS * 4])
        if text is None:
            return None
        text = text[:MAX_TEXT_CHARS]
        if ext == ".csv":
            return {"kind": "csv", "rows": _csv_to_table(text, ","),
                    "chars": len(text)}
        if ext == ".tsv":
            return {"kind": "csv", "rows": _csv_to_table(text, "\t"),
                    "chars": len(text)}
        if ext == ".json":
            try:
                pretty = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
                text = pretty[:MAX_TEXT_CHARS]
            except Exception:
                pass
        return {"kind": "text", "text": text, "chars": len(text),
                "language": _lang_of(ext)}

    # 未登记的纯文本兜底：能按 utf-8 解出且不含 NUL，就当文本
    try:
        raw = data[:120_000]
        if b"\x00" not in raw:
            text = raw.decode("utf-8")
            if text and sum(c.isprintable() or c in "\n\r\t" for c in text) / len(text) > 0.85:
                return {"kind": "text", "text": text[:MAX_TEXT_CHARS],
                        "chars": len(text), "language": ""}
    except Exception:
        pass
    return None


def _decode(raw: bytes) -> str | None:
    for enc in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def _pdf_extract(data: bytes) -> dict | None:
    """PDF 文本抽取

    PDF 的内容流不像 Office 那样有标准 XML，必须靠解析器。
    pypdf 是纯 Python 实现，装在镜像里即可离线工作，不依赖系统 poppler。
    扫描件（图片型 PDF）抽不出文字，返回页文本为空的结构，由上层判为
    「无正文可索引」而不是报错。
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        return None

    try:
        reader = PdfReader(io.BytesIO(data))
        if getattr(reader, "is_encrypted", False):
            try:
                reader.decrypt("")
            except Exception:
                return None

        pages = []
        total = 0
        for i in range(min(len(reader.pages), MAX_SLIDES)):
            try:
                text = (reader.pages[i].extract_text() or "").strip()
            except Exception:
                text = ""
            if len(text) > MAX_TEXT_CHARS - total:
                text = text[: max(0, MAX_TEXT_CHARS - total)]
            total += len(text)
            pages.append({"index": i + 1, "text": text})
            if total >= MAX_TEXT_CHARS:
                break

        meta = {}
        try:
            info = reader.metadata or {}
            for k, key in (("/Title", "title"), ("/Author", "author"),
                           ("/Subject", "subject")):
                if info.get(k):
                    meta[key] = str(info.get(k))
        except Exception:
            pass

        return {
            "kind": "pdf",
            "pages": pages,
            "pageCount": len(reader.pages),
            "chars": total,
            "meta": meta,
        }
    except Exception:
        return None



def plain_text(data: bytes, filename: str) -> str:
    """把文档压成一段纯文本，供 FTS 索引与向量化使用

    与 extract_bytes 的区别：这里只关心「拿到文字」，不关心渲染结构，
    所以表格被拍平成制表符分隔的行。
    """
    doc = extract_bytes(data, filename)
    if not doc:
        return ""
    kind = doc.get("kind")
    if kind == "text":
        return doc.get("text") or ""
    if kind == "pdf":
        out = []
        for p in doc.get("pages") or []:
            t = (p.get("text") or "").strip()
            if t:
                out.append(f"[第 {p.get('index')} 页]\n{t}")
        meta = doc.get("meta") or {}
        if meta.get("title"):
            out.insert(0, f"[标题] {meta['title']}")
        return "\n".join(out)
    if kind == "docx":
        out = []
        for b in doc.get("blocks") or []:
            if b.get("type") == "table":
                for row in b.get("rows") or []:
                    out.append(" | ".join(str(c) for c in row))
            else:
                out.append(b.get("text") or "")
        return "\n".join(x for x in out if x)
    if kind == "xlsx":
        out = []
        for sh in doc.get("sheets") or []:
            out.append(f"[{sh.get('name')}]")
            for row in sh.get("rows") or []:
                out.append(" | ".join(str(c) for c in row if c))
        return "\n".join(x for x in out if x)
    if kind == "pptx":
        out = []
        for s in doc.get("slides") or []:
            out.append(f"[第 {s.get('index')} 页] " + " ".join(s.get("lines") or []))
        return "\n".join(x for x in out if x.strip())
    if kind == "csv":
        return "\n".join(" | ".join(str(c) for c in row)
                         for row in (doc.get("rows") or []))
    return ""



def _lang_of(ext: str) -> str:
    return {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".json": "json", ".xml": "xml", ".html": "html", ".htm": "html",
        ".css": "css", ".sh": "bash", ".sql": "sql", ".yml": "yaml",
        ".yaml": "yaml", ".md": "markdown", ".markdown": "markdown",
        ".java": "java", ".go": "go", ".rs": "rust", ".rb": "ruby",
        ".php": "php", ".c": "c", ".cpp": "cpp",
    }.get(ext, "")
