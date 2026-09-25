<template>
  <div class="page">
    <PageTitle
      title="可视化驾驶舱"
      subtitle="把分散在各处的数据摆到一屏上。卡片可自由组合：指标、图表、表格、清单、说明文字"
      icon-key="DataLine"
    >
      <el-button @click="openBlank">
        <el-icon><Plus /></el-icon>新建空白
      </el-button>
      <el-button type="primary" @click="openTemplates">
        <el-icon><MagicStick /></el-icon>从模板创建
      </el-button>
    </PageTitle>

    <div v-loading="loading" class="dash-grid">
      <div v-for="d in items" :key="d.id" class="dash-card" :class="{ pinned: d.pinned }"
           @click="open(d)">
        <div class="dc-top">
          <span class="dc-icon">{{ d.icon || '📊' }}</span>
          <div class="dc-title-block">
            <div class="dc-name">{{ d.name }}</div>
            <code class="dc-key">{{ d.key }}</code>
          </div>
          <el-tooltip :content="d.pinned ? '取消置顶' : '置顶到列表最前'" placement="top">
            <button class="dc-pin" :class="{ on: d.pinned }" @click.stop="togglePin(d)">
              <el-icon :size="15"><StarFilled /></el-icon>
            </button>
          </el-tooltip>
        </div>

        <p class="dc-desc">{{ d.description || '还没有写说明' }}</p>

        <div class="dc-foot">
          <span class="dc-stat">
            <el-icon :size="13"><Grid /></el-icon>{{ d.widget_count }} 张卡片
          </span>
          <span class="dc-time">{{ formatTime(d.updated_at) }}</span>
        </div>

        <div v-if="canWrite" class="dc-actions">
          <el-button size="small" link type="primary" @click.stop="openMeta(d)">
            <el-icon><Edit /></el-icon>重命名
          </el-button>
          <el-button size="small" link type="danger" @click.stop="del(d)">
            <el-icon><Delete /></el-icon>删除
          </el-button>
        </div>
      </div>

      <button v-if="!loading" class="dash-add" @click="openTemplates">
        <el-icon :size="24"><Plus /></el-icon>
        <span>新建驾驶舱</span>
        <span class="da-hint">从模板起步最快</span>
      </button>
    </div>

    <div v-if="!loading && !items.length" class="empty-state">
      <div class="empty-icon"><el-icon :size="32"><DataLine /></el-icon></div>
      <div class="empty-title">还没有驾驶舱</div>
      <div class="empty-desc">从模板创建一个，再按需要增删卡片</div>
      <el-button type="primary" style="margin-top:16px" @click="openTemplates">
        <el-icon><MagicStick /></el-icon>从模板创建
      </el-button>
    </div>

    <!-- 从模板 -->
    <el-dialog v-model="tplOpen" title="从模板创建驾驶舱" width="620px"
               class="rich-dialog" :close-on-click-modal="false">
      <div class="dialog-summary">
        <el-icon :size="18"><MagicStick /></el-icon>
        <span>模板是可直接使用的成品，建好后卡片都能改：换数据源、改图表、调宽度、重排。</span>
      </div>
      <div class="tpl-list">
        <label v-for="t in templates" :key="t.key" class="tpl-item"
               :class="{ on: tplForm.key === t.key }">
          <el-radio v-model="tplForm.key" :value="t.key"><span /></el-radio>
          <span class="ti-icon">{{ t.icon }}</span>
          <span class="ti-body">
            <span class="ti-name">{{ t.name }}</span>
            <span class="ti-desc">{{ t.description }}</span>
            <span class="ti-meta">{{ t.layout.length }} 张卡片 ·
              {{ typeSummary(t.layout) }}</span>
          </span>
        </label>
        <div v-if="!templates.length" class="tpl-empty">后端还没有可用模板</div>
      </div>
      <el-form label-width="80px" style="margin-top:14px">
        <el-form-item label="名称">
          <el-input v-model="tplForm.name" placeholder="留空则用模板名称" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="tplOpen = false">取消</el-button>
        <el-button type="primary" :loading="creating" :disabled="!tplForm.key" @click="createFromTpl">
          创建并打开
        </el-button>
      </template>
    </el-dialog>

    <!-- 新建空白 -->
    <el-dialog v-model="blankOpen" title="新建空白驾驶舱" width="520px"
               class="rich-dialog" :close-on-click-modal="false">
      <el-form :model="blankForm" label-width="80px">
        <el-form-item label="标识" required>
          <el-input v-model="blankForm.key" placeholder="英文/下划线，如 ops_board" />
          <div class="form-hint">用于接口与链接，创建后不可修改。</div>
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input v-model="blankForm.name" placeholder="显示在列表与顶部" />
        </el-form-item>
        <el-form-item label="图标">
          <el-input v-model="blankForm.icon" placeholder="一个 emoji 即可" style="width:110px" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="blankForm.description" type="textarea" :rows="2"
                    placeholder="这个驾驶舱关注什么" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="blankOpen = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createBlank">创建并打开</el-button>
      </template>
    </el-dialog>

    <!-- 重命名 / 改说明 -->
    <el-dialog v-model="metaOpen" title="编辑信息" width="480px" class="rich-dialog">
      <el-form :model="metaForm" label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="metaForm.name" />
        </el-form-item>
        <el-form-item label="图标">
          <el-input v-model="metaForm.icon" style="width:110px" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="metaForm.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="metaOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveMeta">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Api } from '../api'
