<template>
  <div class="page dev-ws" v-loading="loading && !project">
    <!-- ============ 顶部：项目抬头 ============ -->
    <header class="ws-head">
      <div class="ws-head-left">
        <el-button text @click="backToList">
          <el-icon><ArrowLeft /></el-icon>项目列表
        </el-button>
        <h2 class="ws-title">{{ project?.name || '项目' }}</h2>
        <el-tag v-if="project" :type="projectStatus(project.status).type" size="small">
          {{ projectStatus(project.status).label }}
        </el-tag>
        <el-tag :type="modeType(project?.mode)" size="small" effect="plain">
          {{ project?.mode_label || modeLabel(project?.mode) }}
        </el-tag>
        <el-tag v-if="project?.feedback_round" size="small" type="success" effect="plain">
          闭环第 {{ project.feedback_round }} 轮
        </el-tag>
      </div>
      <div class="ws-head-right">
        <el-button :loading="generating === 'plan'" @click="genPlan">
          <el-icon><Aim /></el-icon>生成方案
        </el-button>
        <el-button :loading="generating === 'all'" @click="genAll">
          <el-icon><Files /></el-icon>逐任务生成
        </el-button>
        <el-button type="primary" :loading="feeding" @click="openFeedback">
          <el-icon><RefreshRight /></el-icon>反哺知识库
        </el-button>
      </div>
    </header>

    <p v-if="project?.goal" class="ws-goal">{{ project.goal }}</p>

    <!-- 进度条：长任务必须有进度，不然用户只能干等 -->
    <div v-if="job" class="job-bar" :class="{ failed: jobProgress(job).failed }">
      <el-progress
        :percentage="jobProgress(job).percent"
        :status="jobProgress(job).failed ? 'exception' : jobProgress(job).done ? 'success' : undefined"
        :stroke-width="10"
      />
      <div class="job-text">
        {{ jobProgress(job).text }}
        <span v-if="job.error" class="job-error">{{ job.error }}</span>
        <span v-if="job.detail" class="job-detail">{{ job.detail }}</span>
      </div>
    </div>

    <!-- 缺什么、怎么配：生成被挡下来时，后端会给这两样 -->
    <el-alert
      v-for="(n, i) in blockers"
      :key="'b' + i"
      type="warning"
      :closable="false"
      show-icon
      class="ws-alert"
    >
      <template #title>{{ n.title }}</template>
      <div v-if="n.missing?.length" class="blk-line">缺：{{ n.missing.join('、') }}</div>
      <div v-if="n.how_to_fix?.length" class="blk-line">怎么配：{{ n.how_to_fix.join('；') }}</div>
    </el-alert>

    <!-- 降级说明：「没搜到」和「没搜」必须分开说 -->
    <el-alert
      v-for="(n, i) in notices"
      :key="'n' + i"
      type="info"
      :closable="false"
      show-icon
      class="ws-alert"
    >{{ n }}</el-alert>

    <div class="ws-body">
      <!-- ============ 左：方案与任务树 ============ -->
      <aside class="ws-col ws-left">
        <section class="col-block">
          <div class="col-head">
            <span class="col-title">方案</span>
            <el-button size="small" text @click="genPlan">重新生成</el-button>
          </div>
          <div v-if="planOutline(project?.plan_json)" class="plan-summary">
            {{ planOutline(project.plan_json) }}
          </div>
          <div v-if="project?.tech_notes" class="plan-notes">{{ project.tech_notes }}</div>
          <div v-if="project?.tech_stack?.length" class="plan-stack">
            <el-tag v-for="t in project.tech_stack" :key="t" size="small" type="info" effect="plain">
              {{ t }}
            </el-tag>
          </div>
          <EmptyState
            v-if="!project?.plan_json || !Object.keys(project.plan_json).length"
            compact
            icon="Aim"
            title="还没有方案"
            description="点「生成方案」，模型会结合喂养的源码知识拆出任务。"
          />
        </section>

        <section class="col-block grow">
          <div class="col-head">
            <span class="col-title">任务树</span>
            <el-button size="small" text @click="openTask()">
              <el-icon><Plus /></el-icon>加任务
            </el-button>
          </div>
          <div v-if="tasks.length" class="task-list">
            <div
              v-for="t in flatTasks"
              :key="t.id"
              class="task-item"
              :style="{ marginLeft: (t.depth || 0) * 14 + 'px' }"
            >
              <div class="task-main" @click="toggleTask(t.id)">
                <el-tag :type="taskStatus(t.status).type" size="small" effect="plain">
                  {{ taskStatus(t.status).label }}
                </el-tag>
                <span class="task-title">{{ t.title }}</span>
              </div>
              <div v-if="t.description" class="task-desc">{{ t.description }}</div>
              <div v-if="t.acceptance" class="task-acc">验收：{{ t.acceptance }}</div>
              <div class="task-ops">
                <el-button size="small" text @click="genTaskOutput(t)">生成产出</el-button>
                <el-button size="small" text @click="openTask(t)">编辑</el-button>
                <el-button size="small" text type="danger" @click="removeTask(t)">删除</el-button>
              </div>
              <div v-if="taskWarnings[t.id]?.length" class="task-warn">
                <div v-for="(w, wi) in taskWarnings[t.id]" :key="wi" class="warn-line">
                  <el-tag :type="warningSeverity(w).type" size="small" effect="dark">
                    {{ warningSeverity(w).label }}
                  </el-tag>
                  <span>{{ describeWarning(w) }}</span>
                </div>
              </div>
            </div>
          </div>
          <EmptyState
            v-else
            compact
            icon="List"
            title="还没有任务"
            description="生成方案后任务会自动落在这里。"
          />
        </section>
      </aside>

      <!-- ============ 中：对话与生成 ============ -->
      <section class="ws-col ws-mid">
        <div class="col-head">
          <span class="col-title">对话与生成</span>
          <span class="col-note">每一句回答都带出处，点右侧「知识引用」可以看到它靠什么撑起来</span>
        </div>

        <div class="chat-scroll" ref="scrollBox">
          <div v-if="!messages.length" class="chat-empty">
            <EmptyState
              compact
              icon="ChatDotRound"
              title="问点什么，或者直接生成"
              description="问题会带上这个项目的方案、任务与喂养的源码知识一起问模型。"
            />
          </div>
          <div v-for="m in messages" :key="m.key" class="msg" :class="m.role">
            <div class="msg-head">
              <span class="msg-who">{{ m.role === 'user' ? '我' : (m.model || '模型') }}</span>
              <span class="msg-time">{{ shortTime(m.at) }}</span>
            </div>
            <div class="msg-body">{{ m.text }}</div>
            <div v-if="m.notices?.length" class="msg-notice">
              <div v-for="(n, i) in m.notices" :key="i">· {{ n }}</div>
            </div>
            <div v-if="m.citations?.length" class="msg-cites">
              <el-tag
                v-for="(c, i) in m.citations"
                :key="i"
                size="small"
                effect="plain"
                :type="citationKind(c.kind).type"
              >{{ c.title || c.ref }}</el-tag>
            </div>
          </div>
        </div>

        <div class="chat-input">
          <el-input
            v-model="question"
            type="textarea"
            :rows="3"
            placeholder="问模型：怎么做这个任务？需要哪些知识支撑？"
            @keydown.enter.exact.prevent="send"
          />
          <div class="chat-ops">
            <el-button type="primary" :loading="chatting" @click="send">发送</el-button>
            <el-button :loading="generating === 'plan'" @click="genPlan">生成方案</el-button>
            <el-button :loading="generating === 'all'" @click="genAll">逐任务生成</el-button>
          </div>
        </div>
      </section>

      <!-- ============ 右：产出物与知识引用 ============ -->
      <aside class="ws-col ws-right">
        <section class="col-block">
          <div class="col-head">
            <span class="col-title">产出物</span>
            <span class="col-note">{{ artifactSummary.text }}</span>
          </div>
          <div v-if="artifacts.length" class="art-list">
            <div v-for="a in artifacts" :key="a.id" class="art-item">
              <div class="art-main" @click="openArtifact(a)">
                <el-icon class="art-icon"><Document /></el-icon>
                <div class="art-info">
                  <div class="art-name">{{ a.filename || a.path || '未命名' }}</div>
                  <div class="art-meta">
                    {{ formatBytes(a.size) }}
                    · {{ artifactSource(a.source).label }}
                    <span v-if="a.document_id" class="art-imported">· 已入库</span>
                  </div>
                </div>
              </div>
              <div v-if="(a.warnings || []).length" class="art-warn">
                <el-tag
                  v-for="(w, wi) in a.warnings"
                  :key="wi"
                  :type="warningSeverity(w).type"
                  size="small"
                  effect="plain"
                >{{ warningSeverity(w).label }}</el-tag>
              </div>
              <div class="art-ops">
                <el-checkbox v-model="acceptedMap[a.id]" size="small">采纳</el-checkbox>
                <el-button size="small" text @click="importArtifact(a)" :loading="importing === a.id">
                  入库
                </el-button>
                <el-button size="small" text type="danger" @click="removeArtifact(a)">删除</el-button>
              </div>
            </div>
          </div>
          <EmptyState
            v-else
            compact
            icon="Document"
            title="还没有产出物"
            description="生成任务产出后，文件会出现在这里。"
          />
        </section>

        <section class="col-block grow">
          <div class="col-head">
            <span class="col-title">知识引用</span>
            <span class="col-note">{{ citations.length }} 条</span>
          </div>
          <div v-if="citations.length" class="cite-list">
            <div v-for="g in citationGroups" :key="g.kind" class="cite-group">
              <div class="cite-group-head">
                <el-tag :type="citationKind(g.kind).type" size="small" effect="plain">
                  {{ g.label }}
                </el-tag>
                <span class="cite-count">{{ g.items.length }}</span>
              </div>
              <div v-for="c in g.items" :key="c.id" class="cite-item">
                <div class="cite-title">{{ c.title || c.ref }}</div>
                <div v-if="c.snippet" class="cite-snippet">{{ c.snippet }}</div>
                <div class="cite-meta">
                  <span class="cite-ref">{{ c.ref }}</span>
                  <span class="cite-conf" :class="'lv-' + scoreLevel(c.confidence)">
                    置信度 {{ formatPercent(c.confidence) }}
                  </span>
                </div>
              </div>
            </div>
          </div>
          <EmptyState
            v-else
            compact
            icon="Link"
            title="还没有引用"
            description="生成或问答之后，用到的知识会出现在这里。"
          />
        </section>
      </aside>
    </div>

    <!-- 任务编辑 -->
    <el-dialog v-model="taskDialog" :title="editingTask ? '编辑任务' : '新建任务'" width="560px">
      <el-form label-width="88px" @submit.prevent>
        <el-form-item label="标题" required>
          <el-input v-model="taskForm.title" maxlength="120" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="taskForm.description" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="验收标准">
          <el-input v-model="taskForm.acceptance" type="textarea" :rows="2" placeholder="做到什么程度算完成" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="taskForm.status">
            <el-option v-for="(v, k) in TASK_STATUS" :key="k" :label="v.label" :value="k" />
          </el-select>
        </el-form-item>
        <el-form-item label="依赖">
          <el-select v-model="taskForm.depends_on" multiple placeholder="依赖哪些任务">
            <el-option v-for="t in tasks" :key="t.id" :label="t.title" :value="t.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="taskDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingTask" @click="saveTask">保存</el-button>
      </template>
    </el-dialog>

    <!-- 产出物内容 -->
    <el-dialog v-model="artifactDialog" :title="currentArtifact?.filename || '产出物'" width="760px">
      <pre class="art-content">{{ currentArtifact?.content || '（空）' }}</pre>
      <template #footer>
        <el-button @click="artifactDialog = false">关闭</el-button>
        <el-button type="primary" @click="importArtifact(currentArtifact)" :loading="importing === currentArtifact?.id">
          导入数据中心
        </el-button>
      </template>
    </el-dialog>

    <!-- 反哺：闭环的收口 -->
    <el-dialog v-model="feedbackDialog" title="反哺知识库" width="640px">
      <p class="fb-hint">
        把这次开发认可过的产出物沉淀成养料库里的新基因，
        下一轮开发就能直接检索到 —— 这就是闭环的最后一环。
      </p>
      <el-form label-width="88px">
        <el-form-item label="产出物">
          <el-checkbox-group v-model="feedbackForm.artifact_ids">
            <el-checkbox v-for="a in artifacts" :key="a.id" :value="a.id">
              {{ a.filename || a.path || '未命名' }}
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="经验补充">
          <el-input
            v-model="feedbackForm.lessons"
            type="textarea"
            :rows="3"
            placeholder="这次开发学到了什么？会写成一条项目级经验"
          />
        </el-form-item>
      </el-form>
      <div v-if="feedbackReport" class="fb-report">
        <div class="fb-round">第 {{ feedbackReport.round }} 轮闭环</div>
        <ul>
          <li>新沉淀基因 {{ feedbackReport.genes_created }} 条</li>
          <li v-if="feedbackReport.confidence_raised?.length">
            置信度提升：
            <span v-for="c in feedbackReport.confidence_raised" :key="c.gene_id">
              {{ c.title }} {{ c.before }} → {{ c.after }}
            </span>
          </li>
          <li v-if="feedbackReport.expression_raised?.length">
            表达度提升：
            <span v-for="c in feedbackReport.expression_raised" :key="c.gene_id">
              {{ c.title }} {{ c.before }} → {{ c.after }}
            </span>
          </li>
          <li v-if="feedbackReport.mechanism">
            评分机制：{{ feedbackReport.mechanism }}
          </li>
        </ul>
      </div>
      <template #footer>
        <el-button @click="feedbackDialog = false">关闭</el-button>
        <el-button type="primary" :loading="feeding" @click="doFeedback">执行反哺</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
