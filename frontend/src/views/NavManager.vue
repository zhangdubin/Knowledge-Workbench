<template>
  <div class="page">
    <PageTitle
      title="导航管理"
      subtitle="把常用的应用、页面挂到左侧导航上。改完立刻生效，所有人看到的是同一份"
      icon-key="Menu"
    >
      <el-button :loading="loading" @click="reload">
        <el-icon><Refresh /></el-icon>刷新
      </el-button>
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>新增导航项
      </el-button>
    </PageTitle>

    <el-alert v-if="loadError" type="error" show-icon :closable="false" class="load-err">
      <template #title>{{ loadError }}</template>
    </el-alert>

    <!-- 提示：自定义项是什么、能指到哪 -->
    <el-alert type="info" :closable="false" class="tip">
      <template #title>
        导航项只是一个入口：点进去之后能看到什么，仍由那个页面自己的权限决定。
        路径填站内地址（如 <code>/apps/customer</code>），不能填外部网址。
      </template>
    </el-alert>

    <div v-if="loading && !items.length" class="skeleton-wrap">
      <el-skeleton :rows="4" animated />
    </div>

    <EmptyState
      v-else-if="!items.length"
      icon="Menu"
      title="还没有自定义导航项"
      description="左侧导航的内置项（工作台、知识库、应用中心…）不能删，但你可以把常用的应用、页面额外挂上去。"
    >
      <el-button type="primary" size="small" @click="openCreate">
        <el-icon><Plus /></el-icon>新增第一个
      </el-button>
    </EmptyState>

    <div v-else class="nav-list">
      <div v-for="it in items" :key="it.id" class="nav-card">
        <div class="nav-icon">
          <el-icon :size="18"><component :is="it.icon || 'Link'" /></el-icon>
        </div>
        <div class="nav-main">
          <div class="nav-title-row">
            <span class="nav-label">{{ it.label }}</span>
            <el-tag size="small" type="info" effect="plain">{{ it.group_name || '自定义' }}</el-tag>
            <span class="nav-path">{{ it.path }}</span>
          </div>
          <div v-if="it.description" class="nav-desc">{{ it.description }}</div>
        </div>
        <div class="nav-actions">
          <el-button link type="primary" size="small" @click="openEdit(it)">
            <el-icon><EditPen /></el-icon>编辑
          </el-button>
          <el-button link type="danger" size="small" @click="remove(it)">
            <el-icon><Delete /></el-icon>删除
          </el-button>
        </div>
      </div>
    </div>

    <!-- 新增 / 编辑 -->
    <el-dialog
      v-model="dialogOpen"
      :title="editing ? '编辑导航项' : '新增导航项'"
      width="480px"
      append-to-body
      class="nav-dialog"
    >
      <div class="form-body">
        <label class="field">
          <span class="field-label">显示名称 <b class="req">*</b></span>
          <el-input v-model="form.label" maxlength="32" show-word-limit placeholder="如：客户案例库" />
        </label>

        <label class="field">
          <span class="field-label">路径 <b class="req">*</b></span>
          <el-input v-model="form.path" placeholder="如 /apps/customer（站内路径，不能是网址）" />
          <span class="field-hint">填了受控页面（如 /apps、/notes）时，只有有权限的人才看得到这个入口</span>
        </label>

        <label class="field">
          <span class="field-label">图标</span>
          <el-select v-model="form.icon" placeholder="选一个图标" clearable filterable style="width: 100%">
            <el-option v-for="ic in ICON_CHOICES" :key="ic" :label="ic" :value="ic">
              <span class="icon-opt">
                <el-icon><component :is="ic" /></el-icon>{{ ic }}
              </span>
            </el-option>
          </el-select>
        </label>

        <label class="field">
          <span class="field-label">所属分组</span>
          <el-input v-model="form.group_name" maxlength="32" placeholder="如：应用（留空则归到「自定义」）" />
        </label>

        <label class="field">
          <span class="field-label">说明</span>
          <el-input v-model="form.description" maxlength="256" placeholder="可选，一句话说清这个入口是干什么的" />
        </label>
      </div>

      <template #footer>
        <el-button size="small" @click="dialogOpen = false">取消</el-button>
        <el-button size="small" type="primary" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, EditPen, Plus, Refresh } from '@element-plus/icons-vue'
