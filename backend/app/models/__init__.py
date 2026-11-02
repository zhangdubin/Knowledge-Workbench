from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Boolean,
    Float,
    ForeignKey,
    JSON,
    LargeBinary,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..database import Base


# ============ 元数据：实体类型（表） ============
class EntityType(Base):
    __tablename__ = "entity_type"

    id = Column(Integer, primary_key=True)
    key = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=False)
    icon = Column(String(32), default="📦")
    description = Column(Text, default="")
    app = Column(String(32), default="default")  # 所属应用分组
    order = Column(Integer, default=0)
    deleted_at = Column(DateTime, index=True)     # 软删除：进回收站
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    fields = relationship(
        "FieldDefinition", back_populates="entity_type",
        cascade="all, delete-orphan", order_by="FieldDefinition.order"
    )
    records = relationship(
        "EntityRecord", back_populates="entity_type",
        cascade="all, delete-orphan"
    )
    views = relationship(
        "View", back_populates="entity_type",
        cascade="all, delete-orphan", order_by="View.order"
    )


# ============ 元数据：字段定义 ============
class FieldDefinition(Base):
    __tablename__ = "field_definition"

    id = Column(Integer, primary_key=True)
    entity_type_id = Column(
        Integer, ForeignKey("entity_type.id", ondelete="CASCADE"), nullable=False
    )
    key = Column(String(64), nullable=False)
    name = Column(String(128), nullable=False)
    type = Column(String(32), nullable=False)  # text/textarea/richtext/number/date/datetime/select/multiselect/boolean/file/image/reference
    required = Column(Boolean, default=False)
    options = Column(JSON, default=dict)  # 选项：select选项、reference目标实体等
    order = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())

    entity_type = relationship("EntityType", back_populates="fields")

    __table_args__ = (
        Index("ix_field_entity_key", "entity_type_id", "key", unique=True),
    )


# ============ 数据：实体记录 ============
class EntityRecord(Base):
    __tablename__ = "entity_record"

    id = Column(Integer, primary_key=True)
    entity_type_id = Column(
        Integer, ForeignKey("entity_type.id", ondelete="CASCADE"), nullable=False, index=True
    )
    data = Column(JSON, default=dict)  # 字段值
    search_text = Column(Text, default="")  # 全文检索文本
    deleted_at = Column(DateTime, index=True)         # 软删除：进回收站
    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), index=True)

    entity_type = relationship("EntityType", back_populates="records")
    attachments = relationship(
        "Attachment", back_populates="record",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_record_search", "search_text"),
    )


# ============ 元数据：关系定义 ============
class RelationDef(Base):
    """关系定义：两端各自可以是「业务模型的记录」或「数据中心文件」

    为什么要 source_kind/target_kind 而不是再加一张表：
    关系是「A 指向 B」的二元结构，两端只有两种可能的主体。
    用 kind 区分 + type_id 只在 record 端必填，比拆成
    「记录关系表 / 文件关系表」少一半代码，图谱也只需要一套遍历。
    """
    __tablename__ = "relation_def"

    id = Column(Integer, primary_key=True)
    key = Column(String(64), unique=True, nullable=False)
    name = Column(String(128), nullable=False)
    source_kind = Column(String(16), default="record")   # record | document
    source_type_id = Column(
        Integer, ForeignKey("entity_type.id", ondelete="CASCADE"), nullable=True
    )
    target_kind = Column(String(16), default="record")
    target_type_id = Column(
        Integer, ForeignKey("entity_type.id", ondelete="CASCADE"), nullable=True
    )
    cardinality = Column(String(16), default="many-to-many")  # one-to-many / many-to-many
    description = Column(String(256), default="")
    created_at = Column(DateTime, server_default=func.now())


# ============ 数据：关系记录 ============
class RelationRecord(Base):
    """关系实例：两端按 kind 填 record_id 或 document_id，各自可空"""
    __tablename__ = "relation_record"

    id = Column(Integer, primary_key=True)
    relation_def_id = Column(
        Integer, ForeignKey("relation_def.id", ondelete="CASCADE"), nullable=False
    )
    source_record_id = Column(
        Integer, ForeignKey("entity_record.id", ondelete="CASCADE"), nullable=True, index=True
    )
    target_record_id = Column(
        Integer, ForeignKey("entity_record.id", ondelete="CASCADE"), nullable=True, index=True
    )
    source_document_id = Column(
        Integer, ForeignKey("document.id", ondelete="CASCADE"), nullable=True
    )
    target_document_id = Column(
        Integer, ForeignKey("document.id", ondelete="CASCADE"), nullable=True
    )
    data = Column(JSON, default=dict)  # 关系属性（如：角色、数量）
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_relrec_src_doc", "source_document_id"),
        Index("ix_relrec_tgt_doc", "target_document_id"),
    )