/**
 * 软件开发 · 项目工作台
 *
 * 三栏布局：左边是「计划与任务」，中间是「对话与生成」，右边是「产出物与知识引用」。
 * 这样摆的原因：开发是一个「看计划 → 提问题 → 看结果」的循环，
 * 三样东西必须同屏可见 —— 换页签就会打断这个循环。
 *
 * 两条硬规矩：
 *   1) 缺配置时把后端给的 missing / how_to_fix 原样显示，不自己编；
 *   2) 在线模式下「没搜到」与「没搜」必须分开说 —— 降级要诚实地降级。
 */
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import EmptyState from '../../components/EmptyState.vue'
import DevApi from '../../api/dev.js'
import {
  TASK_STATUS, modeLabel, modeType, projectStatus, taskStatus,
  artifactSource, citationKind, warningSeverity, describeWarning,
  planOutline, buildTaskTree, flattenTaskTree, groupCitations,
  jobProgress, formatPercent, scoreLevel, formatBytes, summarizeArtifacts,
} from '../../utils/dev.js'

const route = useRoute()
const router = useRouter()
const projectId = computed(() => Number(route.params.id))

const loading = ref(false)
const project = ref(null)
const tasks = ref([])
const artifacts = ref([])
const sessions = ref([])
const citations = ref([])
const messages = ref([])
const job = ref(null)
const blockers = ref([])
const notices = ref([])
const taskWarnings = ref({})
const acceptedMap = reactive({})
const generating = ref('')
const chatting = ref(false)
const feeding = ref(false)
const savingTask = ref(false)
const importing = ref(null)
const question = ref('')
const scrollBox = ref(null)

