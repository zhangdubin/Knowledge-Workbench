<template>
  <div class="page">
    <PageTitle
      title="应用中心"
      subtitle="每个应用是一组数据模型的容器 · 可从模板一键生成"
      icon-key="Grid"
    >
      <el-button @click="$router.push('/guide')">
        <el-icon><Compass /></el-icon>使用指南
      </el-button>
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>新建应用
      </el-button>
    </PageTitle>

    <!-- 上手引导 -->
    <div v-if="!loading && !apps.length" class="onboard">
      <div class="onboard-icon"><el-icon :size="26"><Compass /></el-icon></div>
      <div class="onboard-body">
        <div class="onboard-title">三步开始使用</div>
        <div class="onboard-steps">
          <div class="onboard-step"><b>1</b> 新建应用（选业务模板，自动生成数据模型）</div>
          <div class="onboard-step"><b>2</b> 在应用下录入业务记录</div>
          <div class="onboard-step"><b>3</b> 把关键记录「沉淀为笔记」接入知识库</div>
        </div>
      </div>
      <el-button type="primary" @click="openCreate">立即新建</el-button>
    </div>

    <div class="app-grid">
      <div v-for="app in apps" :key="app.key" class="app-card" @click="goApp(app)">
        <div class="app-card-header">
          <div class="app-icon">
            <el-icon :size="24"><component :is="resolveIcon(app)" /></el-icon>
          </div>
          <el-dropdown trigger="click" @command="(c) => onCmd(c, app)" @click.stop>
            <el-button text size="small" class="more-btn" @click.stop>
              <el-icon><MoreFilled /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-item command="open">
                <el-icon><View /></el-icon>打开
              </el-dropdown-item>
              <el-dropdown-item command="newtype">
                <el-icon><Plus /></el-icon>新建数据模型
              </el-dropdown-item>
              <el-dropdown-item command="edit" divided>
                <el-icon><Edit /></el-icon>编辑
              </el-dropdown-item>
              <el-dropdown-item command="del">
                <el-icon style="color:var(--danger)"><Delete /></el-icon>
                <span style="color:var(--danger)">删除</span>
              </el-dropdown-item>
            </template>
          </el-dropdown>
        </div>
        <div class="app-name">{{ app.name }}</div>
        <div class="app-desc">{{ app.description || '暂无说明' }}</div>
        <div class="app-meta">
          <span><el-icon><Files /></el-icon>{{ app.entity_count }} 个模型</span>
          <span><el-icon><Document /></el-icon>{{ app.record_count }} 条记录</span>
        </div>
      </div>

      <!-- 新建占位卡 -->
      <div v-if="apps.length" class="app-card add-card" @click="openCreate">
        <div class="add-icon"><el-icon :size="26"><Plus /></el-icon></div>
        <div class="add-title">新建应用</div>
        <div class="add-desc">选模板自动生成模型与关联</div>
      </div>
    </div>

    <!-- 编辑/新建对话框 -->
    <el-dialog
      v-model="dialogOpen"
      :title="editingApp ? `编辑应用 · ${editingApp.name}` : '新建应用'"
      width="720px"
      destroy-on-close
      class="kb-dialog"
      :close-on-click-modal="false"
    >
      <div class="dialog-summary">
        <el-icon><Grid /></el-icon>
        <div>
          应用是数据模型的分组容器。选择模板后，系统会自动生成该业务场景所需的
          <b>数据模型、字段与关联关系</b>，创建完即可直接录数据。
        </div>
      </div>

      <!-- 模板选择（仅新建时） -->
      <div v-if="!editingApp" class="tpl-section">
        <div class="form-section-title">
          选择模板
          <span v-if="tplMeta" class="tpl-meta">
            将生成 {{ tplMeta.type_count }} 个模型 · {{ tplMeta.field_count }} 个字段 · {{ tplMeta.relation_count }} 条关联
          </span>
        </div>
        <div class="tpl-grid">
          <div
            v-for="t in templates"
            :key="t.key"
            class="tpl-card"
            :class="{ active: form.template === t.key }"
            @click="pickTemplate(t)"
          >
            <div class="tpl-icon"><el-icon :size="20"><component :is="t.icon" /></el-icon></div>
            <div class="tpl-body">
              <div class="tpl-name">{{ t.name }}</div>
              <div class="tpl-desc">{{ t.description }}</div>
              <div v-if="t.types.length" class="tpl-tags">
                <el-tag v-for="x in t.types" :key="x.key" size="small" effect="plain">
                  {{ x.name }}
                </el-tag>
              </div>
            </div>
          </div>
        </div>
      </div>

      <el-form :model="form" label-width="76px" label-position="right">
        <el-form-item v-if="!editingApp" label="Key">
          <el-input v-model="form.key" placeholder="英文唯一标识，如 crm" />
          <div class="form-hint">
            创建后不可修改。模板会以此为前缀生成模型 Key，例如 <code>{{ form.key || 'crm' }}_customer</code>
          </div>
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="如：CRM / 库存管理" />
        </el-form-item>
        <el-form-item label="图标">
          <div class="icon-picker">
            <button
              v-for="ic in ICON_CHOICES"
              :key="ic"
              type="button"
              class="icon-choice"
              :class="{ active: form.icon === ic }"
              @click="form.icon = ic"
            >
              <el-icon :size="18"><component :is="ic" /></el-icon>
            </button>
          </div>
        </el-form-item>
        <el-form-item label="说明">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="3"
            placeholder="一句话描述这个应用的用途…"
          />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.order" :min="0" />
          <span class="form-hint" style="margin-left:10px">数值越小越靠前</span>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">
          {{ editingApp ? '保存修改' : (form.template === 'blank' ? '创建应用' : '按模板创建') }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Grid, Plus, Compass } from '@element-plus/icons-vue'
