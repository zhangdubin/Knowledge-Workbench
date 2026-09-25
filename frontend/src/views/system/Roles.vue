<template>
  <div class="page">
    <PageTitle
      title="角色权限"
      subtitle="角色是一组权限的集合；把角色分给用户，用户就拥有了这组页面、功能与数据范围"
      icon-key="Lock"
    >
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>新建角色
      </el-button>
    </PageTitle>

    <div class="role-layout">
      <!-- 左：角色清单 -->
      <aside class="role-list card" style="padding:0;overflow:hidden">
        <div class="list-head">
          <span>角色</span>
          <span class="badge">{{ roles.length }}</span>
        </div>
        <button
          v-for="r in roles"
          :key="r.id"
          class="role-item"
          :class="{ active: r.id === selectedId }"
          @click="select(r)"
        >
          <span class="ri-icon" :class="{ super: r.perms?.all }">
            <el-icon :size="15"><component :is="r.perms?.all ? 'Medal' : 'UserFilled'" /></el-icon>
          </span>
          <span class="ri-body">
            <span class="ri-name">
              {{ r.name }}
              <el-icon v-if="r.is_builtin" class="ri-lock" :size="12"><Lock /></el-icon>
            </span>
            <span class="ri-key">{{ r.key }}</span>
          </span>
          <span class="ri-count" :title="`${r.user_count} 个用户`">{{ r.user_count }}</span>
        </button>
        <div v-if="!roles.length && !loading" class="list-empty">暂无角色</div>
      </aside>

      <!-- 右：权限矩阵 -->
      <section class="role-detail">
        <div v-if="!selected" class="empty-state" style="margin:0">
          <div class="empty-icon"><el-icon :size="32"><Lock /></el-icon></div>
          <div class="empty-title">选择一个角色</div>
          <div class="empty-desc">左侧点选角色，即可查看并编辑它的权限范围</div>
        </div>

        <template v-else>
          <div class="card editor-head">
            <div class="eh-main">
              <el-input v-model="draft.name" class="eh-name" placeholder="角色名称" />
              <div class="eh-meta">
                <code>{{ selected.key }}</code>
                <el-tag v-if="selected.is_builtin" size="small" effect="plain">内置</el-tag>
                <span class="eh-users">{{ selected.user_count }} 个用户</span>
              </div>
              <el-input v-model="draft.description" type="textarea" :rows="2"
                        placeholder="这个角色适合谁用？一句话说明" />
            </div>
            <div class="eh-side">
              <div class="all-perm">
                <el-switch v-model="draft.all" :disabled="!canToggleAll" />
                <div>
                  <div class="ap-title">全部权限</div>
                  <div class="ap-desc">{{ allHint }}</div>
                </div>
              </div>
              <div v-if="dirty" class="dirty-flag">
                <el-icon :size="13"><WarningFilled /></el-icon>有未保存的修改
              </div>
            </div>
          </div>

          <div v-if="draft.all" class="card all-banner">
            <el-icon :size="18"><InfoFilled /></el-icon>
            <span>该角色拥有<strong>全部权限</strong>：忽略下列任何勾选，所有页面、功能与模型都是可读写的。</span>
          </div>

          <div class="card" :class="{ muted: draft.all }">
            <div class="card-title">
              <span class="card-title-text"><el-icon class="title-ico"><Grid /></el-icon>页面权限</span>
              <span class="actions">
                <el-button size="small" link type="primary" :disabled="draft.all" @click="allPages(true)">全选</el-button>
                <el-button size="small" link :disabled="draft.all" @click="allPages(false)">清空</el-button>
              </span>
            </div>
            <div class="check-grid">
              <label v-for="p in meta.pages" :key="p.key" class="check-item"
                     :class="{ on: draft.pages.includes(p.key), dis: draft.all }">
                <el-checkbox :model-value="draft.pages.includes(p.key)" :disabled="draft.all"
                             @change="v => togglePage(p.key, v)" />
                <span class="ci-label">{{ p.label }}</span>
                <code class="ci-key">{{ p.key }}</code>
              </label>
            </div>
          </div>

          <div class="card" :class="{ muted: draft.all }">
            <div class="card-title">
              <span class="card-title-text"><el-icon class="title-ico"><SetUp /></el-icon>功能权限</span>
              <span class="actions">
                <el-button size="small" link type="primary" :disabled="draft.all" @click="allFeatures(true)">全开</el-button>
                <el-button size="small" link :disabled="draft.all" @click="allFeatures(false)">全关</el-button>
              </span>
            </div>
            <div class="feat-grid">
              <label v-for="f in meta.features" :key="f.key" class="feat-item"
                     :class="{ dis: draft.all }">
                <span class="fi-text">
                  <span class="fi-label">{{ f.label }}</span>
                  <code class="fi-key">{{ f.key }}</code>
                </span>
                <el-switch :model-value="!!draft.features[f.key]" :disabled="draft.all"
                           @change="v => draft.features[f.key] = v" />
              </label>
            </div>
            <div class="hint-line">
              <el-icon :size="13"><InfoFilled /></el-icon>
              「录入/修改业务记录」不在这里 —— 它由下面的<strong>模型权限</strong>逐模型控制。
            </div>
          </div>

          <div class="card" :class="{ muted: draft.all }">
            <div class="card-title">
              <span class="card-title-text"><el-icon class="title-ico"><Coin /></el-icon>模型权限</span>
              <span class="actions">
                <el-select v-model="defaultLevel" size="small" style="width:150px" :disabled="draft.all">
                  <el-option label="默认：不可见" value="none" />
                  <el-option label="默认：只读" value="read" />
                  <el-option label="默认：可读写" value="write" />
                </el-select>
              </span>
            </div>
            <div class="model-table">
              <div class="mt-row mt-head">
                <span>数据模型</span><span>覆盖级别</span>
              </div>
              <div v-for="t in types" :key="t.id" class="mt-row">
                <span class="mt-name">
                  <el-icon :size="14"><component :is="entityIcon(t.key)" /></el-icon>
                  <span class="mtn-text">{{ t.name }}</span>
                  <code>{{ t.key }}</code>
                </span>
                <el-select
                  :model-value="overrides[t.key] || ''"
                  size="small" style="width:150px" :disabled="draft.all"
                  @change="v => setOverride(t.key, v)"
                >
                  <el-option label="跟随默认" value="" />
                  <el-option label="不可见" value="none" />
                  <el-option label="只读" value="read" />
                  <el-option label="可读写" value="write" />
                </el-select>
              </div>
              <div v-if="!types.length" class="mt-empty">还没有数据模型</div>
            </div>
            <div class="hint-line">
              <el-icon :size="13"><InfoFilled /></el-icon>
              「默认」作用于所有未单独设置（含以后新建）的模型，适合「整体可用 + 个别模型收紧」。
            </div>
          </div>

          <div class="save-bar">
            <el-button v-if="!selected.is_builtin" type="danger" plain :disabled="selected.user_count > 0"
                        @click="del">
              <el-icon><Delete /></el-icon>删除角色
            </el-button>
            <span class="sb-tip" v-if="selected.user_count > 0 && !selected.is_builtin">
              还有 {{ selected.user_count }} 个用户在用，改派后才能删除
            </span>
            <span class="spacer" />
            <el-button :disabled="!dirty" @click="reset">撤销更改</el-button>
            <el-button type="primary" :loading="saving" :disabled="!dirty" @click="save">
              <el-icon><Check /></el-icon>保存权限
            </el-button>
          </div>
        </template>
      </section>
    </div>

    <!-- 新建角色 -->
    <el-dialog v-model="createOpen" title="新建角色" width="520px"
               class="rich-dialog" :close-on-click-modal="false">
      <div class="dialog-summary">
        <el-icon :size="18"><Lock /></el-icon>
        <span>从一个现有角色复制权限作为起点，比从零勾选快得多，也不容易漏。</span>
      </div>
      <el-form :model="form" label-width="90px">
        <el-form-item label="标识" required>
          <el-input v-model="form.key" placeholder="英文/下划线，如 auditor" />
          <div class="form-hint">接口与代码里用它识别角色，创建后不可修改。</div>
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="如 审计员" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="form.description" placeholder="这个角色能做什么" />
        </el-form-item>
        <el-form-item label="复制自">
          <el-select v-model="form.copy_from" clearable placeholder="不复制（默认只给工作台）"
                     style="width:100%">
            <el-option v-for="r in roles" :key="r.id" :label="`${r.name}（${r.key}）`" :value="r.key" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="doCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Api } from '../../api'