const taskDialog = ref(false)
const editingTask = ref(null)
const taskForm = reactive({
  title: '', description: '', acceptance: '', status: 'todo', depends_on: [],
})

const artifactDialog = ref(false)
const currentArtifact = ref(null)

const feedbackDialog = ref(false)
const feedbackReport = ref(null)
const feedbackForm = reactive({ artifact_ids: [], lessons: '' })

let pollTimer = null

const flatTasks = computed(() => flattenTaskTree(buildTaskTree(tasks.value)))
const citationGroups = computed(() => groupCitations(citations.value))
const artifactSummary = computed(() => summarizeArtifacts(artifacts.value))

async function load() {
  loading.value = true
  try {
    const res = await DevApi.project(projectId.value)
    if (!res) return
    project.value = res.project
    tasks.value = res.tasks || []
    artifacts.value = res.artifacts || []
    sessions.value = res.sessions || []
    citations.value = res.citations || []
    artifacts.value.forEach((a) => {
      acceptedMap[a.id] = !!a.accepted
    })
    // 历史会话铺进对话区：工作台要能看到「之前聊过什么」
    messages.value = (res.sessions || [])
      .slice()
      .reverse()
      .map((s) => ({
        key: 's' + s.id,
        role: 'assistant',
        text: s.reply || '',
        model: s.model,
        at: s.created_at,
        notices: s.notice ? [s.notice] : [],
        citations: s.citations || [],
      }))
  } catch (e) {
    const d = e.response?.data || {}
    ElMessage.error(d.detail || '加载项目失败')
  } finally {
    loading.value = false
  }
}

