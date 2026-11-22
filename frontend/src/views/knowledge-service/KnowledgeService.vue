<template>
  <div class="page ks-page">
    <PageTitle title="知识服务" description="查阅制度和手册，核对适用版本，定位出处。" icon-key="Document">
      <button v-if="capabilities.template" class="ks-button" type="button" :disabled="managementBusy" @click="openManagement('template')">安装知识模板</button>
    </PageTitle>

    <p v-if="notice" class="ks-notice" role="status">{{ notice }}</p>
    <p v-if="catalog.busy" class="ks-panel" role="status">正在读取知识空间…</p>
    <div v-else-if="catalog.error" class="ks-panel ks-stack">
      <p class="ks-error" role="alert">{{ catalog.error }}</p>
      <button class="ks-button" type="button" @click="loadCatalog()">重新读取知识空间</button>
    </div>
    <p v-else-if="!space && !management" class="ks-panel">当前没有可访问的知识空间。</p>

    <KnowledgeManagement
      v-if="management && canManagePanel"
      :key="`${management}-${filters.ontology_id}`"
      ref="managementPanel"
      :kind="management" :space-id="filters.ontology_id"
      :candidates="catalog.data?.source_candidates"
      :candidates-incomplete="catalog.data?.source_candidates_incomplete"
      :revisions="state.sources.data?.items"
      :selected-revision="selectedRevision"
      @close="management = ''; selectedRevision = null"
      @installed="installed" @registered="registered" @permission="permissionChanged" @saving="managementBusy = $event"
    />

    <template v-if="space">
      <nav class="ks-switcher ks-actions" aria-label="知识服务功能">
        <button type="button" class="ks-button" :disabled="managementBusy" :aria-pressed="tab === 'search'" @click="selectTab('search')">知识检索</button>
        <button type="button" class="ks-button" :disabled="managementBusy" :aria-pressed="tab === 'sources'" @click="selectTab('sources')">资料版本</button>
        <button type="button" class="ks-button" :disabled="managementBusy" :aria-pressed="tab === 'feedback'" @click="selectTab('feedback')">
          {{ capabilities.review ? '反馈审核' : '我的反馈' }}
        </button>
      </nav>

      <div class="ks-layout" :class="{ 'ks-with-details': details }">
        <div class="ks-stack ks-main">
          <section v-if="tab !== 'feedback'" class="ks-panel ks-stack">
            <form v-if="tab === 'search'" class="ks-form ks-stack" @submit.prevent="search">
              <div class="ks-between">
                <h3>检索知识</h3>
              </div>
              <div class="ks-tasks ks-actions" aria-label="常用任务">
                <button
                  v-for="task in tasks" :key="task.name" class="ks-button ks-task"
                  type="button" :aria-pressed="queryForm.task === task.name"
                  @click="chooseTask(task)"
                >{{ task.name }}</button>
              </div>
              <p v-if="queryForm.task" class="ks-muted">{{ tasks.find(task => task.name === queryForm.task)?.help }}</p>
              <div class="ks-question">
                <label>
                  <span>问题或关键词</span>
                  <input ref="questionInput" v-model="filters.question" maxlength="500" type="search" :placeholder="queryForm.placeholder" />
                </label>
                <button class="ks-button ks-primary" type="submit" :disabled="!filters.question.trim() || state.query.busy">
                  {{ state.query.busy ? '正在检索…' : '检索知识' }}
                </button>
              </div>

              <div class="ks-form-grid ks-filters">
                <label>
                  <span>知识空间</span>
                  <select :value="filters.ontology_id" :disabled="managementBusy" @change="chooseSpace($event.target.value)">
                    <option v-for="item in catalog.data.spaces" :key="item.id" :value="item.id">{{ item.name }}</option>
                  </select>
                </label>
                <label>
                  <span>适用范围</span>
                  <select v-model="filters.scope">
                    <option value="">全部范围</option>
                    <option v-for="scope in scopeOptions" :key="scope" :value="scope">{{ scope }}</option>
                  </select>
                </label>
                <label>
                  <span>主题</span>
                  <select v-model="filters.topic">
                    <option value="">全部主题</option>
                    <option v-for="topic in space.topics" :key="topic" :value="topic">{{ topic }}</option>
                  </select>
                </label>
                <label>
                  <span>条目类型</span>
                  <select v-model="filters.type_id">
                    <option value="">全部类型</option>
                    <option v-for="type in space.types" :key="type.id" :value="type.id">{{ type.name }}</option>
                  </select>
                </label>
                <label>
                  <span>适用日期</span>
                  <input v-model="filters.as_of" type="date" />
                </label>
              </div>
              <div class="ks-between">
                <label class="ks-check"><input v-model="filters.generate" type="checkbox" /><span>请求生成式答复</span></label>
                <button class="ks-button ks-text" type="button" :disabled="state.terms.busy" @click="lookupTerms">
                  {{ state.terms.busy ? '正在查询术语…' : '查术语与别名' }}
                </button>
              </div>
              <p v-if="catalog.data.incomplete || space.incomplete" class="ks-muted">筛选选项受可见范围和检索上限限制。</p>
            </form>

            <template v-else>
              <div class="ks-between">
                <h3>资料版本</h3>
                <button
                  v-if="capabilities.sources" class="ks-button"
                  type="button" :disabled="managementBusy" @click="openManagement('sources')"
                >登记资料修订</button>
              </div>
              <label class="ks-form">
                <span>知识空间</span>
                <select :value="filters.ontology_id" :disabled="managementBusy" @change="chooseSpace($event.target.value)">
                  <option v-for="item in catalog.data.spaces" :key="item.id" :value="item.id">{{ item.name }}</option>
                </select>
              </label>
              <p v-if="state.sources.busy" role="status">正在加载资料版本…</p>
              <p v-if="state.sources.error" class="ks-error" role="alert">{{ state.sources.error }}</p>
              <button v-if="state.sources.error" class="ks-button" type="button" :disabled="managementBusy" @click="loadSources(state.sources.target)">重新加载资料</button>
              <template v-if="state.sources.data">
                <ul v-if="state.sources.data.items.length" class="ks-rows">
                  <li v-for="source in state.sources.data.items" :key="source.id" class="ks-row ks-between">
                    <div>
                      <strong>{{ source.label }}</strong>
                      <div class="ks-meta">
                        <span v-if="source.scope">{{ source.scope }}</span><span v-if="source.topic">{{ source.topic }}</span>
                        <span>{{ effectivePeriod(source) }}</span>
                      </div>
                    </div>
                    <div class="ks-actions">
                      <button class="ks-button ks-text" type="button" @click="showDetail(openSource, source.id)">查看快照与版本</button>
                      <button v-if="management === 'sources' && capabilities.sources" class="ks-button ks-text" type="button" :disabled="managementBusy" @click="selectPredecessor(source)">
                        选择为替代对象
                      </button>
                    </div>
                  </li>
                </ul>
                <p v-else>本页暂无资料版本。</p>
                <p v-if="state.sources.data.incomplete && state.sources.data.next_offset == null" class="ks-muted">已显示扫描限额内的资料。</p>
                <div class="ks-actions">
                  <button v-if="state.sources.target > 0" class="ks-button" type="button" :disabled="managementBusy" @click="loadSources(state.sources.target - 50)">上一页</button>
                  <button v-if="state.sources.data.next_offset != null" class="ks-button" type="button" :disabled="managementBusy" @click="loadSources(state.sources.data.next_offset)">下一页</button>
                </div>
              </template>
            </template>
          </section>

          <template v-if="tab === 'search'">
            <section v-if="terms || state.terms.error" class="ks-panel ks-stack" aria-label="术语与别名">
              <h3>术语与别名</h3>
              <p v-if="state.terms.error" class="ks-error" role="alert">{{ state.terms.error }}</p>
              <p v-if="ambiguous" class="ks-error" role="status">找到多个含义。请选择术语或调整适用范围。</p>
              <ul v-if="terms?.length" class="ks-rows">
                <li v-for="term in terms" :key="term.id" class="ks-row">
                  <div class="ks-between">
                    <strong>{{ term.preferred }}</strong>
                    <button class="ks-button ks-text" type="button" @click="pickTerm(term)">使用此术语<span v-if="term.scope"> · {{ term.scope }}</span></button>
                  </div>
                  <p v-if="term.definition">{{ term.definition }}</p>
                  <p v-if="term.aliases?.length" class="ks-meta">别名 · {{ term.aliases.join('、') }}</p>
                </li>
              </ul>
              <p v-else-if="!state.terms.error">未找到匹配术语。</p>
              <p v-if="state.terms.data?.incomplete" class="ks-muted">仅显示检索限额内的术语。</p>
            </section>

            <section v-if="state.query.busy || state.query.error || state.result" class="ks-panel ks-stack" aria-label="检索结果">
              <p v-if="state.query.busy" role="status">{{ state.query.target ? '正在核对原查询的访问权限…' : '正在按选定范围检索…' }}</p>
              <p v-if="state.query.error" class="ks-error" role="alert">{{ state.query.error }}</p>
              <template v-if="state.result">
                <div class="ks-between">
                  <h3>检索结果</h3>
                  <div class="ks-actions">
                    <button class="ks-button" type="button" @click="showDetail(openRun, state.result.run_id)">查询回放</button>
                    <button class="ks-button" type="button" @click="runFeedback">反馈本次查询</button>
                  </div>
                </div>
                <KnowledgeResult :result="state.result" :type-names="typeNames" allow-feedback
                  @item="showItem" @source="(id, citation) => showSource(id, citation, state.result)" @feedback="item => showDetail(startRunItemFeedback, state.result, item)" />
              </template>
            </section>
          </template>

          <section v-if="tab === 'feedback'" class="ks-panel ks-stack">
            <div class="ks-between">
              <h3>{{ capabilities.review ? '职责范围内的反馈' : '我的反馈' }}</h3>
              <button class="ks-button" type="button" :disabled="state.feedbackList.busy" @click="loadFeedback()">刷新记录</button>
            </div>
            <p v-if="state.feedbackList.busy" role="status">正在加载反馈…</p>
            <p v-if="state.feedbackList.error" class="ks-error" role="alert">{{ state.feedbackList.error }}</p>
            <template v-if="state.feedbackList.data">
              <ul v-if="state.feedbackList.data.items.length" class="ks-rows">
                <li v-for="feedback in state.feedbackList.data.items" :key="feedback.id" class="ks-row">
                  <div class="ks-between">
                    <strong>{{ feedback.category }}</strong>
                    <span class="ks-tag" :data-tone="feedback.status === 'resolved' ? 'success' : 'warning'">{{ feedbackStatus(feedback.status) }}</span>
                  </div>
                  <p class="ks-preline">{{ feedback.message }}</p>
                  <div class="ks-meta"><span>{{ dateTime(feedback.created_at) }}</span></div>
                  <button class="ks-button ks-text" type="button" @click="showDetail(openFeedback, feedback.id)">查看反馈</button>
                </li>
              </ul>
              <p v-else>本页暂无反馈。</p>
              <p v-if="state.feedbackList.data.incomplete" class="ks-muted">记录受扫描上限限制。</p>
              <div class="ks-actions">
                <button v-if="state.feedbackList.target > 0" class="ks-button" type="button" @click="loadFeedback(state.feedbackList.target - 50)">上一页</button>
                <button v-if="state.feedbackList.data.next_offset != null" class="ks-button" type="button" @click="loadFeedback(state.feedbackList.data.next_offset)">下一页</button>
              </div>
            </template>
          </section>
        </div>

        <section v-if="details" ref="detailPanel" class="ks-panel ks-stack ks-detail" tabindex="-1" aria-labelledby="ks-detail-title">
          <div class="ks-between">
            <h3 id="ks-detail-title">{{ detailTitle }}</h3>
            <button class="ks-button ks-text" type="button" @click="dismissDetail">关闭</button>
          </div>
          <p v-if="detailState?.busy" role="status">正在加载…</p>
          <p v-if="detailState?.error" class="ks-error" role="alert">{{ detailState.error }}</p>

          <KnowledgeSource
            v-if="details === 'source' && state.source.data"
            :source="state.source.data" :comparison="state.comparison" :citation="state.source.target?.citation"
            :checking="state.source.target?.checking"
            @compare="compareSource"
          />

          <template v-else-if="details === 'item' && state.item.data">
            <h4>{{ state.item.data.title }}</h4>
            <p v-if="state.item.data.summary">{{ state.item.data.summary }}</p>
            <div class="ks-meta">
              <span>当前版本 {{ state.item.data.version }}</span>
              <span v-if="typeNames.get(state.item.data.type_id)">{{ typeNames.get(state.item.data.type_id) }}</span>
              <span v-if="state.item.data.scope">{{ state.item.data.scope }}</span>
              <span v-if="state.item.data.topic">{{ state.item.data.topic }}</span>
            </div>
            <button class="ks-button" type="button" @click="showDetail(startItemFeedback, state.item.data)">反馈当前条目版本</button>
            <KnowledgeEvidence :facts="state.item.data.facts" :citations="state.item.data.citations" :items="[state.item.data]" @source="(id, citation) => showSource(id, citation, state.item.data)" />
            <section v-if="state.item.data.relations.length" class="ks-stack">
              <h4>关联条目</h4>
              <ul class="ks-rows">
                <li v-for="relation in state.item.data.relations" :key="relation.claim_id" class="ks-row">
                  <button class="ks-button ks-text" type="button" @click="showItem(relation.target)">{{ relation.title || '查看关联条目' }}</button>
                </li>
              </ul>
            </section>
            <section class="ks-stack">
              <h4>条目版本历史</h4>
              <p v-if="!state.item.data.history.length" class="ks-muted">暂无可显示的版本记录。</p>
              <details v-for="version in state.item.data.history" :key="version.version" class="ks-row">
                <summary>版本 {{ version.version }} · {{ dateTime(version.created_at) }}</summary>
                <dl v-if="historyFields(version).length" class="ks-history">
                  <template v-for="field in historyFields(version)" :key="field.label">
                    <dt>{{ field.label }}</dt><dd>{{ displayValue(field.value) }}</dd>
                  </template>
                </dl>
                <details v-if="technicalHistoryFields(version.data).length">
                  <summary>高级 · 原始字段</summary>
                  <dl class="ks-history">
                    <template v-for="[key, value] in technicalHistoryFields(version.data)" :key="key">
                      <dt>{{ key }}</dt><dd>{{ displayValue(value) }}</dd>
                    </template>
                  </dl>
                </details>
              </details>
            </section>
            <p v-if="state.item.data.incomplete" class="ks-muted">仅显示限额内的事实、关系及历史。</p>
          </template>

          <template v-else-if="details === 'run' && state.run.data">
            <h4>{{ state.run.data.request.question }}</h4>
            <div class="ks-meta">
              <span>{{ statusLabel(state.run.data.status) }}</span>
              <span v-if="state.run.data.request.scope">{{ state.run.data.request.scope }}</span>
              <span v-if="state.run.data.request.topic">{{ state.run.data.request.topic }}</span>
              <span>适用时点 {{ state.run.data.request.as_of }}</span>
            </div>
            <p class="ks-muted">原查询于 {{ dateTime(state.run.data.created_at) }} 执行，耗时 {{ state.run.data.elapsed_ms }} 毫秒。引文已按当前权限校验。</p>
            <p v-if="state.run.data.incomplete" class="ks-muted">原查询选中的内容受检索上限限制。</p>
            <KnowledgeResult :result="state.run.data" :type-names="typeNames" replay allow-feedback
              @item="showItem" @source="(id, citation) => showSource(id, citation, state.run.data)" @feedback="item => showDetail(startRunItemFeedback, state.run.data, item)" />
            <details class="ks-row">
              <summary>检索预算</summary>
              <p class="ks-meta">
                结果上限 {{ state.run.data.request.limit }} 项 · 关系深度 {{ state.run.data.request.depth }} 跳
                <template v-if="state.run.data.budget?.scan_limit"> · 扫描上限 {{ state.run.data.budget.scan_limit }}</template>
              </p>
            </details>
          </template>

          <template v-else-if="details === 'submit' && feedbackTarget">
            <p class="ks-muted">{{ feedbackTarget.label }}</p>
            <div v-if="state.submission.data" class="ks-notice ks-stack" role="status">
              <strong>反馈已提交</strong>
              <span>反馈编号 {{ state.submission.data.id }}</span>
              <button class="ks-button ks-text" type="button" @click="showDetail(openFeedback, state.submission.data.id)">查看此反馈</button>
            </div>
            <form v-else class="ks-form ks-stack" @submit.prevent="submitFeedback">
              <label>
                <span>反馈类别</span>
                <select v-model="feedbackForm.category" :disabled="state.submission.busy">
                  <option v-for="category in feedbackCategories" :key="category">{{ category }}</option>
                </select>
              </label>
              <label>
                <span>问题说明</span>
                <textarea v-model="feedbackForm.message" placeholder="请描述有疑问的内容或出处" required maxlength="2000" rows="4" :disabled="state.submission.busy" />
              </label>
              <button class="ks-button ks-primary" type="submit" :disabled="!feedbackForm.message.trim() || state.submission.busy">
                {{ state.submission.busy ? '正在提交…' : state.submission.error ? '重试提交' : '提交反馈' }}
              </button>
            </form>
          </template>

          <template v-else-if="details === 'feedback' && state.feedback.data">
            <div class="ks-between">
              <h4>{{ state.feedback.data.category }}</h4>
              <span class="ks-tag" :data-tone="state.feedback.data.status === 'resolved' ? 'success' : 'warning'">{{ feedbackStatus(state.feedback.data.status) }}</span>
            </div>
            <p class="ks-preline">{{ state.feedback.data.message }}</p>
            <p class="ks-meta">反馈编号 {{ state.feedback.data.id }} · {{ dateTime(state.feedback.data.created_at) }}</p>
            <div class="ks-actions">
              <button v-if="state.feedback.data.run_id" class="ks-button ks-text" type="button" @click="showDetail(openRun, state.feedback.data.run_id)">查看关联查询</button>
              <button v-if="state.feedback.data.record_id" class="ks-button ks-text" type="button" @click="showItem(state.feedback.data.record_id)">
                查看关联条目（反馈版本 {{ state.feedback.data.record_version }}）
              </button>
            </div>
            <div v-if="state.feedback.data.status === 'resolved'" class="ks-row">
              <h4>处理结论</h4>
              <p class="ks-preline">{{ state.feedback.data.resolution }}</p>
              <p class="ks-meta">{{ dateTime(state.feedback.data.resolved_at) }} · 反馈版本 {{ state.feedback.data.version }}</p>
            </div>
            <form v-else-if="capabilities.review" class="ks-form ks-stack" @submit.prevent="resolveFeedback">
              <label>
                <span>处理结论</span>
                <textarea v-model="resolution" required maxlength="2000" rows="4" :disabled="state.resolution.busy" />
              </label>
              <p class="ks-meta">正在处理反馈版本 {{ state.feedback.data.version }}</p>
              <p v-if="state.resolution.error" class="ks-error" role="alert">{{ state.resolution.error }}</p>
              <button class="ks-button ks-primary" type="submit" :disabled="!resolution.trim() || state.resolution.busy">
                {{ state.resolution.busy ? '正在处理…' : state.resolution.error ? '重试处理' : '确认处理' }}
              </button>
            </form>
          </template>
        </section>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import PageTitle from '../../components/PageTitle.vue'