import { entityIcon } from '../../utils/icons'
import { useAuthStore } from '../../stores/auth'
import PageTitle from '../../components/PageTitle.vue'

const auth = useAuthStore()

const roles = ref([])
const types = ref([])
const loading = ref(false)
const saving = ref(false)
const creating = ref(false)
const createOpen = ref(false)

const selectedId = ref(null)
const selected = computed(() => roles.value.find(r => r.id === selectedId.value) || null)

// 草稿与基线：dirty = 两者序列化后不一致。
// 用 JSON 比较而不是逐字段 flag，省掉「改了又改回来」仍提示未保存的假阳性。
const draft = reactive({ name: '', description: '', all: false, pages: [], features: {} })
const overrides = reactive({})          // 逐模型覆盖：{model_key: level}
const defaultLevel = ref('none')        // 对应 perms.models['*']
let baseline = ''

const meta = computed(() => auth.meta || { pages: [], features: [], levels: [] })

const canToggleAll = computed(() => auth.isSuper && selected.value?.key !== 'admin')

const allHint = computed(() => {
  if (selected.value?.key === 'admin') return '管理员角色必须保留全部权限'
  if (!auth.isSuper) return '只有超级管理员能授予'
  return '忽略下面的所有勾选'
})

const dirty = computed(() => snapshot() !== baseline)