import { formatTime } from '../utils/format'
import { useAuthStore } from '../stores/auth'
import PageTitle from '../components/PageTitle.vue'

const router = useRouter()
const auth = useAuthStore()

const items = ref([])
const templates = ref([])
const loading = ref(false)
const creating = ref(false)
const saving = ref(false)

const tplOpen = ref(false)
const blankOpen = ref(false)
const metaOpen = ref(false)

const tplForm = reactive({ key: '', name: '' })
const blankForm = reactive({ key: '', name: '', icon: '📊', description: '' })
const metaForm = reactive({ id: null, name: '', icon: '', description: '' })

const canWrite = computed(() => auth.can('dashboard_write'))

const TYPE_LABELS = { stat: '指标', chart: '图表', table: '表格', list: '清单', text: '文字' }

function typeSummary(layout) {
  const counts = {}
  ;(layout || []).forEach(w => { counts[w.type] = (counts[w.type] || 0) + 1 })
  return Object.entries(counts).map(([k, v]) => `${TYPE_LABELS[k] || k}×${v}`).join('、')
}

async function load() {
  loading.value = true
  try {
    const r = await Api.listDashboards()
    items.value = r.items || []
  } catch (e) { /* 拦截器已提示 */ } finally {
    loading.value = false
  }
}

function open(d) { router.push(`/dashboards/${d.id}`) }

async function openTemplates() {
  try {
    const r = await Api.dashboardTemplates()
    templates.value = r.items || []
  } catch { templates.value = [] }
  tplForm.key = templates.value[0]?.key || ''
  tplForm.name = ''
  tplOpen.value = true
}

function openBlank() {
  Object.assign(blankForm, { key: '', name: '', icon: '📊', description: '' })
  blankOpen.value = true
}

function openMeta(d) {
  Object.assign(metaForm, { id: d.id, name: d.name, icon: d.icon, description: d.description })
  metaOpen.value = true
}

async function createFromTpl() {
  creating.value = true
  try {
    const d = await Api.createFromTemplate(tplForm.key, tplForm.name.trim())
    ElMessage.success('已创建')
    tplOpen.value = false
    router.push(`/dashboards/${d.id}`)
  } catch (e) { /* 拦截器已提示 */ } finally {
    creating.value = false
  }
}

async function createBlank() {
  const key = (blankForm.key || '').trim()
  if (!/^[a-z][a-z0-9_]*$/.test(key)) {
    ElMessage.warning('标识需以小写字母开头，只含小写字母、数字与下划线')
    return
  }
  if (!blankForm.name.trim()) { ElMessage.warning('请填写名称'); return }
  creating.value = true
  try {
    const d = await Api.createDashboard({
      key, name: blankForm.name.trim(), icon: blankForm.icon || '📊',
      description: blankForm.description, layout: [],
    })
    ElMessage.success('已创建，接下来添加卡片')
    blankOpen.value = false
    router.push(`/dashboards/${d.id}`)
  } catch (e) { /* 拦截器已提示 */ } finally {
    creating.value = false
  }
}

async function saveMeta() {
  saving.value = true
  try {
    await Api.updateDashboard(metaForm.id, {
      name: metaForm.name, icon: metaForm.icon, description: metaForm.description,
    })
    ElMessage.success('已保存')
    metaOpen.value = false
    await load()
  } catch (e) { /* 拦截器已提示 */ } finally {
    saving.value = false
  }
}

async function togglePin(d) {
  try {
    await Api.updateDashboard(d.id, { pinned: !d.pinned })
    // 置顶在列表里排前面，本地重排避免整页刷新
    items.value = items.value
      .map(x => (x.id === d.id ? { ...x, pinned: !d.pinned } : x))
      .sort((a, b) => (Number(b.pinned) - Number(a.pinned)) || (a.order - b.order) || (a.id - b.id))
  } catch (e) { /* 拦截器已提示 */ }
}