# ============ 数据：附件（v0.1 遗留，仅用于存量迁移） ============
class Attachment(Base):
    """v0.1 的附件表：文件落磁盘，这里只存路径元数据。

    v0.2 起文件一律进 Document（数据库 BLOB），本表保留只为让
    旧数据还能被读到并迁移，新代码不再写入。
    """
    __tablename__ = "attachment"

    id = Column(Integer, primary_key=True)
    record_id = Column(
        Integer, ForeignKey("entity_record.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field_key = Column(String(64), nullable=False)
    filename = Column(String(256), nullable=False)
    stored_name = Column(String(256), nullable=False)
    size = Column(Integer, default=0)
    content_type = Column(String(128), default="")
    created_at = Column(DateTime, server_default=func.now())

    record = relationship("EntityRecord", back_populates="attachments")


# ============ 数据：文档（文件原文外置，一等公民） ============
class Document(Base):
    """文件主表 —— 元数据 + 抽取文本 + 原文位置

    原文归属（storage / path 两列）：
      - storage='fs' + path=<相对路径>：原文在文件系统（v0.3 起的默认）
      - storage='db' + data=<BLOB>：原文还在库里（v0.2 的历史数据，
        迁移完成后这一档会归零）

    为什么要显式两列而不是「path 非空即外置」：迁移是分批进行的，
    过程中两种来源必然共存；而且回退时只要把 file_store 改成 db，
    新文件就继续进库，读取路径必须同时容忍两种形态。

    为什么 path 不直接用 sha256 推算：写在列里才能让「文件被误删」
    这类故障可被检测（path 有值但盘上没文件 = 明确的损坏信号，
    而推算路径时这个信息会被无声地吞掉）。
    """
    __tablename__ = "document"

    id = Column(Integer, primary_key=True)
    title = Column(String(512), default="")          # 展示标题（可改）
    filename = Column(String(512), nullable=False)    # 原始文件名
    ext = Column(String(32), default="", index=True)
    mime = Column(String(128), default="")
    size = Column(Integer, default=0)
    sha256 = Column(String(64), default="", index=True)

    # 原文所在：fs → path；db → data
    storage = Column(String(8), default="db", index=True)
    path = Column(String(256), default="")
    data = Column(LargeBinary)                        # 仅 storage='db' 时使用

    kind = Column(String(32), default="other", index=True)  # doc/image/video/audio/other

    tags = Column(JSON, default=list)
    summary = Column(Text, default="")
    description = Column(Text, default="")
    source = Column(String(32), default="upload")     # upload / migrated / note
    app = Column(String(32), default="default")

    # 正文抽取（供全文检索与 AI 使用）
    extracted_text = Column(Text, default="")
    extract_status = Column(String(16), default="pending")  # pending/ok/failed/skipped
    extract_error = Column(String(512), default="")
    extract_kind = Column(String(32), default="")           # docx/xlsx/pptx/text/csv

    # 向量索引状态
    embed_status = Column(String(16), default="pending")    # pending/ok/failed/partial/skipped
    embed_error = Column(String(512), default="")
    embed_dim = Column(Integer, default=0)
    indexed_at = Column(DateTime)

    deleted_at = Column(DateTime, index=True)         # 软删除
    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    links = relationship(
        "DocumentLink", back_populates="document",
        cascade="all, delete-orphan"
    )
    chunks = relationship(
        "DocumentChunk", back_populates="document",
        cascade="all, delete-orphan"
    )


# ============ 知识库：自定义分组 ============
class NoteGroup(Base):
    """笔记分组（知识库左侧的分组栏）

    笔记本体不在这张表里 —— 笔记是「笔记」模型（entity_type key='note'）的
    entity_record，分组归属存在那条记录的 data JSON 里（data.group_id），
    和「父笔记」的 data.parent 是同一套路子：字段由模型自己定义，
    记录里多带一个键，不需要为它单独加一列。

    为什么分组要单独一张表，而不是拿记录的某个字段来分：
    分组是**实体**，有稳定 id、能改名、能换颜色、能排序、能统计条数，
    界面上要有确定的契约；而记录里的字段是模型自己定义的，
    「分组」这种东西对别的模型不一定存在。

    name 上的 unique 只是数据库层的兜底：真正的判重在应用层做
    （strip + casefold），因为 SQLite 的 UNIQUE 是大小写敏感的，
    光靠它拦不住「Work」与「work」并存。
    """
    __tablename__ = "note_group"

    id = Column(Integer, primary_key=True)
    name = Column(String(40), nullable=False, unique=True)
    color = Column(String(16), default="")      # 颜色值（如 #4f46e5），前端画色块用
    description = Column(Text, default="")
    sort_order = Column(Integer, default=0)     # 越小越靠前
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ============ 自定义导航项 ============
class NavItem(Base):
    """左侧导航的自定义项

    内置导航（工作台 / 知识库 / 应用中心…）是写死在前端的，
    但每个部署要的东西不一样：有人要把自己的一堆文档入口挂在侧栏，
    有人要把某个应用顶到最前面。

    所以另开一张表存**用户自己加的**导航项，内置项仍然由前端提供 ——
    两边在前端合并（自定义项插在最后，或按 order 排）。

    为什么不做「内置项也能改」：
    内置项的 perm 是权限判定的一部分，删了会让某些页面没人能进，
    还得再存一份权限配置 —— 复杂度暴涨。给一个「自定义项」已经够用了。

    path 是站内路径（如 /apps/customer），必须是相对路径且不以 // 开头，
    免得被塞进外站地址。
    """
    __tablename__ = "nav_item"

    id = Column(Integer, primary_key=True)
    label = Column(String(64), nullable=False)
    path = Column(String(256), nullable=False)
    icon = Column(String(32), default="")        # Element Plus 图标名（如 Grid）
    group_name = Column(String(32), default="自定义")   # 挂在哪个分组下
    description = Column(String(256), default="")
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class DocumentLink(Base):
    """文档 ↔ 业务记录 的关联

    为什么要单独一张表：v0.1 的 Attachment 强制绑定 record_id，
    导致「数据中心上传文件」必须先伪造一条笔记当容器。这里把
    record_id 变成可空，文件就能独立存在，也能挂到任意记录的
    file/image 字段上，还能一个文件关联多条记录。
    """
    __tablename__ = "document_link"

    id = Column(Integer, primary_key=True)
    document_id = Column(
        Integer, ForeignKey("document.id", ondelete="CASCADE"), nullable=False, index=True
    )
    record_id = Column(
        Integer, ForeignKey("entity_record.id", ondelete="CASCADE"), nullable=True, index=True
    )
    field_key = Column(String(64), nullable=True)     # 挂在哪个字段上；NULL 表示独立文件
    note = Column(String(256), default="")
    created_at = Column(DateTime, server_default=func.now())

    document = relationship("Document", back_populates="links")

    __table_args__ = (
        UniqueConstraint("document_id", "record_id", "field_key", name="uq_doc_link"),
    )


class DocumentChunk(Base):
    """文档分块 —— 向量检索的最小单位

    正文按 chunk_size 切片，每片一行；对应的向量存在 document_vec
    虚拟表里，rowid 与这里的 id 一一对应。

    独立成表而不是直接把向量塞进 Document，是为了以后换 embedding
    模型时只需重建 document_vec，正文分块不必重算。
    """
    __tablename__ = "document_chunk"

    id = Column(Integer, primary_key=True)
    document_id = Column(
        Integer, ForeignKey("document.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq = Column(Integer, default=0)
    text = Column(Text, default="")
    char_len = Column(Integer, default=0)
    embedded = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())

    document = relationship("Document", back_populates="chunks")

    __table_args__ = (
        Index("ix_chunk_doc_seq", "document_id", "seq"),
    )


# ============ DNA 养料库：基因 ============
class DnaGene(Base):
    """一条基因 —— 养料库里最小的可复用知识单元

    「养料」（喂给模型的资料）到了 DNA 模块这一层会被拆成两类东西：
      结构层：文档、章节、块 —— 东西**长什么样**
      基因层：事实、方法、经验、接口、约定 —— 东西**能做什么**

    为什么要多这一层：文档是给机器读的原料，人和模型真正需要复用的是
    「怎么做」「踩过什么坑」「这个接口长什么样」。把这些抽成独立的基因，
    才能跨文档复用、能单独检索、能在离线时直答、能统计哪些知识真被用过。

    源码的吸收走的是同一条路：蒸馏出的方法与经验进这里，
    **原文不留**（meta.destroyed 里留销毁证明：指纹、时间、文件名）。
    留证据不留原文，是「吸收后销毁」这个要求能落地的唯一办法。

    uid 是跨库稳定的身份（内容指纹派生），打包到别的机器再导回来，
    靠它认出「这条基因那边已经有了」，不会变成两条。
    """
    __tablename__ = "dna_gene"

    id = Column(Integer, primary_key=True)
    uid = Column(String(64), nullable=False, unique=True, index=True)
    kind = Column(String(16), nullable=False, index=True)     # fact/method/experience/interface/policy
    title = Column(String(256), default="")
    content = Column(Text, default="")
    summary = Column(String(512), default="")
    tags = Column(JSON, default=list)
    # 来源：基因是从哪来的。code 表示来自源码（原文已销毁）
    source_kind = Column(String(24), default="", index=True)  # document/record/note/code/manual/derived
    source_ref = Column(String(64), default="", index=True)   # doc-3 / record-14 / code:<sha256>
    source_title = Column(String(256), default="")
    fingerprint = Column(String(64), default="", index=True)   # 内容指纹，去重与变更检测用
    # 置信度：镜像自 dna_gene_score.confidence（权威值与分项在评分表里）。
    # 这里留一列是为了让已有的排序/筛选代码不用改。
    confidence = Column(Float, default=0.7)
    # active 在用 / superseded 被更新的版本取代 / archived 归档 / destroyed 原文已销毁（基因本身还在）
    status = Column(String(16), default="active", index=True)
    superseded_by = Column(Integer, nullable=True)
    # 表达度：镜像自 dna_gene_score.expressiveness（权威值与分项在评分表里）
    expressiveness = Column(Float, default=0.0)
    # 评分模型版本：评分口径变了就 +1，回填脚本按它决定谁要重算
    score_version = Column(Integer, default=0)
    # usage_count：这条基因被检索/引用过多少次。
    # 注意它只是「被用过」的计数，不是表达度本身 ——
    # 表达度是「说清楚了没有」，由具体度/可执行性/可检索性/被复用度四个分项合成。
    usage_count = Column(Integer, default=0)
    last_used_at = Column(DateTime, nullable=True)
    meta = Column(JSON, default=dict)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_gene_kind_status", "kind", "status"),
    )


# ============ DNA 养料库：基因评分 ============
class DnaGeneScore(Base):
    """一条基因的评分明细 —— 分数 + 分项 + 依据

    为什么要单独一张表，而不是在 dna_gene 上加几列：
      - 分项是**结构化**的（四个维度各自有权重与依据），
        塞进 meta JSON 会让「按表达度排序」「筛低置信」这类查询
        只能全表扫；独立成表才能建索引。
      - 计数（复用成功/失败、人工纠正）属于**这条基因的履历**，
        与基因内容是两份数据：内容变了可以重算，履历不能重算。
      - 老基因（v8 之前入库的）也要有评分；补列做不到「一行一人」，
        新表可以。

    dna_gene.confidence / dna_gene.expressiveness 是这两个值的**镜像**，
    为了让已有的排序、筛选代码不用改。权威值以本表为准。
    """
    __tablename__ = "dna_gene_score"

    id = Column(Integer, primary_key=True)
    gene_id = Column(
        Integer, ForeignKey("dna_gene.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True)
    # 表达度总分 0..1：「这条基因说清楚了没有」
    expressiveness = Column(Float, default=0.0)
    # 置信度总分 0..1：「这条基因有多可信」
    confidence = Column(Float, default=0.0)
    # 分项：{分项 key: {label, score, weight, detail}}
    express_parts = Column(JSON, default=dict)
    confidence_parts = Column(JSON, default=dict)
    # 依据：完整的评分快照（分项 + 扣分项 + 版本）
    evidence = Column(JSON, default=dict)
    # 履历计数（不可重算，只增不减）
    use_success = Column(Integer, default=0)     # 复用成功次数
    use_fail = Column(Integer, default=0)       # 复用失败次数
    corrections = Column(Integer, default=0)     # 人工纠正次数（负反馈，扣分）
    corroborations = Column(Integer, default=0)  # 交叉印证次数
    distinct_sources = Column(Integer, default=1)  # 说过同一件事的来源数
    # 抽取时的启发式置信度（旧版那条裸 confidence）：
    # 保留下来当独立信号参与「来源权威度」计算，不能被新分数顶掉
    extraction_confidence = Column(Float, default=0.7)
    version = Column(Integer, default=0)         # 评分模型版本
    last_scored_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_gene_score_conf", "confidence"),
        Index("ix_gene_score_expr", "expressiveness"),
    )


# ============ DNA 养料库：可复用产出（资产） ============
class DnaAsset(Base):
    """从高分基因里落出来的**可复用产出**

    「学以致用」如果只停在「检索命中」，那还是知识，不是产出。
    这一层把基因里的可执行部分抽出来，落成能直接用的东西：
      code_snippet   可复制的代码片段
      api_contract   接口契约（端点/字段/参数）
      checklist      操作步骤（照着做的那几步）
      note           结构化要点

    为什么资产要跟基因分开存：
      - 基因是「知道什么」，资产是「能直接拿走用什么」；
      - 资产有**自己的**履历：被哪个项目用过、用了几次、成没成功；
      - 基因被用会加分，但「用」这件事的主体是资产 ——
        反馈要能精确落到「哪条知识、哪个项目、结果如何」。
    """
    __tablename__ = "dna_asset"

    id = Column(Integer, primary_key=True)
    uid = Column(String(64), nullable=False, unique=True, index=True)
    # code_snippet / api_contract / checklist / note
    kind = Column(String(24), default="note", index=True)
    title = Column(String(256), default="")
    content = Column(Text, default="")
    language = Column(String(32), default="")
    # 产出自哪条基因（可以为空：手工建的资产）
    gene_id = Column(
        Integer, ForeignKey("dna_gene.id", ondelete="SET NULL"),
        nullable=True, index=True)
    source_kind = Column(String(24), default="")
    source_title = Column(String(256), default="")
    # 被复用的次数与结果（成功/失败）—— 反馈置信度的原料
    use_count = Column(Integer, default=0)
    use_success = Column(Integer, default=0)
    use_fail = Column(Integer, default=0)
    # 最近一次被用在哪个项目/任务
    last_project = Column(String(128), default="")
    last_used_at = Column(DateTime, nullable=True)
    meta = Column(JSON, default=dict)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_asset_kind_gene", "kind", "gene_id"),
    )


class DnaAssetUse(Base):
    """资产被使用的一次事件 —— 闭环的证据链

    这一行就是「学 → 用 → 更准」中间那个「用」的原始记录：
      哪条基因 → 哪个资产 → 哪个项目/任务 → 成没成功 → 谁用的 → 什么时候

    为什么单独记事件而不是只累加计数：
      计数只能回答「用过几次」，回答不了「在哪儿用的、结果如何」。
      而置信度里的「复用成功率」需要的是**结果**，
      没有事件表就只能靠猜。
    """
    __tablename__ = "dna_asset_use"

    id = Column(Integer, primary_key=True)
    asset_id = Column(
        Integer, ForeignKey("dna_asset.id", ondelete="CASCADE"),
        nullable=False, index=True)
    gene_id = Column(
        Integer, ForeignKey("dna_gene.id", ondelete="SET NULL"),
        nullable=True, index=True)
    project = Column(String(128), default="", index=True)  # 用在哪个项目
    task = Column(String(256), default="")                # 哪个任务
    # success / fail / unknown
    outcome = Column(String(16), default="unknown", index=True)
    note = Column(Text, default="")
    actor = Column(String(64), default="")                # 谁用的（审计用）
    used_at = Column(DateTime, server_default=func.now(), index=True)
    created_at = Column(DateTime, server_default=func.now())


# ============ DNA 养料库：外部开源项目 ============
class DnaOpenkbSource(Base):
    """一次外部开源项目吸收的来源档案

    「参考 openkb 这类开源项目」要能落地，先得说清楚三件事：
      1. 这个仓库是谁、什么许可证 —— 能不能商用、要不要开源传染
      2. 我们吸收了它的哪些部分（哪些文件、哪些接口）
      3. 什么时候吸收的、吸收出多少知识

    许可证信息放在这里而不是塞进基因的 meta，是因为**合规提示是整体性的**：
    一个仓库的许可证对它所有基因是一样的，逐条复制一遍没有意义，
    反而容易在基因被单独导出时丢掉。
    """
    __tablename__ = "dna_openkb_source"

    id = Column(Integer, primary_key=True)
    # owner/repo 或本地镜像目录名
    repo = Column(String(256), nullable=False, index=True)
    url = Column(String(512), default="")
    # 许可证标识（MIT / Apache-2.0 / GPL-3.0 …）
    license = Column(String(64), default="", index=True)
    # 是否属于传染性许可证（GPL/AGPL/SSPL…）—— 界面要给出合规提示
    copyleft = Column(Boolean, default=False)
    star_count = Column(Integer, default=0)
    default_branch = Column(String(64), default="")
    commit = Column(String(64), default="")
    # 本地镜像路径（离线导入时记录，方便复现）
    local_path = Column(String(512), default="")
    # pending / running / done / failed
    status = Column(String(16), default="pending", index=True)
    genes = Column(Integer, default=0)        # 吸收出多少基因
    assets = Column(Integer, default=0)       # 落成多少资产
    files = Column(Integer, default=0)        # 读了多少文件
    error = Column(Text, default="")
    # 合规提示文案（导入时算好，界面直接显示）
    notice = Column(Text, default="")
    meta = Column(JSON, default=dict)
    principal = Column(String(64), default="")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ============ DNA 养料库：后台任务 ============
class DnaJob(Base):
    """一个后台吸收任务的进度条

    为什么要有这张表：吸收一棵源码树是分钟级的事，
    放在 HTTP 请求里做会超时；做成「提交完就返回、进度另查」，
    页面才能一边跑一边显示「现在在解析哪个文件」。

    进度写回库里而不是只放内存：
    内存里的进度一重启就没了，用户看到的进度条会永远卡在 0%。
    """
    __tablename__ = "dna_job"

    id = Column(Integer, primary_key=True)
    job_type = Column(String(24), default="source_tree", index=True)
    title = Column(String(256), default="")
    # pending 排队 / running 进行中 / done 完成 / failed 失败 / canceled 已取消
    status = Column(String(16), default="pending", index=True)
    total = Column(Integer, default=0)          # 总文件数
    processed = Column(Integer, default=0)      # 已处理
    current = Column(String(512), default="")   # 正在处理的文件
    created = Column(Integer, default=0)        # 新建基因
    updated = Column(Integer, default=0)        # 更新基因
    skipped = Column(Integer, default=0)        # 跳过（无价值/重复）
    failed = Column(Integer, default=0)         # 失败
    bytes_read = Column(Integer, default=0)     # 读了多少字节
    error = Column(Text, default="")
    detail = Column(JSON, default=dict)         # 明细（每个文件一行，最多留 200 条）
    principal = Column(String(64), default="")  # 发起人（审计用）
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_dna_job_status_created", "status", "created_at"),
    )


# ============ DNA 养料库：知识缺口 ============
class DnaGap(Base):
    """系统答不上来的问题 —— 下一轮该喂什么

    「不断喂养、不断自主进化」要能闭环，光有吸收不够：
    得知道**缺什么**。用户问了一个问题，系统答「资料里没有」，
    那这个问题就是一条缺口；等哪天补上了同样的知识，
    缺口自动关闭 —— 一次完整的进化就是这么走完的。

    没有这张表，系统就只知道「自己有什么」，
    不知道「自己缺什么」，喂养就永远靠人拍脑袋。
    """
    __tablename__ = "dna_gap"

    id = Column(Integer, primary_key=True)
    question = Column(String(512), nullable=False, index=True)
    fingerprint = Column(String(64), default="", index=True)   # 同一个问题问多次算一条
    asked = Column(Integer, default=1)          # 被问过几次
    status = Column(String(16), default="open", index=True)   # open / filled
    note = Column(String(256), default="")       # 补上的说明
    filled_by = Column(String(64), default="")   # 补上它的基因编号
    last_asked_at = Column(DateTime, server_default=func.now())
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ============ 系统元信息（向量维度等运行时状态） ============
class SysMeta(Base):
    __tablename__ = "sys_meta"

    key = Column(String(64), primary_key=True)
    value = Column(Text, default="")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())



