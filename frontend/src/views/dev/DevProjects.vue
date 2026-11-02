<template>
  <div class="page dev-page">
    <PageTitle
      title="软件开发"
      subtitle="把喂养的源码知识变成能交付的项目：在线协同用大模型 + GitHub + 网络知识，离线闭环只靠本机知识与本地模型"
      icon-key="Cpu"
    >
      <el-button :loading="loading" @click="loadAll">
        <el-icon><Refresh /></el-icon>刷新
      </el-button>
      <el-button @click="goSettings">
        <el-icon><Setting /></el-icon>开发设置
      </el-button>
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>新建项目
      </el-button>
    </PageTitle>

    <!-- 模式条：当前是在线还是离线，必须一眼可见 ——
         离线模式的全部承诺是「不发外网请求」，用户得随时确认这一点 -->
    <div class="mode-band" :class="mode">
      <div class="mode-left">
        <el-icon class="mode-icon"><component :is="mode === 'online' ? 'Connection' : 'Lock'" /></el-icon>
        <div>
          <div class="mode-title">
            {{ modeLabel(mode) }}
            <span class="mode-hint">{{ modeDesc(mode) }}</span>
          </div>
          <div class="mode-sub">
            模型：{{ modelText }}
            <span v-if="doctor && doctor.outbound_enabled === false" class="mode-warn">
              · 出网总闸已关闭（连在线模式也不发外网请求）
            </span>
          </div>
        </div>
      </div>
      <div class="mode-right">
        <el-button size="small" :loading="switching" @click="toggleMode">
          切到{{ mode === 'online' ? '离线闭环' : '在线协同' }}
        </el-button>
        <el-button size="small" @click="runDoctor">
          <el-icon><FirstAidKit /></el-icon>能力自检
        </el-button>
      </div>
    </div>

    <!-- 缺什么、怎么配：后端给什么就显示什么，不自己编 -->
    <el-alert
      v-if="missing.length"
      type="warning"
      :closable="false"
      show-icon
      class="missing-alert"
    >
      <template #title>当前还差这些才能顺畅开发</template>
      <ul class="missing-list">
        <li v-for="(m, i) in missing" :key="'m' + i">{{ m }}</li>
      </ul>
      <ul v-if="howToFix.length" class="missing-list">
        <li v-for="(h, i) in howToFix" :key="'h' + i">· {{ h }}</li>
      </ul>
    </el-alert>

    <!-- 降级说明：在线模式下「没搜到」和「没搜」是两回事，必须写清楚 -->
    <el-alert
      v-for="(n, i) in notices"
      :key="'n' + i"
      type="info"
      :closable="false"
      show-icon
      class="notice-alert"
    >{{ n }}</el-alert>

    <div class="toolbar">
      <el-input
        v-model="keyword"
        placeholder="搜项目名 / 目标"
        clearable
        class="toolbar-search"
        @keyup.enter="loadProjects"
        @clear="loadProjects"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="statusFilter" placeholder="状态" clearable class="toolbar-select" @change="loadProjects">
        <el-option
          v-for="(v, k) in PROJECT_STATUS"
          :key="k"
          :label="v.label"
          :value="k"
        />
      </el-select>
    </div>

    <div v-loading="loading && !projects.length" class="proj-wrap">
      <div v-if="projects.length" class="proj-grid">
        <article v-for="p in projects" :key="p.id" class="proj-card" @click="goWorkspace(p)">
          <header class="proj-head">
            <h3 class="proj-name">{{ p.name }}</h3>
            <el-tag :type="modeType(p.mode)" size="small" effect="plain">
              {{ p.mode_label || modeLabel(p.mode) }}
            </el-tag>
          </header>
          <p class="proj-goal">{{ p.goal || '（还没写目标）' }}</p>
          <div class="proj-tags">
            <el-tag
              v-for="t in (p.tech_stack || [])"
              :key="t"
              size="small"
              type="info"
              effect="plain"
            >{{ t }}</el-tag>
            <el-tag :type="projectStatus(p.status).type" size="small">
              {{ projectStatus(p.status).label }}
            </el-tag>
            <el-tag v-if="p.feedback_round" size="small" type="success" effect="plain">
              已反哺 {{ p.feedback_round }} 轮
            </el-tag>
          </div>
          <footer class="proj-foot">
            <span class="proj-meta">{{ p.principal || '—' }} · {{ shortTime(p.updated_at) }}</span>
            <span class="proj-ops" @click.stop>
              <el-button size="small" text @click="goWorkspace(p)">工作台</el-button>
              <el-button size="small" text @click="openEdit(p)">编辑</el-button>
              <el-button size="small" text type="danger" @click="remove(p)">删除</el-button>
            </span>
          </footer>
        </article>
      </div>

      <EmptyState
        v-else-if="!loading"
        title="还没有开发项目"
        description="新建一个项目，写清楚要做什么 —— 之后可以喂给它源码知识，让它按你的知识来做。"
      >
        <el-button type="primary" @click="openCreate">新建项目</el-button>
      </EmptyState>
    </div>

    <!-- 新建 / 编辑 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editing ? '编辑项目' : '新建项目'"
      width="620px"
      destroy-on-close
    >
      <el-form label-width="88px" @submit.prevent>
        <el-form-item label="项目名" required>
          <el-input v-model="form.name" placeholder="例如：对账小工具" maxlength="80" />
        </el-form-item>
        <el-form-item label="目标">
          <el-input
            v-model="form.goal"
            type="textarea"
            :rows="3"
            placeholder="要解决什么问题、做到什么程度算完成"
            maxlength="500"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="技术栈">
          <el-input
            v-model="form.tech_stack_text"
            placeholder="逗号分隔，例如 Python, SQLite, Vue"
          />
        </el-form-item>
        <el-form-item label="技术选型">
          <el-input
            v-model="form.tech_notes"
            type="textarea"
            :rows="3"
            placeholder="为什么选这套技术、有什么坑 —— 模型会带着这些约束去做"
          />
        </el-form-item>
        <el-form-item label="开发模式">
          <el-radio-group v-model="form.mode">
            <el-radio value="offline">离线闭环</el-radio>
            <el-radio value="online">在线协同</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">
          {{ editing ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
/**
 * 软件开发 · 项目列表
 *
 * 这一页只干三件事：让人看清当前模式、让人看到缺什么、让人能开新项目。
 * 生成与产出的细节都在工作台里，不在这里堆。
 *
 * 「缺什么、怎么配」一律照抄后端给的 missing / how_to_fix ——
 * 前端自己判断「该怎么配」就会跟后端的真实能力对不上，
 * 而对不上的后果是：用户照着做完了，接口还是报错。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import PageTitle from '../../components/PageTitle.vue'
import EmptyState from '../../components/EmptyState.vue'
import DevApi from '../../api/dev.js'
import {
  PROJECT_STATUS, modeLabel, modeDesc, modeType, projectStatus,
} from '../../utils/dev.js'

const router = useRouter()
const loading = ref(false)
const saving = ref(false)
const switching = ref(false)
const projects = ref([])
const keyword = ref('')
const statusFilter = ref('')
const mode = ref('offline')
const modelText = ref('未配置')
const doctor = ref(null)
const missing = ref([])
const howToFix = ref([])
const notices = ref([])

const dialogVisible = ref(false)
const editing = ref(null)
const form = reactive({
  name: '',
  goal: '',
  tech_stack_text: '',
  tech_notes: '',
  mode: 'offline',
})

async function loadAll() {
  loading.value = true
  try {
    await Promise.all([loadProjects(), loadConfig()])
  } finally {
    loading.value = false
  }
}

async function loadProjects() {
  const params = {}
  if (keyword.value) params.keyword = keyword.value
  if (statusFilter.value) params.status = statusFilter.value
  const res = await DevApi.projects(params)
  projects.value = (res && res.projects) || []
}

async function loadConfig() {
  const cfg = await DevApi.config()
  if (!cfg) return
  mode.value = cfg.mode || 'offline'
  const m = cfg.model || {}
  modelText.value = m.ready ? (m.name || m.model || '已就绪') : '未配置'
  missing.value = []
  howToFix.value = []
}

async function runDoctor() {
  const res = await DevApi.doctor(mode.value)
  if (!res) return
  doctor.value = res
  missing.value = res.missing || []
  howToFix.value = res.how_to_fix || []
  const bad = (res.capabilities || []).filter((c) => !c.ok)
  if (!bad.length && !missing.value.length) {
    ElMessage.success('能力自检通过，当前配置可以直接开工')
  }
}

async function toggleMode() {
  const next = mode.value === 'online' ? 'offline' : 'online'
  switching.value = true
  try {
    const res = await DevApi.switchMode(next)
    mode.value = res.mode || next
    if (res.missing && res.missing.length) {
      missing.value = res.missing
      howToFix.value = res.how_to_fix || []
      ElMessage.warning('已切换，但还差配置才能真正开工')
    } else {
      missing.value = []
      howToFix.value = []
      ElMessage.success('已切到' + modeLabel(mode.value))
    }
  } catch (e) {
    ElMessage.error('切换失败：' + (e.response?.data?.detail || e.message))
  } finally {
    switching.value = false
  }
}

function openCreate() {
  editing.value = null
  form.name = ''
  form.goal = ''
  form.tech_stack_text = ''
  form.tech_notes = ''
  form.mode = mode.value
  dialogVisible.value = true
}

function openEdit(p) {
  editing.value = p
  form.name = p.name || ''
  form.goal = p.goal || ''
  form.tech_stack_text = (p.tech_stack || []).join(', ')
  form.tech_notes = p.tech_notes || ''
  form.mode = p.mode || 'offline'
  dialogVisible.value = true
}

async function save() {
  if (!form.name.trim()) {
    ElMessage.warning('项目名不能为空')
    return
  }
  saving.value = true
  try {
    const payload = {
      name: form.name.trim(),
      goal: form.goal.trim(),
      tech_stack: form.tech_stack_text
        .split(/[,，]/)
        .map((s) => s.trim())
        .filter(Boolean),
      tech_notes: form.tech_notes.trim(),
      mode: form.mode,
    }
    if (editing.value) {
      await DevApi.patchProject(editing.value.id, payload)
      ElMessage.success('已保存')
    } else {
      const res = await DevApi.createProject(payload)
      ElMessage.success('项目已创建')
      dialogVisible.value = false
      if (res && res.project) goWorkspace(res.project)
      return
    }
    dialogVisible.value = false
    await loadProjects()
  } catch (e) {
    const d = e.response?.data || {}
    const msg = d.detail || e.message || '保存失败'
    ElMessage.error(msg + (d.how_to_fix?.length ? '：' + d.how_to_fix[0] : ''))
  } finally {
    saving.value = false
  }
}

async function remove(p) {
  try {
    await ElMessageBox.confirm(
      '删除后项目里的方案、任务、产出物都会没掉，确定吗？',
      '删除项目「' + p.name + '」',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '算了' }
    )
  } catch {
    return
  }
  try {
    await DevApi.deleteProject(p.id)
    ElMessage.success('已删除')
    await loadProjects()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}

function goWorkspace(p) {
  router.push('/dev/' + p.id)
}

function goSettings() {
  router.push('/dev/settings')
}

function shortTime(t) {
  if (!t) return ''
  return String(t).replace('T', ' ').slice(0, 16)
}

onMounted(loadAll)
</script>

<style scoped>
.dev-page {
  padding: var(--space-6);
}

/* ---------- 模式条 ---------- */
.mode-band {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  flex-wrap: wrap;
  padding: var(--space-4) var(--space-5);
  margin-bottom: var(--space-4);
  border-radius: var(--radius-lg);
  border: 1px solid var(--border);
  background: var(--bg-card);
  box-shadow: var(--shadow-card);
}
.mode-band.offline {
  border-left: 3px solid var(--accent-blue);
}
.mode-band.online {
  border-left: 3px solid var(--accent-green);
}
.mode-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}
.mode-icon {
  font-size: 22px;
  color: var(--primary);
}
.mode-title {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--text-primary);
}
.mode-hint {
  margin-left: var(--space-2);
  font-size: var(--text-xs);
  font-weight: 400;
  color: var(--text-tertiary);
}
.mode-sub {
  margin-top: 3px;
  font-size: var(--text-xs);
  color: var(--text-secondary);
}
.mode-warn {
  color: var(--warning-text);
  margin-left: var(--space-1);
}
.mode-right {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

/* ---------- 提示 ---------- */
.missing-alert,
.notice-alert {
  margin-bottom: var(--space-3);
}
.missing-list {
  margin: var(--space-1) 0 0;
  padding-left: 1.2em;
  font-size: var(--text-sm);
  line-height: 1.8;
}

/* ---------- 工具条 ---------- */
.toolbar {
  display: flex;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
  flex-wrap: wrap;
}
.toolbar-search {
  width: 280px;
}
.toolbar-select {
  width: 150px;
}

/* ---------- 项目卡片 ---------- */
.proj-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--space-4);
}
.proj-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  border-radius: var(--radius-lg);
  border: 1px solid var(--border);
  background: var(--bg-card);
  box-shadow: var(--shadow-card);
  cursor: pointer;
  transition: border-color var(--duration) var(--ease-out),
              transform var(--duration) var(--ease-out);
}
.proj-card:hover {
  border-color: var(--primary);
  transform: translateY(-2px);
}
.proj-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}
.proj-name {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: 620;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.proj-goal {
  margin: 0;
  font-size: var(--text-sm);
  line-height: 1.7;
  color: var(--text-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 2.9em;
}
.proj-tags {
  display: flex;
  gap: var(--space-1);
  flex-wrap: wrap;
}
.proj-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px solid var(--border-light);
}
.proj-meta {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
</style>