/* ============ 生成 ============ */

function collectError(e, fallback) {
  const d = (e && e.response && e.response.data) || {}
  blockers.value = [{
    title: d.detail || fallback || '生成没成',
    missing: d.missing || [],
    how_to_fix: d.how_to_fix || [],
  }]
}

async function genPlan() {
  generating.value = 'plan'
  blockers.value = []
  try {
    const res = await DevApi.generatePlan(projectId.value, {})
    if (!res || !res.job) {
      collectError(null, '生成方案没启动')
      return
    }
    job.value = res.job
    pollJob(res.job.id)
  } catch (e) {
    collectError(e, '生成方案没启动')
  } finally {
    generating.value = ''
  }
}

async function genAll() {
  generating.value = 'all'
  blockers.value = []
  try {
    const res = await DevApi.generateAllTasks(projectId.value, {})
    if (!res || !res.job) {
      collectError(null, '生成产出没启动')
      return
    }
    job.value = res.job
    pollJob(res.job.id)
  } catch (e) {
    collectError(e, '生成产出没启动')
  } finally {
    generating.value = ''
  }
}

async function genTaskOutput(t) {
  try {
    const res = await DevApi.generateTaskOutput(t.id, {})
    if (!res) return
    taskWarnings.value = { ...taskWarnings.value, [t.id]: res.warnings || [] }
    if ((res.blocked || []).length) {
      ElMessage.warning(
        '有 ' + res.blocked.length + ' 个文件被安全体检拦下：' +
        (res.blocked[0].reason || res.blocked[0].message || '')
      )
    } else {
      ElMessage.success('产出已生成')
    }
    await load()
  } catch (e) {
    collectError(e, '生成产出失败')
  }
}

