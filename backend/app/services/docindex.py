"""文档索引层：FTS5 全文索引 + sqlite-vec 向量索引

三个不那么显然但很关键的取舍：

1. **中文必须逐字切分再入 FTS5**
   SQLite 的 unicode61 分词器把一整串汉字当作「一个词」
   （"采购合同" → 单个 token），而 trigram 分词器虽然支持子串匹配，
   却要求查询至少 3 个字符 —— 实测「深圳」这种两字查询直接返回空。
   所以这里把 CJK 逐字用空格隔开再入库（"采购合同" → "采 购 合 同"），
   查询同样处理并整体作为短语匹配。两字/四字/长句全部命中。

2. **向量表维度不能写死**
   MiniMax embo-01 的维度在不同资料里有 1024 / 1536 两种说法，
   硬编码会导致插入时维度不匹配。因此维度在首次调用 embedding 后
   探测得到，存进 sys_meta，再据此创建 vec0 表。

3. **索引失败不应影响业务**
   FTS5 / vec0 都是「增强」。文件能不能存、能不能看，不依赖它们，
   所以这里的异常一律吞掉并降级。
"""
from __future__ import annotations

import logging
import math
import re
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings

log = logging.getLogger("kb.index")


# ---------- 进程内缓存（TTL + 容量上限） ----------

