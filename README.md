# 🧠 知识管理工作台 (KB Workbench)

> 统一管理**结构化 + 非结构化**数据 · **跨实体关联分析** · 承载**项目管理 / 销售管理 / 合同管理**等多种业务应用

## ✨ 核心特性

- 🎨 **零代码数据建模** —— 可视化创建实体类型（表）、自定义字段类型（文本/数字/日期/选择/文件/外键/富文本）
- 📊 **多视图数据管理** —— 列表 / 表单 / 详情 / 图谱 多种数据展示方式
- 🔗 **跨实体关联分析** —— 可视化关系图谱，发现实体间的隐含关联
- 📁 **非结构化数据** —— 文件附件、图片、富文本，一个平台全部承载
- 🔍 **全局全文检索** —— 跨所有实体类型的关键字搜索
- 🖥️ **自由画布驾驶舱** —— 卡片任意拖拽缩放、吸附对齐、宽度自适应填满、一键切全屏高感大屏
- 🤖 **AI 助理（对话即操作）** —— 一句话查数据、记一笔、改记录，写操作先确认后执行
- 🚀 **多应用承载** —— 同一套数据底座，预置项目管理、销售管理、合同管理 3 个示例应用
- 🐳 **Docker 一键部署** —— `bash start.sh` 即可启动

## 🏗 架构

```
┌──────────────────────────────────────────────────┐
│   浏览器                                         │
└───────────────────┬──────────────────────────────┘
                    │ :8082
        ┌───────────▼─────────────┐
        │   Frontend (nginx)      │ Vue3 + Element Plus
        │   - 静态文件             │ SPA + 反代 /api → backend
        └───────────┬─────────────┘
                    │
        ┌───────────▼─────────────┐
        │   Backend (FastAPI)     │ Python 3.12
        │   - Meta-Schema 引擎    │ SQLAlchemy async
        │   - REST API            │ SQLite（含文件原文 BLOB
        └───────────┬─────────────┘  + FTS5 全文 + vec0 向量）
                    │
        ┌───────────▼─────────────┐
        │  ./data  (bind mount)   │ kb.db  ← 唯一的数据载体
        │  ./backups              │ 一致性备份（建议指向另一块盘）
        └─────────────────────────┘
```

### Meta-Schema 数据底座

```
EntityType (实体类型/表)
  ├─ FieldDefinition[] (字段定义)
  └─ EntityRecord[] (记录，数据存为 JSON)
        ├─ Attachment[] (附件)
        └─ RelationRecord[] (关系记录，跨实体)
RelationDef (关系定义) — 桥接 source ↔ target
```

## 🚀 快速启动

```bash
cd kb-workbench

# 一键启动（首次会自动构建镜像）
bash start.sh

# 访问
#   前端: http://localhost:8082
#   API:  http://localhost:8001/api/docs
```

### 登录

首次启动会自动创建管理员 `admin`，口令取自后端环境变量 `KB_ADMIN_PASSWORD`，
**未设置时用内置默认值**，并且登录后会被强制要求修改（改完才放行其他接口）。

注意 `KB_ADMIN_PASSWORD` **只在首次初始化时生效**：库里已经有 admin 之后，
再改这个环境变量不会改口令，需要用下面的脚本重置。

```bash
# 忘记口令 / 想换口令（交互输入，不经过 shell 历史；已有数据不受影响）
./scripts/reset-admin-password.sh
```

> 💡 验证脚本 `scripts/v17-verify.cjs` 默认口令也是 `KB_ADMIN_PASSWORD` 的值。
> 若你已通过界面改过口令，执行验证时请传环境变量：
> `KB_PASS='你的新口令' node scripts/v17-verify.cjs`。

## 💾 数据存储与备份

### 存在哪

数据分两处存放（**v0.3 起文件原文已拆出库外**）：

| 位置 | 内容 |
|---|---|
| `data/kb.db` | 元数据、业务数据、FTS5 全文索引、sqlite-vec 向量索引 |
| `files/` | **文件原文**，内容寻址布局 `files/<sha[0:2]>/<sha[2:4]>/<sha[4:]><ext>` |

