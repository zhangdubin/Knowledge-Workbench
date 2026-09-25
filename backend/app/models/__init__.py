from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Boolean,
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


__all__ = [
    "EntityType", "FieldDefinition", "EntityRecord",
    "RelationDef", "RelationRecord", "Attachment", "View", "App",
    "Document", "DocumentLink", "DocumentChunk", "SysMeta",
    "Dashboard", "Role", "User", "UserSession", "AuditLog",
]