import { useAuthStore } from '../../stores/auth'
import { dateTime, displayValue, effectivePeriod, feedbackCategories, feedbackStatus, statusLabel } from '../../utils/knowledgeService.js'
import { useKnowledgeWorkspace } from './useKnowledgeWorkspace.js'
import KnowledgeEvidence from './KnowledgeEvidence.vue'
import KnowledgeManagement from './KnowledgeManagement.vue'
import KnowledgeResult from './KnowledgeResult.vue'
import KnowledgeSource from './KnowledgeSource.vue'

const route = useRoute()
const {
  state, catalog, filters, space, scopeOptions, capabilities, tab, details, notice, queryForm, feedbackTarget,
  feedbackForm, resolution, loadCatalog, refreshAuthorization, changeSpace, switchTab, search, lookupTerms, pickTerm, loadSources,
  openItem, openSource, compareSource, openRun, closeDetails, startRunFeedback, startRunItemFeedback, startItemFeedback, submitFeedback,
  loadFeedback, openFeedback, resolveFeedback,
} = useKnowledgeWorkspace(useAuthStore(), route.query.scope, route.query.question)

const tasks = [
  { name: '查制度', placeholder: '输入制度名称、文号或适用条款', help: '可以用制度名称或文号查找，在适用日期选择需要核对的时间。', topics: ['制度流程', '制度'] },
  { name: '查手册', placeholder: '输入手册名称或具体操作', help: '可以按手册名称或操作关键词检索，也可选择维护等已配置主题。', topics: ['手册', '维护'] },
  { name: '看差异', placeholder: '输入要比较的资料名称', help: '打开一项资料的快照，再选择同组版本对照。' },
  { name: '追出处', placeholder: '输入需要核实的表述', help: '在检索结果的证据引文中选择「定位原文」。' },
  { name: '提疑问', placeholder: '输入希望反馈的问题或条目', help: '检索后可反馈本次查询或具体条目版本。' },
]
const detailTitles = { item: '知识条目详情', source: '资料快照与版本', run: '查询回放', submit: '提交知识反馈', feedback: '反馈详情' }
const detailTitle = computed(() => detailTitles[details.value])
const detailState = computed(() => state[details.value === 'submit' ? 'submission' : details.value])
const detailPanel = ref(null)
const questionInput = ref(null)
const managementPanel = ref(null)
const management = ref('')
const managementBusy = ref(false)
const typeNames = computed(() => new Map((space.value?.types || []).map(type => [type.id, type.name])))
const selectedRevision = ref(null)
const terms = computed(() => state.terms.data?.items || (state.result?.terms?.length || state.result?.status === 'ambiguous' ? state.result.terms || [] : null))
const ambiguous = computed(() => state.terms.data ? state.terms.data.ambiguous : state.result?.status === 'ambiguous')
const canManagePanel = computed(() => management.value === 'template' ? capabilities.value.template : capabilities.value.sources)
let returnFocus = null