拆开的理由：原文留在库里时，库文件体积由「上传了多少文件」决定，
备份窗口、`VACUUM` 耗时、崩溃恢复时间会跟着一起涨；而且 SQLite 读 BLOB 是
整块进内存，大文件并发下载能把进程内存打满。外置之后库只随元数据与索引增长。

内容寻址带来三个直接好处：
1. **去重**：同一份文件重复上传零额外占用（sha256 相同即同一路径）
2. **原子写**：先写临时文件再 `rename`，不会出现「库里有记录、盘上是半个文件」
3. **增量备份**：文件只增不改，快照间用硬链接共享，备份快得几乎免费

库内剩余构成（当前样例库，原文外置后）：

| 组成部分 | 说明 |
|---|---|
| `document_vec*` | 向量索引，每块 `dim×4` 字节（1536 维 = 6144 B），vec0 按 1024 块一批分配 |
| `document_fts*` | 全文索引及其影子表 |
| 业务表 + `document` | 记录、关联、驾驶舱、用户、审计、文件元数据 |

**向量索引是库内最大的体积来源**，约为正文文本量的 14 倍（6144 B / 平均 439 字符每块）。
要压缩库文件优先看它，而不是业务数据。

### 装在哪：安装目录 ≠ 数据目录

这两件事经常被混在一起，结果「磁盘满了」去搬安装目录，白忙一场：

| | 内容 | 体积 |
|---|---|---|
| 安装目录 | `docker-compose.yml`、`.env`、`scripts/` | 几百 KB，基本不增长 |
| 数据根目录 | `data/`、`files/`、`backups/`、`backups-alt/` | 随业务增长，`files/` 和 `backups/` 是大头 |

所以生产环境的标准姿势是**小盘装程序、大盘放数据**：

```bash
# 全新安装时就分开
bash install.sh --dir /opt/kb-workbench --data-dir /data/kb-workbench
```

已经装好了才想换（比如默认的 `~/kb-workbench` 所在分区太小）：

```bash
cd ~/kb-workbench
bash scripts/move-data.sh /data/kb-workbench
```

`move-data.sh` 会：停服 → 搬 `data`/`files`/`backups` → 改 `.env` → 起服务 → 等健康检查。
动手前先备份 `.env`，中途任何一步失败（磁盘写满、权限、Ctrl-C）都会自动把服务
按原配置拉回来 —— 不会给你留一个「服务停着、配置没改、数据搬一半」的现场。

几个刻意的设计：

- **同盘用 `mv`**：rename 是原子的、瞬时完成；**跨盘用 rsync 复制后逐项校验**
  （文件数 + 实际占用 + 硬链接是否保留）。硬链接那一项是重点 —— 备份快照之间
  靠硬链接共享未变动的文件，一旦被展开成独立副本，备份体积会成倍膨胀，而且
  要等到磁盘报警才会发现。脚本用「目标占用不得明显大于源」来卡住这种情况。
- **按 rsync 版本挑参数**：`-aHAX` 需要 rsync 3.x；macOS 自带的是 2.6.9，不认
  `-A`/`-X`，但支持 `-E`（而且 `-E` 在 3.x 里含义完全不同）。所以按版本号选，
  rsync 走不通再降级到 `tar` 管道（tar 默认会把同一批文件里的硬链接存成链接）。
- **跨盘搬迁保留原目录**：校验通过才切 `.env`，原目录留到你确认服务正常之后，
  脚本退出时打印清理命令。同盘搬迁则 `mv` 完顺手清掉搬空的原父目录。
- **升级安装不改数据目录**：`install.sh` 在已有 `.env` 的目录上只更新编排文件；
  `--data-dir` 在这种情况下不会生效（`.env` 里的路径优先级更高），脚本会明确
  告诉你「当前 / 想要 / 怎么搬」，而不是静默忽略。

### 怎么备份

```bash
./scripts/backup.sh                      # 完整快照（库 + 文件），保留最近 14 份
./scripts/backup.sh --keep 30            # 保留 30 份
./scripts/backup.sh --dir /mnt/nas/kb    # 这一次临时搬到别处
./scripts/backup.sh --set-dir /mnt/kb-backup  # 把默认备份目录改成容器内路径
```

一份备份 = 一个快照目录：

```
backups/snap-20260924-220600/
├── kb.db        # VACUUM INTO 一致性副本（含校验）
├── files/       # 文件原文；与上一份快照硬链接共享未变动的文件
└── meta.json    # 校验结果、文件数、体积
```