function pollJob(jobId) {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    try {
      const j = await DevApi.job(jobId)
      if (!j) return
      job.value = j
      const p = jobProgress(j)
      if (p.done) {
        clearInterval(pollTimer)
        pollTimer = null
        if (p.failed) {
          ElMessage.error('后台作业失败：' + j.error)
        } else {
          ElMessage.success('生成完成')
        }
        await load()
      }
    } catch {
      // 轮询失败不打断作业：作业还在后端跑，下一轮再看
    }
  }, 1500)
}

/* ============ 对话 ============ */

async function send() {
  const q = question.value.trim()
  if (!q) return
  chatting.value = true
  messages.value.push({
    key: 'u' + Date.now(),
    role: 'user',
    text: q,
    at: new Date().toISOString(),
  })
  question.value = ''
  await nextTick()
  scrollDown()
  try {
    const res = await DevApi.chat(projectId.value, q)
    if (!res) return
    messages.value.push({
      key: 'a' + (res.session ? res.session.id : Date.now()),
      role: 'assistant',
      text: res.answer || '',
      model: res.session ? res.session.model : '',
      at: new Date().toISOString(),
      notices: res.notices || [],
      citations: res.citations || [],
    })
    if (res.notices && res.notices.length) notices.value = res.notices
    await load()
  } catch (e) {
    const d = (e.response && e.response.data) || {}
    blockers.value = [{
      title: d.detail || '问答失败',
      missing: d.missing || [],
      how_to_fix: d.how_to_fix || [],
    }]
    messages.value.push({
      key: 'a' + Date.now(),
      role: 'assistant',
      text: d.detail || '问答失败',
      at: new Date().toISOString(),
    })
  } finally {
    chatting.value = false
    await nextTick()
    scrollDown()
  }
}