async function chooseTask(task) {
  queryForm.task = task.name
  queryForm.placeholder = task.placeholder
  const topic = task.topics?.find(value => space.value?.topics.includes(value))
  if (topic) filters.topic = topic
  if (task.name === '看差异') {
    await selectTab('sources')
    return
  }
  if (task.name === '提疑问' && state.result) {
    runFeedback()
    return
  }
  questionInput.value?.focus()
}

async function selectTab(next) {
  if (next === tab.value || managementBusy.value) return
  if (management.value === 'sources') management.value = ''
  await switchTab(next)
}

function chooseSpace(id) {
  if (managementBusy.value) return
  management.value = ''
  selectedRevision.value = null
  changeSpace(id)
  if (tab.value === 'sources') void loadSources()
}

async function showDetail(action, ...args) {
  if (!detailPanel.value?.contains(document.activeElement)) returnFocus = document.activeElement
  const task = action(...args)
  await nextTick()
  detailPanel.value?.focus()
  await task
}
const showItem = id => showDetail(openItem, id)
const showSource = (id, citation, owner) => showDetail(openSource, id, citation, owner)

function dismissDetail() {
  closeDetails()
  if (returnFocus?.isConnected) returnFocus.focus()
  else questionInput.value?.focus()
  returnFocus = null
}