> ⚠️ **只备份 `kb.db` 会得到一份「记录在、内容丢」的空壳。**
> 原文已外置，务必用 `backup.sh`（它会同时快照 `files/`）。
>
> ⚠️ **不要用 `cp kb.db` 备份。** 库跑在 WAL 模式下，最新数据可能还只在 `-wal`
> 文件里，单拷主库会得到一份过期副本；写入进行中还可能拷到撕裂的页。

备份目录默认落在 `./backups/`（容器内 `/app/backups`）。
**把它和数据放在同一个目录里只能防误删、防不了磁盘故障。**

推荐做法（另一块物理盘）：

1. 在 `docker-compose.yml` 里把宿主机上的盘挂进容器：`./backups` 不动，
   新增 `./backups-alt`（或你的 NAS）映射到 `/mnt/kb-backup`。
2. 在 `.env` 里填上 `KB_BACKUP_ALT_HOST_DIR=/Volumes/Trisome/kb-backups`
   与 `BACKUP_SEPARATE_MOUNTS=/mnt/kb-backup`。
3. 启动后进入「系统设置 → 备份目录」，从候选列表里选 `/mnt/kb-backup/kb-backups`。
   点保存后**立即生效**，不需要重启容器。

```bash
# 或者用命令行改默认目录
./scripts/backup.sh --set-dir /mnt/kb-backup/kb-backups
```

> 为什么还需要 `BACKUP_SEPARATE_MOUNTS`：在 Docker Desktop（macOS/Windows）里，
> 所有 bind mount 都被呈现为同一个伪设备，容器内用 `st_dev` 根本区分不出
> 宿主机磁盘边界。这个变量显式声明哪些挂载点是「独立于数据盘的备份盘」，
> 让界面和健康检查给出准确的判断。

定时备份（crontab）：

```cron
0 2 * * * cd /path/to/kb-workbench && ./scripts/backup.sh >> logs/backup.log 2>&1
```

### 怎么还原

有两条路，按「服务还能不能打开」选：

1. **界面上点一下（推荐）**：「系统管理 → 存储与备份 → 备份列表」每份快照
   右侧有「还原」按钮。输入快照名确认后在线完成 —— 不停服务，用的是
   SQLite 官方在线备份 API（对 WAL / FTS5 全文索引 / vec0 向量表均兼容）。
   流程：校验快照 → 自动给当前状态留一份**退路快照** → 暂时挡住其他
   请求（503）→ 同步文件原文 → 在线换库 → 自检，**自检不过会自动回滚到
   还原前状态**。还原到早于当前登录的快照后需要重新登录。

2. **命令行（服务起不来时）**：

```bash
./scripts/restore.sh                            # 交互式选快照
./scripts/restore.sh backups/snap-20260924-220600
```

它会停后端 → 校验备份 → 先给当前状态留退路 → 换库换文件 → 起后端 →
深度自检。属于灾难恢复路径，界面上那颗按钮够用时不要用它。

### 在界面上看

「系统管理 → 存储与备份」提供体积构成、容量余量、磁盘余量、
文件原文存储与外迁进度、索引一致性体检、原文完整性普查、
维护动作（刷新查询计划 / 检查点 / 回收空间 / 完整性校验 / 外迁原文）、
备份列表与**一键还原**。

### 容量红线

| 指标 | 舒适 | 需留意 | 建议迁移 |
|---|---|---|---|
| 单库文件体积 | < 10 GB | 10 – 50 GB | > 50 GB |
| 文件原文总量 | < 20 GB | 20 – 100 GB | > 100 GB |
| 业务记录行数 | < 20 万 | 20 万 – 100 万 | > 100 万 |
| 向量分块数 | < 20 万 | 20 万 – 100 万 | > 100 万 |

越过红线后，备份窗口、`VACUUM` 耗时与崩溃恢复时间会一起变成问题。
真正需要迁移时，第一刀是**把文件原文从库里拆到对象存储**（`document.data`
换成路径或对象键），业务表与索引留在 SQLite 完全够用。

## 📦 预置应用

启动后自动创建 3 个示例应用，包含完整字段、关系与样例数据：