function scrollDown() {
  const el = scrollBox.value
  if (el) el.scrollTop = el.scrollHeight
}

/* ============ 任务 ============ */

function toggleTask(id) {
  const t = tasks.value.find((x) => x.id === id)
  if (!t) return
  const next = t.status === 'done' ? 'todo' : 'done'
  DevApi.patchTask(id, { status: next })
    .then(load)
    .catch((e) => ElMessage.error((e.response?.data || {}).detail || '更新任务失败'))
}

function openTask(t) {
  editingTask.value = t || null
  taskForm.title = t ? t.title : ''
  taskForm.description = t ? t.description : ''
  taskForm.acceptance = t ? t.acceptance : ''
  taskForm.status = t ? t.status : 'todo'
  taskForm.depends_on = t && t.depends_on ? [...t.depends_on] : []
  taskDialog.value = true
}

async function saveTask() {
  if (!taskForm.title.trim()) {
    ElMessage.warning('任务标题不能为空')
    return
  }
  savingTask.value = true
  try {
    const payload = {
      title: taskForm.title.trim(),
      description: taskForm.description,
      acceptance: taskForm.acceptance,
      status: taskForm.status,
      depends_on: taskForm.depends_on,
    }
    if (editingTask.value) {
      await DevApi.patchTask(editingTask.value.id, payload)
    } else {
      await DevApi.createTask(projectId.value, payload)
    }
    taskDialog.value = false
    await load()
  } catch (e) {
    ElMessage.error((e.response?.data || {}).detail || '保存任务失败')
  } finally {
    savingTask.value = false
  }
}

async function removeTask(t) {
  try {
    await ElMessageBox.confirm('删除任务「' + t.title + '」？', '删除任务', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '算了',
    })
  } catch {
    return
  }
  try {
    await DevApi.deleteTask(t.id)
    await load()
  } catch (e) {
    ElMessage.error((e.response?.data || {}).detail || '删除失败')
  }
}

/* ============ 产出物 ============ */

async function openArtifact(a) {
  try {
    const res = await DevApi.artifact(a.id)
    currentArtifact.value = res && (res.artifact || res)
    artifactDialog.value = true
  } catch (e) {
    ElMessage.error((e.response?.data || {}).detail || '读不到产出物内容')
  }
}

