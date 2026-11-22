# 中文知识服务第一期 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让普通业务用户在中文工作区查到适用知识、核对逐字出处、反馈疑问，并让授权人员处理反馈。

**Architecture:** 在现有本体领域上增加 knowledge_service 模块化应用；复用 EntityRecord、SourceSnapshot、Evidence 和已接受 Claim。应用读权限独立于 types，所有读路径使用原 Principal 逐层校验模型及来源；新增资料修订、查询运行与反馈表，旧业务数据不自动转换。

**Tech Stack:** Vue 3 / Element Plus / FastAPI / SQLAlchemy async / SQLite / unittest / Node test。

**Spec:** docs/superpowers/specs/2026-11-22-knowledge-service-foundation-design.md（用户 2026-11-22 已批准按推荐设计实施第一期）。

## Global Constraints

- 首期以制度流程、保障参考资料、培训材料和项目知识为可配置领域。
- 普通用户无需掌握本体 UUID、JSON 或数据库结构；界面、错误和状态以中文为主。
- 保留现有五项主导航；知识服务位于业务应用与应用命令目录内。
- 普通读者可以获准使用知识服务而无权进入模型编辑；不能通过构造提升后的 Principal 复用工作室接口。
- 最多 50 项结果、最多两跳关系和明确扫描预算；完整导入对象继续要求全部来源可读。
- 引用必须属于本次授权检索集合且逐字定位正确；没有证据不能生成有依据结论。
- 资料修订引用原 Document ID、哈希和明确分组，业务生效日期与系统记录时间分别保存；新资料不自动取得替代权威。
- 测试仅使用受控响应、临时数据库和恢复副本，不自动向外部模型发送业务资料。
- 不推送、不合并 main；从现有隔离工作区实施，保留原资料与配置。新版本经完整副本验收和备份后本机升级。

## File structure and contracts

新增 `backend/app/knowledge_service/{__init__,models,schemas,policy,template,sources,retrieval,answers,feedback,router}.py`，分别负责注册、持久化、请求合同、应用授权、显式模板、资料版本、受控检索、引文答复、幂等反馈和 HTTP。
新增 `backend/tests/test_knowledge_service.py` 与可复用安全 fixture（如有需要）。仅在 `backend/app/main.py`、`database.py` 和 `services/permissions.py` 增量注册；必要时在 ontology 查询中抽取不要求页面权限的领域读函数，工作室路由保留原 types 检查。
新增 `frontend/src/api/knowledgeService.js`、`views/knowledge-service/KnowledgeService.vue` 及聚焦子组件、`utils/knowledgeService.js`、`tests/knowledge-service.test.mjs`；修改 router、Apps 和 workspaceNavigation，新增业务应用入口。

HTTP 前缀 `/api/knowledge-service`：

```text
GET /catalog -> {spaces:[{id,name,types:[{id,key,name}],scopes:[],topics:[]}],can_manage:bool,can_review:bool}
GET /template -> {name,description,schema:{types,relations}}
POST /template {key,name} -> {space_id,change_id,preview}   # 原持久化预览流程，明确确认后安装
POST /template/{change_id}/confirm {} -> {space_id,...}  # 复用领域确认，保留原主体
POST /sources {ontology_id,document_id,group_key,label,scope,topic,effective_from,effective_to,supersedes_id?} -> revision
GET /sources?ontology_id=... -> {items:[revision]}
GET /sources/{id} -> revision + authorized snapshot text and original document entry
GET /terms?ontology_id=...&q=... -> {items:[{id,preferred,aliases,definition,scope}],ambiguous:bool}
POST /query {ontology_id,question,type_id?,scope?,topic?,as_of?,limit:1..50,depth:0..2,generate?:bool} -> {run_id,status,answer,generation,items,facts,citations,sources,conflicts,incomplete,reasons,terms,as_of,scope}
GET /items/{record_id} -> {id,title,version,data,scope,facts,citations,sources,relations,history}
GET /runs/{id} -> currently authorized execution summary (owner/reviewer only)
POST /feedback {run_id?,record_id?,record_version?,category,message,idempotency_key} -> feedback
GET /feedback -> {items:[feedback]}
GET /feedback/{id} -> feedback
POST /feedback/{id}/resolve {expected_version,resolution,idempotency_key} -> feedback
```

`status` 为 supported/conflict/insufficient/incomplete/ambiguous；`generation` 明确 disabled/not_requested/generated/error。`citations` 保留 Evidence 的 id/document_id/snapshot_id/quote/start/end，附 revision_id/label/scope/effective_from/effective_to；前端使用这些字段打开资料修订。API 允许返回额外明确字段，但合同改动必须记录并通知后续任务。

