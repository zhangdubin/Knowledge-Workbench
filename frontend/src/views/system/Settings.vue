<template>
  <div class="page">
    <PageTitle
      title="系统设置"
      subtitle="这里的改动立即生效，不需要重启容器 —— 备份目录、保留份数、初始管理员口令"
      icon-key="Setting"
    >
      <el-button :loading="loading" @click="load">
        <el-icon><Refresh /></el-icon>刷新
      </el-button>
    </PageTitle>

    <el-alert v-if="loadError" type="error" show-icon :closable="false" class="load-err">
      <template #title>{{ loadError }}</template>
    </el-alert>

    <!-- 配置从哪来：把优先级摆明，避免「改了没生效」的困惑 -->
    <div class="card">
      <div class="card-title">
        <span class="card-title-text">
          <el-icon class="title-ico"><InfoFilled /></el-icon>配置从哪来
        </span>
      </div>
      <div class="legend">
        <div v-for="p in precedence" :key="p.source" class="legend-row">
          <el-tag size="small" :type="srcTagType(p.source)" effect="light">{{ p.label }}</el-tag>
          <span class="legend-note">{{ p.note }}</span>
        </div>
        <div class="legend-row">
          <el-tag size="small" type="info" effect="plain">优先级</el-tag>
          <span class="legend-note">
            本页设置 &gt; 环境变量 &gt; 代码默认值。同一项被多处设置时，左边的赢。
          </span>
        </div>
      </div>
      <div class="note">
        <el-icon><FolderOpened /></el-icon>
        <span>
          配置文件 <code class="mono">{{ file || '—' }}</code> —— 与 <code class="mono">kb.db</code> 分开放。
          这么设计是有原因的：<b>备份目录不能存在数据库里</b>，否则灾难恢复时会出现
          「要先知道备份在哪，而这条信息正好在你要恢复的库里」的死循环。
        </span>
      </div>
    </div>

    <!-- 按分组渲染 -->
    <div v-for="g in groups" :key="g.name" class="card">
      <div class="card-title">
        <span class="card-title-text">
          <el-icon class="title-ico">
            <component :is="g.name === '安全' ? 'Lock' : 'Coin'" />
          </el-icon>{{ g.name }}
        </span>
      </div>

      <div v-for="it in g.items" :key="it.key" class="set-row" :class="{ dirty: isDirty(it) }">
        <div class="set-head">
          <div class="set-name">
            {{ it.label }}
            <el-tag size="small" :type="srcTagType(it.source)" effect="light">
              来源：{{ srcLabel(it.source) }}
            </el-tag>
            <el-tag v-if="it.source === 'env' && it.env_value" size="small" type="warning" effect="plain">
              环境变量会覆盖默认值
            </el-tag>
            <template v-if="it.kind === 'secret'">
              <el-tag v-if="it.is_set" size="small" type="success" effect="plain">已自定义</el-tag>
              <el-tag v-else-if="it.is_weak" size="small" type="danger" effect="plain">仍是默认弱口令</el-tag>
            </template>
          </div>
          <div class="set-key mono">{{ it.key }}</div>
        </div>

        <div class="set-help">{{ it.help }}</div>

        <div class="set-body">
          <!-- 整数 -->
          <el-input-number
            v-if="it.kind === 'int'"
            v-model="draft[it.key]"
            :min="it.min" :max="it.max"
            controls-position="right"
            style="width: 180px"
          />

          <!-- 路径：候选下拉 + 可手填 -->
          <template v-else-if="it.kind === 'path'">
            <div class="path-row">
              <el-select
                v-model="draft[it.key]"
                filterable allow-create default-first-option
                placeholder="选择一个候选目录，或直接输入容器内绝对路径"
                style="flex: 1; min-width: 280px"
              >
                <el-option
                  v-for="c in candidates"
                  :key="c.path"
                  :value="c.path"
                  :disabled="!!c.blocked || !c.ok"
                  :label="c.path"
                >
                  <span class="opt-path mono">{{ c.path }}</span>
                  <span class="opt-tags">
                    <el-tag v-if="c.is_current" size="small" type="info" effect="plain">当前</el-tag>
                    <el-tag v-if="c.recommended" size="small" type="success" effect="plain">推荐</el-tag>
                    <el-tag v-else-if="c.blocked" size="small" type="danger" effect="plain">不可用</el-tag>
                    <el-tag v-else-if="!c.ok" size="small" type="info" effect="plain">不存在</el-tag>
                    <el-tag v-else-if="c.same_device_as_data" size="small" type="warning" effect="plain">与数据同盘</el-tag>
                  </span>
                </el-option>
              </el-select>
              <el-button :loading="probing" @click="doProbe">
                <el-icon><Aim /></el-icon>测试
              </el-button>
            </div>

            <div v-if="probeResult" class="probe" :class="probeResult.ok ? 'ok' : 'bad'">
              <el-icon><component :is="probeResult.ok ? 'CircleCheck' : 'WarningFilled'" /></el-icon>
              <span v-if="probeResult.ok">
                可用 —— 位于挂载点 <code class="mono">{{ probeResult.mount }}</code>，
                剩余 {{ fmtBytes(probeResult.free_bytes) }}；
                {{ probeResult.separate_declared ? '已声明为独立备份盘' :
                   probeResult.same_device_as_data ? '与数据目录同盘（只防误删）' : '与数据目录不同盘' }}
              </span>
              <span v-else>{{ probeResult.error }}</span>
            </div>

            <!-- 候选目录表：让「有没有别的盘可用」一眼可见 -->
            <div class="cand-box">
              <div class="cand-title">
                <span>容器内可用作备份的目录（{{ candidates.length }}）</span>
                <span v-if="!hasAlternate" class="cand-warn">
                  <el-icon><WarningFilled /></el-icon>
                  没有与数据盘分离的盘 —— 见下方挂载指引
                </span>
              </div>
              <el-table :data="candidates" size="small" class="data-table"
                        :row-class-name="candRowClass"
                        empty-text="没有探测到可用目录">
                <el-table-column label="路径" min-width="200">
                  <template #default="{ row }">
                    <span class="mono">{{ row.path }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="状态" width="190">
                  <template #default="{ row }">
                    <el-tag v-if="row.is_current" size="small" type="info" effect="plain">当前生效</el-tag>
                    <el-tag v-else-if="row.recommended" size="small" type="success" effect="plain">推荐</el-tag>
                    <el-tag v-else-if="row.blocked" size="small" type="danger" effect="plain">禁止</el-tag>
                    <el-tag v-else-if="!row.ok" size="small" type="info" effect="plain">不可用</el-tag>
                    <el-tag v-else size="small" type="warning" effect="plain">可用</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="说明" min-width="260">
                  <template #default="{ row }">
                    <span v-if="row.blocked" class="bad-text">{{ row.blocked }}</span>
                    <span v-else-if="!row.ok" class="bad-text">{{ row.error }}</span>
                    <span v-else class="dim">
                      {{ row.note }}
                      <template v-if="row.same_device_as_data"> · 与数据同盘</template>
                      <template v-else> · 独立盘{{ row.separate_declared ? '（按部署声明）' : '' }}</template>
                    </span>
                  </template>
                </el-table-column>
                <el-table-column label="剩余" width="100">
                  <template #default="{ row }">{{ row.free_bytes ? fmtBytes(row.free_bytes) : '—' }}</template>
                </el-table-column>
                <el-table-column label="" width="70">
                  <template #default="{ row }">
                    <el-button v-if="row.ok && !row.blocked && !row.is_current" link type="primary"
                               @click="draft[it.key] = row.path">选用</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>

            <!-- 没有独立盘时给出可复制的挂载指引：这是 Docker 层的边界，
                 应用层绕不过去，所以如实告诉用户下一步在宿主机做什么 -->
            <div v-if="!hasAlternate" class="note warn">
              <el-icon><WarningFilled /></el-icon>
              <div class="guide">
                <p>
                  当前所有候选都与数据目录在<b>同一块盘</b>上 —— 这样的备份只能防误删，
                  防不了磁盘故障。要真正分盘，需要在 <code class="mono">docker-compose.yml</code>
                  里把宿主机上另一块盘挂进容器：
                </p>
                <div v-for="(s, i) in guides" :key="i" class="guide-step">
                  <div class="guide-title">{{ i + 1 }}. {{ s.title }}</div>
                  <pre class="guide-code">{{ s.snippet }}</pre>
                </div>
              </div>
            </div>
          </template>

          <!-- 口令 -->
          <div v-else-if="it.kind === 'secret'" class="secret-row">
            <el-input
              v-model="draft[it.key]"
              type="password" show-password
              :placeholder="it.is_set ? '已自定义过；留空表示不修改' : '留空表示沿用环境变量/默认值'"
              style="max-width: 360px"
            />
            <span class="dim">至少 {{ it.min_len }} 位</span>
          </div>

          <el-input v-else v-model="draft[it.key]" style="max-width: 360px" />
        </div>

        <div class="set-foot">
          <span v-if="isDirty(it)" class="dirty-tip">
            <el-icon><EditPen /></el-icon>已修改，尚未保存
          </span>
          <span v-else-if="it.source === 'file'" class="dim">
            与 <code class="mono">{{ file }}</code> 中的值一致
          </span>
          <span v-else class="dim">沿用{{ srcLabel(it.source) }}，未做本页设置</span>
          <el-button v-if="it.source === 'file'" link type="danger"
                     @click="doReset(it)">恢复默认</el-button>
          <el-button v-else-if="isDirty(it)" link @click="revert(it)">撤销改动</el-button>
        </div>
      </div>
    </div>

    <!-- 底部操作条 -->
    <div class="save-bar">
      <div class="save-info">
        <template v-if="dirtyKeys.length">
          <el-icon><WarningFilled /></el-icon>
          待保存 {{ dirtyKeys.length }} 项：<span class="mono">{{ dirtyKeys.join('、') }}</span>
        </template>
        <template v-else>没有未保存的改动</template>
      </div>
      <div>
        <el-button :disabled="!dirtyKeys.length || saving" @click="revertAll">全部撤销</el-button>
        <el-button type="primary" :disabled="!dirtyKeys.length" :loading="saving" @click="save">
          <el-icon><Select /></el-icon>保存修改
        </el-button>
      </div>
    </div>

    <!-- 关于系统：版本标识的「正式户口」——排障时让人一眼说清跑的是哪一版 -->
    <div class="card">
      <div class="card-title">
        <span class="card-title-text">
          <el-icon class="title-ico"><Info /></el-icon>关于系统
        </span>
      </div>
      <div class="about-rows">
        <div class="about-row">
          <span class="about-label">版本</span>
          <span class="about-value mono">v{{ auth.sysVersion || '—' }}</span>
        </div>
        <div class="about-row">
          <span class="about-label">服务名</span>
          <span class="about-value">知识工作台 · Knowledge Workbench</span>
        </div>
        <div class="about-row">
          <span class="about-label">版本说明</span>
          <span class="about-value dim">
            升级离线包后此处的版本号会自动更新；报障时请附上版本号与「存储与备份」页的深度自检结果。
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Api } from '../../api'
import { useAuthStore } from '../../stores/auth'
import PageTitle from '../../components/PageTitle.vue'