function snapshot() {
  return JSON.stringify({
    name: draft.name,
    description: draft.description,
    all: draft.all,
    pages: [...draft.pages].sort(),
    features: draft.features,
    models: { ...overrides, ...(defaultLevel.value === 'none' ? {} : { '*': defaultLevel.value }) },
  })
}

function fill(role) {
  const p = role?.perms || {}
  draft.name = role?.name || ''
  draft.description = role?.description || ''
  draft.all = !!p.all
  draft.pages = [...(p.pages || [])]
  draft.features = { ...(p.features || {}) }

  Object.keys(overrides).forEach(k => delete overrides[k])
  const m = { ...(p.models || {}) }
  defaultLevel.value = m['*'] || 'none'
  delete m['*']
  Object.assign(overrides, m)

  baseline = snapshot()
}

function select(role) {
  if (dirty.value && selectedId.value && role.id !== selectedId.value) {
    ElMessageBox.confirm('切换角色会丢弃当前未保存的修改，继续？', '未保存的修改',
      { type: 'warning', confirmButtonText: '放弃并切换', cancelButtonText: '留在这里' })
      .then(() => { selectedId.value = role.id; fill(role) })
      .catch(() => {})
    return
  }
  selectedId.value = role.id
  fill(role)
}

function reset() { if (selected.value) fill(selected.value) }

function togglePage(key, on) {
  const i = draft.pages.indexOf(key)
  if (on && i < 0) draft.pages.push(key)
  if (!on && i >= 0) draft.pages.splice(i, 1)
}
function allPages(on) {
  draft.pages = on ? meta.value.pages.map(p => p.key) : []
}
function allFeatures(on) {
  meta.value.features.forEach(f => { draft.features[f.key] = on })
}
function setOverride(key, val) {
  if (!val) delete overrides[key]
  else overrides[key] = val
}

async function load(keepId = null) {
  loading.value = true
  try {
    const [r, t] = await Promise.all([Api.listRoles(), Api.listEntityTypes()])
    roles.value = r.items || []
    types.value = Array.isArray(t) ? t : (t.items || [])
    const want = keepId ?? selectedId.value ?? roles.value[0]?.id
    const hit = roles.value.find(x => x.id === want) || roles.value[0]
    if (hit) { selectedId.value = hit.id; fill(hit) }
    else { selectedId.value = null }
  } catch (e) { /* 拦截器已提示 */ } finally {
    loading.value = false
  }
}

async function save() {
  if (!selected.value) return
  if (!draft.name.trim()) { ElMessage.warning('请填写角色名称'); return }
  const models = { ...overrides }
  if (defaultLevel.value !== 'none') models['*'] = defaultLevel.value

  saving.value = true
  try {
    await Api.updateRole(selected.value.id, {
      name: draft.name.trim(),
      description: draft.description,
      perms: { all: draft.all, pages: draft.pages, models, features: draft.features },
    })
    const n = selected.value.user_count
    ElMessage.success(n
      ? `已保存；${n} 个使用该角色的用户已被要求重新登录`
      : '已保存')
    await load(selected.value.id)
  } catch (e) { /* 拦截器已提示 */ } finally {
    saving.value = false
  }
}

