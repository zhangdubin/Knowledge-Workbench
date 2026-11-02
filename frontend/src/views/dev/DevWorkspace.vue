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
        <el-button :loading="generating === 'all'" @click="genAll">
          <el-icon><Files /></el-icon>逐任务生成
        </el-button>
        <el-button type="primary" :loading="feeding" @click="openFeedback">
          <el-icon><RefreshRight /></el-icon>反哺知识库
        </el-button>
      </div>
    </header>

    <p v-if="project?.goal" class="ws-goal">{{ project.goal }}</p>

    <!-- 流水线总览：当前在哪一步 -->
    <div v-if="!pipelineMissing" class="ws-progress">
      <span class="ws-progress-label">当前阶段</span>
      <span class="ws-progress-name">{{ currentStageTitle }}</span>
      <span class="ws-progress-note">{{ currentStageNote }}</span>
    </div>

    <!-- 进度条：长任务必须有进度 -->
    <div v-if="job" class="job-bar" :class="{ failed: jobProgress(job).failed }">
      <el-progress
        v-if="!jobProgress(job).indeterminate"
        :percentage="jobProgress(job).percent"
        :status="jobProgress(job).failed ? 'exception' : jobProgress(job).done ? 'success' : undefined"
        :stroke-width="10"
      />
      <!-- 总量未知时不显示百分比：假的 50% 比不给更害人 -->
      <el-progress
        v-else
        :percentage="100"
        :indeterminate="true"
        :duration="3"
        :stroke-width="10"
      />
      <div class="job-text">
        {{ jobProgress(job).text }}
        <span v-if="job.error" class="job-error">{{ job.error }}</span>
        <span v-if="job.detail" class="job-detail">{{ jobDetailText }}</span>
        <span v-if="jobTimeout" class="job-timeout">
          已经等了很久（超过 10 分钟），可以刷新页面看最新状态。
        </span>
      </div>
      <div v-if="jobMissing.length || jobHowToFix(job).length" class="job-fix">
        <span v-if="jobMissing.length" class="job-fix-title">缺什么：</span>
        <span v-if="jobMissing.length">{{ jobMissing.join('、') }}</span>
        <span v-if="jobHowToFix(job).length" class="job-fix-title">怎么修：</span>
        {{ jobHowToFix(job).join('；') }}
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
      <div v-if="canSwitchOnline" class="blk-ops">
        <el-button type="primary" size="small" :loading="switching" @click="switchOnline">
          切到在线协同模式并重跑
        </el-button>
        <span class="blk-ops-note">{{ doctorSummaryText }}</span>
      </div>
    </el-alert>

    <!-- 模型不可用：给一条出路，而不是只说「缺什么」。
         契约第 4.6 条：模式不能把功能锁死 ——
         离线闭环模式不认应用里已配好的云端大模型，用户明明有模型却用不了。
         所以这里给一个「切到在线协同模式并重跑」的按钮。 -->
    <el-alert
      v-if="doctorMissing.length && canSwitchOnline && !blockers.length"
      type="warning"
      :closable="false"
      show-icon
      class="ws-alert"
    >
      <template #title>模型还不可用</template>
      <div class="blk-line">{{ doctorSummaryText }}</div>
      <div class="blk-ops">
        <el-button type="primary" size="small" :loading="switching" @click="switchOnline">
          <el-icon><Connection /></el-icon>切到在线协同模式并重跑
        </el-button>
      </div>
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
      <!-- ============ 左：四阶段导航 ============ -->
      <DevStageNav
        class="ws-col ws-left"
        :stages="stageList"
        :current-stage="pipeline?.current_stage || ''"
        :active="activeStage"
        :gates="gates"
        @select="selectStage"
      />

      <!-- ============ 中：当前阶段 ============ -->
      <section class="ws-col ws-mid">
        <!-- 阶段级兜底：后端自动推进的阶段没有 job 可轮询，
             这里用阶段状态 + 计时器盯着，超时了就说「还在跑/已超时」，
             不能让用户对着一个永远转的骨架屏发呆。 -->
        <el-alert
          v-if="stageTimeout"
          type="warning"
          :closable="false"
          show-icon
          class="ws-alert"
          title="这一步还在跑，已经超过 10 分钟"
        >
          <div class="blk-line">
            后端可能卡住了。可以点面板里的「重新生成」重跑，或者刷新页面看最新状态。
          </div>
        </el-alert>
        <!-- 后端还没上线流水线接口：说清楚，别白屏 -->
        <div v-if="pipelineMissing" class="pipeline-missing">
          <el-alert type="info" :closable="false" show-icon title="后端还没上线这个阶段">
            <div class="fail-line">
              四阶段流水线接口（/api/dev/projects/{id}/pipeline）还没上线，
              这里暂时只能用旧的一次性流程。
            </div>
          </el-alert>
          <div class="legacy-box">
            <div class="legacy-title">方案</div>
            <p v-if="planText" class="legacy-plan">{{ planText }}</p>
            <p v-else class="legacy-plan muted">还没有方案</p>
            <div v-if="project?.tech_stack?.length" class="plan-stack">
              <el-tag v-for="t in project.tech_stack" :key="t" size="small" type="info" effect="plain">
                {{ t }}
              </el-tag>
            </div>
            <el-button type="primary" :loading="generating === 'plan'" @click="genPlan">
              <el-icon><Aim /></el-icon>生成方案
            </el-button>
          </div>
        </div>

        <DevStageClarify
          v-else-if="activeStage === 'clarify'"
          :stage="stageOf('clarify')"
          :busy="runningStage === 'clarify'"
          @run="runStage('clarify', $event)"
          @submit="answerStage('clarify', $event)"
        />

        <DevStageSpecify
          v-else-if="activeStage === 'specify'"
          :stage="stageOf('specify')"
          :busy="runningStage === 'specify'"
          @run="runStage('specify', $event)"
          @submit="answerStage('specify', $event)"
        />

        <DevStageDesign
          v-else-if="activeStage === 'design'"
          :stage="stageOf('design')"
          :tasks="tasks"
          :warnings="taskWarnings"
          :busy="runningStage === 'design'"
          @run="runStage('design', $event)"
          @gen-task="genTaskOutput"
          @edit-task="openTask"
          @del-task="removeTask"
          @toggle-task="toggleTask"
        />

        <DevStageImplement
          v-else-if="activeStage === 'implement'"
          :stage="stageOf('implement')"
          :artifacts="artifacts"
          :busy="runningStage === 'implement'"
          :exporting="exporting"
          :importing="importing"
          @run="runStage('implement', $event)"
          @export="doExport"
          @import="importArtifact"
          @remove="removeArtifact"
        />

        <div v-else class="panel-placeholder">
          <EmptyState
            icon="Guide"
            title="选一个阶段开始"
            description="左边是四个阶段，先从「需求理解」开始。"
          />
        </div>
      </section>

      <!-- ============ 右：会话与知识引用 ============ -->
      <aside class="ws-col ws-right">
        <section class="col-block grow chat-block">
          <div class="col-head">
            <span class="col-title">会话记录</span>
            <span class="col-note">每一句回答都带出处</span>
          </div>

          <div class="chat-scroll" ref="scrollBox">
            <div v-if="!messages.length" class="chat-empty">
              <EmptyState
                compact
                icon="ChatDotRound"
                title="问点什么"
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
            </div>
          </div>
        </section>

        <section class="col-block">
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
 * 布局：左栏四阶段导航 / 中栏当前阶段 / 右栏会话与引用。
 *
 * 为什么这么摆：
 *   专业开发是一条有先后依赖的流水线 —— 用户最需要知道的是
 *   「我在哪一步、这一步该做什么、为什么下一步还不能跑」。
 *   原来的三栏（方案+任务 / 对话 / 产出物+引用）把内容平铺着，
 *   看着多，实际看不出流程。
 *
 * 两条硬规矩：
 *   1) 缺配置时把后端给的 missing / how_to_fix 原样显示，不自己编；
 *   2) 判定一律用后端给的结论（gates / pipeline），前端不自己算状态机。
 */
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import EmptyState from '../../components/EmptyState.vue'
import DevApi, { downloadExport } from '../../api/dev.js'
import DevStageNav from './DevStageNav.vue'
import DevStageClarify from './DevStageClarify.vue'
import DevStageSpecify from './DevStageSpecify.vue'
import DevStageDesign from './DevStageDesign.vue'
import DevStageImplement from './DevStageImplement.vue'
import {
  TASK_STATUS, modeLabel, modeType, projectStatus, taskStatus,
  citationKind, warningSeverity, describeWarning,
  planOutline, groupCitations, stageMeta, stageSummary,
  jobProgress, jobHowToFix, unwrapJob, doctorSummary, doctorMissingText,
  formatPercent, scoreLevel,
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
const runningStage = ref('')
const chatting = ref(false)
const feeding = ref(false)
const savingTask = ref(false)
const importing = ref(null)
const exporting = ref(false)
const switching = ref(false)
const question = ref('')
const scrollBox = ref(null)

/* ---- 四阶段流水线 ---- */
const pipeline = ref(null)
const stageList = ref([])
const gates = ref({})
const pipelineMissing = ref(false)
const pipelineNotice = ref('')
const activeStage = ref('')
const doctor = ref(null)

const taskDialog = ref(false)
const editingTask = ref(null)
const taskForm = reactive({
  title: '', description: '', acceptance: '', status: 'todo', depends_on: [],
})

const feedbackDialog = ref(false)
const feedbackReport = ref(null)
const feedbackForm = reactive({ artifact_ids: [], lessons: '' })

let pollTimer = null
let pollStartedAt = 0
const JOB_TIMEOUT_MS = 10 * 60 * 1000
const jobTimeout = ref(false)

/* ---- 阶段级超时兜底 ---- */
// 后端自动推进的阶段不一定返回 job（比如 answer 之后后端自己把下一阶段排上了），
// 那时候没有作业可轮询，就只剩一个转圈的骨架屏 ——
// 这里用「阶段状态 + 计时」盯着，超时了明确告诉用户「还在跑/已超时」。
const STAGE_TIMEOUT_MS = 10 * 60 * 1000
const stageStartedAt = ref(0)
const stageTimeout = ref(false)
let stageClock = null

function syncStageClock() {
  const st = stageOf(activeStage.value)
  if (st && st.status === 'running') {
    if (!stageStartedAt.value) stageStartedAt.value = Date.now()
    if (Date.now() - stageStartedAt.value > STAGE_TIMEOUT_MS) stageTimeout.value = true
  } else {
    stageStartedAt.value = 0
    stageTimeout.value = false
  }
}

const citationGroups = computed(() => groupCitations(citations.value))
const planText = computed(() => planOutline(project.value?.plan_json))
const currentStageKey = computed(() => pipeline.value?.current_stage || '')
const currentStageTitle = computed(() => stageMeta(currentStageKey.value).title)
const currentStageNote = computed(() => stageSummary(stageOf(currentStageKey.value)))
const doctorMissing = computed(() => doctorMissingText(doctor.value?.missing))
const doctorSummaryText = computed(() => doctorSummary(doctor.value))

/**
 * 作业失败时后端挂在 job 顶层的 missing / how_to_fix。
 *
 * 注意：别去挖 job.detail —— dna_job 的序列化只带 detail.items，
 * 缺什么、怎么配是路由层单独提上来的，挖不到。
 */
const jobMissing = computed(() => {
  const m = job.value?.missing
  if (Array.isArray(m)) return m.map(String)
  if (m) return [String(m)]
  return []
})

/**
 * 模型不可用时能不能给「切在线协同」这个出口。
 *
 * 契约第 4.6 条：模式不能把功能锁死 ——
 * 离线模式没有本地模型时，后端在 doctor 里要明确给出
 * 「系统大模型已就绪，可切到在线协同」，前端给一个一键切换并重跑的按钮。
 */
const canSwitchOnline = computed(() => {
  const d = doctor.value
  if (!d) return false
  return d.mode !== 'online'
})

/* ============ 载入 ============ */

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

/**
 * 读流水线状态。
 *
 * 后端还没上线这个接口时（404）不是错误 ——
 * 页面上说清「后端还没上线这个阶段」，并保留旧流程，
 * 而不是白屏或者一堆红字。
 */
async function loadPipeline() {
  try {
    const res = await DevApi.pipeline(projectId.value)
    applyPipeline(res)
  } catch (e) {
    const status = e.response?.status
    pipelineMissing.value = true
    pipelineNotice.value = status === 404
      ? '后端还没上线这个阶段'
      : ('流水线状态读不到：' + ((e.response?.data || {}).detail || e.message || '未知错误'))
  }
}

/** 体检：模型到底能不能用。离线模式下不发任何外网请求 */
async function loadDoctor() {
  try {
    doctor.value = await DevApi.doctor(project.value?.mode || '')
  } catch (e) {
    doctor.value = null
  }
}

/**
 * 把一份流水线数据套到界面上。
 *
 * GET /pipeline 与 POST /stages/{stage}/answer 返回的是同一套结构
 * （{pipeline, stages, gates}），所以共用这一个渲染入口。
 */
function applyPipeline(res) {
  if (!res) return
  pipeline.value = res.pipeline || null
  stageList.value = res.stages || []
  gates.value = res.gates || {}
  pipelineMissing.value = false
  pipelineNotice.value = ''
  const cur = pipeline.value?.current_stage || ''
  if (!activeStage.value && cur) {
    activeStage.value = cur
    return
  }
  // 阶段跑完之后自动跟到当前阶段：用户不该还要手动点一下
  const prev = stageOf(activeStage.value)
  if (cur && activeStage.value !== cur && prev && prev.status === 'done') {
    activeStage.value = cur
  }
}

function stageOf(key) {
  if (!key) return null
  return (pipeline.value && pipeline.value.stages && pipeline.value.stages[key]) || null
}

function selectStage(key) {
  activeStage.value = key
  syncStageClock()
}

/* ============ 阶段执行 ============ */

function collectError(e, fallback) {
  const d = (e && e.response && e.response.data) || {}
  blockers.value = [{
    title: d.detail || fallback || '这一步没成',
    missing: d.missing || [],
    how_to_fix: d.how_to_fix || [],
  }]
}

/**
 * 跑一个阶段。
 *
 * 闸门不通过时后端直接返回 409 与原因 ——
 * 那是「正常的拒绝」，要把原因显示出来，不该当成异常弹个红字。
 */
async function runStage(stage, body) {
  runningStage.value = stage
  blockers.value = []
  jobTimeout.value = false
  try {
    const res = await DevApi.runStage(projectId.value, stage, body || {})
    const j = unwrapJob(res)
    if (!j || !j.id) {
      collectError(null, '这一步没启动')
      return
    }
    job.value = j
    pollJob(j.id)
  } catch (e) {
    collectError(e, '这一步没启动')
    // 失败多半是「模型不可用」，拉一次体检，好给「切在线协同」的出口
    await loadDoctor()
  } finally {
    runningStage.value = ''
  }
}

/** 提交澄清答案 / 修订说明 */
async function answerStage(stage, body) {
  runningStage.value = stage
  try {
    const res = await DevApi.answerStage(projectId.value, stage, body || {})
    // 后端 answer 接口直接返回 {pipeline, stages, gates}，与 GET /pipeline 同构，
    // 先用它渲染，再刷新一次兜底（后端可能在 answer 里顺手把下一阶段排上了）。
    applyPipeline(res)
    ElMessage.success('已提交')
    await loadPipeline()
  } catch (e) {
    collectError(e, '提交没成功')
    await loadDoctor()
  } finally {
    runningStage.value = ''
  }
}

/**
 * 一键切到在线协同模式并重跑当前阶段。
 *
 * 为什么要有这个按钮：模块默认离线闭环，而离线闭环不认
 * 应用里已经配好的云端大模型 —— 用户明明有模型却用不了。
 * 与其让人自己去设置里翻，不如这里直接给一条出路。
 */
async function switchOnline() {
  switching.value = true
  try {
    const res = await DevApi.switchMode('online')
    if (res && res.mode) {
      ElMessage.success('已切到在线协同模式，正在重跑')
    }
    await loadDoctor()
    await load()
    const stage = activeStage.value || currentStageKey.value
    if (stage) await runStage(stage, { force: true })
  } catch (e) {
    ElMessage.error((e.response?.data || {}).detail || '切换模式失败')
  } finally {
    switching.value = false
  }
}

/**
 * 轮询后台作业。
 *
 * ⚠️ 必须 unwrapJob：后端返回的是 { job: {...} }，
 * 直接把整个包装对象塞进 job.value 的话，
 * job.total 永远是 undefined —— 进度条于是永远停在 50%、
 * 文案永远停在「进行中」，作业其实早就 failed 了，页面全程不报错。
 *
 * 另外必须有超时兜底：作业卡住时不能无限转圈。
 */
function pollJob(jobId) {
  if (pollTimer) clearInterval(pollTimer)
  pollStartedAt = Date.now()
  jobTimeout.value = false
  pollTimer = setInterval(async () => {
    try {
      const res = await DevApi.job(jobId)
      const j = unwrapJob(res)
      if (!j) return
      job.value = j
      const p = jobProgress(j)
      if (p.done) {
        clearInterval(pollTimer)
        pollTimer = null
        if (p.failed) {
          ElMessage.error('后台作业失败：' + (j.error || '（后端没给原因）'))
        } else {
          ElMessage.success('生成完成')
        }
        await load()
        await loadPipeline()
        return
      }
      if (Date.now() - pollStartedAt > JOB_TIMEOUT_MS) {
        clearInterval(pollTimer)
        pollTimer = null
        jobTimeout.value = true
        ElMessage.warning('等太久了，先停下来；可以刷新页面看最新状态')
      }
    } catch {
      // 轮询失败不打断作业：作业还在后端跑，下一轮再看
    }
  }, 1500)
}

/* ============ 旧的一次性流程（流水线没上线时的兜底） ============ */

async function genPlan() {
  generating.value = 'plan'
  blockers.value = []
  try {
    const res = await DevApi.generatePlan(projectId.value, {})
    const j = unwrapJob(res)
    if (!j || !j.id) {
      collectError(null, '生成方案没启动')
      return
    }
    job.value = j
    pollJob(j.id)
  } catch (e) {
    collectError(e, '生成方案没启动')
    await loadDoctor()
  } finally {
    generating.value = ''
  }
}

async function genAll() {
  generating.value = 'all'
  blockers.value = []
  try {
    const res = await DevApi.generateAllTasks(projectId.value, {})
    const j = unwrapJob(res)
    if (!j || !j.id) {
      collectError(null, '生成产出没启动')
      return
    }
    job.value = j
    pollJob(j.id)
  } catch (e) {
    collectError(e, '生成产出没启动')
    await loadDoctor()
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

function toggleTask(t) {
  if (!t) return
  const next = t.status === 'done' ? 'todo' : 'done'
  DevApi.patchTask(t.id, { status: next })
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
  if (!a) return
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

/**
 * 导出项目 ZIP。
 *
 * 不用 window.open 裸链：裸链不带会话 cookie，后端认不出是谁直接 401，
 * 而且失败时浏览器只会跳一个 JSON 错误页，用户完全不知道发生了什么。
 */
async function doExport() {
  exporting.value = true
  try {
    const name = (project.value?.name || 'project').replace(/[\\/:*?"<>|]/g, '_')
    await downloadExport(projectId.value, name + '.zip')
    ElMessage.success('已导出 ZIP')
  } catch (e) {
    ElMessage.error((e.response?.data || {}).detail || e.message || '导出失败')
  } finally {
    exporting.value = false
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

/** 作业的 detail 后端给的是数组，渲染出来会变成「a,b,c」 */
const jobDetailText = computed(() => {
  const d = job.value?.detail
  if (!d) return ''
  if (Array.isArray(d)) return d.map((x) => (typeof x === 'string' ? x : JSON.stringify(x))).join('；')
  return String(d)
})

onMounted(async () => {
  await load()
  await Promise.all([loadPipeline(), loadDoctor()])
  // 阶段状态兜底计时：没有作业可轮询时，至少要告诉用户「还在跑，别干等」。
  // 后端自动推进的阶段不会给前端 job，前端只能自己定期读一次流水线状态 ——
  // 否则后端早就跑完了，前端还停在骨架屏上。
  stageClock = setInterval(async () => {
    const st = stageOf(activeStage.value)
    syncStageClock()
    if (st && st.status === 'running') {
      await loadPipeline()
    }
  }, 5000)
})
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (stageClock) clearInterval(stageClock)
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

/* ---------- 流水线总览 ---------- */
.ws-progress {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  background: var(--primary-bg);
  border-radius: var(--radius-md);
  font-size: var(--text-xs);
}
.ws-progress-label { color: var(--text-tertiary); }
.ws-progress-name { font-weight: 650; color: var(--primary); }
.ws-progress-note { color: var(--text-secondary); }

/* ---------- 进度 ---------- */
.job-bar {
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
}
.job-bar.failed {
  border-color: var(--danger);
  background: var(--danger-bg);
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
.job-timeout {
  color: var(--warning-text);
  margin-left: var(--space-2);
}
.job-fix {
  margin-top: var(--space-2);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  line-height: 1.7;
}
.job-fix-title { font-weight: 600; color: var(--text-primary); }

/* ---------- 拦截提示 ---------- */
.ws-alert { margin-bottom: var(--space-1); }
.blk-line { font-size: var(--text-sm); line-height: 1.8; }
.blk-ops {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-top: var(--space-2);
  flex-wrap: wrap;
}
.blk-ops-note {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  line-height: 1.6;
}

/* ---------- 三栏 ---------- */
.ws-body {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr) 340px;
  gap: var(--space-4);
  flex: 1 1 auto;
  min-height: 0;
}
.ws-col {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  min-height: 0;
  min-width: 0;
}
.ws-left,
.ws-mid,
.ws-right {
  overflow: auto;
}
.ws-mid {
  display: block;
}
.col-block {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-4);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
}
.col-block.grow {
  flex: 1 1 auto;
  min-height: 0;
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

/* ---------- 流水线缺失时的兜底 ---------- */
.pipeline-missing {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.legacy-box {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  align-items: flex-start;
  padding: var(--space-5);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
}
.legacy-title {
  font-size: var(--text-sm);
  font-weight: 620;
  color: var(--text-primary);
}
.legacy-plan {
  margin: 0;
  font-size: var(--text-base);
  line-height: 1.8;
  color: var(--text-secondary);
  max-width: 72ch;
}
.legacy-plan.muted { color: var(--text-tertiary); }
.plan-stack { display: flex; gap: var(--space-1); flex-wrap: wrap; }
.panel-placeholder {
  padding: var(--space-5);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
}
.fail-line { font-size: var(--text-sm); line-height: 1.7; }

/* ---------- 会话 ---------- */
.chat-block { min-height: 0; }
.chat-scroll {
  flex: 1 1 auto;
  min-height: 180px;
  max-height: 46vh;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding-right: var(--space-1);
}
.chat-empty { padding: var(--space-4) 0; }
.msg {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  background: var(--bg-subtle);
}
.msg.user {
  background: var(--primary-bg);
}
.msg-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-2);
}
.msg-who { font-size: var(--text-xs); font-weight: 600; color: var(--text-secondary); }
.msg-time { font-size: var(--text-xs); color: var(--text-tertiary); }
.msg-body {
  font-size: var(--text-sm);
  line-height: 1.8;
  color: var(--text-primary);
  white-space: pre-wrap;
}
.msg-notice {
  font-size: var(--text-xs);
  color: var(--warning-text);
  line-height: 1.7;
}
.msg-cites { display: flex; gap: var(--space-1); flex-wrap: wrap; }
.chat-input {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px solid var(--border-light);
}
.chat-ops { display: flex; gap: var(--space-2); }

/* ---------- 引用 ---------- */
.cite-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  max-height: 34vh;
  overflow: auto;
}
.cite-group { display: flex; flex-direction: column; gap: var(--space-2); }
.cite-group-head { display: flex; align-items: center; gap: var(--space-2); }
.cite-count { font-size: var(--text-xs); color: var(--text-tertiary); }
.cite-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-2) var(--space-3);
  border-left: 2px solid var(--border-strong);
  background: var(--bg-subtle);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}
.cite-title { font-size: var(--text-xs); font-weight: 600; color: var(--text-primary); }
.cite-snippet {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.cite-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
.cite-ref { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
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
  background: var(--bg-subtle);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  line-height: 1.9;
}
.fb-round { font-weight: 600; color: var(--text-primary); }
.fb-report ul { margin: var(--space-1) 0 0; padding-left: 18px; }

/* ---------- 窄屏 ---------- */
@media (max-width: 1280px) {
  .ws-body {
    grid-template-columns: 260px minmax(0, 1fr) 300px;
  }
}
@media (max-width: 1024px) {
  .ws-body {
    grid-template-columns: minmax(0, 1fr);
  }
  .ws-left,
  .ws-mid,
  .ws-right {
    overflow: visible;
  }
}
</style>