| 应用 | 实体类型 | 关系 |
|------|---------|------|
| 📋 **项目管理** | 项目、任务 | 任务 → 项目 |
| 💼 **销售管理** | 客户、商机、订单 | 商机/订单 → 客户 |
| 📄 **合同管理** | 合同、付款计划 | 付款 → 合同；合同 → 客户/商机 |

## 🎯 使用场景

### 1. 数据建模
进入「数据模型」页面，点击「新建模型」：
- 填写模型名、Key、所属应用
- 添加字段：选择字段类型（文本/数字/日期/选择/文件/外键/富文本）
- 保存后自动生成对应的数据列表和表单
- 删除模型：在「数据模型」页悬停卡片，点击「⋯」→「删除模型」；或在模型编辑页顶部点击「删除模型」。删除是软删除，会移入「系统管理 → 回收站」，可恢复；在回收站里「彻底删除」才会物理级联删除字段、记录、关联定义。

### 2. 数据管理
进入「应用中心」或「数据模型」，点击某个实体类型：
- 列表视图：分页浏览，支持搜索
- 点击行：打开详情侧栏，查看字段 + 关联关系
- 编辑按钮：修改字段值
- 详情中可添加/删除关联关系
- 记录删除会进入回收站，可恢复；列表上方支持「导出 CSV」「导入」批量数据

### 3. 回收站
进入「系统管理 → 回收站」：
- 已删除的模型：显示字段数、记录数、删除时间，可恢复或彻底删除
- 已删除的记录：显示所属模型、内容摘要、删除时间，可恢复或彻底删除
- 彻底删除模型时必须输入模型 Key 确认，物理级联不可恢复

### 4. AI 助理（对话即操作）
点击顶栏「AI 助理」按钮，或首页「AI 助手」快捷入口：

**查询（直接执行）**
- 「有哪些数据模型」「搜一下 XX 记录」「费用管理里金额总和是多少」「文件里有没有关于项目的资料」
- 工具：列出模型 / 查看字段结构 / 搜索记录 / 字段统计（计数·求和·平均·分组）/ 文件混合检索

**写入（先确认后执行）**
- 「帮我在费用管理里记一笔：今天差旅 380 元」→ AI 生成**待确认卡片**
- 卡片逐字段列出改动（修改类显示 `旧值 → 新值`）、风险色标（新建 / 修改 / 删除）、
  字段校验警告；点「确认执行」才真正落库，点「取消」不留任何痕迹
- 确认后由 AI 接着说明结果，可一键跳「去记录页看看」
- 删除是**软删除**，进回收站可恢复；所有写操作记入审计日志

安全边界（为什么敢让 AI 动数据）：
- 模型没有「直接改数据」的通道：写工具只产出待确认清单，落库由用户点击驱动
- 确认时后端**重新校验**参数（权限 + 字段 Key + 必填 + 类型），不信任前端回传
- 未知字段 Key、必填缺失、数字字段塞非数字一律拦下；单选值越界给警告
- 修改只覆盖用户提到的字段，其余保持原值；改了个寂寞（值没变）也会被拦下
- 重复提交闸门：同一人同一份参数 15 秒内只落库一次（防双击 / 重试重复记账）
- 写权限收紧：查询只要 read 权限，写工具额外要求对应模型的 write 权限
- 可在「AI 设置 → 代执行操作」一键关掉写能力，退回纯查询模式

写操作会在审计日志里留痕（`resource=ai_agent`），可查「谁、经哪个工具、
动了哪条记录、写入了哪些字段」。

### 3. 关联分析
进入「关联图谱」：
- 按记录展开：以一条记录为中心，递归展开所有关联（深度 1-4）
- 按类型全局：展示某一类型的所有记录及其内部关系
- 节点可拖拽、点击跳转

### 4. 全局检索
进入「全局搜索」：
- 输入关键字，搜索所有实体类型的数据
- 点击结果跳转详情

### 5. 文件管理
字段类型选择「文件」/「图片」：
- 在详情/编辑中上传附件（默认上限 1024MB，由 `UPLOAD_MAX_MB` 控制）
- 原文落到 `files/` 目录（内容寻址），库里只存元数据与索引
- 同一份文件重复上传自动去重（秒传），不占额外空间