### Task 1: 知识服务后端及安全验收集

**Files:** 上述 backend/app/knowledge_service 全模块；backend/app/main.py、database.py、services/permissions.py；backend/tests/test_knowledge_service.py；必要的 ontology 领域读边界；services/ai.py 的向后兼容可选 token 上限与重试参数。

**Interfaces:** 消费对象与证据领域服务；产出完整上述 HTTP 合同。`knowledge_service` 新页面位与 `knowledge_review` 功能位分别管理查阅和反馈处理；模板安装需原 types/model_manage/relation_manage，修订登记需来源写权限及对应模型写权限。审核反馈还需关联范围可读，不能通过功能位全局越权。

- [ ] **Step 1: 写失败的受控 API 测试及 40 用例清单。** 使用 `_guard.use_temp_db()`，原 fixture 发布一个知识空间、创建含换行 emoji 的原文、候选及人工接受。普通读者明确只有 knowledge_service 页面和所需模型/来源读权限，types 为 false。关键断言：

```python
result = client.post('/api/knowledge-service/query', json={
    'ontology_id': space_id, 'question': '维护规程', 'as_of': '2026-11-22'
})
self.assertEqual(result.status_code, 200)
self.assertFalse(reader.has_page('types'))
self.assertEqual(result.json()['status'], 'supported')
for ev in result.json()['citations']:
    self.assertEqual(snapshot_text[ev['start']:ev['end']], ev['quote'])
```

40 用例分组：直接查阅12（目录/安装预览/确认/重复确认/条目/原文/术语/别名/文号/标点/空输入/无模型）；跨资料8（双来源/相同依据/冲突/候选拒绝/关系接受/关系未接受/歧义/不同范围不冲突）；历史6（当前/过去/未来/明确替代/日期非法/新时间不自动替代）；权限6（普通无types/无入口/模型拒绝/来源拒绝/撤回后运行/他人运行）；不足4（空库/无依据/引文越界/扫描超限）；反馈4（重试一次/伪造关联/版本冲突/处理审计）。测试允许按具体行为增加子用例，必须保持可追溯用例编号。

- [ ] **Step 2: 运行红灯。**

```sh
docker run --rm --network none -e PYTHONDONTWRITEBYTECODE=1 -v "$PWD/backend:/src:ro" -w /tmp kb-workbench-backend:1.11.0-3d39657 sh -c 'cp -R /src /tmp/testbackend && cd /tmp/testbackend && python -m unittest discover -s tests -p test_knowledge_service.py'
```

预期新增路由/模块缺失失败，不能是依赖或测试库护栏错误。

- [ ] **Step 3: 实现持久化和显式模板。** 资料修订不可变且唯一关联 Document/hash/snapshot/显式group，日期验证、替代仅同组且旧版本只在新版本生效后停止当前适用。模板包含知识条目(title/summary/scope/topic)、术语(preferred/aliases/definition/scope)和引用依据/主题/术语相关/明确替代关系；模板预览不发布，不把旧记录自动接管。字段稳定身份由现有注册器生成。运行保存主体、请求、修订、证据ID、状态、提示/模型版本、耗时及预算，不保存隐式推理；不在日志泄露正文或密钥。

- [ ] **Step 4: 实现检索和证据答复。** Unicode NFKC/中文标点和文号规范化；仅在授权词表内扩展别名，歧义返回候选；先来源/模型/范围/时点筛选再限额排序。已接受事实与可见关系提供依据，候选可提示但不提供已核实结论。原文独立搜索允许展示资料摘录，不能把未经审核摘录冒充已接受知识。明确记录扫描预算耗尽；范围不同不判冲突，冲突在截断前检测。模型通过既有 ai.chat_real_meta 可选启用；仅为知识服务设置输出上限1200及零重试，其他调用保持原默认行为；运行记录保存真实usage、最大token及重试信息；只发送本次授权证据，结构化响应中逐项验证 evidence_id/quote/start/end，失败不降格为有依据；无配置保留结构化检索。对已有模型/来源撤回再读运行、条目、术语、关联、修订、反馈均重验，不返回历史缓存正文。

- [ ] **Step 5: 实现反馈闭环。** 所有者读本人运行和反馈，审核者还需 knowledge_review 且关联模型与来源可读；提交 run/item 至少一个且有版本，验证同一用户或明确审核可读。幂等键与请求摘要绑定；同键异载荷409。处理 expected_version 和事务审计，重复同键返回原结果，不同旧版本409。反馈列表先逐项授权后分页，不暴露隐藏计数。