async function del(d) {
  try {
    await ElMessageBox.confirm(
      `删除驾驶舱「${d.name}」？其中的 ${d.widget_count} 张卡片配置会一起删除，业务数据不受影响。`,
      '删除驾驶舱', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await Api.deleteDashboard(d.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) { /* 取消 */ }
}

onMounted(load)
</script>

<style scoped>
.dash-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
  gap: var(--space-4);
  min-height: 120px;
}

.dash-card {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--radius-md); padding: 16px 18px;
  box-shadow: var(--shadow-xs); cursor: pointer; position: relative;
  transition: border-color var(--duration) var(--ease-out),
              box-shadow var(--duration) var(--ease-out),
              transform var(--duration) var(--ease-out);
  display: flex; flex-direction: column;
}
.dash-card:hover {
  border-color: var(--primary-200); box-shadow: var(--shadow);
  transform: translateY(-2px);
}
.dash-card.pinned { border-color: var(--primary-200); background: linear-gradient(160deg, var(--primary-bg), transparent 62%); }

.dc-top { display: flex; align-items: flex-start; gap: 10px; }
.dc-icon {
  width: 38px; height: 38px; border-radius: var(--radius); flex-shrink: 0;
  background: var(--bg-subtle); display: inline-flex;
  align-items: center; justify-content: center; font-size: 19px; line-height: 1;
}
.dc-title-block { flex: 1; min-width: 0; }
.dc-name {
  font-size: var(--text-md); font-weight: 650; color: var(--text-primary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.dc-key {
  font-family: var(--font-mono); font-size: var(--text-xs); color: var(--text-tertiary);
}
.dc-pin {
  border: none; background: transparent; cursor: pointer; padding: 4px;
  color: var(--text-disabled); border-radius: var(--radius-xs); flex-shrink: 0;
  transition: color var(--duration) var(--ease-out), background var(--duration) var(--ease-out);
}
.dc-pin:hover { background: var(--bg-subtle); color: var(--warning); }
.dc-pin.on { color: var(--warning); }

.dc-desc {
  margin: 10px 0 0; font-size: var(--text-sm); color: var(--text-tertiary);
  line-height: 1.55; min-height: 34px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}

.dc-foot {
  display: flex; align-items: center; justify-content: space-between;
  gap: 8px; margin-top: 12px; padding-top: 10px;
  border-top: 1px solid var(--border-light);
  font-size: var(--text-xs); color: var(--text-tertiary);
}
.dc-stat { display: inline-flex; align-items: center; gap: 5px; }
.dc-time { font-variant-numeric: tabular-nums; }
.dc-actions {
  display: flex; gap: 4px; margin-top: 8px; padding-top: 6px;
  border-top: 1px dashed var(--border-light);
  opacity: 0; transition: opacity var(--duration) var(--ease-out);
}
.dash-card:hover .dc-actions { opacity: 1; }

.dash-add {
  min-height: 168px; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 6px;
  border: 1px dashed var(--border-strong); border-radius: var(--radius-md);
  background: transparent; cursor: pointer; color: var(--text-tertiary);
  font-family: inherit; font-size: var(--text-base);
  transition: all var(--duration) var(--ease-out);
}
.dash-add:hover { border-color: var(--primary); color: var(--primary); background: var(--primary-bg); }
.da-hint { font-size: var(--text-xs); opacity: 0.75; }

.tpl-list { display: flex; flex-direction: column; gap: 8px; max-height: 320px; overflow: auto; }
.tpl-item {
  display: flex; align-items: flex-start; gap: 10px; padding: 12px 14px;
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  cursor: pointer; transition: all var(--duration) var(--ease-out);
}
.tpl-item:hover { border-color: var(--primary-200); }
.tpl-item.on { border-color: var(--primary); background: var(--primary-bg); }
.tpl-item :deep(.el-radio) { margin-right: 0; height: auto; margin-top: 6px; }
.tpl-item :deep(.el-radio__label) { display: none; }
.ti-icon { font-size: 20px; line-height: 1; margin-top: 4px; }
.ti-body { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.ti-name { font-size: var(--text-base); font-weight: 650; color: var(--text-primary); }
.ti-desc { font-size: var(--text-sm); color: var(--text-tertiary); line-height: 1.5; }
.ti-meta { font-size: var(--text-xs); color: var(--text-disabled); font-variant-numeric: tabular-nums; }
.tpl-empty { padding: 26px; text-align: center; color: var(--text-tertiary); font-size: var(--text-sm); }
.form-hint { font-size: var(--text-xs); color: var(--text-tertiary); margin-top: 6px; }

@media (max-width: 768px) {
  .dash-grid { grid-template-columns: 1fr; }
  .dc-actions { opacity: 1; }
}
</style>