async function importArtifact(a) {
  if (!a) return
  importing.value = a.id
  try {
    const res = await DevApi.importArtifact(a.id)
    ElMessage.success('已导入数据中心')
    if (res && res.document && res.document.id) {
      a.document_id = res.document.id
    }
    await load()
  } catch (e) {
    const d = (e.response && e.response.data) || {}
    ElMessage.error(d.detail || '导入失败')
  } finally {
    importing.value = null
  }
}

async function removeArtifact(a) {
  try {
    await ElMessageBox.confirm('删除产出物「' + (a.filename || '') + '」？', '删除产出物', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '算了',
    })
  } catch {
    return
  }
  try {
    await DevApi.deleteArtifact(a.id)
    await load()
  } catch (e) {
    ElMessage.error((e.response?.data || {}).detail || '删除失败')
  }
}

/* ============ 反哺 ============ */

function openFeedback() {
  feedbackReport.value = null
  feedbackForm.artifact_ids = artifacts.value
    .filter((a) => acceptedMap[a.id])
    .map((a) => a.id)
  feedbackForm.lessons = ''
  feedbackDialog.value = true
}

async function doFeedback() {
  feeding.value = true
  try {
    const res = await DevApi.feedback(projectId.value, {
      artifact_ids: feedbackForm.artifact_ids,
      lessons: feedbackForm.lessons,
    })
    if (!res) return
    feedbackReport.value = res.report || {}
    ElMessage.success('已反哺知识库')
    await load()
  } catch (e) {
    const d = (e.response && e.response.data) || {}
    ElMessage.error(d.detail || '反哺失败')
  } finally {
    feeding.value = false
  }
}

function backToList() {
  router.push('/dev')
}

function shortTime(t) {
  if (!t) return ''
  return String(t).replace('T', ' ').slice(5, 16)
}

onMounted(load)
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.dev-ws {
  padding: var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-height: calc(100vh - 64px);
}