- [ ] **Step 6: 运行聚焦及全量后端测试，提交。** 沿用Step2容器命令，先聚焦绿灯，再一次全量 `python -m unittest discover -s tests`。完整报告写本计划 workspace/task-1-report.md，含红绿证据、40用例映射及API精确返回样例。提交 `feat(knowledge): add authorized Chinese knowledge service`。

### Task 2: 中文知识工作区与反馈界面

**Files:** 上述 frontend 新文件；router/index.js、views/Apps.vue、utils/workspaceNavigation.js、package.json（追加测试）。

**Interfaces:** 消费 Task1 HTTP 合同，使用现有 api axios wrapper 和 auth store；所有菜单按 knowledge_service、所有审核按钮按 knowledge_review，模板按 types/model_manage/relation_manage，不能默认提升用户权限。

- [ ] **Step 1: 写行为红灯。** Node测试使用可测试状态工具覆盖中文状态、Unicode区间、筛选变化清空旧答复、失败清空旧详情、反馈幂等键重试、过期响应忽略、仅当前证据可打开、模型未配置提示、普通读者入口、主导航仍五项。

```js
assert.equal(statusLabel('insufficient'), '信息不足')
assert.equal(validQuote('规程😀\n正文', {start:0,end:3,quote:'规程😀'}), true)
const state = createKnowledgeState()
state.begin({scope:'保障'})
const previous = state.requestId
state.begin({scope:'培训'})
assert.equal(state.accept(previous, {answer:'旧答复'}), false)
assert.equal(state.result, null)
```

- [ ] **Step 2: 运行红灯。** `cd frontend && node --test tests/knowledge-service.test.mjs`，预期新模块不存在。
- [ ] **Step 3: 实现页面。** `/knowledge-service` 页面嵌入现有布局，应用中心显示知识服务入口且命令目录可搜索。空间、主题、范围、日期、中文问题；五个常用任务提供可解释占位和筛选；结果显示状态及原因、条目版本/适用期/证据和原文，历史原文版本与当前原文件分别标注。支持条目详情、关系、历史、来源修订登记表单及术语别名/歧义选择。仅构建者可展开模板预览并明确确认，不在mount写数据。
- [ ] **Step 4: 实现反馈界面。** 当前运行或条目版本提交反馈，成功显示编号；请求失败可保留幂等键重试，切换目标清空旧表单。本人记录、审核者职责列表及带版本处理表单；授权撤回和加载失败清除旧证据、历史和反馈，过期异步响应不能覆盖新范围。按钮忙状态及可访问标签，390px/暗色/键盘可用，无额外主导航。
- [ ] **Step 5: 运行聚焦、全量与构建，提交。**

```sh
cd frontend
node --test tests/knowledge-service.test.mjs
npm test
npm run build
```

报告 workspace/task-2-report.md，提交 `feat(knowledge): add Chinese knowledge workspace`。

### Task 3: 副本业务验收、备份与本机升级

**Files:** docs/knowledge-service-operations.md、CHANGELOG.md、backend/app/config.py、本计划、持久化验收和部署manifest；安全验收脚本位于本计划workspace，收尾先归档再清理。

**Interfaces:** 消费Task1/2最终成品；后端与前端版本1.12.0，保留1.11.0实际镜像和两盘一致性备份。

- [ ] **Step 1: 完整代码审查。** 从本计划起点提交到最终提交生成review-package，修复Critical/Important并针对修复重审，保留审批记录。核对40用例映射，标明合成资料、未进行真实专家模型评测。
- [ ] **Step 2: 成品镜像验收。** 构建1.12.0版本镜像，副本只挂载一致性导出数据。重放知识检索→原文定位→反馈→授权人员处理；普通读者无types。重启检查运行/反馈持久化及重试无重复。逐项对比旧行与文件hash；浏览器桌面/390px暗色/键盘/无旧结果串入，保存截图。
- [ ] **Step 3: 双盘备份与本机切换。** 原生产服务内部一致性备份；保存当前实际镜像、配置、Git bundle和源码，两盘逐文件SHA256。生产仅运行健康与只读烟测，不创建测试账户；从本工作区compose保留绝对原挂载，使用已验收镜像no-build部署。故障保留新数据并按明确回滚说明恢复，不用测试库覆盖。
- [ ] **Step 4: 记录交付。** manifest记录镜像ID/代码commit/健康/原表与文件校验/备份路径/模型测试限制，更新计划勾选、操作说明和CHANGELOG，提交文档。保留分支与worktree，不推送和合并main。归档所需截图与审查/测试/运行证据后只删除本计划scratch。