const form = reactive({ key: '', name: '', description: '', copy_from: '' })

function openCreate() {
  Object.assign(form, { key: '', name: '', description: '', copy_from: '' })
  createOpen.value = true
}

async function doCreate() {
  const key = (form.key || '').trim()
  if (!/^[a-z][a-z0-9_]*$/.test(key)) {
    ElMessage.warning('标识需以小写字母开头，只含小写字母、数字与下划线')
    return
  }
  if (!form.name.trim()) { ElMessage.warning('请填写角色名称'); return }

  // 复制来源：把它的 perms 直接作为新角色的初始权限
  const src = roles.value.find(r => r.key === form.copy_from)
  const perms = src
    ? JSON.parse(JSON.stringify(src.perms || {}))
    : { all: false, pages: ['dashboard'], models: { '*': 'read' }, features: {} }

  creating.value = true
  try {
    const r = await Api.createRole({ key, name: form.name.trim(), description: form.description, perms })
    ElMessage.success('已创建')
    createOpen.value = false
    await load(r?.id)
  } catch (e) { /* 拦截器已提示 */ } finally {
    creating.value = false
  }
}

async function del() {
  const r = selected.value
  try {
    await ElMessageBox.confirm(
      `删除角色「${r.name}」后不可恢复。其权限配置会一并丢失。`,
      '删除角色', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await Api.deleteRole(r.id)
    ElMessage.success('已删除')
    selectedId.value = null
    await load()
  } catch (e) { /* 取消 */ }
}

onMounted(async () => {
  await auth.loadMeta()
  await load()
})
</script>

<style scoped>
.role-layout {
  display: grid;
  grid-template-columns: 258px minmax(0, 1fr);
  gap: var(--space-4);
  align-items: start;
}
.role-list { display: flex; flex-direction: column; position: sticky; top: 16px; }
.list-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 13px 16px; font-size: var(--text-sm); font-weight: 600;
  color: var(--text-tertiary); border-bottom: 1px solid var(--border-light);
}
.role-item {
  display: flex; align-items: center; gap: 10px; width: 100%;
  padding: 11px 14px; border: none; background: transparent; cursor: pointer;
  text-align: left; font-family: inherit; border-left: 3px solid transparent;
  transition: background var(--duration) var(--ease-out), border-color var(--duration) var(--ease-out);
}
.role-item:hover { background: var(--bg-subtle); }
.role-item.active { background: var(--primary-bg); border-left-color: var(--primary); }
.ri-icon {
  width: 28px; height: 28px; border-radius: var(--radius-sm); flex-shrink: 0;
  display: inline-flex; align-items: center; justify-content: center;
  background: var(--bg-sunken); color: var(--text-tertiary);
}
.ri-icon.super { background: var(--primary-bg); color: var(--primary); }
.ri-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.ri-name {
  display: flex; align-items: center; gap: 5px; font-size: var(--text-base);
  font-weight: 600; color: var(--text-primary);
}
.ri-lock { color: var(--text-disabled); }
.ri-key { font-size: var(--text-xs); color: var(--text-tertiary); font-family: var(--font-mono); }
.ri-count {
  font-size: var(--text-xs); font-variant-numeric: tabular-nums;
  color: var(--text-tertiary); background: var(--bg-sunken);
  border-radius: var(--radius-full); padding: 1px 7px; flex-shrink: 0;
}
.role-item.active .ri-count { background: var(--bg-card); color: var(--primary); }
.list-empty { padding: 28px 16px; text-align: center; color: var(--text-tertiary); font-size: var(--text-sm); }

.role-detail { min-width: 0; }

