# 养料 DNA —— 功能规格

> 状态：v0.7.3 之后新增的独立模块。
> 后端服务 + 前端页面并行开发，**接口契约以本文为准**，两边不得各写各的。

---

## 一、这个模块是干什么的

**「养料」= 喂给模型的所有东西**（文档、笔记、块、向量）。
DNA 就是这份养料的**体检报告 + 基因图谱**：回答四个问题

1. **成分** —— 我到底喂了什么进去？（多少文档、多少块、多少字、什么类型、什么标签）
2. **骨架** —— 这些东西长什么样？（每篇文档的标题层级 = OpenKB 的 PageIndex 树）
3. **指纹** —— 它的主题特征是什么？（高信息量词条 = 这批资料的「基因」）
4. **健康度** —— 哪里有毛病？（抽取失败、没向量化、重复内容、维度对不上）

**不做的事**：DNA 是**只读**的。它不调用 LLM、不改写原文、不重算向量。
（OpenKB 把「二级」改写成「乙级」还持久化进索引 —— 那种做法在 DNA 里绝不能有。）

### 从 OpenKB 吸收了什么

| OpenKB 的做法 | 在 DNA 里的落点 |
|---|---|
| PageIndex：把文档编成树，靠结构定位 | `/api/dna/tree` —— 全库结构索引（OpenKB `index.md` 的等价物） |
| summaries / concepts / entities / sources 四件套 | 文档谱系列表 + 单篇 DNA（摘要 / 主题词 / 结构 / 来源与指纹） |
| `AGENTS.md`：给 agent 的一份总索引 | `/api/dna/report` —— 可复制的 Markdown 总索引 |
| 显式拒答 + 覆盖率意识 | 体检项 `checks`：明确指出「哪些喂不进去、为什么」 |
| 摄入成本量化 | 成本体检：每篇文档的正文/块/向量字节与占库比例 |

---

## 二、接口契约（前端只依赖这几个）

所有接口都挂在 `/api/dna` 下，返回 JSON（`report` 除外）。

### 1. `GET /api/dna/overview`

```jsonc
{
  "generated_at": "2026-11-01T11:00:00",
  "totals": {
    "documents": 6, "notes": 2, "chunks": 44, "words": 12983,
    "vector_rows": 44, "embedded": 44, "links": 3, "db_bytes": 7467008,
    "vector_bytes": 6291456
  },
  "engine": {
    "embed_model": "embo-01", "embed_dim": 1536, "vec_metric": "cosine",
    "chunk_size": 850, "chunk_overlap": 100,
    "fts_available": true, "vec_available": true
  },
  "composition": {
    "by_kind":  [{"key": "doc", "label": "文档", "count": 4}],
    "by_ext":   [{"key": ".pdf", "count": 1}],
    "by_tag":   [{"key": "handbook", "count": 1}],
    "by_source":[{"key": "upload", "count": 4}],
    "by_month": [{"month": "2026-09", "count": 2}]
  },
  "fingerprint": [
    {"term": "投标截止", "weight": 18.4, "docs": 1},
    {"term": "vault", "weight": 12.1, "docs": 1}
  ],
  "checks": [
    {
      "key": "not_embedded",
      "level": "warn",              // ok | warn | error
      "title": "2 篇文档还没向量化",
      "detail": "文档 #3 处于 pending 状态，语义检索会漏掉它",
      "hint": "在文档列表点「重建索引」，或跑 scripts/reindex_all.py",
      "action": "reindex",          // 可选：前端可挂「重建索引」按钮
      "count": 2
    }
  ],
  "score": 92                      // 0~100 健康分，error 扣得狠
}
```

### 2. `GET /api/dna/documents`

```jsonc
{"items": [{
  "id": 2, "title": "军队采购网.pdf", "kind": "doc", "ext": ".pdf",
  "tags": [], "summary": "这是一份……",
  "words": 2355, "chars": 2355, "chunks": 4, "embedded": 4,
  "embed_status": "ok", "extract_status": "ok", "has_text": true,
  "sha256": "7ca2eb…", "source": "upload", "storage": "fs",
  "created_at": "2026-09-24T16:30:00", "updated_at": "…",
  "headings": 3, "links": 0
}]}
```