const auth = useAuthStore()

const loading = ref(false)
const saving = ref(false)
const probing = ref(false)
const loadError = ref('')
const items = ref([])
const file = ref('')
const precedence = ref([])
const targets = ref(null)
const probeResult = ref(null)
const draft = reactive({})

const candidates = computed(() => targets.value?.candidates || [])
const guides = computed(() => targets.value?.guides || [])
// 判断依据来自后端：Docker Desktop 下容器分不清宿主机磁盘，
// 所以「有没有独立盘」是「自动判断 或 部署方显式声明」的合并结论
const hasAlternate = computed(() => !!targets.value?.has_alternate_disk)

const groups = computed(() => {
  const map = new Map()
  for (const it of items.value) {
    if (!map.has(it.group)) map.set(it.group, [])
    map.get(it.group).push(it)
  }
  return [...map.entries()].map(([name, list]) => ({ name, items: list }))
})

function srcLabel(s) {
  return { file: '系统设置', env: '环境变量', default: '代码默认值' }[s] || s
}
function srcTagType(s) {
  return { file: 'success', env: 'warning', default: 'info' }[s] || 'info'
}
function fmtBytes(v) {
  if (v === null || v === undefined) return '—'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let n = Number(v), i = 0
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++ }
  return `${n >= 100 ? n.toFixed(0) : n.toFixed(1)} ${u[i]}`
}
function candRowClass({ row }) {
  if (row.blocked) return 'row-blocked'
  if (row.recommended) return 'row-good'
  return ''
}