# ============ 元数据：视图 ============
class View(Base):
    __tablename__ = "view"

    id = Column(Integer, primary_key=True)
    entity_type_id = Column(
        Integer, ForeignKey("entity_type.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(128), nullable=False)
    type = Column(String(32), default="list")  # list / kanban / detail / graph / gallery
    config = Column(JSON, default=dict)
    order = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())

    entity_type = relationship("EntityType", back_populates="views")


# ============ 应用分组（可自定义） ============
class App(Base):
    __tablename__ = "app"

    id = Column(Integer, primary_key=True)
    key = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=False)
    icon = Column(String(32), default="📦")
    description = Column(String(256), default="")
    order = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ============ 自定义驾驶舱 ============
class Dashboard(Base):
    """可视化驾驶舱：一个驾驶舱 = 若干张卡片 + 布局

    卡片配置整体存在 layout(JSON) 里，而不是拆成 Widget 表：
    卡片是纯展示产物、永远跟着驾驶舱一起被读写，拆表只会让
    「保存一次布局」变成 N 次增删改，得不偿失。
    """
    __tablename__ = "dashboard"

    id = Column(Integer, primary_key=True)
    key = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=False)
    description = Column(String(512), default="")
    icon = Column(String(32), default="📊")
    app = Column(String(32), default="default")
    order = Column(Integer, default=0)
    pinned = Column(Boolean, default=False)          # 固定到「工作台」
    # 布局：[{id, type, title, span, source:{...}}]；schema 见 services/dashboard.py
    layout = Column(JSON, default=list)
    # 大屏显示设置：{theme, auto_refresh, show_clock}。放模型列而不是塞进
    # layout —— layout 是纯卡片数组，混进配置会让前端遍历卡片时处处判空
    settings = Column(JSON, default=dict)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ============ 安全：角色 / 用户 / 会话 / 审计 ============