### 6. 驾驶舱（自由画布 + 大屏）
「驾驶舱」里的卡片铺在一块**无限画布**上，不再受列网格限制：

- **摆放**：拖动卡片任意移动；右下/四边八个手柄任意缩放；宽高精确到像素
- **吸附**：移动时按 8px 网格吸附，贴近其他卡片边缘或中线会出现对齐辅助线并自动对齐
- **画布**：空白处拖动平移、双击空白新建卡片、`Ctrl/⌘ + 滚轮`缩放、工具条「适应窗口 / 100% / 自动整理」
- **微调**：点选卡片后用方向键移动 1px（按住 Shift 走 8px），Delete 删除，卡片角标可置顶
- **卡片类型**：指标 / 图表（柱·折·饼·环·面积·横向条·雷达）/ 仪表盘 / 排行榜 / 表格 / 清单 / 文字
- **大屏**：点「大屏」进全屏科技风（星云蓝·极光紫·深渊青 + 实时时钟 + 自动刷新），
  用的是同一份自由布局，按视口等比自适应
- **兼容**：老驾驶舱的「占 N 列」布局打开时自动换算成自由坐标，不用手工重排

## 🔧 API 接口速览

所有接口前缀 `/api`：

| 模块 | 接口 |
|------|------|
| 健康检查 | `GET /api/health`（轻量，含库自检缓存）、`GET /api/health/deep`（深度自检） |
| 应用列表 | `GET /api/apps` |
| 全局统计 | `GET /api/stats` |
| 实体类型 | `GET/POST/PUT/DELETE /api/entity-types` |
| 记录 CRUD | `GET/POST/PUT/DELETE /api/records/...` |
| 记录导出/导入 | `GET /api/records/type/{id}/export` · `POST /api/records/type/{id}/import` |
| 回收站 | `GET /api/recycle` · `POST /api/recycle/types/{id}/restore` · `DELETE /api/recycle/types/{id}` · `POST /api/recycle/records/{id}/restore` |
| 关系管理 | `GET/POST/DELETE /api/relations/...` |
| 附件 | `POST /api/attachments/upload`、`GET /api/attachments/{id}/download` |
| 全文搜索 | `GET /api/search?keyword=xx` |
| AI 助理 | `POST /api/ai/agent`（工具调用）`POST /api/ai/ask`（RAG 问答）|
| 关联图谱 | `GET /api/graph/record/{id}?depth=2`、`GET /api/graph/type/{id}` |

完整 Swagger 文档：`http://localhost:8001/api/docs`

## 📁 目录结构

```
kb-workbench/
├── backend/                # FastAPI 后端
│   ├── app/
│   │   ├── main.py         # 入口
│   │   ├── config.py       # 配置
│   │   ├── database.py     # 数据库连接
│   │   ├── models/         # ORM 模型（Meta-Schema）
│   │   ├── schemas.py      # Pydantic 模型
│   │   ├── routers/        # REST 路由
│   │   └── services/       # 业务逻辑（含 seed）
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/               # Vue3 前端
│   ├── src/
│   │   ├── api/            # API 客户端
│   │   ├── components/     # 通用组件（DynamicForm/FileUploader/...）
│   │   ├── views/          # 页面
│   │   ├── router/         # 路由
│   │   ├── styles/         # 全局样式
│   │   └── utils/          # 工具函数
│   ├── Dockerfile
│   ├── nginx.conf
│   ├── vite.config.js
│   └── package.json
├── docker-compose.yml      # 一键编排
├── start.sh                # 启停脚本
└── README.md
```

## 📦 离线安装包

给「目标机器不能联网」的场景用：把应用镜像 + 运行编排 + 安装脚本打成一个包，
拷过去解压执行即可。目标机不需要源码，不需要 Python / Node，也不需要访问外网。

### 造包（在能联网的开发机上）

```bash
# 1. 构建双架构镜像（arm64 + amd64）
./scripts/build-offline-images.sh

# 2. 组装离线包，并自动输出压缩包到桌面
./scripts/make-offline-package.sh
```

产物：

- `dist-offline/kb-workbench-offline-v<版本>-<日期>/` —— 包目录
- `~/Desktop/kb-workbench-offline-v<版本>-<日期>.tar.gz` —— 可直接拷走的压缩包