import PageTitle from '../components/PageTitle.vue'
import EmptyState from '../components/EmptyState.vue'
import { Api } from '../api'

/** 可选的图标（Element Plus 图标名） */
const ICON_CHOICES = [
  'Link', 'Grid', 'Folder', 'FolderOpened', 'Document', 'Files', 'Notebook',
  'Collection', 'Coin', 'Share', 'Connection', 'DataAnalysis', 'List',
  'Star', 'Flag', 'Compass', 'Position', 'Tickets', 'Memo',
]

const items = ref([])
const loading = ref(false)
const saving = ref(false)
const loadError = ref('')
const dialogOpen = ref(false)
const editing = ref(null)

const form = reactive({
  label: '', path: '', icon: '', group_name: '', description: '',
})

async function reload() {
  loading.value = true
  loadError.value = ''
  try {
    const rows = await Api.listNavItems()
    items.value = Array.isArray(rows) ? rows : []
  } catch (e) {
    loadError.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  Object.assign(form, { label: '', path: '', icon: '', group_name: '', description: '' })
  dialogOpen.value = true
}

function openEdit(it) {
  editing.value = it
  Object.assign(form, {
    label: it.label || '',
    path: it.path || '',
    icon: it.icon || '',
    group_name: it.group_name || '',
    description: it.description || '',
  })
  dialogOpen.value = true
}

async function submit() {
  if (!form.label.trim()) { ElMessage.warning('名称不能为空'); return }
  if (!form.path.trim()) { ElMessage.warning('路径不能为空'); return }
  saving.value = true
  try {
    const payload = {
      label: form.label.trim(),
      path: form.path.trim(),
      icon: form.icon || '',
      group_name: form.group_name.trim(),
      description: form.description.trim(),
    }
    if (editing.value) await Api.updateNavItem(editing.value.id, payload)
    else await Api.createNavItem(payload)
    dialogOpen.value = false
    ElMessage.success(editing.value ? '已保存' : '已新增')
    await reload()
  } catch (e) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function remove(it) {
  try {
    await ElMessageBox.confirm(
      `确定删除导航项「${it.label}」吗？`,
      '删除导航项',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch { return }
  try {
    await Api.deleteNavItem(it.id)
    ElMessage.success('已删除')
    await reload()
  } catch (e) {
    ElMessage.error(e?.message || '删除失败')
  }
}

onMounted(reload)
</script>

<style scoped>
.load-err { margin-bottom: var(--space-4); }
.tip { margin-bottom: var(--space-4); }
.tip code {
  font-family: var(--font-mono);
  background: var(--bg-subtle);
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 12px;
}
.skeleton-wrap {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  padding: var(--space-5);
}

.nav-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.nav-card {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  transition: border-color var(--duration-fast) var(--ease-out);
}
.nav-card:hover { border-color: var(--border); }
.nav-icon {
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  background: var(--primary-bg);
  color: var(--primary-dark);
}
html.dark .nav-icon { color: var(--primary-light); }
.nav-main { flex: 1; min-width: 0; }
.nav-title-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.nav-label {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--text-primary);
}
.nav-path {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
.nav-desc {
  margin-top: 2px;
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
.nav-actions { flex-shrink: 0; display: flex; align-items: center; gap: var(--space-1); }

.form-body { display: flex; flex-direction: column; gap: var(--space-4); }
.field { display: flex; flex-direction: column; gap: 6px; }
.field-label { font-size: var(--text-sm); color: var(--text-secondary); }
.field-label .req { color: var(--danger); }
.field-hint { font-size: var(--text-xs); color: var(--text-tertiary); line-height: 1.6; }
.icon-opt { display: flex; align-items: center; gap: 6px; }

@media (max-width: 720px) {
  .nav-card { flex-wrap: wrap; }
  .nav-actions { width: 100%; justify-content: flex-end; }
}
</style>