### 3. `GET /api/dna/documents/{id}`

```jsonc
{
  "document": { /* 同上单篇，外加 extracted_chars */ },
  "outline": [                    // 结构树：OpenKB PageIndex 的等价物
    {"level": 1, "title": "V-MAX Agent 协同记录手册", "path": "…",
     "children": [{"level": 2, "title": "0. 关键路径速查", "children": []}]}
  ],
  "chunks": [
    {"id": 75, "seq": 0, "chars": 820, "embedded": true,
     "heading": "## 10. 变更日志", "preview": "…前 120 字…"}
  ],
  "terms":  [{"term": "vault", "count": 12, "docs": 1}],
  "links":  [{"id": 3, "title": "…", "rel": "related"}],
  "issues": [{"level": "warn", "title": "…", "detail": "…"}]
}
```

### 4. `GET /api/dna/tree`

```jsonc
{"items": [{"id": 3, "title": "…", "words": 14224, "outline": [ /* 同 outline */ ]}]}
```

### 5. `GET /api/dna/report`

返回 `text/markdown; charset=utf-8`（文件名 `养料-DNA.md`）。
内容 = 全库总索引：体检结论 + 成分表 + 每篇文档的标题树 + 主题词。

### 6. `GET /api/dna/report.json`

返回完整 JSON 报告（overview + documents + tree）。

---

## 三、后端实现要点

- 新增 `backend/app/services/dna.py`（纯计算，不写库）
- 新增 `backend/app/routers/dna.py`（只读路由，统一挂 `current_principal` 依赖）
- `backend/app/routers/__init__.py` 里注册路由
- `backend/app/services/permissions.py` 的 `PAGES` 加 `"dna"`，
  `PAGE_LABELS` 加 `"dna": "养料 DNA"`；`editor_perms()` 也要给上（只读页面）
- **不许新增 Python 依赖**（离线/预编译 wheel 约束）
- 中文分词：没有 jieba，用「汉字 2-gram + 拉丁词整词」，再按 IDF 加权
  （照抄 `docindex.keyword_terms` 的思路，但只在这里用，别去动检索链路）
- 结构树：从 `document.extracted_text` 抽 Markdown 标题层级
  （`#`~`######`）；PDF 没有标题就退化成「正文」单节点
- 体检项至少覆盖：抽取失败、无正文、未向量化/向量化失败、
  维度与 `sys_meta.embed_dim` 不一致、度量不是 cosine、
  sha256 重复（同一份文件传了两次）、空块、孤儿块、FTS/vec 不可用
- 健康分：满分 100，每个 error 扣 8、warn 扣 3，下限 0
- 所有 SQL 走 SQLAlchemy async，**不要**拼裸字符串 SQL
- 日志用 `logging`，中文注释说明「为什么」，别写「做了什么」

---

## 四、前端实现要点

- 新增 `frontend/src/views/DnaView.vue`
- 路由：`{ path: 'dna', name: 'dna', component: () => import('../views/DnaView.vue'), meta: { title: '养料 DNA', perm: 'dna' } }`
- 左侧导航：在 `frontend/src/components/Layout.vue` 的 `navItems` 里
  **「发现」组**加一项 `{ path: '/dna', label: '养料 DNA', icon: 'DataAnalysis'... }`
  （图标名用 Element Plus 包里真实存在的，别写错）
- `frontend/src/api/index.js` 的 `Api` 对象里加：
  `dnaOverview / dnaDocuments / dnaDocument(id) / dnaTree / dnaReportUrl / dnaReportJson`
