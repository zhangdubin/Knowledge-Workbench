# Palantir 应用能力与中文知识服务

适用范围为组织内部制度、业务手册、培训材料、项目资料与经审核的参考知识。以下为文档调研与优先级建议。Palantir 能力来自公开产品文档，本项目能力依据 1.11.0 验收记录及代码入口。首期建议优先查阅当前适用条文、核对引用、由专家处理分歧，并追踪资料修订后的影响。

## 使用者与构建者

Foundry 将入口按用途分开。Object Explorer 提供可直接使用的搜索与探索，Object Views 为单个对象聚合资料和关联内容。Workshop 供构建者用对象、关系、动作和组件配置交互业务应用，Slate 支持直接接入数据集和更深入的代码定制。Carbon 组合既有应用、分析和对象视图，为特定岗位整理日常工作区。Quiver 支持探索式聚合、统计和时间序列分析，分析结果可发布为面向其他用户的只读仪表盘。 [应用参考与比较（英）](https://www.palantir.com/docs/foundry/ontology/applications) · [中文应用参考](https://www.palantir.com/docs/zh/foundry/ontology/applications) · [应用案例开发](https://www.palantir.com/docs/zh/foundry/app-building/overview)

本项目已核实全局搜索、资料库、知识笔记、应用工作区、关联图谱、本体工作室及角色权限等导航入口。本体工作室包含模式与修订、对象与历史、资料加工、事实与证据。1.11.0 验收确认候选审核、证据查询、历史、来源撤回、矛盾与时间筛选、只读账号写入拒绝。查询上限为 50 项、关系深度最多两跳，预算耗尽会标注结果不完整。建议普通用户从中文查阅和反馈任务进入，专家从待审事项进入，模型配置由本体构建人员在工作室维护。现有“驾驶舱”“AI 设置”等路由仅证明入口存在，相关能力的成熟度需另行验证。 [动态本体验收](../dynamic-ontology-operations.md) · [路由](../../frontend/src/router/index.js) · [应用工作区](../../frontend/src/views/AppWorkspace.vue)

## 能力、现状与验收

优先级为调研建议。首期优先覆盖知识查阅、引用、复核与更新影响。后续增量以实测需求和可靠数据为前提。表内“未见”指本次导航和验收材料没有发现对应能力。

| 能力 | 厂商功能 | 项目现状与建议验收 |
|---|---|---|
| Object Explorer 搜索与对象集 | 关键字与属性搜索，支持引号、AND/OR、通配和模糊匹配。按对象类型、属性、关键词和链接筛选，结果可表格排序、选列、预览及进入对象页。可配置首页类型分组与深链接。 [搜索语法](https://www.palantir.com/docs/zh/foundry/object-explorer/search-syntax) · [筛选](https://www.palantir.com/docs/zh/foundry/object-explorer/filter-results) · [结果](https://www.palantir.com/docs/zh/foundry/object-explorer/view-results) | 部分具备。已有全局检索入口、本体证据查询和关系路径。首期以中文文号、简称、术语及条款搜索为入口。验收以同一文号跨修订检索为例，可按适用范围、时点、资料类型查到正确条款并打开可读原文。 |
| Explorer 图表、转向关联类型、比较与保存 | 图表可按属性或链接对象聚合，交互筛选并继续下钻。Pivot 将探索主体转为关联对象类型。比较可选两个动态对象集或已保存探索。保存探索保留筛选与图表配置，保存列表固定对象成员。还可对选集调用动作、交给其他应用或导出。 [图表](https://www.palantir.com/docs/zh/foundry/object-explorer/explore-charts) · [关联转向](https://www.palantir.com/docs/zh/foundry/object-explorer/pivot-linked) · [比较](https://www.palantir.com/docs/zh/foundry/object-explorer/compare-object-sets) · [保存探索](https://www.palantir.com/docs/zh/foundry/object-explorer/save-explorations) · [保存列表](https://www.palantir.com/docs/zh/foundry/object-explorer/save-lists) · [动作](https://www.palantir.com/docs/zh/foundry/object-explorer/apply-actions) | 部分具备。已有关系查询，未见统一对象集探索和保存流程。首期支持从修订转到受影响条款和知识条目、并排查看双版本证据。后续支持保存动态条件、保存静态清单、按状态聚合下钻和集合差异。验收时新增资料进入动态集合，静态清单成员保持原样，接收人按当前权限重新取数。 |
| Object Views 对象详情 | 360 视图聚合属性、关系、指标、相关应用与资料。可使用 Workshop 标签页、角色展示配置、视图版本发布和可复用配置。对象评论支持提及、附件和图像。 [对象视图](https://www.palantir.com/docs/zh/foundry/object-views/overview) · [标签页](https://www.palantir.com/docs/zh/foundry/object-views/config-workshop-tabs) · [展示配置](https://www.palantir.com/docs/zh/foundry/object-views/config-profiles) · [视图版本](https://www.palantir.com/docs/zh/foundry/object-views/manage-versions) · [评论](https://www.palantir.com/docs/zh/foundry/object-views/comment-on-objects) | 部分具备。已有对象历史、证据与笔记基础。首期建议资料或知识条目详情统一展示当前修订、适用范围、证据、关联资料和复核状态，相关按钮按角色显示且服务端重新授权。后续再评估可复用模板、评论及提及。 |
| AIP Logic 与评估 | 可视化组合对象属性、变量、LLM、转换、执行和动作等块，定义输入、工具和输出，支持调试、发布及模型或提示对比。写入需经发布的操作调用，也可经 Automate 产生待批准提案。评估套件包含用例、期望结果及评估函数，可对比批次、用例指标、执行时间和踪迹。 [核心概念](https://www.palantir.com/docs/zh/foundry/logic/concepts) · [评估套件](https://www.palantir.com/docs/zh/foundry/logic/evaluations-create-suite) · [指标面板](https://www.palantir.com/docs/zh/foundry/logic/evaluations-metrics-dashboard) · [自动化](https://www.palantir.com/docs/zh/foundry/logic/aip-logic-integration-automate) | 部分具备。已有抽取候选、逐条审核、来源追溯及产品回归用例，真实外部模型效果未在本次验收验证。首期建议用固定中文用例校验修订选择、原文定位、矛盾提示、证据不足与拒绝越权，记录模型和提示版本。发布知识由专家动作确认。可视化逻辑编辑器和评估仪表盘可后续评估。 |
| Object Monitors / Automate | Object Monitors 已由 Automate 取代。旧工具文档提供对象集输入、事件或阈值条件、实时/计划/手动评估、活动日志、订阅、静音、通知模板和受权动作等参考。 [产品替代说明](https://www.palantir.com/docs/zh/foundry/object-monitors/overview) · [评估](https://www.palantir.com/docs/zh/foundry/object-monitors/evaluation) · [通知](https://www.palantir.com/docs/zh/foundry/object-monitors/notifications) | 未见通用监视和订阅入口。首期如纳入更新闭环，可先用站内待复核清单和影响记录。后续按资料发布、替代或撤回事件订阅。验收覆盖重复事件仅产生一条待办、失败可追查、撤权后通知及访问不泄露标题、条文或计数。 |
| Vertex 图谱、事件、时间序列、场景 | 用关系遍历、参数化模板、样式及保存共享来生成或探索图。关联事件有时间范围，可在时间轴过滤。时间序列表示随时间变化的测量值，可配置阈值。场景调用发布模型预测指定输入下的结果，支持串联模型及基线对比。 [关系图](https://www.palantir.com/docs/zh/foundry/vertex/explore-object-relationships) · [模板](https://www.palantir.com/docs/zh/foundry/vertex/graphs-template) · [事件](https://www.palantir.com/docs/zh/foundry/vertex/events-overview) · [时间序列](https://www.palantir.com/docs/zh/foundry/vertex/explore-time-series) · [场景](https://www.palantir.com/docs/zh/foundry/vertex/scenarios-overview) | 部分具备。已有图谱入口、路径及时间过滤。首期显示“引用、替代、适用于、解释”关系的方向和证据，验收能从旧条款追到新版和受影响知识条目。事件轴可用于修订、发布和撤回历史。趋势分析需连续观测数据，场景模拟需要可验证模型和明确问题，建议延期。 |
| Machinery 流程挖掘 | 将具有可枚举状态的对象和带时间的状态日志映射为流程。可绘制期望路径或从日志挖掘实际转换、节点停留、偏离及相关动作，以 Workshop 组件呈现实际状态。 [流程概念](https://www.palantir.com/docs/zh/foundry/process-mining/core-concepts) · [设置](https://www.palantir.com/docs/zh/foundry/process-mining/process-mining-setup) · [投入使用](https://www.palantir.com/docs/zh/foundry/process-mining/process-mining-operationalize) | 部分具备审核与历史日志基础，未见自动挖掘与流程图。后续用候选、待审、退回、发布和撤回事件分析复核积压。验收用可重放日志核对实际路径、耗时及重复事件去重，历史缺失单独标记。 |
| Foundry Rules | 将规则和规则提案建模为对象。工作流负责人配置输入、输出、转换及执行。规则作者通过 Workshop 编辑输入和逻辑块，规则提案可审核后应用。输出可限制允许值并设置默认值。部分 Taurus 管道配置属于历史版本。 [概念](https://www.palantir.com/docs/zh/foundry/foundry-rules/core-concepts) · [规则逻辑](https://www.palantir.com/docs/zh/foundry/foundry-rules/rule-logic) · [工作流配置](https://www.palantir.com/docs/zh/foundry/foundry-rules/foundry-rules-workflow-configuration) · [审核应用](https://www.palantir.com/docs/zh/foundry/foundry-rules/workshop-application) | 部分具备确认、提案式审核与版本基础，未见通用低代码规则编排。首期可借鉴适用期检查和发布前规则，将命中原因带入审阅。验收可重放同一规则版本与输入，只有有授权的角色能启用或批准。后续按新增规则需求评估编辑器。 |
| Map 与时间轴 | 汇集地理对象、图层、注释、事件和时间序列，支持空间筛选、交互选取、时间窗口播放、模板和 Workshop 嵌入。 [地图总览](https://www.palantir.com/docs/zh/foundry/map/overview) · [时间轴](https://www.palantir.com/docs/zh/foundry/map/timeline) · [模板](https://www.palantir.com/docs/zh/foundry/map/templates) | 未见对应 GIS 工作区。首期可用文字化的适用区域和资料修订时间轴。仅在档案或培训场馆查询出现明确地理需求时评估 GIS。届时验收不同图层及空间筛选结果服从资料权限。 |
| 动态调度 | 将任务与资源建模，在 Workshop 的日历或甘特图展示。甘特图的场景暂存改动，通过保存动作提交。验证规则判定约束，建议函数标示适合时段，搜索函数寻找候选安排。 [概念](https://www.palantir.com/docs/zh/foundry/dynamic-scheduling/scheduling-concepts) · [日历](https://www.palantir.com/docs/zh/foundry/dynamic-scheduling/scheduling-calendar-overview) · [规则](https://www.palantir.com/docs/zh/foundry/dynamic-scheduling/scheduling-validation-rules) | 未见对应调度工作区。首期用复核截止日期和重要修订生效日期即可。若将来确有培训教室或专家时段协调需求，可评估通用日历和冲突检查。届时验收草案独立、提交前重新查冲突、并发修改可识别。 |

## 平台层参考

- **平台与入门。** 厂商以数据、模型、业务逻辑、分析和动作围绕本体组织能力，分别介绍管理者、构建者及最终用户的入门路径。项目已有工作台与使用指南入口。首期建议用中文示例引导常用查阅、反馈和复核任务，验收普通用户以自己的角色走通流程。 [平台概览](https://www.palantir.com/docs/zh/foundry/platform-overview/overview) · [入门](https://www.palantir.com/docs/zh/foundry/getting-started/overview)
- **数据连接与模型。** 厂商以连接、变换、管道管理形成数据供应，并通过建模目标支持模型评估、审批、版本和部署。项目已核验文档上传、分块、候选加工和确认，外部连接器、通用数据管道及模型治理未在本次材料核实。首期可按现有上传路径校验源文档哈希、修订和派生记录。 [数据集成](https://www.palantir.com/docs/zh/foundry/data-integration/overview) · [模型集成](https://www.palantir.com/docs/zh/foundry/model-integration/overview)
- **分析与产品交付。** 厂商提供探索分析与外部分析连通性，并以 DevOps 和 Marketplace 打包、安装、更新产品资源。项目有驾驶舱路由和 1.11.0 部署回滚证据，尚无等价能力证据。初期以审核队列、资料更新记录及现有部署验证覆盖实际任务，后续可视需求评估只读统计或受控配置包。 [分析](https://www.palantir.com/docs/zh/foundry/analytics/overview) · [产品交付](https://www.palantir.com/docs/zh/foundry/devops/overview)
- **安全与管理。** 厂商概览描述治理、细粒度访问控制、认证、审计与资源管理。项目已有角色入口和只读账号验收。现有混合来源导入对象仅在全部来源可读且有效时展示完整对象。首期用双角色验证原文、答案、集合、图谱、派生知识与待办统一执行权限，并按审计记录追查审核和发布。 [安全与治理](https://www.palantir.com/docs/zh/foundry/security/overview) · [管理](https://www.palantir.com/docs/zh/foundry/administration/overview)

## 四条首期知识服务验收路径

1. **查当前制度或手册。** 用中文提问“今年新员工入职培训签到材料保留多久”。按组织范围、业务对象和生效日期选择适用修订，展示条款号、精确原文引用和文档版本，允许按历史日期复查。用同一问题在两个岗位账号重放，验证无权限资料无法通过答案、搜索提示、链接或统计间接读出。引用不足时明确显示“信息不足”。
2. **处理跨文档冲突。** 培训管理办法和办理手册对提交期限有差异。并列展示两段原文、来源类型、修订、生效期及适用范围，把事项交给有授权的专家。适用范围不同的结论分别保留，真实冲突记录审查理由和处理结果。用测试语料验证新版或发布日期较晚的条目需要具备明确的适用与替代依据。
3. **形成可复用知识。** 专家将同类问题整理为标准问答或办事说明，保留证据和适用范围，随后审核发布。普通用户可检索已经发布、对其开放的版本。待审提案、拒绝条目及其关系路径继续受状态和权限控制。验收能由每个已发布结论打开获准阅读的对应版本及引文。
4. **从反馈到修订影响。** 用户对说明提交疑问，专家处理后记录结论。上游资料替代或撤回时，以已验证的引用关系定位受影响的条目、笔记及复核任务。验收复核任务可回溯触发来源和状态，受影响条目按新状态处理，审核后可切换至新引用，历史仍可按权限查看。

## 覆盖与限制

在本地目录快照中检查了 160 个中文页面的目录标题、节标题或导读，详读支撑上述功能区别的关键页，并对读了中英文两篇本体应用概览。160 页包括 Logic 10、Object Explorer 14、Object Monitors 11、Object Views 17、Vertex 26、Machinery 4、Foundry Rules 27、Map 32、动态调度 10，以及九个顶层概览各 1 页。专项产品中 Workshop、Slate、Carbon、Quiver 和 Automate 的判断限于应用参考或交叉文献所述范围。中文采集页标注机器翻译。结论属于文档能力调研，当前项目现状来自指定验收记录与入口核查。 [本地目录](palantir-source-index.json) · [本体应用参考（英）](https://www.palantir.com/docs/foundry/ontology/applications)
