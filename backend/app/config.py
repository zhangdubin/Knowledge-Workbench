from pathlib import Path
import logging
import os

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("kb.config")


def _promote_kb_env() -> None:
    """把 `KB_` 前缀的环境变量映射成不带前缀的同名变量

    运维文档、.env.example、docker-compose 一直用 `KB_ADMIN_PASSWORD` /
    `KB_FILE_STORE_DIR` 这类带前缀的写法，而 pydantic-settings 读取的其实是
    **无前缀**的字段名（`ADMIN_PASSWORD` / `FILE_STORE_DIR`）。也就是说这些
    「文档里写着、实际不生效」的变量此前一直在静默失效 —— 部署时改了配置
    却毫无变化，是最难排查的一类问题。

    优先级：显式无前缀 > KB_ 前缀 > 代码默认值。
    （已存在的无前缀变量不覆盖，两种写法混用时以无前缀为准。）
    """
    for key, value in list(os.environ.items()):
        if not key.startswith("KB_") or len(key) <= 3:
            continue
        bare = key[3:]
        if bare and bare not in os.environ:
            os.environ[bare] = value


def _drop_empty_env(field_names) -> list[str]:
    """把空串形式的配置项当作「未设置」摘掉

    脚本里 `docker exec -e "BACKUP_KEEP=${KEEP:-}"` 这种写法会把变量设成空串，
    而空串对 int 字段是解析错误，结果是整个服务起不来 —— 一个「可选参数没传」
    直接把部署搞崩。空串在 shell 语义里几乎总是「没有这个值」。

    只清理与配置字段同名的变量，不动其它环境变量，避免影响第三方库对
    「变量存在与否」的判断。
    """
    dropped = []
    for name in field_names:
        key = name.upper()
        if os.environ.get(key) == "":
            os.environ.pop(key, None)
            dropped.append(key)
    return dropped


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "KB Workbench"
    # 版本号是全链路标识的唯一事实来源：
    #   - /api/health、/api/health/deep、/api/auth/status 都从这里读
    #   - 备份快照元数据记录当时的版本（maintenance.py）
    #   - 离线包文件名（make-offline-package.sh 从本文件 grep 出来）
    # 发版规则（语义化）：主版本.次版本.修订号 ——
    #   修订号：修 bug、小改进；次版本：新功能；主版本：不兼容的库结构/接口变动。
    # 每次发布 CHANGELOG.md 必须同步更新。
    app_version: str = "0.3.4"

    # ==== 升级更新（依托 GitHub Releases）====
    # update_repo：GitHub 仓库标识「owner/name」。空 = 未配置，
    #   更新检查接口会如实返回 configured=false 并提示怎么配。
    # update_proxy：容器访问 GitHub API 的 http 代理（如 http://10.10.10.252:1086），
    #   直连可达就留空。只影响「检查更新」这一个出站请求。
    update_repo: str = ""
    update_proxy: str = ""
    # 检查请求的超时秒数。GitHub API 未认证限额 60 次/小时/IP，
    # 服务侧再做 10 分钟结果缓存，正常使用远碰不到限额。
    update_timeout: float = 8.0
    update_cache_seconds: float = 600.0

    # 数据目录：kb.db（元数据 + 全文索引 + 向量索引）就放在这里
    data_dir: str = "./data"
    database_url: str = "sqlite+aiosqlite:///./data/kb.db"

    # ==== 文件原文存储 ====
    # fs = 原文落文件系统（默认，推荐）；db = 原文进 SQLite BLOB（历史行为）
    # 生产务必保持 fs：库文件从此只装元数据与索引，体积增长慢一个量级，
    # 备份窗口 / VACUUM 耗时 / 崩溃恢复时间都不会再被大文件拖着走。
    file_store: str = "fs"
    file_store_dir: str = "./files"
    # 落盘后是否 fsync。开了更耐断电，代价是每次上传多一次磁盘同步；
    # 有备份机制时保持 False 更划算（备份才是真正的数据安全网）。
    file_store_fsync: bool = False
    # 单次上传硬上限（MB）。超过直接拒绝：读上传体是整块进内存的，
    # 不设上限等于把内存交给用户决定。0 表示不限制（不推荐）。
    upload_max_mb: int = 1024

    # 备份保留份数。原文外置后一次备份 = 库文件 + 文件目录快照，
    # 快照之间用硬链接共享未变动的文件，所以「保留 14 份」不会真的占 14 倍空间。
    backup_keep: int = 14
    # 备份目录。容器内固定挂到 /app/backups；
    # 生产请把宿主侧指向另一块物理盘或网络存储。
    backup_dir: str = "/app/backups"
    # 声明「这些容器内挂载点在宿主机上是独立于数据盘的备份盘」，
    # 多个用**逗号**分隔，例如 `/mnt/kb-backup`。
    # （用逗号而不是 JSON 数组，是因为沿用同一套写法的人很容易在这里
    #   写成裸路径，而 list 类型的字段会被 pydantic 当 JSON 解析、直接报错。）
    #
    # 为什么需要人工声明：在 Docker Desktop（macOS / Windows）里，所有
    # bind mount 都被呈现成同一个伪设备（fakeowner / virtiofs），容器内拿
    # st_dev 根本区分不出宿主机的磁盘边界 —— 于是「备份到底有没有和数据
    # 分盘」这件事在容器里无从判断。Linux 宿主上系统能自动判断，留空即可；
    # Docker Desktop 部署下填上，界面就会把该挂载点标成独立盘，
    # 并去掉「同盘」警告。宁可让人显式声明，也不要猜错后给出虚假的安心感。
    backup_separate_mounts: str = ""

    # 仅用于「存量迁移」：v0.1 时代文件落在磁盘 uploads/ 下
    # v0.2 起文件进数据库，v0.3 起外置到 file_store_dir；
    # 该目录只在首次启动时被扫描一次
    legacy_upload_dir: str = "./data/uploads"

    app_env: str = "production"
    # 日志级别：DEBUG / INFO / WARNING / ERROR。
    # 生产用 INFO 就够；排障时临时改 DEBUG 并重启即可。
    log_level: str = "INFO"
    # 允许跨域来源。默认空 = 只允许同源 —— 前端由 nginx 反代 /api，
    # 开发态走 vite proxy，两种模式都是同源，压根不需要 CORS。
    # 只有前端单独部署在别的域名时才需要在这里列出来。
    # 注意：设成 ["*"] 时无法同时携带 Cookie（浏览器会拒绝），
    # 所以下面会在启动时自动关闭 allow_credentials，避免「看着配了却不生效」。
    cors_origins: list[str] = []

    # ==== SQLite 调优 ====
    # 页缓存（MB）。SQLite 默认只给 2MB，热数据一超就得回读磁盘。
    sqlite_cache_mb: int = 64
    # mmap 上限（MB）。读路径走内存映射，省掉 read() 系统调用，
    # 是这一组参数里对读性能提升最明显的一个。0 表示关闭。
    sqlite_mmap_mb: int = 256
    # 单条 WAL 达到多少页就自动检查点（每页 4KB，默认 1000 页 ≈ 4MB）。
    # 调大能减少写放大的停顿，代价是 WAL 文件更大。
    sqlite_wal_autocheckpoint: int = 1000
    # 启动时做一次完整性自检（quick_check 只扫索引结构，通常毫秒级）
    startup_quick_check: bool = True

    # 单文件超过该体积时，上传结果里附带提示（不阻止上传）
    # 0 表示不提示。SQLite 读 BLOB 是整块进内存的，提示用于防止误传大文件
    large_file_warn_mb: int = 200

    # 向量维度探测失败时的兜底值（MiniMax embo-01 实际维度以运行时探测为准）
    embed_dim_fallback: int = 1536

    # 单次送往 embedding 接口的最大文本条数（防止请求体过大）
    embed_batch_size: int = 16
    # 单个文本送入 embedding 前的截断长度（字符）
    embed_max_chars: int = 1500
    # 文档分块的字符长度与重叠
    chunk_size: int = 800
    chunk_overlap: int = 120

    # ==== 安全 ====
    # 是否开启登录鉴权。关闭后所有请求按管理员身份处理，
    # 只适合完全可信的内网单机调试；生产务必保持 True。
    auth_enabled: bool = True
    # 会话有效期（天）
    session_days: int = 14
    # Cookie 是否只走 HTTPS。用 HTTPS 反代（nginx/Caddy）时必须开，
    # 否则会话 Cookie 在明文链路上可被嗅探。纯 HTTP 内网保持 False。
    cookie_secure: bool = False
    # 初始管理员口令：仅在库里一个用户都没有时使用，登录后强制改密
    admin_password: str = "admin12345"
    # 审计日志只记写操作与登录事件
    audit_enabled: bool = True
    # 审计日志保留天数，0 表示不清理
    audit_keep_days: int = 180

    # ==== 后台维护 ====
    # 定时维护开关：过期会话清理、审计日志清理、查询计划刷新、WAL 检查点。
    # 关掉之后这些动作只在启动/关停时发生，长跑数月的实例会慢慢积累垃圾。
    maintenance_enabled: bool = True
    # 过期会话清理间隔（分钟）
    session_sweep_minutes: int = 5
    # 审计清理 + PRAGMA optimize 间隔（分钟）
    audit_sweep_minutes: int = 60
    # 定期检查点间隔（分钟）。PASSIVE 模式不阻塞写入，只是把 WAL 内容推回主库；
    # WAL 长期不检查点会一直膨胀，是所有 SQLite 部署最常见的隐形故障。
    checkpoint_minutes: int = 30
    # 数据库自检缓存刷新间隔（分钟），健康检查接口读这个缓存值
    health_probe_minutes: int = 10


_promote_kb_env()
# 注意顺序：先做前缀映射，再按字段名清理空值 ——
# 反过来的话，`KB_BACKUP_KEEP=` 这种带前缀的空值刚被映射出来就被漏掉
_dropped = _drop_empty_env(Settings.model_fields.keys())
if _dropped:
    log.warning(
        "以下配置项环境变量为空串，已按「未设置」处理并使用默认值：%s",
        ", ".join(sorted(_dropped)),
    )

settings = Settings()

# 确保数据目录存在
Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
# 文件原文目录同理：外置存储启用时，目录必须在启动前就存在，
# 否则第一次上传才会暴露权限/挂载问题
if (settings.file_store or "fs").lower() != "db":
    Path(settings.file_store_dir).mkdir(parents=True, exist_ok=True)