- 页面结构（自上而下）：
  1. `PageTitle`（title="养料 DNA"，subtitle 说明这是什么），
     右侧动作：**导出 Markdown**、**下载 JSON**、**刷新**
  2. 统计卡行：文档数 / 块数 / 字数 / 向量覆盖 / 健康分
  3. **体检清单**（最重要，放前面）：红黄绿列表，每条给标题 + 详情 + 提示；
     带 `action == "reindex"` 的条目挂「重建索引」按钮（调 POST /api/documents/{id}/reindex）
  4. **主题指纹**：词条 + 权重条形（纯 div 即可，别为这个引图表库）
  5. **成分分布**：按类型/标签/月份（纯 div 列表或 element-plus 表格）
  6. **文档谱系**：表格（标题 / 类型 / 字数 / 块数 / 嵌入状态 / 摘要），
     点行展开单篇 DNA：结构树（缩进列表）+ 块清单 + 主题词
- 样式：复用 `views/pages.css` 的 `.pcard / .pgrid / .ptag / .ptable`，
  颜色一律用 CSS 变量（`--primary`、`--bg-card`、`--border`、`--text-secondary`…），
  **不要写死十六进制颜色**，深浅主题都要成立
- 空态、加载态、错误态都要有；接口 401 时走全局拦截器（api/index.js 已处理）
- 页面不能有任何写操作，唯一的例外是体检项里的「重建索引」按钮

---

## 五、验收

- `GET /api/dna/overview` 等 6 个接口在真实库上返回 200 且字段齐全
- 前端 `npm run build` 通过；页面上能看到体检清单与文档谱系
- 不引入新依赖；不改动检索链路（`docindex.py` / `document.py` 的检索逻辑不许动）

---

## 六、实现说明（后端已交付，前端按第二节实现即可）

> 本节是**交付备注**，不是新契约。第二节的字段与路径一个字没改，
> 这里只解释「后端实际是怎么算的」，免得两边对同一个数字理解不一致。

### 6.1 交付物

| 文件 | 作用 |
|---|---|
| `backend/app/services/dna.py` | 纯计算服务（只读，不写库） |
| `backend/app/routers/dna.py` | 6 个只读接口 |
| `backend/app/routers/__init__.py` | 显式导出 dna 模块 |
| `backend/app/main.py` | **实际注册点**：把 `dna` 加进 `PROTECTED` 列表 |
| `backend/app/services/permissions.py` | `PAGES` / `PAGE_LABELS` 加 `dna`，编辑与只读角色随 `PAGES` 一起拿到 |
| `docs/dna-spec.md` | 本节 |

路由注册的实际位置是 `main.py` 的 `PROTECTED` 列表 ——
本仓库的 `routers/__init__.py` 原本是空的（只放模块，不做注册），
`main.py` 里统一 `include_router(..., dependencies=[Depends(current_principal)])`。

### 6.2 数字口径（第二节示例里的数字是示意，实测以真实库为准）

| 字段 | 实际口径 |
|---|---|
| `totals.words` | **去空白后的字符数**（中文按字计），只统计文件正文，不含笔记 |
| `totals.chars`（单篇） | `extracted_text` 的原始字符数（不含去空白处理） |
| `totals.notes` | 知识库笔记（`note` 模型）未删除的条数；读不到 note 模型的人显示 0 |
| `totals.chunks` | 存活且**当前用户可读**的文件所拥有的块数 |
| `totals.embedded` | 上述文件中 `embedded=1` 的块数 |
| `totals.links` | 文件 ↔ 记录的关联条数（`document_link` + 以文件为一端的关系行） |
| `totals.vector_rows` | `document_vec` 里的行数 |
| `totals.db_bytes` | `page_count × page_size` |
| `totals.vector_bytes` | `dbstat` 里 `document_vec*` 一族表占用字节之和（取不到时按 行数×维度×4 估算） |
| `engine.chunk_size/overlap` | 取**运行期配置**（当前是 800 / 120），不是第二节示例里的 850 / 100 |
| `fingerprint[].weight` | `Σ_文档 (1+log(词频)) × BM25 式 idf`，保留一位小数 |
| `fingerprint[].docs` | 出现在几篇文件里 |
| 主题词本身 | **汉字 2-gram + 拉丁整词**（没有 jieba），所以会出现「标截」这种看起来不通顺的片段 —— 这是预期行为，前端照原样显示即可 |
| `score` | 100 − 8×error − 3×warn，下限 0 |