.editor-head { display: flex; gap: var(--space-5); align-items: flex-start; flex-wrap: wrap; }
.eh-main { flex: 1; min-width: 240px; display: flex; flex-direction: column; gap: 10px; }
.eh-name :deep(.el-input__inner) { font-size: var(--text-lg); font-weight: 650; height: 40px; }
.eh-meta { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.eh-meta code {
  font-family: var(--font-mono); font-size: var(--text-sm);
  background: var(--bg-subtle); color: var(--text-secondary);
  padding: 2px 8px; border-radius: var(--radius-xs);
}
.eh-users { font-size: var(--text-sm); color: var(--text-tertiary); }
.eh-side {
  width: 250px; flex-shrink: 0;
  border-left: 1px solid var(--border-light); padding-left: var(--space-5);
}
.all-perm { display: flex; align-items: flex-start; gap: 10px; }
.ap-title { font-weight: 600; font-size: var(--text-base); color: var(--text-primary); }
.ap-desc { font-size: var(--text-xs); color: var(--text-tertiary); margin-top: 3px; line-height: 1.5; }
.dirty-flag {
  display: inline-flex; align-items: center; gap: 5px; margin-top: 12px;
  font-size: var(--text-xs); color: var(--warning);
  background: var(--warning-bg); padding: 3px 9px; border-radius: var(--radius-full);
}

.all-banner {
  display: flex; align-items: center; gap: 10px;
  background: var(--primary-bg); border-color: var(--primary-200);
  color: var(--text-secondary); font-size: var(--text-base); line-height: 1.6;
}
.all-banner strong { color: var(--primary); }
.card.muted { opacity: 0.5; pointer-events: none; }

.check-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 8px;
}
.check-item {
  display: flex; align-items: center; gap: 6px; padding: 8px 10px;
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-card); cursor: pointer;
  transition: all var(--duration) var(--ease-out);
}
.check-item:hover { border-color: var(--primary-200); }
.check-item.on { border-color: var(--primary-200); background: var(--primary-bg); }
.check-item :deep(.el-checkbox) { margin-right: 0; height: auto; }
.ci-label { flex: 1; font-size: var(--text-base); color: var(--text-primary); }
.ci-key { font-size: var(--text-xs); color: var(--text-disabled); font-family: var(--font-mono); }

.feat-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 8px; }
.feat-item {
  display: flex; align-items: center; justify-content: space-between; gap: 10px;
  padding: 9px 12px; border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-subtle);
}
.fi-text { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.fi-label { font-size: var(--text-base); color: var(--text-primary); }
.fi-key { font-size: var(--text-xs); color: var(--text-tertiary); font-family: var(--font-mono); }

.model-table { border: 1px solid var(--border); border-radius: var(--radius-sm); overflow: hidden; }
.mt-row {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 9px 13px; border-bottom: 1px solid var(--border-light);
}
.mt-row:last-child { border-bottom: none; }
.mt-head {
  background: var(--bg-subtle); font-size: var(--text-sm);
  font-weight: 600; color: var(--text-tertiary); padding: 8px 13px;
}
.mt-name { display: flex; align-items: center; gap: 8px; min-width: 0; color: var(--text-secondary); }
.mtn-text { font-size: var(--text-base); color: var(--text-primary); }
.mt-name code { font-size: var(--text-xs); color: var(--text-tertiary); font-family: var(--font-mono); }
.mt-empty { padding: 22px; text-align: center; color: var(--text-tertiary); font-size: var(--text-sm); }

.hint-line {
  display: flex; align-items: flex-start; gap: 6px; margin-top: 12px;
  font-size: var(--text-xs); color: var(--text-tertiary); line-height: 1.6;
}
.hint-line strong { color: var(--text-secondary); }

.save-bar {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  padding: 14px 18px; background: var(--bg-card);
  border: 1px solid var(--border); border-radius: var(--radius-md);
  box-shadow: var(--shadow-xs); position: sticky; bottom: 12px; z-index: 5;
}
.save-bar .spacer { flex: 1; min-width: 8px; }
.sb-tip { font-size: var(--text-xs); color: var(--text-tertiary); }
.form-hint { font-size: var(--text-xs); color: var(--text-tertiary); margin-top: 6px; }

@media (max-width: 1024px) {
  .role-layout { grid-template-columns: 1fr; }
  .role-list { position: static; }
  .eh-side { width: 100%; border-left: none; padding-left: 0; border-top: 1px solid var(--border-light); padding-top: var(--space-4); }
}
@media (max-width: 768px) {
  .check-grid, .feat-grid { grid-template-columns: 1fr; }
  .save-bar { position: static; }
}
</style>