class TTLCache:
    """带存活时间与容量上限的进程内缓存（LRU 淘汰）

    为什么集中写一份而不是各写各的：检索链路上有三处要缓存
    （sys_meta 的索引版本号、查询向量、块级 token 集），
    三处的差别只有「存什么」和「多久过期」，淘汰策略与并发语义完全一样 ——
    抄三份就等于埋三份不同步的 bug。

    淘汰用「插入序 + 写入时顺手清过期」而不是真 LRU：
    Python 3.7+ 的 dict 保证插入序，取最早插入的几个出来丢就够用了；
    真 LRU 要额外维护访问序，在这个量级上不划算。

    并发语义：只在事件循环里用（无锁）。多进程部署时每个进程各有一份 ——
    语义上没问题（缓存的只是「可重算」的东西），只是命中率低一些。
    """

    def __init__(self, max_size: int = 128, ttl: float = 30.0):
        self.max_size = max(1, int(max_size))
        self.ttl = float(ttl)
        self._data: dict[str, tuple[float, Any]] = {}
        self.hits = 0
        self.misses = 0

    @property
    def size(self) -> int:
        return len(self._data)

    def get(self, key: str):
        item = self._data.get(key)
        if item is None:
            self.misses += 1
            return None
        ts, value = item
        if (time.time() - ts) > self.ttl:
            self._data.pop(key, None)
            self.misses += 1
            return None
        self.hits += 1
        return value

    def put(self, key: str, value: Any) -> None:
        if len(self._data) >= self.max_size:
            # 满了就丢最早写入的那批（dict 保插入序）
            for k in list(self._data.keys())[: max(1, self.max_size // 4)]:
                self._data.pop(k, None)
        self._data[key] = (time.time(), value)

    def drop(self, key: str) -> None:
        self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()

# 覆盖基本汉字区 + 扩展 A 区
CJK_RE = re.compile(r"([\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff])")

FTS_TABLE = "document_fts"
VEC_TABLE = "document_vec"
META_EMBED_DIM = "embed_dim"
META_EMBED_MODEL = "embed_model"
META_VEC_METRIC = "vec_metric"

# 块级全文索引：rowid = document_chunk.id，两列（标题 / 正文）
CHUNK_FTS_TABLE = "chunk_fts"
# 分词方案版本号。分词一改，索引里存的就是另一套 token 了，
# 增量补写只会得到「一半旧词一半新词」的索引 —— 查出来看着有命中、
# 其实排序全乱，比空表更难排查。所以版本变了必须整表重建。
CHUNK_FTS_VERSION = "bigram2"
META_CHUNK_FTS_VERSION = "chunk_fts_version"

# 结构命中相对正文命中的权重。标题是作者自己声明的结构，
# 「变更日志」「付款条款」这种词出现在标题里，跟正文里偶然撞上两个字，
# 可靠程度不是一个量级 —— 命中标题的块排序要压过命中正文的块。
STRUCTURE_WEIGHT = 1.6

# 距离度量。vec0 不写这个参数时默认是 L2（欧氏距离），
# 而检索代码一直按「余弦距离」在解释 distance 值 —— 注释与实现对不上。
# 更要命的是：换 embedding 模型后如果新模型输出的向量没有归一化，
# L2 排序会被向量模长带偏，跟语义相关性脱钩。
# 写死 cosine，distance 就恒等于 1 - cos_sim，含义永远成立。
VEC_METRIC = "cosine"


# ---------- 中文分词与查询构造 ----------

def seg_cjk(value: str) -> str:
    """把 CJK 逐字用空格隔开，拉丁词与数字保持完整"""
    return CJK_RE.sub(r" \1 ", value or "")


def fts_query(query: str) -> str:
    """把用户输入转成安全的 FTS5 短语查询

    整体用双引号包成短语，这样：
      - 中文不会被拆成多个必须同时出现的独立 token（避免语义漂移）
      - `AND` / `OR` / `NEAR` / `*` / `(` 等 FTS5 语法符号失效为普通字符，
        用户随手输入 `(` 或 `a*b` 不会导致 SQL 报错
    """
    q = (query or "").strip()
    if not q:
        return ""
    s = " ".join(seg_cjk(q).split())
    return '"' + s.replace('"', '""') + '"'


def tokenize_for_index(*values: str) -> str:
    """把标题/正文等字段拼成入库文本"""
    return "\n".join(seg_cjk(v) for v in values if v)


# ---------- 块级 bigram 分词（chunk_fts 专用） ----------
#
# 为什么另起一套，不改 seg_cjk：
# document_fts 是文档级通道，正在跑，改它的分词等于动整条检索链路。
# 块级通道是新表新函数，老函数一行不动 —— 出问题可以整段回退。
#
# 为什么是 2-gram 而不是逐字：
# 逐字切分把 bm25 的统计建立在「单字」上，而单字在中文里几乎没有
# 区分度 —— 「的」「标」「注」「是」满库都是，真正有指向性的二字词
# 被埋在噪声里。2-gram 天然长得很像词（「投标」「截止」「预算」），
# 又不需要词典：离线装不了 jieba，规则切分是唯一能落地的办法。
# 代价是丢掉单字召回（「预」这种查询搜不到），但那是可接受的取舍。

# CJK 连续串 / 拉丁数字整词（切分的输入单元）
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+")
_TOKEN_RUN_RE = re.compile(
    r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+|[A-Za-z0-9]+")

# Markdown 标题行：块的第一行就是它所属的标题（切块时带上来的）
MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def _token_groups(value: str) -> list[list[str]]:
    """把一段文字切成「短语组」，每组是一个 token 序列

    这是切分的**唯一**实现：索引侧（写进 chunk_fts）和查询侧
    （拼 MATCH 表达式）都必须走它。

    为什么值得为这件事专门抽一个函数：两边只要有一处另写一份，
    整条通道就会静默失效 —— 查询语法合法、不报错，
    只是永远匹配不上（或者只匹配上另一批词）。
    这种错在检索结果上表现为「搜不到」，排查起来最费时间。
    """
    groups: list[list[str]] = []
    for m in _TOKEN_RUN_RE.finditer(value or ""):
        s = m.group(0)
        if _CJK_RUN_RE.fullmatch(s):
            n = len(s)
            # 长度为 1 的串单独成组：2-gram 对它没有定义，
            # 直接丢掉就等于这个字永远搜不到。
            groups.append([s] if n == 1 else [s[i:i + 2] for i in range(n - 1)])
        else:
            groups.append([s.lower()])
    return groups


def seg_bigram(value: str) -> str:
    """CJK 连续串切成重叠 2-gram；拉丁字母与数字保持整词

    索引侧写进 chunk_fts 的就是它切出来的 token。
    """
    out: list[str] = []
    for g in _token_groups(value):
        out.extend(g)
    return " ".join(out)


def chunk_fts_terms(query: str) -> list[str]:
    """查询侧的 token 列表：与索引侧同构（同一个 _token_groups），去重保序

    「同构」是这套方案能用的前提：索引侧写进去的是 bigram，
    查询侧也必须是同一批 bigram，否则查的是另一套词表。
    """
    out: list[str] = []
    for g in _token_groups(query):
        for t in g:
            if t not in out:
                out.append(t)
    return out


def _col_phrase(column: str, phrase: str) -> str:
    """给单个短语加上列过滤

    FTS5 的列过滤**只作用于紧跟其后的那一个短语**，不是整个表达式。
    `{heading} : "a" OR "b"` 里，"b" 是不受限的 —— 它照样能命中正文列，
    于是「只搜标题」变成了「搜全文再假装是标题命中」。
    这个坑很隐蔽：实测命中行数从 3 行变成 15 行，多出来的全是正文命中。
    所以每个 OR 分支都得自己带上列过滤。
    """
    return f"{{{column}}} : {phrase}" if column else phrase


def chunk_fts_query(query: str, *, column: str = "") -> str:
    """块级检索的 MATCH 表达式：bigram token 之间用 OR

    为什么不把整句做成一个短语：整句短语要求原文逐字连续出现整句，
    问句「投标截止时间和开标时间分别是什么」在原文里根本不存在，
    这样的查询永远返回空。拆成 bigram 之后变成「命中了哪些二字组合」，
    排序交给 bm25 —— 稀有组合（git、27123、预算）自然排在前面。

    column 非空时把检索限制在这一列上（结构定位通道用）。
    """
    terms = chunk_fts_terms(query)
    if not terms:
        return ""
    return " OR ".join(_col_phrase(column, f'"{t}"') for t in terms)


def chunk_fts_phrase_query(query: str, *, column: str = "") -> str:
    """块级检索的「短语」表达式：一段连续汉字整体算一个 bigram 短语

    「投标截止时间」→ "投标 标截 截止 止时 时间"，
    只有原文真的出现这个连续子串才命中 —— 精度比逐字高得多。

    token 序列直接来自 _token_groups（索引侧同一个函数），
    不另写一份切分。
    """
    groups = _token_groups(query)
    return " OR ".join(_col_phrase(column, '"' + " ".join(g) + '"') for g in groups)


def chunk_fts_selfcheck(samples: list[str] | None = None) -> dict:
    """自检：索引侧与查询侧必须是同一套切分

    这个坑很安静：两边差一个字，整条通道就查不到东西，
    而且不报错 —— 查询语法合法，只是永远匹配不上。
    所以这里把两边钉死：

      1) 切分只有一份实现（_token_groups），索引侧查询侧都走它；
      2) 再验一遍真正发出去的那条 MATCH 表达式 ——
         把表达式里的 token 抠出来，必须和同一段文字走索引侧切分
         得到的 token 完全一致。

    不一致直接抛异常：让这种错在重建索引时就炸，
    而不是等到检索时才发现「搜不到」。
    """
    samples = samples or [
        "V-MAX 手册 §8：HTTP 27123 端口，自签证书，git fetch 越权",
        "投标截止时间和开标时间分别是什么",
        "变更日志在哪",
        "中",
        "a",
        "12345",
    ]
    checked = 0
    for s in samples:
        index_tokens = seg_bigram(s).split()
        # 宽松表达式：去重后的 token 用 OR 连起来
        loose_expr = chunk_fts_query(s)
        loose_tokens = [t for p in loose_expr.split('"')[1::2] for t in p.split()]
        if loose_tokens != list(dict.fromkeys(index_tokens)):
            raise AssertionError(
                f"宽松查询的 token 与索引侧不一致：{s!r} -> {loose_expr!r}")
        # 短语表达式：每段原文切成一条 bigram 短语，token 顺序与索引侧一致
        phrase_expr = chunk_fts_phrase_query(s)
        phrase_tokens = [t for p in phrase_expr.split('"')[1::2] for t in p.split()]
        if phrase_tokens != index_tokens:
            raise AssertionError(
                f"短语查询的 token 与索引侧不一致：{s!r} -> {phrase_expr!r}")
        checked += 1
    return {"samples": checked, "tokenizer": CHUNK_FTS_VERSION}


def split_chunk_heading(text: str) -> tuple[str, str]:
    """把块拆成 (标题, 正文)

    块的第一行就是它所属的标题（切块时带上的），标题单独成列是
    「结构定位」的前提：用户问「变更日志在哪」，命中的是标题，
    而不是正文里恰好也出现「变更日志」四个字。

    结构锚点只认 H2 及以下：H1 是文档标题，文档级通道
    （document_fts 的 title 列）已经管着它。再把它当成「章节」用，
    每篇文档的标题块都会拿到一张假的结构命中牌，
    把真正的章节命中挤到后面去 —— 排序直接被带偏。
    """
    lines = (text or "").split("\n")
    if lines:
        m = MD_HEADING_RE.match(lines[0].strip())
        if m:
            level = len(m.group(1))
            return (m.group(2) if level >= 2 else ""), "\n".join(lines[1:])
    return "", text or ""


# ---------- 建表 ----------

async def ensure_index_tables(conn) -> None:
    """创建 FTS5 表；向量表若已知维度则一并创建"""
    # 全文索引 —— 不依赖任何扩展
    try:
        await conn.execute(text(
            f"create virtual table if not exists {FTS_TABLE} using fts5("
            "title, body, tokenize='unicode61 remove_diacritics 2')"
        ))
    except Exception as e:
        log.warning("FTS5 索引表创建失败，全文检索将降级为 LIKE：%s", e)

    # 块级全文索引 —— 跟 document_fts 一样只用 FTS5，不引入新扩展
    await ensure_chunk_fts(conn)

    # 向量索引 —— 需要 sqlite-vec 扩展
    dim = await get_meta(conn, META_EMBED_DIM)
    if dim:
        await ensure_vec_table(conn, int(dim))


async def ensure_chunk_fts(conn) -> bool:
    """确保块级索引表存在，且内容是当前分词方案写的

    版本记号（sys_meta.chunk_fts_version）对不上 = 这张表是用旧分词写的，
    得整表重建。重建放在启动时做，是因为「新表刚上线」这个窗口里
    检索必须能用：老库里的块还没有 chunk_fts 索引，
    而块级定位是长文档里找回答案段落的关键一步。
    """
    try:
        await conn.execute(text(
            f"create virtual table if not exists {CHUNK_FTS_TABLE} using fts5("
            "heading, body, tokenize='unicode61 remove_diacritics 2')"
        ))
    except Exception as e:
        log.warning("块级 FTS5 索引表创建失败，块级定位将退回 Python 扫描：%s", e)
        return False

    version = await get_meta(conn, META_CHUNK_FTS_VERSION)
    if version == CHUNK_FTS_VERSION:
        return True
    try:
        # 先验切分：索引侧与查询侧不同构的话，这条通道等于不存在，
        # 而它失败的方式是「搜不到」—— 最安静也最难查的那种错
        chunk_fts_selfcheck()
        n = await rebuild_chunk_fts(conn)
        await set_meta(conn, META_CHUNK_FTS_VERSION, CHUNK_FTS_VERSION)
        log.info("块级全文索引已重建：%s 块（分词方案 %s）", n, CHUNK_FTS_VERSION)
        # 再验「查得回来」：光看代码一致不够，得确认库里写进去的
        # 就是这份代码切出来的
        rt = await chunk_fts_roundtrip_check(conn, limit=3)
        if rt["body_miss"] or rt["head_miss"]:
            log.warning("块级索引自检未通过（检索会静默失效）：%s", rt)
        return True
    except Exception as e:
        log.warning("块级全文索引重建失败，块级定位将退回 Python 扫描：%s", e)
        return False


async def rebuild_chunk_fts(conn, batch: int = 500) -> int:
    """按当前分词方案重建整张块级索引（rowid = document_chunk.id）

    为什么必须整表重建而不是增量补写：分词方案变了（逐字 → bigram），
    索引里存的就是另一套 token 了。增量补写会得到「一半旧词一半新词」
    的索引 —— 查出来看着有命中，其实排序全乱，比空表更难排查。

    软删除的文档不进索引：回收站里的文件不该还能被搜到，
    否则「删除」就只是个摆设。
    """
    await conn.execute(text(f"delete from {CHUNK_FTS_TABLE}"))
    total = 0
    last = 0
    while True:
        rows = (await conn.execute(
            text("select c.id, c.text from document_chunk c "
                 "join document d on d.id = c.document_id "
                 "where c.id > :last and d.deleted_at is null "
                 "order by c.id limit :lim"),
            {"last": last, "lim": batch})).all()
        if not rows:
            break
        payload = []
        for cid, ctext in rows:
            heading, body = split_chunk_heading(ctext or "")
            payload.append({"r": cid, "h": seg_bigram(heading),
                            "b": seg_bigram(body)})
            last = cid
        await conn.execute(
            text(f"insert into {CHUNK_FTS_TABLE}(rowid, heading, body) "
                 "values (:r, :h, :b)"), payload)
        total += len(payload)
    return total


async def chunk_fts_roundtrip_check(db, limit: int = 5) -> dict:
    """拿库里的真实块做一次「查回来」自检

    纯函数自检只能保证「代码里索引侧和查询侧一致」，
    保证不了「库里写进去的就是这份代码切出来的」——
    旧库、旧分词方案、写入路径漏写，都会破这一层。

    所以再补一层：抽几块的正文当查询发出去，这几块必须能被自己查回来；
    再抽几块的结构锚点当查询，标题通道必须能把它们查回来。
    查不回来 = 索引与查询不同构，这条通道等于不存在。
    """
    rows = (await db.execute(
        text("select id, text from document_chunk "
             "where text is not null and length(text) > 40 limit :lim"),
        {"lim": limit * 3})).all()
    body_miss: list[int] = []
    head_miss: list[int] = []
    for cid, ctext in rows:
        heading, body = split_chunk_heading(ctext or "")
        probe = (body or "")[:60].strip()
        if probe:
            hits = await chunk_fts_search(db, probe, limit=60)
            if not any(h["chunk_id"] == cid for h in hits):
                body_miss.append(cid)
        if heading:
            hits = await chunk_heading_search(db, heading, limit=60)
            if not any(h["chunk_id"] == cid for h in hits):
                head_miss.append(cid)
    return {"checked": len(rows), "body_miss": body_miss, "head_miss": head_miss}


async def ensure_vec_table(conn, dim: int) -> bool:
    """确保向量表存在、维度正确、距离度量正确

    三种情况：

    1. **维度变化**（切换 embedding 模型，1024 ↔ 1536）—— 旧向量无法复用，
       必须 DROP 后重建，并清空所有 chunk 的 embedded 标记等待重新向量化。
    2. **距离度量变化**（老库建表时没写 distance_metric，默认是 L2）——
       向量本身是原始 float32，**可以原样搬到新表**，不必重新调用
       embedding 接口（那是要花钱的）。
    3. 一切正常 —— 什么都不做。
    """
    if dim <= 0:
        return False
    try:
        existing = await get_meta(conn, META_EMBED_DIM)
        cur_dim = int(existing) if existing else 0
        metric = await get_meta(conn, META_VEC_METRIC)
        table_exists = await _table_exists(conn, VEC_TABLE)

        if table_exists and cur_dim and cur_dim != dim:
            log.warning("向量维度由 %s 变为 %s，重建向量表", cur_dim, dim)
            await conn.execute(text(f"drop table if exists {VEC_TABLE}"))
            await conn.execute(text("update document_chunk set embedded = 0"))
            # 只清 chunk 的 embedded 位不够：document.embed_status 还停在 'ok'，
            # 后台补向量任务只挑 pending/failed —— 于是这些文件永远不会被
            # 重新向量化，语义检索静默失效，且体检面板还显示「已建向量索引」。
            await conn.execute(
                text("update document set embed_status = 'pending' "
                     "where embed_status in ('ok', 'partial')")
            )
            table_exists = False

        if table_exists and metric != VEC_METRIC:
            # 老表没有度量记录（默认 L2），或度量被改过：
            # 向量字节可以原样搬过去，重建表但不重新向量化
            log.warning("向量表距离度量由 %s 变为 %s，重建向量表并搬运原有向量",
                        metric or "L2(默认)", VEC_METRIC)
            saved = await _dump_vectors(conn)
            await conn.execute(text(f"drop table if exists {VEC_TABLE}"))
            await conn.execute(text(
                f"create virtual table {VEC_TABLE} using vec0("
                f"embedding float[{dim}] distance_metric={VEC_METRIC})"
            ))
            moved = 0
            for cid, blob in saved:
                try:
                    await conn.execute(
                        text(f"insert into {VEC_TABLE}(rowid, embedding) "
                             "values (:r, :e)"), {"r": cid, "e": blob})
                    moved += 1
                except Exception as e:
                    log.warning("向量搬运失败 chunk=%s：%s", cid, e)
            log.info("已搬运 %s/%s 条向量到新表", moved, len(saved))
            table_exists = True

        if not table_exists:
            await conn.execute(text(
                f"create virtual table {VEC_TABLE} using vec0("
                f"embedding float[{dim}] distance_metric={VEC_METRIC})"
            ))
        await set_meta(conn, META_EMBED_DIM, str(dim))
        await set_meta(conn, META_VEC_METRIC, VEC_METRIC)
        return True
    except Exception as e:
        log.warning("向量表创建失败，语义检索将不可用：%s", e)
        return False


async def _dump_vectors(conn, batch: int = 500) -> list[tuple[int, bytes]]:
    """把向量表里的原始字节取出来（用于换表时原样搬运）

    分批取，别一次性把整库向量读进内存 —— 20 万条 × 6 KB 就是 1.2 GB。
    """
    out: list[tuple[int, bytes]] = []
    last = 0
    while True:
        rows = (await conn.execute(
            text(f"select rowid, embedding from {VEC_TABLE} "
                 "where rowid > :last order by rowid limit :lim"),
            {"last": last, "lim": batch},
        )).all()
        if not rows:
            break
        for rid, blob in rows:
            out.append((rid, blob))
            last = rid
    return out


def similarity(distance: float, metric: str | None) -> float:
    """把 vec0 给的 distance 换算成 0~1 的相似度

    cosine 表：distance = 1 - cos_sim，直接取补。
    L2 老表：单位向量下 cos = 1 - d²/2（embo-01 实测模长恒为 1）。
    """
    d = float(distance or 0.0)
    if metric == VEC_METRIC:
        return max(0.0, min(1.0, 1.0 - d))
    return max(0.0, min(1.0, 1.0 - (d * d) / 2.0))


async def _table_exists(conn, name: str) -> bool:
    r = await conn.execute(
        text("select 1 from sqlite_master where type='table' and name=:n"), {"n": name}
    )
    return r.scalar() is not None


# ---------- sys_meta 读写 ----------

# sys_meta 的读缓存：这几个值（向量维度、距离度量、分词版本）
# 一次请求里会被读好几遍，而它们几乎不变。
# 缓存 5 秒：版本号变了最多 5 秒后生效 —— 重建索引这种低频动作，
# 不值得为「立刻可见」去多写一套失效广播。
_meta_cache = TTLCache(max_size=64, ttl=5.0)


async def get_meta(conn, key: str) -> str | None:
    if not getattr(settings, "search_cache_enabled", True):
        r = await conn.execute(text("select value from sys_meta where key=:k"),
                               {"k": key})
        return r.scalar()
    cached = _meta_cache.get(key)
    if cached is not None:
        return cached
    r = await conn.execute(text("select value from sys_meta where key=:k"), {"k": key})
    row = r.scalar()
    if row is not None:
        _meta_cache.put(key, row)
    return row


async def set_meta(conn, key: str, value: str) -> None:
    await conn.execute(text(
        "insert into sys_meta(key, value, updated_at) values (:k, :v, datetime('now')) "
        "on conflict(key) do update set value=:v, updated_at=datetime('now')"
    ), {"k": key, "v": value})
    # 自己刚写的值要立刻可见，不能等缓存过期
    _meta_cache.drop(key)


# ---------- 文档写入索引 ----------

async def index_document(db: AsyncSession, doc_id: int, title: str,
                         filename: str, tags: list | None,
                         summary: str, body: str) -> None:
    """把文档写进 FTS5（rowid = document.id，先删后插保证幂等）"""
    try:
        await db.execute(
            text(f"delete from {FTS_TABLE} where rowid = :rid"), {"rid": doc_id}
        )
        await db.execute(
            text(f"insert into {FTS_TABLE}(rowid, title, body) values (:rid, :t, :b)"),
            {
                "rid": doc_id,
                "t": tokenize_for_index(title, filename, " ".join(tags or [])),
                "b": tokenize_for_index(summary, body),
            },
        )
    except Exception as e:
        log.warning("FTS 索引写入失败 doc=%s：%s", doc_id, e)


async def remove_fts(db: AsyncSession, doc_id: int) -> None:
    """只从 FTS5 移除，不动向量表（供「仅重建全文索引」的场景使用）"""
    try:
        await db.execute(text(f"delete from {FTS_TABLE} where rowid = :rid"), {"rid": doc_id})
    except Exception as e:
        log.warning("FTS 索引删除失败 doc=%s：%s", doc_id, e)


# ---------- 块级索引写入 ----------

async def index_chunks(db, doc_id: int, chunks: list[tuple[int, str]]) -> int:
    """把切好的块写进块级索引（rowid = document_chunk.id，标题/正文两列）

    幂等：写之前先清掉这篇文档在 chunk_fts 里的旧行，
    同一次切块重跑不会留下上一轮的残骸。
    """
    if not chunks:
        return 0
    try:
        await db.execute(
            text(f"delete from {CHUNK_FTS_TABLE} where rowid in "
                 "(select id from document_chunk where document_id = :d)"),
            {"d": doc_id},
        )
        payload = []
        for cid, ctext in chunks:
            heading, body = split_chunk_heading(ctext or "")
            payload.append({"r": cid, "h": seg_bigram(heading),
                            "b": seg_bigram(body)})
        await db.execute(
            text(f"insert into {CHUNK_FTS_TABLE}(rowid, heading, body) "
                 "values (:r, :h, :b)"), payload)
        # 块内容变了，缓存里的 token 集就不再作数
        for cid, _ctext in chunks:
            _chunk_token_cache.drop(f"{cid}:b")
            _chunk_token_cache.drop(f"{cid}:h")
        return len(payload)
    except Exception as e:
        log.warning("块级索引写入失败 doc=%s：%s", doc_id, e)
        return 0


async def remove_chunks(db, chunk_ids: list[int]) -> None:
    """从块级索引里删掉这些块（重新切块时用）"""
    if not chunk_ids:
        return
    qmarks = ",".join(f":c{i}" for i in range(len(chunk_ids)))
    params = {f"c{i}": cid for i, cid in enumerate(chunk_ids)}
    try:
        await db.execute(
            text(f"delete from {CHUNK_FTS_TABLE} where rowid in ({qmarks})"), params)
    except Exception as e:
        log.warning("块级索引删除失败：%s", e)
    # 块没了，缓存里的 token 集也不能留着
    for cid in chunk_ids:
        _chunk_token_cache.drop(f"{cid}:b")
        _chunk_token_cache.drop(f"{cid}:h")


async def rebuild_document_chunks(db, doc_id: int) -> int:
    """按当前分词方案重建某篇文档的块级索引

    用在「块还在、但索引丢了」的地方：软删除再恢复就是一个。
    """
    try:
        rows = (await db.execute(
            text("select id, text from document_chunk where document_id = :d"),
            {"d": doc_id})).all()
        await db.execute(
            text(f"delete from {CHUNK_FTS_TABLE} where rowid in "
                 "(select id from document_chunk where document_id = :d)"),
            {"d": doc_id})
        payload = []
        for cid, ctext in rows:
            heading, body = split_chunk_heading(ctext or "")
            payload.append({"r": cid, "h": seg_bigram(heading),
                            "b": seg_bigram(body)})
        if payload:
            await db.execute(
                text(f"insert into {CHUNK_FTS_TABLE}(rowid, heading, body) "
                     "values (:r, :h, :b)"), payload)
        # 重建 = 换了分词方案，缓存里的旧 token 集必须作废
        for cid, _text in rows:
            _chunk_token_cache.drop(f"{cid}:b")
            _chunk_token_cache.drop(f"{cid}:h")
        return len(payload)
    except Exception as e:
        log.warning("块级索引重建失败 doc=%s：%s", doc_id, e)
        return 0


async def remove_document(db: AsyncSession, doc_id: int) -> None:
    """从 FTS5、块级索引与向量表移除文档"""
    await remove_fts(db, doc_id)

    # 块级索引：删文档就等于删掉它所有块的索引行，
    # 不然回收站里的文件照样能被关键词搜出来 —— 「删除」成了摆设。
    try:
        await db.execute(
            text(f"delete from {CHUNK_FTS_TABLE} where rowid in "
                 "(select id from document_chunk where document_id = :d)"),
            {"d": doc_id})
    except Exception as e:
        log.warning("块级索引删除失败 doc=%s：%s", doc_id, e)

    try:
        rows = (await db.execute(
            text("select id from document_chunk where document_id = :d"), {"d": doc_id}
        )).scalars().all()
        for cid in rows:
            await db.execute(
                text(f"delete from {VEC_TABLE} where rowid = :rid"), {"rid": cid}
            )
            _chunk_token_cache.drop(f"{cid}:b")
            _chunk_token_cache.drop(f"{cid}:h")
    except Exception as e:
        log.warning("向量索引删除失败 doc=%s：%s", doc_id, e)


# ---------- 检索 ----------

async def fts_search(db: AsyncSession, query: str, limit: int = 30) -> list[dict]:
    """FTS5 检索，返回 [{document_id, score}]（score 越大越相关）"""
    fq = fts_query(query)
    if not fq:
        return []
    try:
        rows = (await db.execute(
            text(f"select rowid, bm25({FTS_TABLE}) as r from {FTS_TABLE} "
                 f"where {FTS_TABLE} match :q order by rank limit :lim"),
            {"q": fq, "lim": limit},
        )).all()
        # bm25() 是「越小越相关」的负数，取反得到越大越相关
        return [{"document_id": r[0], "score": -float(r[1] or 0.0)} for r in rows]
    except Exception as e:
        log.warning("FTS 检索失败（降级为 LIKE）：%s", e)
        return await like_search(db, query, limit)


async def like_search(db: AsyncSession, query: str, limit: int = 30) -> list[dict]:
    """兜底：短查询或 FTS 不可用时的 LIKE 检索"""
    kw = (query or "").strip()
    if not kw:
        return []
    like = f"%{kw}%"
    rows = (await db.execute(
        text(
            "select id, "
            "  (case when title like :l then 2 else 0 end) "
            "+ (case when filename like :l then 1 else 0 end) as score "
            "from document where deleted_at is null "
            "and (title like :l or filename like :l or tags like :l or extracted_text like :l) "
            "order by score desc, id desc limit :lim"
        ),
        {"l": like, "lim": limit},
    )).all()
    return [{"document_id": r[0], "score": float(r[1] or 0.0) + 0.5} for r in rows]


async def vec_search(db: AsyncSession, vector: list[float], limit: int = 30) -> list[dict]:
    """向量 KNN 检索，返回 [{chunk_id, document_id, distance, text}]

    这里把命中块的正文一并带出来。块是向量检索的最小单位，
    也是唯一知道「答案落在哪一段」的东西 —— 只回一个 document_id，
    等于把这个信息扔掉：上层只好重新拿整篇文档的前几千字去喂模型，
    长文档里命中在后面的段落就永远答不对（这正是「向量库换了也没用」
    的根因：索引准了，取材没跟上）。
    """
    if not vector:
        return []
    try:
        import sqlite_vec
        blob = sqlite_vec.serialize_float32(vector)
        rows = (await db.execute(
            text(
                f"select rowid, distance from {VEC_TABLE} "
                "where embedding match :q order by distance limit :lim"
            ),
            {"q": blob, "lim": limit},
        )).all()
        if not rows:
            return []
        chunk_ids = [r[0] for r in rows]
        # 把 chunk 映射回 document，顺带把块的正文取出来
        id_map = {}
        qmarks = ",".join(f":c{i}" for i in range(len(chunk_ids)))
        params = {f"c{i}": cid for i, cid in enumerate(chunk_ids)}
        cmap = (await db.execute(
            text(f"select id, document_id, text from document_chunk where id in ({qmarks})"),
            params,
        )).all()
        for cid, did, ctext in cmap:
            id_map[cid] = (did, ctext or "")

        out = []
        for cid, dist in rows:
            got = id_map.get(cid)
            if got is None:
                continue
            did, ctext = got
            out.append({
                "chunk_id": cid,
                "document_id": did,
                "distance": float(dist),
                "text": ctext,
            })
        return out
    except Exception as e:
        log.warning("向量检索失败：%s", e)
        return []


# ---------- 块级关键词定位 ----------

# 连续汉字串 / 拉丁词
_CJK_RUN = re.compile(r"[一-鿿㐀-䶿豈-﫿]+")
_LATIN_RUN = re.compile(r"[A-Za-z0-9_.\-]{2,}")


_WS_RE = re.compile(r"\s+")


def _flat(text: str) -> str:
    """去掉所有空白 —— 中文正文里的换行会把词劈开，比对前要先压平"""
    return _WS_RE.sub("", text or "")


def keyword_terms(query: str, max_cjk: int = 12, max_latin: int = 6) -> list[str]:
    """把查询拆成用于块级扫描的关键词

    为什么不能直接拿原句去 LIKE：用户问的是「项目预算是多少」，
    正文里根本不会出现这整句话，永远命中不了。
    改成「连续汉字取 2 字滑窗 + 拉丁词整词」，命中面宽但不啰嗦。

    拉丁词单独留配额：像 vault、agent、git 这类词，
    往往比汉字滑窗更有指向性，不能被汉字挤掉。
    """
    q = (query or "").strip()
    if not q:
        return []
    latin: list[str] = []
    for w in _LATIN_RUN.findall(q):
        w = w.lower()
        if w not in latin:
            latin.append(w)
    cjk: list[str] = []
    for run in _CJK_RUN.findall(q):
        for i in range(len(run) - 1):
            t = run[i:i + 2]
            if t not in cjk and t not in latin:
                cjk.append(t)
    return latin[:max_latin] + cjk[:max_cjk]


async def chunk_keyword_scan(db: AsyncSession, doc_ids: list[int], query: str,
                             limit: int = 12, max_docs: int = 6,
                             max_chunks: int = 1500) -> list[dict]:
    """块级关键词定位：优先查 chunk_fts，查不动再退回 Python 扫描

    FTS5 表一行一篇文档（rowid = document.id），所以文档级通道只能
    告诉你「哪篇文档相关」，说不出「哪一段相关」。长文档里答案常在
    中间偏后，只给模型整篇开头就会答不上来 —— 这一步补上块级定位。

    现在是查索引而不是把候选块的正文拉回 Python 做字符串匹配：
    一次 MATCH 把全库的块排好序，既不再受「只扫前 6 篇文档 / 前 1500 块」
    的截断影响，也让 bm25 的 idf 建立在全库统计上 ——
    局部 idf 会把「在这几篇文档里常见」误当成「有信息量」。

    兜底必须留着：chunk_fts 是新表，老库里它是空的（版本记号对不上），
    直接返回空 = 长文档里的检索整体失效。
    """
    if not keyword_terms(query):
        return []
    if await chunk_fts_ready(db):
        return await chunk_fts_search(db, query, limit=limit)
    return await _chunk_keyword_scan_python(db, doc_ids, query, limit, max_docs,
                                            max_chunks)


async def chunk_fts_ready(db) -> bool:
    """块级索引能不能用（表建好了、且是当前分词方案写的）

    判据用 sys_meta 里的版本记号，而不是「表里有没有行」：
    count(*) 在 FTS5 上是全表扫描，库大了每次检索都白扫一遍。
    """
    try:
        version = await get_meta(db, META_CHUNK_FTS_VERSION)
    except Exception:
        return False
    return (version or "") == CHUNK_FTS_VERSION


async def _chunk_fts_rows(db, expr: str, limit: int) -> list[tuple[int, float]]:
    """跑 chunk_fts 的 MATCH，返回 [(chunk_id, 相关度)]，相关度越大越相关

    expr 里自带列过滤（结构定位通道用）：命中的是标题，
    不是正文里恰好也出现的那几个字。
    """
    if not expr:
        return []
    try:
        rows = (await db.execute(
            text(f"select rowid, bm25({CHUNK_FTS_TABLE}) as r from {CHUNK_FTS_TABLE} "
                 f"where {CHUNK_FTS_TABLE} match :q order by rank limit :lim"),
            {"q": expr, "lim": limit})).all()
    except Exception as e:
        log.warning("块级 FTS 检索失败：%s", e)
        return []
    # bm25() 是「越小越相关」的负数，取反得到越大越相关
    return [(r[0], -float(r[1] or 0.0)) for r in rows]


# 块级 token 集缓存：同一个块被反复命中时，不用每次重新切一遍 bigram。
#
# 为什么值得缓存：切词是纯 CPU 开销，而且**与查询无关** ——
# 同一个块在 10 个不同查询里命中 10 次，就要切 10 遍。
# 实测这一项在「块级 FTS5」这条路径上占了将近 1ms，
# 而候选块一多它还会线性涨 —— 属于「数据变多就变慢」的那一类。
#
# 块是「切好就不动」的（重新切块时会显式清掉缓存），所以缓存它很安全。
_chunk_token_cache = TTLCache(
    max_size=max(16, int(getattr(settings, "search_cache_max", 256))),
    ttl=max(5.0, float(getattr(settings, "search_cache_ttl", 120.0))),
)


def _chunk_tokens(chunk_id: int, text: str, structure: bool) -> set[str]:
    """取一个块的 token 集（标题通道取标题，正文通道取正文）"""
    heading, body = split_chunk_heading(text)
    if not getattr(settings, "search_cache_enabled", True):
        return set(seg_bigram(heading if structure else body).split())
    key = f"{chunk_id}:{'h' if structure else 'b'}"
    hit = _chunk_token_cache.get(key)
    if hit is not None:
        return hit
    tokens = set(seg_bigram(heading if structure else body).split())
    _chunk_token_cache.put(key, tokens)
    return tokens


async def _hydrate_chunk_hits(db, rows: list[tuple[int, float]], query: str,
                              *, structure: bool = False) -> list[dict]:
    """回表取 document_id/seq/text，并统计命中了几个词

    「命中了几个词」用来在同分时排序：一个块命中 3 个词比只命中 1 个强。
    命中数按索引侧同一套切分统计（而不是把空白压平再子串匹配），
    否则「被换行劈开的二字词」会被算成命中，与索引事实不符。

    结构通道只数标题里的命中：正文里命中再多词，也说明不了
    「这一节就是你要的那一节」。
    """
    if not rows:
        return []
    ids = [r[0] for r in rows]
    qmarks = ",".join(f":c{i}" for i in range(len(ids)))
    params = {f"c{i}": cid for i, cid in enumerate(ids)}
    try:
        meta = (await db.execute(
            text(f"select id, document_id, seq, text from document_chunk "
                 f"where id in ({qmarks})"), params)).all()
    except Exception as e:
        log.warning("块级命中回表失败：%s", e)
        return []
    info = {r[0]: (r[1], r[2], r[3] or "") for r in meta}

    terms = chunk_fts_terms(query)
    # 分数在本通道内归一化：bm25 的绝对值跨通道没有可比性
    # （idf 随语料变化，正文通道的 20 分和标题通道的 20 分不是一回事），
    # 归一化之后才能诚实地给标题命中加权。
    top = max((s for _cid, s in rows), default=0.0) or 1.0
    out: list[dict] = []
    for cid, score in rows:
        got = info.get(cid)
        if got is None:
            continue
        did, seq, ctext = got
        tokens = _chunk_tokens(cid, ctext, structure)
        out.append({
            "chunk_id": cid,
            "document_id": did,
            "seq": seq,
            "text": ctext,
            "hits": sum(1 for t in terms if t in tokens),
            "score": round(score / top, 6),
            "structure": structure,
        })
    return out


async def chunk_fts_search(db, query: str, limit: int = 12) -> list[dict]:
    """块级正文检索（chunk_fts 的 body 列）

    查全库，不限文档：块级定位的价值就在于「答案可能落在
    排名靠后那篇文档的中后段」，只扫前几篇文档等于把这部分答案扔掉。
    """
    expr = chunk_fts_query(query)
    if not expr:
        return []
    rows = await _chunk_fts_rows(db, expr, limit)
    return await _hydrate_chunk_hits(db, rows, query)


async def chunk_heading_search(db, query: str, limit: int = 12) -> list[dict]:
    """结构定位：只在 chunk_fts 的 heading 列上匹配

    问「变更日志在哪」「付款条款是什么」，命中的是标题而不是正文 ——
    标题是作者自己声明的结构，比正文里偶然撞上的几个字可靠得多。
    这就是 OpenKB 里 PageIndex 那套「靠结构定位」的落法。

    先用短语表达式（精确：原文得真出现这个连续子串），
    命中不了再退回 bigram OR（召回：问句里「在哪」「是什么」这类
    问词不在标题里，整句短语永远匹配不上）。

    列过滤必须逐个 OR 分支都带上（FTS5 的列过滤只管紧跟其后的那个短语），
    否则「只搜标题」会漏成「搜全文」，结构命中牌就发错了。
    """
    expr = chunk_fts_phrase_query(query, column="heading")
    rows = await _chunk_fts_rows(db, expr, limit)
    if not rows:
        expr = chunk_fts_query(query, column="heading")
        rows = await _chunk_fts_rows(db, expr, limit)
    return await _hydrate_chunk_hits(db, rows, query, structure=True)


async def _chunk_keyword_scan_python(db: AsyncSession, doc_ids: list[int],
                                     query: str, limit: int = 12,
                                     max_docs: int = 6,
                                     max_chunks: int = 1500) -> list[dict]:
    """兜底：没有块级索引时，在指定文档的块里做字符串匹配

    这是块级索引上线之前的做法，现在只在 chunk_fts 不可用时兜底。

    打分用 BM25 那套 idf：命中「写入」这种到处都是的词，
    不该和命中「27123」这种只出现一次的词等价。
    没有 idf 时，问句里的「是什么」「会怎样」会跟正文里任何一块
    打成平手，真正稀有的那条反而被淹没。

    匹配前把空白去掉再比：抽取出来的正文里，一个词被换行劈开是常事
    （「涉密信息\\n系统集成」），带空白的 LIKE 永远匹配不上，
    带空白的整词查询也会失手。

    只在排名靠前的几篇文档里扫，不扫全库：这是兜底路径，
    全库扫一遍的代价在库大了以后受不了。
    """
    terms = keyword_terms(query)
    if not terms or not doc_ids:
        return []
    docs = list(dict.fromkeys(int(d) for d in doc_ids))[:max_docs]
    qmarks = ",".join(f":d{i}" for i in range(len(docs)))
    params = {f"d{i}": d for i, d in enumerate(docs)}
    try:
        rows = (await db.execute(
            text(f"select id, document_id, seq, text from document_chunk "
                 f"where document_id in ({qmarks}) limit :lim"),
            {**params, "lim": max_chunks},
        )).all()
    except Exception as e:
        log.warning("块级关键词扫描失败：%s", e)
        return []
    if not rows:
        return []

    flat_terms = [_flat(t) for t in terms]
    total = len(rows)
    df = [0] * len(terms)
    flats = []
    for _cid, _did, _seq, ctext in rows:
        flat = _flat(ctext or "")
        flats.append(flat)
        for i, ft in enumerate(flat_terms):
            if ft and ft in flat:
                df[i] += 1
    idf = [math.log(1.0 + (total - d + 0.5) / (d + 0.5)) for d in df]

    out = []
    for (cid, did, seq, ctext), flat in zip(rows, flats):
        matched = [i for i, ft in enumerate(flat_terms) if ft and ft in flat]
        out.append({
            "chunk_id": cid,
            "document_id": did,
            "seq": seq,
            "text": ctext or "",
            "hits": len(matched),
            "score": sum(idf[i] for i in matched),
            "structure": False,
        })
    out.sort(key=lambda x: (-x["score"], -x["hits"], x["chunk_id"]))
    return out[:limit]



# ---------- 记录级全文索引（entity_record） ----------
#
# 为什么记录也要一张倒排索引：
#   记录检索原来靠 `search_text like '%kw%'`，那是**全表扫描** ——
#   命中一条和一条没命中，代价都跟库里有多少条记录成正比。
#   而记录恰恰就是「经验数据」的主要载体，是最会长大的那张表。
#   全表扫描撞上「经验变多」，表现就是搜索越来越慢，
#   而且慢得毫无道理（数据没坏、索引没坏，纯粹是扫得多了）。
#
# 同步靠 SQLite 触发器，不靠 Python 钩子：
#   触发器写在库里，任何写入路径（ORM、批量 update、迁移脚本、
#   将来新增的接口）都自动生效。靠 Python 钩子的话，
#   只要漏掉一条写入路径，索引就悄悄过期了 —— 搜不到东西，而且不报错。

RECORD_FTS_TABLE = "record_fts"
# 分词方案版本号。变了就得整表重建（同 chunk_fts 的道理）。
# 版本号变了 = 触发器写法或分词方案变了，要整表重建一次。
# 「bigram3」：触发器改用普通 DELETE（原因见 ensure_record_fts 里的说明）。
RECORD_FTS_VERSION = "bigram3"
META_RECORD_FTS_VERSION = "record_fts_version"


def seg_bigram_sql(text: str | None) -> str:
    """触发器里用的 bigram 切分（与 seg_bigram 必须逐字一致）

    SQLite 触发器只能调 SQLite 内置函数，除非我们把 Python 函数
    注册进去（见 database.py 的 _on_connect）。注册的是这个函数，
    索引里写进去的也就是这个函数算出来的 —— 两边只要有一处不同构，
    这条通道就会静默失效：查出来看着有命中，其实排序全乱。
    """
    return seg_bigram(text or "")


def record_fts_query(query: str) -> str:
    """记录级 MATCH 表达式

    与块级同一套 bigram OR：命中「哪些二字组合」而不是「整句原样出现」。
    用户搜「知识库采购项目」时，这整句在字段值里根本不会连续出现，
    拆成二字词才有召回；召回变宽了由 bm25 排序把最像的顶上来。

    单字查询（「张」）在 bigram 索引里没有对应 token，强行查会返回空 ——
    这种查询交给 LIKE 兜底（见 record_search）。
    """
    terms = chunk_fts_terms(query)
    multi = [t for t in terms if len(t) >= 2]
    if not multi:
        return ""
    return " OR ".join('"' + t + '"' for t in multi)


async def ensure_record_fts(conn) -> bool:
    """确保记录级全文索引存在，且内容是当前分词方案写的

    返回 False = 索引不可用（调用方退回 LIKE 扫描，功能不中断）。
    """
    try:
        await conn.execute(text(
            f"create virtual table if not exists {RECORD_FTS_TABLE} using fts5("
            "body, tokenize='unicode61 remove_diacritics 2')"))
    except Exception as e:
        log.warning("记录级 FTS5 索引表创建失败，记录检索将退回 LIKE：%s", e)
        return False

    # 触发器：写记录即写索引。ifnull 是为了 search_text 为 NULL 时
    # 不给 FTS5 塞 NULL（FTS5 收到 NULL 会报「SQL logic error」）。
    # 触发器：写记录即写索引。
    #
    # 删除为什么用 `delete from 索引表 where rowid=...` 而不是 FTS5 的
    # 'delete' 命令：'delete' 命令要求把**原文**再喂一遍，
    # 而这里喂的是 UDF 现算出来的分词结果 —— 一旦两边不一致，
    # FTS5 会直接报 "SQL logic error"（实测：改一次记录就整条更新失败）。
    # 普通 DELETE 走 FTS5 自己的删除路径，不依赖原文，最稳。
    triggers = [
        ("record_fts_ai", "after insert on entity_record",
         f"insert into {RECORD_FTS_TABLE}(rowid, body) "
         "values (new.id, kb_seg_bigram(ifnull(new.search_text, '')));"),
        ("record_fts_ad", "after delete on entity_record",
         f"delete from {RECORD_FTS_TABLE} where rowid = old.id;"),
        ("record_fts_au", "after update of search_text on entity_record",
         f"delete from {RECORD_FTS_TABLE} where rowid = old.id; "
         f"insert into {RECORD_FTS_TABLE}(rowid, body) "
         "values (new.id, kb_seg_bigram(ifnull(new.search_text, '')));"),
    ]
    for name, when, body in triggers:
        try:
            # 先删再建：create trigger if not exists 不会替换旧触发器，
            # 触发器写法改了却没重建 = 索引静默不同步（搜不到新建的记录）
            await conn.execute(text(f"drop trigger if exists {name}"))
            await conn.execute(text(
                f"create trigger {name} {when} begin {body} end;"))
        except Exception as e:
            log.warning("记录级索引触发器 %s 创建失败：%s", name, e)
            return False

    version = await get_meta(conn, META_RECORD_FTS_VERSION)
    if version == RECORD_FTS_VERSION:
        return True
    try:
        await conn.execute(text(f"delete from {RECORD_FTS_TABLE}"))
        await conn.execute(text(
            f"insert into {RECORD_FTS_TABLE}(rowid, body) "
            "select id, kb_seg_bigram(ifnull(search_text, '')) "
            "from entity_record"))
        await set_meta(conn, META_RECORD_FTS_VERSION, RECORD_FTS_VERSION)
        log.info("记录级全文索引已重建（分词方案 %s）", RECORD_FTS_VERSION)
        return True
    except Exception as e:
        log.warning("记录级全文索引重建失败，记录检索将退回 LIKE：%s", e)
        return False


async def record_fts_ready(db) -> bool:
    """记录级索引能不能用（表建好了、且是当前分词方案写的）"""
    try:
        version = await get_meta(db, META_RECORD_FTS_VERSION)
    except Exception:
        return False
    return (version or "") == RECORD_FTS_VERSION


async def record_search(db: AsyncSession, keyword: str, limit: int = 50,
                        allowed_type_ids: list[int] | None = None) -> list[dict]:
    """记录级检索：倒排索引缩小候选 + 一次 JOIN 拿全类型信息

    两处改动，都冲着「数据变多别变慢」去：

      1. 用 record_fts 倒排索引把候选缩到少量，而不是全表 LIKE；
         LIKE 条件仍然保留在最终过滤里 —— 它保证结果集与原来
         **完全一致**（索引只用来缩小候选，不改变命中口径）。
      2. 类型信息一次 JOIN 拿完，不再「取 N 条记录 → 再回表 N 次」
         （N+1：结果条数一多，查询次数就线性涨）。

    索引不可用时返回 None，调用方退回原来的 LIKE 扫描。
    """
    q = (keyword or "").strip()
    if not q:
        return []
    expr = record_fts_query(q)
    if not expr or not await record_fts_ready(db):
        return None

    sql = [
        "select r.id, r.entity_type_id, r.data, r.search_text, "
        "t.key, t.name, t.icon "
        "from entity_record r "
        "left join entity_type t on t.id = r.entity_type_id "
        "where r.id in (select rowid from record_fts "
        "where record_fts match :m) "
        "and r.search_text like :like "
        "and r.deleted_at is null"]
    params: dict[str, Any] = {"m": expr, "like": f"%{q}%", "lim": int(limit)}
    if allowed_type_ids is not None:
        ids = [int(i) for i in allowed_type_ids]
        if not ids:
            return []
        sql.append("and r.entity_type_id in (" +
                   ",".join(f":t{i}" for i in range(len(ids))) + ")")
        for i, tid in enumerate(ids):
            params[f"t{i}"] = tid
    sql.append("order by r.updated_at desc limit :lim")
    try:
        rows = (await db.execute(text(" ".join(sql)), params)).all()
    except Exception as e:
        log.warning("记录级索引检索失败，退回 LIKE：%s", e)
        return None

    out: list[dict] = []
    low = q.lower()
    for rid, etid, data, search_text, key, name, icon in rows:
        text_src = search_text or ""
        idx = text_src.lower().find(low)
        if idx >= 0:
            start = max(0, idx - 30)
            end = min(len(text_src), idx + len(q) + 30)
            snippet = ("..." if start > 0 else "") + text_src[start:end] + (
                "..." if end < len(text_src) else "")
        else:
            snippet = text_src[:80]
        out.append({
            "record_id": rid,
            "entity_type_id": etid,
            "entity_type_key": key or "",
            "entity_type_name": name or "",
            "entity_type_icon": icon or "📦",
            "snippet": snippet,
            "data": data or {},
        })
    return out