import { Api } from '../api'
import { appIcon, APP_ICON_CHOICES } from '../utils/icons'
import PageTitle from '../components/PageTitle.vue'

const router = useRouter()
const apps = ref([])
const templates = ref([])
const dialogOpen = ref(false)
const editingApp = ref(null)
const saving = ref(false)
const loading = ref(true)

const ICON_CHOICES = APP_ICON_CHOICES

const form = reactive({
  key: '', name: '', icon: 'Grid', description: '', order: 0, template: 'blank',
})

const tplMeta = computed(() => templates.value.find(t => t.key === form.template) || null)

// 若 form.icon 是合法图标名就用它，否则按 key 推导
function resolveIcon(app) {
  if (app.icon && ICON_CHOICES.includes(app.icon)) return app.icon
  return appIcon(app.key)
}

async function load() {
  loading.value = true
  try {
    apps.value = await Api.listApps()
  } finally {
    loading.value = false
  }
}

async function loadTemplates() {
  try {
    templates.value = await Api.listAppTemplates()
  } catch (e) {
    templates.value = [{ key: 'blank', name: '空白应用', icon: 'Grid',
                         description: '不预置任何模型', types: [],
                         type_count: 0, field_count: 0, relation_count: 0 }]
  }
}

function openCreate() {
  editingApp.value = null
  Object.assign(form, {
    key: '', name: '', icon: 'Grid', description: '', order: apps.value.length,
    template: 'blank',
  })
  dialogOpen.value = true
}

// 选中模板时，把模板风格带进表单，减少输入
function pickTemplate(t) {
  form.template = t.key
  if (t.key === 'blank') return
  if (!form.name || templates.value.some(x => x.name === form.name)) form.name = t.name
  form.icon = ICON_CHOICES.includes(t.icon) ? t.icon : form.icon
  if (!form.description) form.description = t.description
  if (!form.key) form.key = t.key
}

function openEdit(app) {
  editingApp.value = app
  Object.assign(form, {
    key: app.key,
    name: app.name,
    icon: resolveIcon(app),
    description: app.description || '',
    order: app.order || 0,
    template: 'blank',
  })
  dialogOpen.value = true
}