class Role(Base):
    """角色 = 一份权限清单

    perms 结构（JSON）：
      {
        "all": false,                       # 超级管理员，绕过一切检查
        "pages": ["dashboard", "library"],  # 允许访问的页面 key
        "models": {"*": "write"},           # 模型 key → read | write
        "features": {                       # 功能位
          "user_manage": true, "role_manage": true, "audit_view": true,
          "model_manage": true, "file_write": true, "file_delete": true,
          "ai": true, "dashboard_write": true, "relation_manage": true
        }
      }
    用一份 JSON 而不是权限表：权限点是固定的一小撮枚举，
    查表拼装反而更绕，且读一次就能整份缓存。
    """
    __tablename__ = "role"

    id = Column(Integer, primary_key=True)
    key = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(64), nullable=False)
    description = Column(String(256), default="")
    is_builtin = Column(Boolean, default=False)
    perms = Column(JSON, default=dict)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class User(Base):
    __tablename__ = "user"

    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    display_name = Column(String(64), default="")
    password_hash = Column(String(256), nullable=False)
    role_id = Column(Integer, ForeignKey("role.id", ondelete="SET NULL"), nullable=True, index=True)
    is_active = Column(Boolean, default=True)
    # 初始管理员密码是公开的默认值，必须改掉才能继续用
    must_change_password = Column(Boolean, default=False)
    last_login_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class UserSession(Base):
    """服务端会话表（不签 JWT）

    用不透明 token + 服务端表：能即时吊销（改密码/停用账号立刻失效），
    也不用管时钟偏移与密钥轮换。<img>/<iframe> 预览没法带 Authorization
    头，所以会话走 Cookie，前端 axios 只需 withCredentials。
    """
    __tablename__ = "user_session"

    token = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now())
    expires_at = Column(DateTime, nullable=False, index=True)
    last_seen_at = Column(DateTime)
    ip = Column(String(64), default="")
    user_agent = Column(String(256), default="")