function runFeedback() {
  void showDetail(startRunFeedback)
}

const historyLabels = { title: '标题', summary: '摘要', scope: '适用范围', topic: '主题',
  preferred: '首选词', aliases: '别名', definition: '释义' }
function historyFields(version) {
  const current = state.item.data
  const data = { ...version.data }
  if (current.version === version.version) {
    for (const key of ['title', 'summary', 'scope', 'topic']) {
      if (current[key]) data[key] = current[key]
    }
  }
  return Object.entries(data)
    .filter(([key]) => Object.hasOwn(historyLabels, key))
    .map(([key, value]) => ({ label: historyLabels[key], value }))
}
function technicalHistoryFields(data) {
  return Object.entries(data || {}).filter(([key]) => !Object.hasOwn(historyLabels, key))
}

async function openManagement(kind) {
  if (managementBusy.value) return
  management.value = kind
  selectedRevision.value = null
  await nextTick()
  const panel = managementPanel.value?.$el
  const firstControl = panel?.querySelector('input, select') || panel?.querySelector('button')
  firstControl?.focus()
}
async function selectPredecessor(source) {
  if (managementBusy.value) return
  selectedRevision.value = source
  await nextTick()
  managementPanel.value?.$el?.querySelector('select')?.focus()
}

async function installed(spaceId) {
  management.value = ''
  await selectTab('search')
  await loadCatalog(spaceId)
  notice.value = '知识服务模板已安装。'
}

async function registered() {
  management.value = ''
  selectedRevision.value = null
  await loadCatalog()
  notice.value = '资料修订已登记。'
}

async function permissionChanged(message) {
  management.value = ''
  selectedRevision.value = null
  await refreshAuthorization(message)
}

watch(canManagePanel, allowed => {
  if (!allowed) management.value = ''
}, { flush: 'sync' })
</script>

<style src="./knowledge-service.css"></style>