async function save() {
  if (!form.name?.trim()) {
    ElMessage.warning('请填写应用名称')
    return
  }
  if (!editingApp.value && !form.key?.trim()) {
    ElMessage.warning('请填写 Key')
    return
  }
  if (!editingApp.value && !/^[a-zA-Z][a-zA-Z0-9_]*$/.test(form.key.trim())) {
    ElMessage.warning('Key 只能用英文字母、数字、下划线，且以字母开头')
    return
  }
  saving.value = true
  try {
    if (editingApp.value) {
      await Api.updateApp(editingApp.value.id, {
        name: form.name,
        icon: form.icon,
        description: form.description,
        order: form.order,
      })
      ElMessage.success('已保存')
      dialogOpen.value = false
      await load()
    } else if (form.template && form.template !== 'blank') {
      const r = await Api.createAppFromTemplate({ ...form })
      ElMessage.success(
        `已按「${tplMeta.value?.name || form.template}」创建：` +
        `${r.types?.length || 0} 个模型 · ${r.relations?.length || 0} 条关联`
      )
      dialogOpen.value = false
      await load()
      router.push(`/apps/${r.app.key}`)
    } else {
      await Api.createApp({
        key: form.key, name: form.name, icon: form.icon,
        description: form.description, order: form.order,
      })
      ElMessage.success('已创建')
      dialogOpen.value = false
      await load()
    }
  } catch (e) {
    ElMessage.error('保存失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    saving.value = false
  }
}

async function del(app) {
  try {
    await ElMessageBox.confirm(
      `删除应用「${app.name}」后不可撤销。该应用下的数据模型与记录会保留，但将失去分组归属。`,
      '删除应用',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await Api.deleteApp(app.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    /* 取消 */
  }
}

function onCmd(cmd, app) {
  if (cmd === 'edit') openEdit(app)
  else if (cmd === 'del') del(app)
  else if (cmd === 'open') goApp(app)
  else if (cmd === 'newtype') router.push({ path: '/types/new', query: { app: app.key } })
}

function goApp(app) {
  router.push(`/apps/${app.key}`)
}

onMounted(() => {
  load()
  loadTemplates()
})
</script>

<style scoped>
.app-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.more-btn { opacity: 0.6; }
.app-card:hover .more-btn { opacity: 1; }

/* 上手引导 */
.onboard {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  background: linear-gradient(135deg, var(--primary-50), var(--bg-card));
  border: 1px solid var(--primary-light);
  border-radius: var(--radius-lg);
  margin-bottom: var(--space-4);
}
.onboard-icon {
  width: 48px; height: 48px; flex-shrink: 0;
  border-radius: var(--radius);
  background: var(--primary-bg);
  color: var(--primary);
  display: flex; align-items: center; justify-content: center;
}
.onboard-body { flex: 1; min-width: 0; }
.onboard-title { font-weight: 700; font-size: var(--text-md); margin-bottom: 6px; }
.onboard-steps { display: flex; flex-direction: column; gap: 3px; }
.onboard-step {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  display: flex; align-items: center; gap: 8px;
}
.onboard-step b {
  display: inline-flex; align-items: center; justify-content: center;
  width: 18px; height: 18px; border-radius: 50%;
  background: var(--primary); color: #fff;
  font-size: 11px; flex-shrink: 0;
}

/* 新建占位卡 */
.add-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  border: 2px dashed var(--border);
  background: transparent;
  box-shadow: none;
  min-height: 180px;
  gap: 6px;
}
.add-card::before { display: none; }
.add-card:hover {
  border-color: var(--primary);
  background: var(--primary-50);
  box-shadow: none;
}
.add-icon {
  width: 48px;
  height: 48px;
  border-radius: var(--radius);
  background: var(--primary-bg);
  color: var(--primary);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 4px;
}
.add-title { font-weight: 600; font-size: var(--text-md); }
.add-desc { font-size: var(--text-xs); color: var(--text-tertiary); }

/* 模板选择 */
.tpl-section { margin-bottom: var(--space-5); }
.tpl-meta {
  float: right;
  font-weight: 500;
  color: var(--text-tertiary);
  text-transform: none;
  letter-spacing: 0;
}
.tpl-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  gap: var(--space-3);
  max-height: 320px;
  overflow-y: auto;
  padding: 2px;
}
.tpl-card {
  display: flex;
  gap: 10px;
  padding: 12px;
  border: 1.5px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-card);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}
.tpl-card:hover {
  border-color: var(--primary-light);
  background: var(--primary-50);
}
.tpl-card.active {
  border-color: var(--primary);
  background: var(--primary-50);
  box-shadow: 0 0 0 2px var(--primary-bg);
}
.tpl-icon {
  width: 34px; height: 34px; flex-shrink: 0;
  border-radius: var(--radius-sm);
  background: var(--primary-bg);
  color: var(--primary);
  display: flex; align-items: center; justify-content: center;
}
.tpl-body { min-width: 0; flex: 1; }
.tpl-name { font-weight: 700; font-size: var(--text-sm); margin-bottom: 3px; }
.tpl-desc {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  line-height: 1.5;
  margin-bottom: 6px;
}
.tpl-tags { display: flex; flex-wrap: wrap; gap: 3px; }
.tpl-tags :deep(.el-tag) { font-size: 10px; height: 18px; padding: 0 5px; }

/* 图标选择器 */
.icon-picker {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: 6px;
  width: 100%;
  max-height: 132px;
  overflow-y: auto;
}
.icon-choice {
  aspect-ratio: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border);
  background: var(--bg-card);
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--text-secondary);
  transition: all var(--duration-fast) var(--ease-out);
  padding: 0;
}
.icon-choice:hover {
  border-color: var(--primary-light);
  color: var(--primary);
  background: var(--primary-50);
}
.icon-choice.active {
  border-color: var(--primary);
  background: var(--primary-bg);
  color: var(--primary);
  box-shadow: 0 0 0 2px var(--primary-bg);
}
.form-hint {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  margin-top: 6px;
  line-height: 1.5;
  display: inline-block;
}
.form-hint code {
  background: var(--bg-subtle);
  padding: 1px 4px;
  border-radius: 3px;
  font-family: var(--font-mono);
}
</style>