### 6.3 体检项（`checks`）

只有**有问题的**条目才会出现；全部正常时返回一条 `level:"ok"` 的 `healthy` 条目
（前端要有绿色可画）。每条固定带 `key / level / title / detail / hint / count`，
可能再带 `action:"reindex"`（前端挂「重建索引」按钮）与 `doc_ids`（涉及的文档 id 数组，
方便前端把按钮挂到具体文件上）。

| key | level | 触发条件 |
|---|---|---|
| `extract_failed` | error | `extract_status='failed'` |
| `extract_pending` | warn | `extract_status='pending'` |
| `no_chunk` | warn | 有正文但一块都没切出来 |
| `no_text` | error | 文档类文件抽取完成却没有正文 |
| `media_no_text` | warn | 图片/音视频没有正文（不算错，但语义检索覆盖不到） |
| `not_embedded` | warn | 有正文但 `embed_status` 是 pending/partial/skipped |
| `embed_failed` | error | `embed_status='failed'` |
| `dim_mismatch` | error | `document.embed_dim` ≠ `sys_meta.embed_dim` |
| `dim_missing` | warn | 有向量但 `sys_meta` 里没记维度 |
| `vec_metric` | error | `sys_meta.vec_metric` 不是 cosine |
| `duplicate_sha` | warn | 同一 sha256 出现在多个文件里 |
| `empty_chunk` | warn | 有空块 |
| `orphan_chunk` | error | 块的 `document_id` 在 `document` 表里不存在 |
| `deleted_doc_chunk` | warn | 块属于已软删除的文件（检索时被过滤掉，白占空间） |
| `fts_unavailable` | error | FTS5 表不存在或索引损坏 |
| `fts_lag` | warn | 有文件没进 FTS |
| `vec_unavailable` | error | sqlite-vec 没加载 / 向量表不存在（且库里有该被向量的正文） |
| `vector_lag` | warn | 已嵌入块数 ≠ 向量行数 |
| `vector_orphan` | warn | 向量表里有找不到对应块的残留向量 |

另外 `overview` 多返回一个 `checks_summary`（`{ok, warn, error}` 计数），前端画概览可用。

### 6.4 `report.json` 的结构

```jsonc
{
  "generated_at": "2026-11-01T11:00:00",
  "overview": { /* 与 GET /api/dna/overview 完全一致 */ },
  "documents": {"items": [ /* 与 GET /api/dna/documents 一致 */ ]},
  "tree":      {"items": [ /* 与 GET /api/dna/tree 一致 */ ]}
}
```

`GET /api/dna/report` 返回 `text/markdown; charset=utf-8`，
`Content-Disposition` 用 RFC 5987 编码的 `filename*=UTF-8''养料-DNA.md`。

### 6.5 鉴权口径（前端要知道）

- 6 个接口统一挂 `current_principal`，**不**硬拦 `dna` 页面权限。
  原因：`permissions.PAGES` 加 `dna` 只对**新建**的内置角色生效，
  `bootstrap.ensure_builtin_roles` 不覆盖库里已存好的 perms JSON，
  线上库的编辑/只读角色并没有 `dna` 这个页面位 —— 一旦硬拦，页面直接 403 且升级不自愈。
- 内容边界靠 `services/access.py` 的统一规则兜：**文件能不能读按现有规则判**，
  读不到的文件不会出现在 DNA 的任何结果里。
- 页面权限位 `dna` 已加进 `PAGES`/`PAGE_LABELS`，新建角色时可分配；
  已有角色需要管理员在「系统管理 → 角色」里勾上（菜单过滤据此）。

### 6.6 性能与已知限制

- 主题指纹与结构树要读**全部文件的正文**，资料量大时这几个接口会变慢；
  当前实现一次性读完，没有做缓存。
- 结构树按 Markdown 标题解析，**代码块里的 `#` 不算标题**，
  开头的 YAML front-matter 会被剥掉；标题层级跳跃（h1 直接到 h3）按栈处理，不会崩。
- PDF 抽不出标题时退化成单节点「正文」。