class AuditLog(Base):
    """操作审计：只记录写操作与登录事件

    读操作量大且无争议，全记会把日志淹掉；写操作才是「谁改了什么」的来源。
    """
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True)
    username = Column(String(64), default="", index=True)
    action = Column(String(32), default="")        # create/update/delete/login/login_failed/upload...
    resource = Column(String(64), default="", index=True)   # entity_type / record / document / relation ...
    resource_id = Column(String(64), default="")
    method = Column(String(8), default="")
    path = Column(String(256), default="")
    status = Column(Integer, default=0)
    ip = Column(String(64), default="")
    detail = Column(JSON, default=dict)
    created_at = Column(DateTime, server_default=func.now(), index=True)


# ============ 软件开发模块：项目 / 任务 / 产出物 / 会话 / 引用 ============
#
# 这一组表回答的是同一个问题的五个侧面：
#   「这个项目是怎么做出来的，以及它凭什么这么说？」
#   项目  = 目标与方案
#   任务  = 可执行的步骤
#   产出物 = 真的写出来的代码/配置/文档
#   会话  = 每一次生成当时的上下文与回答（可追溯、可复现）
#   引用  = 回答里的每一句话挂在哪几条知识上（可核对）
#
# 为什么「会话」和「引用」必须单独存表，不能塞进会话的一个 JSON 字段：
# 引用要能被单独统计（哪条基因被引用得最多 → 表达度），
# 也要能被单独展示（这句话到底依据了哪几行原文）。
# 塞进 JSON 就只能整坨读出来，统计与展示都做不了。