// 口令项：只要输入框非空就算改动（后端不回显明文，没法比对原值）
function isDirty(it) {
  if (it.kind === 'secret') return !!draft[it.key]
  const a = draft[it.key]
  const b = it.value
  return a === undefined || a === null ? false : String(a) !== String(b)
}
const dirtyKeys = computed(() => items.value.filter(isDirty).map(i => i.key))

function fillDraft(keepDirty = false) {
  for (const it of items.value) {
    if (keepDirty && isDirty(it)) continue
    draft[it.key] = it.kind === 'secret' ? '' : it.value
  }
}
function revert(it) {
  draft[it.key] = it.kind === 'secret' ? '' : it.value
  if (it.kind === 'path') probeResult.value = null
}
function revertAll() {
  fillDraft(false)
  probeResult.value = null
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const s = await Api.settings()
    items.value = s.items || []
    file.value = s.file
    precedence.value = s.precedence || []
    fillDraft(false)
    probeResult.value = null
    // 候选目录单独容错：它挂了不该让整个页面变成空白
    try {
      targets.value = await Api.backupTargets()
    } catch (e) {
      targets.value = null
    }
  } catch (e) {
    loadError.value = e?.response?.data?.detail || '配置加载失败，请检查登录状态与后端服务'
  } finally {
    loading.value = false
  }
}