### 装机（在目标机器上）

```bash
tar -xzf kb-workbench-offline-*.tar.gz
cd kb-workbench-offline-*
bash install.sh                 # macOS 也可以直接双击 install.command
```

Windows 双击 `install.bat` 即可。安装脚本会自己识别操作系统与 CPU 架构，
从 `images/` 里挑对应的镜像文件 —— 同一个包通吃 Linux / macOS / Windows、
x86_64 与 arm64，不需要人工选。

### 包内结构

| 路径 | 作用 |
|---|---|
| `install.sh` / `install.command` | macOS、Linux 一键安装 |
| `install.ps1` / `install.bat` | Windows 一键安装 |
| `app/docker-compose.yml` | 离线编排（用 `image:` 引用本地镜像，无 `build:`） |
| `images/` | 按 CPU 架构分文件的应用镜像 |
| `scripts/` | 备份 / 恢复 / 健康检查 / 重置口令 |
| `source/` | 源码快照，只有想自行重建镜像时才用得到 |
| `manifest.json` | 内容清单与 sha256 校验值 |

### 两条设计约束（改包时别踩）

1. **镜像按架构打标签**（`:amd64` / `:arm64`），安装脚本导入之后再打 `:latest`。
   因为 `docker load` 不校验架构，两个架构若都叫 `:latest`，后导入的会覆盖
   先导入的，启动时直接 `exec format error`。
2. **运维脚本从 `.env` 读实例配置**（`COMPOSE_PROJECT_NAME`、`KB_BACKEND_CONTAINER`）。
   用 `install.sh --instance qa` 可以在同一台机器上再装一套完全隔离的实例，
   适合「先装一套验收、再切生产」，或者在同一台机器上跑测试环境。

## 🛠 命令速查

```bash
bash start.sh up        # 启动
bash start.sh stop     # 停止
bash start.sh restart  # 重启
bash start.sh logs     # 查看日志
bash start.sh status   # 查看状态
bash start.sh rebuild  # 重新构建（无缓存）
bash start.sh clean    # ⚠️ 删除所有数据
```

## 🔍 技术栈

- **后端**: Python 3.11 + FastAPI + SQLAlchemy 2.0 (async) + aiosqlite + Pydantic v2
- **前端**: Vue 3.5 + Element Plus 2.9 + Pinia + Vue Router + Vite 6
- **图谱**: vis-network
- **存储**: SQLite（元数据 + 索引） + 本地文件目录（原文）
- **部署**: Docker Compose + nginx

## 🚀 生产部署检查单

上生产前务必按顺序核对：

| # | 检查项 | 命令 / 操作 |
|---|---|---|
| 1 | 复制 `.env.example` → `.env`，并修改 `KB_ADMIN_PASSWORD` | `cp .env.example .env` |
| 2 | 把另一块盘挂进容器（compose 的 `/mnt/kb-backup`），并设 `KB_BACKUP_ALT_HOST_DIR`、`BACKUP_SEPARATE_MOUNTS` | 编辑 `.env` |
| 3 | 到「系统设置 → 备份目录」把备份切到那块盘 | 界面点选，**立即生效** |
| 4 | 若用 HTTPS 反代，`KB_COOKIE_SECURE=true` | 编辑 `.env` |
| 5 | 磁盘剩余空间 > 20 GB | `df -h` |
| 6 | 运行上线自检脚本 | `./scripts/healthcheck.sh` |
| 7 | 跑通一次备份 + 恢复演练 | `./scripts/backup.sh && ./scripts/restore.sh` |
| 8 | 配置 crontab 定时备份 | `0 2 * * * cd $(pwd) && ./scripts/backup.sh >> logs/backup.log 2>&1` |
| 9 | 管理员首次登录后强制改密 | 登录页会提示 |

> ⚠️ 若 `healthcheck.sh` 报「备份目录与数据目录在同一块盘上」，说明第 2–3 步
> 还没做完。同盘备份只防误删、不防磁盘故障 —— 上生产前必须解决。

## 🌐 局域网访问

```bash
# 启动后默认绑定到 0.0.0.0，局域网内可通过主机 IP 访问
# 假设主机 IP 为 10.10.10.5：
http://10.10.10.5:8082

# API
http://10.10.10.5:8001/api/docs
```