class DevProject(Base):
    """一个开发项目 —— 从「想法」到「产出」的容器

    mode 决定这个项目走哪条路：
      offline 离线闭环：只用本机喂养的源码知识 + 本地模型，全程不出网
      online  在线协同：AI + GitHub 开源项目 + 网络知识 + 喂养源码一起驱动
    """
    __tablename__ = "dev_project"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False, index=True)
    goal = Column(Text, default="")                 # 目标描述（要解决什么问题）
    tech_stack = Column(JSON, default=list)        # 技术栈：["Python", "FastAPI"]
    tech_notes = Column(Text, default="")           # 技术选型说明（为什么这么选）
    # draft 草稿 / planning 规划中 / building 实现中 / produced 已产出 / archived 归档
    status = Column(String(16), default="draft", index=True)
    # offline 离线闭环 / online 在线协同
    mode = Column(String(16), default="offline", index=True)
    plan = Column(Text, default="")                 # 项目方案正文
    plan_json = Column(JSON, default=dict)          # 方案的结构化部分（架构/风险/任务）
    gene_refs = Column(JSON, default=list)          # 关联的基因 id（养料库条目）
    library_refs = Column(JSON, default=list)       # 关联的文档 id（数据中心条目）
    github_refs = Column(JSON, default=list)        # 关联的 GitHub 仓库（owner/repo/branch）
    feedback_round = Column(Integer, default=0)     # 已经反哺过几轮（闭环计数）
    principal = Column(String(64), default="", index=True)   # 创建者
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class DevTask(Base):
    """项目下的一个可执行任务

    depends_on 存的是任务 id 列表：任务之间有先后依赖，
    没有依赖信息的话「逐任务生成」就不知道该先做哪个。
    """
    __tablename__ = "dev_task"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("dev_project.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    title = Column(String(200), default="")
    description = Column(Text, default="")
    acceptance = Column(Text, default="")           # 验收标准（可判定的条件）
    # todo 待办 / doing 实现中 / done 已完成 / blocked 被阻塞
    status = Column(String(16), default="todo", index=True)
    depends_on = Column(JSON, default=list)         # 依赖的任务 id
    order = Column(Integer, default=0)              # 项目内的排序
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class DevArtifact(Base):
    """产出物：模型生成 / 知识库摘取 / 人工上传的代码、配置与文档

    content 直接存正文而不是只存文件路径：
    产出物要能被检索、被引用、被再次喂回模型，
    存路径意味着「文件被删了这条产出就没了」。
    """
    __tablename__ = "dev_artifact"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("dev_project.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("dev_task.id", ondelete="SET NULL"),
                     nullable=True, index=True)
    filename = Column(String(256), default="")
    path = Column(String(256), default="")          # 项目内的相对路径
    content = Column(Text, default="")
    language = Column(String(32), default="")
    # code 代码 / config 配置 / doc 文档
    artifact_type = Column(String(16), default="code", index=True)
    # model 模型生成 / knowledge 知识库摘取 / manual 人工上传
    source = Column(String(16), default="model", index=True)
    size = Column(Integer, default=0)
    warnings = Column(JSON, default=list)          # 安全检查告警
    document_id = Column(Integer, nullable=True)    # 已入库到数据中心的文档 id
    accepted = Column(Boolean, default=False)       # 是否已被验收（反哺只看已验收的）
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class DevSession(Base):
    """一次生成过程的上下文与日志 —— 可追溯、可复现的那一份底稿

    prompt / context / reply 三件套：
    prompt 是当时发给模型的话，context 是当时检索到的知识引用，
    reply 是模型原话。有了这三样，半年后回头看这个产出，
    才知道「它凭什么这么写」，也能用同样的输入再跑一遍。
    """
    __tablename__ = "dev_session"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("dev_project.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("dev_task.id", ondelete="SET NULL"),
                     nullable=True, index=True)
    # plan 生成方案 / task 生成任务产出 / chat 自由问答
    kind = Column(String(16), default="plan", index=True)
    prompt = Column(Text, default="")
    context = Column(JSON, default=dict)            # 检索到的知识（引用摘要）
    reply = Column(Text, default="")                # 模型回复原文
    model = Column(String(128), default="")         # 用了哪个模型
    mode = Column(String(16), default="offline")    # 生成时所处的模式
    status = Column(String(16), default="done", index=True)
    notice = Column(Text, default="")               # 降级提示（例：没联网搜索）
    created_at = Column(DateTime, server_default=func.now())


class DevCitation(Base):
    """知识引用：模型的每一段输出挂在哪几条知识上

    kind 区分来源：gene 养料库基因 / doc 文档块 / github 开源项目 / web 网络知识
    confidence 是这条引用有多可信：
    基因用自己的 confidence，文档与 GitHub 用检索得分归一化后的值。
    """
    __tablename__ = "dev_citation"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("dev_session.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    artifact_id = Column(Integer, ForeignKey("dev_artifact.id", ondelete="SET NULL"),
                         nullable=True, index=True)
    kind = Column(String(16), default="gene", index=True)
    ref = Column(String(128), default="")           # gene:12 / doc:34 / repo:owner/repo
    title = Column(String(256), default="")
    snippet = Column(Text, default="")
    confidence = Column(Float, default=0.5)
    created_at = Column(DateTime, server_default=func.now())



__all__ = [
    "EntityType", "FieldDefinition", "EntityRecord",
    "RelationDef", "RelationRecord", "Attachment", "View", "App",
    "Document", "DocumentLink", "DocumentChunk", "SysMeta",
    "Dashboard", "Role", "User", "UserSession", "AuditLog",
    "NoteGroup", "NavItem", "DnaGene",
    "DnaGeneScore", "DnaAsset", "DnaAssetUse", "DnaOpenkbSource",
    "DevProject", "DevTask", "DevArtifact", "DevSession", "DevCitation",
]