/* ---------- 抬头 ---------- */
.ws-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
}
.ws-head-left {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  min-width: 0;
}
.ws-title {
  margin: 0;
  font-size: var(--text-xl);
  font-weight: 650;
  color: var(--text-primary);
}
.ws-head-right {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.ws-goal {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  line-height: 1.7;
}

/* ---------- 进度 ---------- */
.job-bar {
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
}
.job-bar.failed {
  border-color: var(--danger);
}
.job-text {
  margin-top: var(--space-1);
  font-size: var(--text-xs);
  color: var(--text-secondary);
}
.job-error {
  color: var(--danger-text);
  margin-left: var(--space-2);
}
.job-detail {
  color: var(--text-tertiary);
  margin-left: var(--space-2);
}
.ws-alert {
  margin-bottom: var(--space-1);
}
.blk-line {
  font-size: var(--text-sm);
  line-height: 1.8;
}

/* ---------- 三栏 ---------- */
.ws-body {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr) 340px;
  gap: var(--space-3);
  flex: 1 1 auto;
  min-height: 0;
}
.ws-col {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-height: 0;
  overflow: auto;
}
.ws-left,
.ws-right {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: var(--space-3);
  box-shadow: var(--shadow-card);
}
.ws-mid {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: var(--space-3);
  box-shadow: var(--shadow-card);
  overflow: hidden;
}
.col-block {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--border-light);
}
.col-block.grow {
  flex: 1 1 auto;
  border-bottom: none;
  padding-bottom: 0;
}
.col-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-2);
}
.col-title {
  font-size: var(--text-sm);
  font-weight: 620;
  color: var(--text-primary);
}
.col-note {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

/* ---------- 方案 ---------- */
.plan-summary {
  font-size: var(--text-sm);
  line-height: 1.75;
  color: var(--text-secondary);
}
.plan-notes {
  font-size: var(--text-xs);
  line-height: 1.7;
  color: var(--text-tertiary);
  padding: var(--space-2);
  background: var(--bg-sunken);
  border-radius: var(--radius-sm);
  white-space: pre-wrap;
}
.plan-stack {
  display: flex;
  gap: var(--space-1);
  flex-wrap: wrap;
}

/* ---------- 任务 ---------- */
.task-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.task-item {
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-light);
  background: var(--bg-subtle);
}
.task-main {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  cursor: pointer;
}
.task-title {
  font-size: var(--text-sm);
  color: var(--text-primary);
  font-weight: 550;
}
.task-desc {
  margin-top: var(--space-1);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  line-height: 1.7;
}
.task-acc {
  margin-top: 2px;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
.task-ops {
  margin-top: var(--space-1);
  display: flex;
  gap: var(--space-1);
}
.task-warn {
  margin-top: var(--space-1);
}
.warn-line {
  display: flex;
  align-items: baseline;
  gap: var(--space-1);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  line-height: 1.7;
}

/* ---------- 对话 ---------- */
.chat-scroll {
  flex: 1 1 auto;
  overflow: auto;
  padding: var(--space-2);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-height: 240px;
}
.msg {
  padding: var(--space-3);
  border-radius: var(--radius-md);
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
}
.msg.user {
  background: var(--primary-bg);
  border-color: var(--primary);
}
.msg-head {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  margin-bottom: var(--space-1);
}
.msg-who {
  font-size: var(--text-xs);
  font-weight: 620;
  color: var(--text-primary);
}
.msg-time {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
.msg-body {
  font-size: var(--text-sm);
  line-height: 1.8;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}
.msg-notice {
  margin-top: var(--space-2);
  font-size: var(--text-xs);
  color: var(--warning-text);
  line-height: 1.7;
}
.msg-cites {
  margin-top: var(--space-2);
  display: flex;
  gap: var(--space-1);
  flex-wrap: wrap;
}
.chat-input {
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--border-light);
}
.chat-ops {
  margin-top: var(--space-2);
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

/* ---------- 产出物 ---------- */
.art-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.art-item {
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-light);
  background: var(--bg-subtle);
}
.art-main {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  cursor: pointer;
}
.art-icon {
  color: var(--primary);
}
.art-info {
  min-width: 0;
}
.art-name {
  font-size: var(--text-sm);
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.art-meta {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
.art-imported {
  color: var(--success-text);
}
.art-warn {
  margin-top: var(--space-1);
  display: flex;
  gap: var(--space-1);
  flex-wrap: wrap;
}
.art-ops {
  margin-top: var(--space-1);
  display: flex;
  align-items: center;
  gap: var(--space-1);
}
.art-content {
  margin: 0;
  padding: var(--space-3);
  background: var(--bg-sunken);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  line-height: 1.7;
  max-height: 52vh;
  overflow: auto;
  white-space: pre;
}

/* ---------- 引用 ---------- */
.cite-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.cite-group-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-1);
}
.cite-count {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
.cite-item {
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
}
.cite-title {
  font-size: var(--text-sm);
  color: var(--text-primary);
  line-height: 1.5;
}
.cite-snippet {
  margin-top: 2px;
  font-size: var(--text-xs);
  color: var(--text-secondary);
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.cite-meta {
  margin-top: var(--space-1);
  display: flex;
  justify-content: space-between;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
.cite-conf.lv-high { color: var(--success-text); }
.cite-conf.lv-mid { color: var(--warning-text); }
.cite-conf.lv-low { color: var(--danger-text); }

/* ---------- 反哺 ---------- */
.fb-hint {
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  line-height: 1.8;
}
.fb-report {
  margin-top: var(--space-3);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
.fb-round {
  font-weight: 620;
  color: var(--text-primary);
  margin-bottom: var(--space-1);
}
.fb-report ul {
  margin: 0;
  padding-left: 1.2em;
  line-height: 1.9;
}

@media (max-width: 1280px) {
  .ws-body {
    grid-template-columns: 280px minmax(0, 1fr);
  }
  .ws-right {
    grid-column: 1 / -1;
  }
}
@media (max-width: 900px) {
  .ws-body {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