async function doProbe() {
  const p = draft.backup_dir
  if (!p) { ElMessage.warning('请先填写或选择一个目录'); return }
  probing.value = true
  try {
    probeResult.value = await Api.probePath(p)
  } catch (e) {
    probeResult.value = { ok: false, error: e?.response?.data?.detail || '测试失败' }
  } finally {
    probing.value = false
  }
}

async function save() {
  const payload = {}
  for (const it of items.value) {
    if (isDirty(it)) payload[it.key] = draft[it.key]
  }
  if (!Object.keys(payload).length) return
  if (payload.backup_dir) {
    try {
      await ElMessageBox.confirm(
        `备份目录将改为：\n${payload.backup_dir}\n\n`
        + '改完之后新备份会落到新目录；已有备份不会自动搬过去，需要手动迁移或重新备份一次。',
        '确认修改备份目录', { type: 'warning', confirmButtonText: '确认修改', cancelButtonText: '再想想' }
      )
    } catch { return }
  }
  saving.value = true
  try {
    const res = await Api.saveSettings(payload)
    for (const w of res.warnings || []) ElMessage.warning(w)
    if (res.items) items.value = res.items
    fillDraft(false)
    probeResult.value = null
    ElMessage.success(`已保存：${(res.changed || []).join('、')}（立即生效，无需重启）`)
    try { targets.value = await Api.backupTargets() } catch (e) { /* 忽略 */ }
  } catch (e) {
    // 校验失败的具体原因由拦截器弹出，这里保持页面状态不变，便于改正后重存
  } finally {
    saving.value = false
  }
}

async function doReset(it) {
  try {
    await ElMessageBox.confirm(
      `把「${it.label}」恢复成环境变量/默认值？该设置会从配置文件中移除。`,
      '恢复默认', { type: 'warning' }
    )
  } catch { return }
  try {
    const res = await Api.resetSetting(it.key)
    if (res.items) items.value = res.items
    fillDraft(false)
    ElMessage.success('已恢复默认')
    try { targets.value = await Api.backupTargets() } catch (e) { /* 忽略 */ }
  } catch (e) { /* 拦截器已提示 */ }
}

onMounted(load)
</script>

<style scoped>
.page { padding: 0 0 76px; }
.load-err { margin-bottom: 14px; }

