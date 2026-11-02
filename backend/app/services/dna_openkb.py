"""吸收外部开源项目（openkb 类）：让「养料库」不只吃本地源码

用户原话：「结合 openkb 等开源项目提高学习及总结经验的能力」。
所以这一层做的是：**把别人已经踩过的坑，变成我们库里的基因**。

参考的对象是 LangChain / LlamaIndex / mem0 / Zep / GraphRAG 这类
「开源知识库 / 知识图谱构建」项目，以及任何值得学的源码库。
但**只借鉴方法论，不照搬实现** —— 吸收进来的永远是
「它是怎么解决某个问题的」，而不是「它的代码」。

三条硬规矩：

1. **只吃知识，不吃代码**。开源项目的源码同样走蒸馏管线：
   原文不留，只留方法与经验基因 + 销毁证明。
   这既是吸收本地源码时就定下的规矩，对外部项目更该守住 ——
   别人的代码有别人的许可证与著作权。

2. **离线必须可用**。机器没网时，用用户预先 clone 好的本地镜像目录导入，
   走的是**同一条**蒸馏管线，产出一样的基因。
   离线不是「降级功能」，是这套系统的存在理由之一。

3. **许可证要显性**。每个外部来源都在 dna_openkb_source 里记下许可证，
   并在界面上给出**合规提示**：
   - 宽松许可（MIT / Apache-2.0 / BSD）：可参考可摘录，保留声明
   - 传染性许可（GPL / AGPL / SSPL）：并入闭源产品有开源义务，需法务评估
   - 没识别到：按「保留所有权利」处理，只读不抄

来源标注：外部项目来的基因 source_kind='openkb'，
meta 里带 repo / url / license / commit / fetched_at，
这样任何一条知识都能回答「这是谁教的、能不能直接用」。
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import DnaGene, DnaOpenkbSource
from . import dna_distill, dna_ingest

log = logging.getLogger("kb.dna_openkb")

# 外部来源统一用这个 source_kind —— 与本地源码（code）区分开
SOURCE_KIND = "openkb"

# 一次吸收最多读多少文件 / 多少字节。
# 与本地源码树同一套上限：外部仓库往往比想象的��，
# 整棵树读进来既慢又会淹掉真正有价值的部分。
MAX_FILES = dna_ingest.MAX_FILES
MAX_TOTAL_BYTES = dna_ingest.MAX_TOTAL_BYTES

# 优先吸收的文档文件名（小写匹配）
README_NAMES = ("readme.md", "readme.rst", "readme.txt", "readme")
DOC_DIRS = ("docs", "doc", "documentation", "guide", "guides", "examples",
            "example", "samples", "tutorials", "cookbook")
LICENSE_NAMES = ("license", "license.md", "license.txt", "copying",
                 "licence", "licence.md", "licence.txt")
MANIFEST_NAMES = ("requirements.txt", "pyproject.toml", "package.json",
                  "go.mod", "cargo.toml", "pom.xml", "build.gradle",
                  "composer.json", "setup.py", "setup.cfg")

# 传染性许可证关键词
COPYLEFT_MARKERS = ("gpl", "agpl", "sspl", "osl", "eclipse public license",
                    "eupl", "cc-by-sa", "mozilla public license")

# 宽松许可证关键词
PERMISSIVE_MARKERS = ("mit", "apache", "bsd", "isc", "unlicense", "zlib",
                      "python software foundation", "psf")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ============ 仓库引用解析 ============

_REPO_PATTERNS = (
    re.compile(r"^(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?$"),
    re.compile(r"^https?://(?:www\.)?github\.com/(?P<owner>[\w.-]+)/"
               r"(?P<repo>[\w.-]+?)(?:\.git)?/?$"),
    re.compile(r"^git@github\.com:(?P<owner>[\w.-]+)/"
               r"(?P<repo>[\w.-]+?)(?:\.git)?$"),
    re.compile(r"^https?://gitlab\.com/(?P<owner>[\w.-]+)/"
               r"(?P<repo>[\w.-]+?)(?:\.git)?/?$"),
)


def parse_repo_ref(ref: str) -> tuple[str, str]:
    """把各种写法解析成 (owner, repo)

    支持：owner/repo、GitHub/GitLab 网址、git@ SSH 形式。
    解析不出来就抛错 —— 「不知道这是哪个仓库」比瞎猜好。
    """
    raw = (ref or "").strip()
    if not raw:
        raise ValueError("仓库地址为空")
    for rx in _REPO_PATTERNS:
        m = rx.match(raw)
        if m:
            owner = m.group("owner").strip()
            repo = m.group("repo").strip()
            if owner and repo:
                return owner, repo
    raise ValueError(f"认不出仓库地址：{raw}（支持 owner/repo 或 GitHub/GitLab 网址）")


def repo_full_name(ref: str) -> str:
    owner, repo = parse_repo_ref(ref)
    return f"{owner}/{repo}"


def repo_url(full_name: str) -> str:
    return f"https://github.com/{full_name}"


# ============ 许可证与合规提示 ============

def normalize_license(text: str) -> str:
    """从许可证文件头部认出许可证标识

    只做最常见的几种 —— 认不出就返回空字符串，
    由界面按「未识别（按保留所有权利处理）」提示。
    """
    head = (text or "")[:2000].lower()
    if "apache license" in head and "version 2.0" in head:
        return "Apache-2.0"
    if "mit license" in head or "permission is hereby granted, free of charge" in head:
        return "MIT"
    if "gnu affero general public license" in head:
        return "AGPL-3.0"
    if "gnu general public license" in head:
        return "GPL-3.0"
    if "server side public license" in head:
        return "SSPL-1.0"
    if "mozilla public license" in head:
        return "MPL-2.0"
    if "bsd" in head and "redistribution" in head:
        return "BSD"
    if "isc license" in head:
        return "ISC"
    if "unlicense" in head:
        return "Unlicense"
    if "eclipse public license" in head:
        return "EPL-2.0"
    return ""


def is_copyleft(license_id: str) -> bool:
    low = (license_id or "").lower()
    return any(k in low for k in COPYLEFT_MARKERS)


def license_notice(license_id: str, full_name: str = "") -> str:
    """许可证合规提示（界面直接显示给用户看）

    为什么要把这句话写死在这里，而不是让用户自己判断：
    「参考一个开源项目」在多数情况下没问题，
    但「把 GPL 代码抄进闭源产品」是实实在在的法律风险。
    系统应该主动提醒，而不是等出事。
    """
    name = full_name or "该仓库"
    lid = (license_id or "").strip()
    if not lid:
        return (f"未识别到 {name} 的许可证：默认按「保留所有权利」处理。"
                f"本系统只吸收方法与经验，不保留源码原文；"
                f"如需直接引用代码片段，请自行取得授权。")
    if is_copyleft(lid):
        return (f"{name} 使用传染性许可证 {lid}：直接并入闭源产品可能触发开源义务。"
                f"本系统只吸收方法与经验（不保留原文），"
                f"若要落地其代码，请先做法务评估或改用宽松许可的同类方案。")
    if any(k in lid.lower() for k in PERMISSIVE_MARKERS):
        return (f"{name} 使用宽松许可证 {lid}：可参考、可摘录，"
                f"保留原版权声明与许可证原文即可。")
    return (f"{name} 的许可证为 {lid}：使用前请确认条款是否允许你的分发方式。")


# ============ 取仓库（联网 / 本地镜像） ============

async def fetch_repo_metadata(full_name: str, timeout: float = 10.0) -> dict:
    """取仓库元信息（许可证、star、默认分支）

    联网失败不致命 —— 离线镜像导入时这些字段留空，
    许可证改从本地 LICENSE 文件里认。
    """
    try:
        import httpx
    except Exception:
        return {}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{full_name}",
                headers={"Accept": "application/vnd.github+json"})
            if resp.status_code != 200:
                return {}
            data = resp.json()
        lic = ((data.get("license") or {}).get("spdx_id") or "").strip()
        if lic in ("NOASSERTION", ""):
            lic = ""
        return {
            "license": lic,
            "star_count": int(data.get("stargazers_count") or 0),
            "default_branch": str(data.get("default_branch") or "main"),
            "description": str(data.get("description") or "")[:500],
            "url": data.get("html_url") or repo_url(full_name),
            "homepage": str(data.get("homepage") or "")[:256],
        }
    except Exception as e:
        log.info("取仓库元信息失败 %s（离线模式属正常）：%s", full_name, e)
        return {}


async def download_repo_tarball(full_name: str, branch: str = "",
                                timeout: float = 120.0) -> Path:
    """下载仓库压缩包并解开，返回源码目录

    为什么用 codeload 的 tar.gz 而不是 git clone：
      - 不依赖机器上有没有 git
      - 一次请求拿整个仓库，比 clone 快得多
      - 离线场景本来就走本地镜像，这条路失败也不影响
    """
    import httpx
    branch = branch or "main"
    url = f"https://codeload.github.com/{full_name}/tar.gz/refs/heads/{branch}"
    tmp = Path(tempfile.mkdtemp(prefix="openkb-"))
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                # 分支猜错了再试一次 main/master
                for alt in ("main", "master"):
                    if alt == branch:
                        continue
                    url2 = (f"https://codeload.github.com/{full_name}"
                            f"/tar.gz/refs/heads/{alt}")
                    resp = await client.get(url2)
                    if resp.status_code == 200:
                        break
                if resp.status_code != 200:
                    raise RuntimeError(
                        f"下载仓库失败（HTTP {resp.status_code}）：{full_name}")
            tar_path = tmp / "repo.tar.gz"
            tar_path.write_bytes(resp.content)
        with tarfile.open(tar_path, "r:gz") as tf:
            # 安全解包：拒绝绝对路径与 .. 越界条目
            for member in tf.getmembers():
                name = member.name
                if name.startswith("/") or ".." in Path(name).parts:
                    continue
                if member.issym() or member.islnk():
                    continue
                tf.extract(member, tmp, filter="data")
        tar_path.unlink(missing_ok=True)
        # tarball 解开后是 owner-repo-sha/ 一层目录
        for child in tmp.iterdir():
            if child.is_dir():
                return child
        return tmp
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def find_local_mirror(path: str) -> Path | None:
    """找一个本地镜像目录（用户预先 clone 好的仓库）

    允许指向仓库目录本身，也允许指向它的父目录
    （父目录里按名字找同名的子目录）。
    """
    raw = (path or "").strip()
    if not raw:
        return None
    p = Path(raw).expanduser()
    if not p.exists() or not p.is_dir():
        return None
    if (p / ".git").exists():
        return p
    for child in sorted(p.iterdir()):
        if child.is_dir() and (child / ".git").exists():
            name = child.name.lower()
            if name in raw.lower() or raw.lower().endswith(child.name.lower()):
                return child
    return p


# ============ 关键接口抽取 ============

_PY_FUNC_RE = re.compile(
    r"^(?P<indent>\s*)(?:async\s+)?def\s+(?P<name>[A-Za-z_]\w*)\s*"
    r"\((?P<args>[^)]*)\)\s*(->\s*(?P<ret>[^:]+))?:", re.M)
_PY_CLASS_RE = re.compile(r"^\s*class\s+(?P<name>[A-Za-z_]\w*)", re.M)
_JS_FUNC_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?function\s+(?P<name>[A-Za-z_$][\w$]*)"
    r"\s*\((?P<args>[^)]*)\)", re.M)
_GO_FUNC_RE = re.compile(
    r"^func\s+(?P<name>[A-Za-z_]\w*)\s*\((?P<args>[^)]*)\)", re.M)


def extract_public_interfaces(content: str, language: str) -> list[dict]:
    """从一个源文件里抽出对外的接口（函数/类的签名）

    只抽**公开**的（名字不以 _ 开头）：私有函数不是接口，
    把它们当接口交出去等于把实现细节当成契约。
    """
    text = content or ""
    out: list[dict] = []
    if language == "python":
        for m in _PY_CLASS_RE.finditer(text):
            name = m.group("name")
            if name.startswith("_"):
                continue
            out.append({"name": name, "args": "", "ret": "",
                        "kind": "class"})
        for m in _PY_FUNC_RE.finditer(text):
            name = m.group("name")
            if name.startswith("_"):
                continue
            if len(m.group("indent")) > 4:
                continue
            args = " ".join((m.group("args") or "").split())
            ret = (m.group("ret") or "").strip()
            out.append({"name": name, "args": args, "ret": ret,
                        "kind": "func"})
    elif language in ("javascript", "typescript"):
        for m in _JS_FUNC_RE.finditer(text):
            name = m.group("name")
            if name.startswith("_"):
                continue
            args = " ".join((m.group("args") or "").split())
            out.append({"name": name, "args": args, "ret": "", "kind": "func"})
    elif language == "go":
        for m in _GO_FUNC_RE.finditer(text):
            out.append({"name": m.group("name"),
                        "args": " ".join((m.group("args") or "").split()),
                        "ret": "", "kind": "func"})
    # 去重：同名同参只留一条
    seen: set[tuple] = set()
    uniq: list[dict] = []
    for item in out:
        key = (item["kind"], item["name"], item["args"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(item)
    return uniq[:40]


# ============ 吸收主流程 ============

async def absorb_local_repo(db: AsyncSession, path: str, *,
                            repo_name: str = "",
                            license_id: str = "",
                            meta_extra: dict | None = None,
                            principal: str = "",
                            max_files: int = MAX_FILES) -> dict:
    """吸收一个**本地目录**里的开源项目（离线镜像也走这里）

    复用 dna_ingest 的扫描与蒸馏管线：
      - 跳过 .git / node_modules / 二进制 / 超大文件
      - 代码走蒸馏（方法、经验、TODO、高危调用）
      - README 与 docs/ 走文档吸收（事实、方法、接口）
      - 另外抽一遍公开接口，落成接口基因
      - 目录结构、依赖清单、许可证落成「项目画像」基因

    原文同样不留：外部项目的版权更敏感，销毁证明照写。
    """
    root = Path(path).expanduser()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"目录不存在：{path}")
    name = repo_name or root.name
    source = DnaOpenkbSource(
        repo=name, url=repo_url(name) if "/" in name else "",
        license=license_id or "", copyleft=is_copyleft(license_id),
        local_path=str(root), status="running",
        notice=license_notice(license_id, name),
        principal=principal or "",
        meta={"source": "local", **(meta_extra or {})},
        created_at=_now(), updated_at=_now())
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return await _absorb_tree(db, source, root, max_files=max_files)


async def absorb_github_repo(db: AsyncSession, ref: str, *,
                             branch: str = "",
                             principal: str = "",
                             max_files: int = MAX_FILES) -> dict:
    """吸收一个 GitHub 开源项目（需要联网）

    没网时这条会失败 —— 那不是 bug，用户可以用本地镜像导入。
    """
    owner, repo = parse_repo_ref(ref)
    full = f"{owner}/{repo}"
    meta = await fetch_repo_metadata(full)
    license_id = meta.get("license") or ""
    source = DnaOpenkbSource(
        repo=full, url=meta.get("url") or repo_url(full),
        license=license_id, copyleft=is_copyleft(license_id),
        star_count=int(meta.get("star_count") or 0),
        default_branch=meta.get("default_branch") or branch or "main",
        status="running",
        notice=license_notice(license_id, full),
        principal=principal or "",
        meta={"source": "github", "description": meta.get("description") or "",
              "homepage": meta.get("homepage") or ""},
        created_at=_now(), updated_at=_now())
    db.add(source)
    await db.commit()
    await db.refresh(source)
    try:
        root = await download_repo_tarball(
            full, source.default_branch or "main")
    except Exception as e:
        source.status = "failed"
        source.error = str(e)[:500]
        source.updated_at = _now()
        await db.commit()
        raise
    try:
        return await _absorb_tree(db, source, root, max_files=max_files)
    finally:
        shutil.rmtree(root.parent if root.parent.name.startswith("openkb-")
                      else root, ignore_errors=True)


async def _absorb_tree(db: AsyncSession, source: DnaOpenkbSource,
                        root: Path, *, max_files: int = MAX_FILES) -> dict:
    """真正走一遍吸收：代码蒸馏 + 文档吸收 + 接口抽取 + 项目画像"""
    from .dna_library import absorb_code, absorb_text, upsert_gene

    created = updated = 0
    read_files = 0
    total_bytes = 0
    interface_genes = 0
    license_id = source.license or ""
    license_text = ""
    readme_text = ""
    manifests: list[str] = []
    top_dirs: dict[str, int] = {}
    langs: dict[str, int] = {}

    files: list[Path] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        files.append(p)
        if len(files) > max_files * 2:
            break

    # 许可证先扫一遍：
    # 不先扫的话，排在 LICENSE 前面被吸收的那几个文件，
    # 它们的基因 meta 里没有许可证 —— 「来源权威度」就少了一个扣分项
    # （别人家的代码没在本地验证过，权威度天然低一档）。
    for p in files:
        if p.name.lower() not in LICENSE_NAMES:
            continue
        try:
            license_text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            break
        license_id = normalize_license(license_text) or license_id
        source.license = license_id
        source.copyleft = is_copyleft(license_id)
        source.notice = license_notice(license_id, source.repo)
        break

    for p in files:
        if read_files >= max_files or total_bytes > MAX_TOTAL_BYTES:
            break
        rel = str(p.relative_to(root))
        reason = dna_ingest._should_skip(rel, p)
        if reason:
            continue
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        read_files += 1
        total_bytes += len(raw.encode("utf-8", "replace"))
        name = p.name.lower()
        seg = rel.split("/")[0]
        top_dirs[seg] = top_dirs.get(seg, 0) + 1
        # 许可证文件：只认名字，不读进来当知识
        if name in LICENSE_NAMES and not license_text:
            license_text = raw
            if not license_id:
                license_id = normalize_license(raw)
                source.license = license_id
                source.copyleft = is_copyleft(license_id)
                source.notice = license_notice(license_id, source.repo)
            continue
        if name in MANIFEST_NAMES:
            manifests.append(rel)
            continue
        if name in README_NAMES and len(raw) > 100:
            readme_text = raw
            continue
        # docs/ 与 examples/ 里的文档
        if any(rel.lower().startswith(d + "/") for d in DOC_DIRS) and \
                name.endswith((".md", ".rst", ".txt")) and len(raw) > 200:
            try:
                r = await absorb_text(
                    db, raw[:20000], title=f"{source.repo} · {rel}",
                    source_kind=SOURCE_KIND,
                    source_ref=f"openkb:{source.repo}:{rel}"[:64],
                    source_title=f"{source.repo}/{rel}",
                    extra_meta={"repo": source.repo, "license": license_id,
                                "url": source.url, "origin": "openkb"})
                created += r["created"]
                updated += r["updated"]
            except Exception as e:
                log.warning("吸收开源项目文档失败 %s：%s", rel, e)
            continue
        # 源码：走蒸馏（原文不留）
        try:
            res = await absorb_code(
                db, raw, rel, destroy=True, source_kind=SOURCE_KIND,
                extra_meta={"repo": source.repo, "license": license_id,
                            "url": source.url, "origin": "openkb"})
            created += res.get("created") or 0
            updated += res.get("updated") or 0
            lang = res.get("language") or "unknown"
            langs[lang] = langs.get(lang, 0) + 1
            # 公开接口单独再抽一遍：蒸馏器关注的是坑与做法，
            # 而「这个库对外提供什么」是另一类知识
            if (res.get("created") or 0) or (res.get("updated") or 0):
                for item in extract_public_interfaces(raw, lang):
                    if interface_genes >= 40:
                        break
                    title = f"{source.repo} 提供 {item['kind']} {item['name']}"
                    sig = f"{item['name']}({item['args']})"
                    if item.get("ret"):
                        sig += f" -> {item['ret']}"
                    body = (f"{source.repo} 对外提供 {item['kind']} {sig}。"
                            f"参数：{item['args'] or '（无）'}。"
                            f"这是它的公开契约，调用方按这个签名来接。")
                    try:
                        _, is_new = await upsert_gene(
                            db, kind="interface", title=title, content=body,
                            tags=["开源接口", source.repo.split("/")[-1]],
                            source_kind=SOURCE_KIND,
                            source_ref=f"openkb:{source.repo}:{rel}"[:64],
                            source_title=f"{source.repo}/{rel}",
                            confidence=0.75,
                            meta={"repo": source.repo, "license": license_id,
                                  "interface": item, "origin": "openkb"})
                        interface_genes += 1
                        created += 1 if is_new else 0
                    except Exception:
                        continue
        except Exception as e:
            log.warning("吸收开源项目源码失败 %s：%s", rel, e)

    # README：项目级说明
    if readme_text:
        try:
            r = await absorb_text(
                db, readme_text[:20000], title=f"{source.repo} 项目说明",
                source_kind=SOURCE_KIND,
                source_ref=f"openkb:{source.repo}:readme"[:64],
                source_title=f"{source.repo}/README")
            created += r["created"]
            updated += r["updated"]
        except Exception as e:
            log.warning("吸收开源项目 README 失败：%s", e)

    # 项目画像：目录结构 + 依赖 + 许可证 + 入口
    profile = await _write_profile(
        db, source, root, top_dirs, langs, manifests, license_id,
        read_files, created, updated)
    if profile:
        created += 1

    source.genes = created
    source.files = read_files
    source.status = "done"
    source.updated_at = _now()
    await db.commit()
    return {
        "source": serialize_source(source),
        "created": created, "updated": updated,
        "files": read_files, "bytes": total_bytes,
        "interfaces": interface_genes,
        "license": license_id,
        "notice": source.notice,
    }


async def _write_profile(db: AsyncSession, source: DnaOpenkbSource,
                         root: Path, top_dirs: dict, langs: dict,
                         manifests: list[str], license_id: str,
                         files: int, created: int, updated: int) -> bool:
    """把「这个开源项目整体长什么样」落成一条基因

    单个文件看不出项目级的东西：入口在哪、依赖什么、许可证是什么、
    目录怎么分的。这些只有在整棵树上才看得见，
    而这些恰恰是最值得学的部分。
    """
    from .dna_library import upsert_gene
    tree = "\n".join(f"  {k}/（{v} 个文件）"
                      for k, v in sorted(top_dirs.items(), key=lambda kv: -kv[1])[:14])
    lang_line = "、".join(f"{k} {v} 个"
                          for k, v in sorted(langs.items(), key=lambda kv: -kv[1])[:8]) or "未识别"
    entries = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name.lower() in (
                "main.py", "app.py", "index.js", "server.py", "cli.py",
                "__main__.py", "run.py", "start.py", "setup.py"):
            entries.append(str(p.relative_to(root)))
        if len(entries) >= 8:
            break
    content = (
        f"开源项目 {source.repo} 被吸收（{files} 个文件，语言分布 {lang_line}）。\n"
        f"许可证：{license_id or '未识别（按保留所有权利处理）'}。\n"
        f"顶层目录：\n{tree}\n"
        f"入口候选：{'、'.join(entries[:8]) or '未识别'}\n"
        f"依赖清单：{'、'.join(manifests[:8]) or '无'}\n"
        f"本次吸收出 {created} 条新基因、{updated} 条更新。"
        f"（只留方法与经验，源码原文不保留。）"
    )
    try:
        _, is_new = await upsert_gene(
            db, kind="policy",
            title=f"开源项目画像：{source.repo}",
            content=content,
            tags=["开源项目", source.repo.split("/")[-1], "画像"],
            source_kind=SOURCE_KIND,
            source_ref=f"openkb:{source.repo}:profile"[:64],
            source_title=source.repo,
            confidence=0.8,
            meta={"repo": source.repo, "license": license_id,
                  "url": source.url, "copyleft": source.copyleft,
                  "origin": "openkb_profile"})
        return bool(is_new)
    except Exception as e:
        log.warning("写开源项目画像失败：%s", e)
        return False


# ============ 来源档案 ============

def serialize_source(s: DnaOpenkbSource) -> dict:
    return {
        "id": s.id, "repo": s.repo, "url": s.url,
        "license": s.license or "", "copyleft": bool(s.copyleft),
        "star_count": s.star_count or 0,
        "default_branch": s.default_branch or "",
        "local_path": s.local_path or "",
        "status": s.status, "genes": s.genes or 0,
        "files": s.files or 0, "error": s.error or "",
        "notice": s.notice or "",
        "meta": s.meta or {},
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


async def list_sources(db: AsyncSession, limit: int = 50) -> dict:
    rows = (await db.execute(
        select(DnaOpenkbSource).order_by(DnaOpenkbSource.id.desc())
        .limit(limit))).scalars().all()
    return {"items": [serialize_source(s) for s in rows],
            "total": len(rows)}


async def source_genes(db: AsyncSession, source_id: int, limit: int = 100) -> dict:
    """某个外部来源吸收出来的基因"""
    src = (await db.execute(
        select(DnaOpenkbSource).where(DnaOpenkbSource.id == source_id)
    )).scalar_one_or_none()
    if src is None:
        raise ValueError("来源不存在")
    rows = (await db.execute(
        select(DnaGene).where(
            DnaGene.source_kind == SOURCE_KIND,
            DnaGene.source_ref.like(f"openkb:{src.repo}%"))
        .order_by(DnaGene.id.desc()).limit(limit))).scalars().all()
    return {"source": serialize_source(src),
            "items": [{"id": g.id, "kind": g.kind, "title": g.title,
                       "summary": g.summary, "source_title": g.source_title,
                       "confidence": round(float(g.confidence or 0), 3),
                       "expressiveness": round(float(g.expressiveness or 0), 3)}
                      for g in rows]}