.card {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-light);
  border-radius: 10px;
  padding: 16px 18px;
  margin-bottom: 14px;
}
.card-title {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 14px;
}
.card-title-text {
  display: inline-flex; align-items: center; gap: 6px;
  font-weight: 600; font-size: 15px; color: var(--el-text-color-primary);
}
.title-ico { color: var(--el-color-primary); }

.legend { display: flex; flex-direction: column; gap: 8px; }
.legend-row { display: flex; align-items: center; gap: 10px; font-size: 13px; }
.legend-note { color: var(--el-text-color-regular); }

.note {
  display: flex; gap: 8px; align-items: flex-start;
  margin-top: 12px; padding: 10px 12px;
  border-radius: 8px; font-size: 13px; line-height: 1.7;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-regular);
}
.note.warn {
  background: var(--el-color-warning-light-9);
  color: var(--el-color-warning-dark-2);
}
.note code, .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }

.set-row {
  padding: 14px 0;
  border-top: 1px solid var(--el-border-color-lighter);
}
.set-row:first-of-type { border-top: none; padding-top: 0; }
.set-row.dirty { background: var(--el-color-primary-light-9); border-radius: 8px; padding-left: 10px; padding-right: 10px; }
.set-head {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; flex-wrap: wrap;
}
.set-name {
  display: inline-flex; align-items: center; gap: 8px;
  font-weight: 600; color: var(--el-text-color-primary);
}
.set-key { font-size: 12px; color: var(--el-text-color-placeholder); }
.set-help {
  margin: 6px 0 10px; font-size: 13px; line-height: 1.75;
  color: var(--el-text-color-regular); max-width: 900px;
}
.set-body { display: flex; flex-direction: column; gap: 10px; }
.set-foot {
  display: flex; align-items: center; gap: 10px;
  margin-top: 10px; font-size: 12px;
}
.dirty-tip { display: inline-flex; align-items: center; gap: 4px; color: var(--el-color-primary); }
.dim { color: var(--el-text-color-secondary); }
.bad-text { color: var(--el-color-danger); }

.path-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.secret-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }

.probe {
  display: flex; align-items: center; gap: 6px;
  font-size: 13px; padding: 8px 10px; border-radius: 6px;
}
.probe.ok { background: var(--el-color-success-light-9); color: var(--el-color-success-dark-2); }
.probe.bad { background: var(--el-color-danger-light-9); color: var(--el-color-danger); }

.cand-box { margin-top: 4px; }
.cand-title {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  font-size: 13px; color: var(--el-text-color-regular); margin-bottom: 8px;
}
.cand-warn { display: inline-flex; align-items: center; gap: 4px; color: var(--el-color-warning-dark-2); }
.opt-path { margin-right: 10px; }
.opt-tags { float: right; }
.data-table { width: 100%; }

.guide { flex: 1; }
.guide p { margin: 0 0 8px; }
.guide-step { margin-top: 6px; }
.guide-title { font-weight: 600; margin-bottom: 4px; }
.guide-code {
  margin: 0; padding: 8px 10px; border-radius: 6px; overflow-x: auto;
  background: var(--el-fill-color-darker);
  color: var(--el-text-color-primary);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px; line-height: 1.6;
}

.save-bar {
  position: sticky; bottom: 0; z-index: 5;
  display: flex; align-items: center; justify-content: space-between; gap: 14px;
  padding: 12px 18px; border-radius: 10px;
  background: var(--el-bg-color-overlay);
  border: 1px solid var(--el-border-color-light);
  box-shadow: 0 -2px 12px rgba(0, 0, 0, .06);
}
.save-info {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 13px; color: var(--el-text-color-regular);
}

/* 关于系统 */
.about-rows { display: flex; flex-direction: column; gap: 10px; }
.about-row { display: flex; gap: 16px; align-items: baseline; }
.about-label {
  flex-shrink: 0;
  width: 72px;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
}
.about-value { font-size: 14px; color: var(--el-text-color-primary); }
.about-value.mono { font-family: var(--font-mono); font-weight: 600; }
.about-value.dim { color: var(--el-text-color-secondary); font-size: 13px; }

:deep(.row-blocked) { opacity: .75; }
:deep(.row-good) { background: var(--el-color-success-light-9); }
</style>
