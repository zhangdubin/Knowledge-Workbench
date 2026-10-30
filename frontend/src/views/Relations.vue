<template>
  <div class="page">
    <PageTitle
      title="关联定义"
      subtitle="定义两端之间的关系。两端都可以是「业务记录」或「数据中心文件」，定义一次即可反复建立具体关联"
      icon-key="Connection"
    >
      <el-button @click="$router.push('/graph')">
        <el-icon><Share /></el-icon>查看图谱
      </el-button>
      <el-button v-if="canManage" type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>新建关联
      </el-button>
    </PageTitle>

    <div class="info-banner">
      <el-icon :size="18"><InfoFilled /></el-icon>
      <div>
        关联定义描述的是<b>两端类型之间</b>的关系，例如「项目 → 任务」「合同 → 数据中心文件」。
        定义好之后：源端是<b>业务记录</b>时，进任意一条该模型的记录详情点「添加关联」；
        源端是<b>数据中心文件</b>时，在数据中心点文件的「元数据」图标，切到「关联」页签即可挂接。
      </div>
    </div>

    <!-- 工具条：视图切换 + 数量 -->
    <div class="rel-toolbar">
      <el-radio-group v-model="viewMode" class="tb-view" aria-label="视图切换">
        <el-radio-button value="card">
          <el-icon><Grid /></el-icon>卡片
        </el-radio-button>
        <el-radio-button value="table">
          <el-icon><Menu /></el-icon>表格
        </el-radio-button>
      </el-radio-group>
      <span class="toolbar-count">共 {{ defs.length }} 条关联定义</span>
    </div>

    <!-- 卡片视图 -->
    <div v-if="viewMode === 'card' && defs.length" v-loading="loading" class="rel-grid">
      <div
        v-for="row in defs"
        :key="row.id"
        class="rel-card pcard"
        :class="`ac-${cardinalityAccent(row.cardinality)}`"
      >
        <div class="rel-card-head">
          <div class="rel-card-title">
            <span class="rel-card-name" :title="row.name">{{ row.name }}</span>
            <code class="rel-key" :title="row.key">{{ row.key }}</code>
          </div>
          <span class="ptag" :class="`ac-${cardinalityAccent(row.cardinality)}`">
            {{ cardLabel(row.cardinality) }}
          </span>
        </div>

        <!-- 两端：源端蓝、目标端青，一眼看出方向 -->
        <div class="rel-flow">
          <div class="rel-end" :class="`ac-${REL_SOURCE_ACCENT}`">
            <span class="rel-end-tag">源</span>
            <span class="rel-end-icon">{{ endEmoji(row.source_kind, row.source_icon) }}</span>
            <span class="rel-end-name" :title="row.source_label">{{ row.source_label }}</span>
          </div>
          <el-icon class="rel-flow-arrow"><Right /></el-icon>
          <div class="rel-end" :class="`ac-${REL_TARGET_ACCENT}`">
            <span class="rel-end-tag">目标</span>
            <span class="rel-end-icon">{{ endEmoji(row.target_kind, row.target_icon) }}</span>
            <span class="rel-end-name" :title="row.target_label">{{ row.target_label }}</span>
          </div>
        </div>

        <p class="rel-card-desc">{{ row.description || '暂无说明' }}</p>

        <div class="rel-card-meta">
          <span class="rel-card-count" :class="{ zero: !row.link_count }">
            {{ row.link_count || 0 }} 条关联
          </span>
          <div class="rel-card-actions" @click.stop>
            <el-button v-if="row.source_kind === 'document'" size="small" text type="primary"
                       @click="$router.push('/library')">
              <el-icon><Coin /></el-icon>去数据中心
            </el-button>
            <el-button v-else size="small" text type="primary"
                       @click="$router.push(`/records/${row.source_type_id}`)">
              <el-icon><Document /></el-icon>去录入
            </el-button>
            <el-button v-if="canManage" size="small" text @click="openEdit(row)">
              <el-icon><Edit /></el-icon>编辑
            </el-button>
            <el-button v-if="canManage" size="small" text type="danger" @click="del(row)">
              <el-icon><Delete /></el-icon>删除
            </el-button>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="card" style="padding:0;overflow:hidden">
      <EmptyState
        v-if="!defs.length && !loading"
        icon="Connection"
        title="还没有关联定义"
        description="例如「项目 → 任务」，之后就能把具体任务挂到项目下面；也可以定义「合同 → 数据中心文件」，把扫描件挂到合同上。"
        variant="plain"
      >
        <template #default>
          <el-button v-if="canManage" type="primary" @click="openCreate">
            <el-icon><Plus /></el-icon>新建关联
          </el-button>
          <el-button v-if="!types.length" @click="$router.push('/types/new')">
            <el-icon><Files /></el-icon>先去建数据模型
          </el-button>
        </template>
      </EmptyState>

      <el-table v-else :data="defs" v-loading="loading" class="data-table ptable table-striped table-density-default">
        <el-table-column label="关联名称" min-width="200">
          <template #default="{ row }">
            <div class="rel-name-cell">
              <span class="ptag" :class="`ac-${cardinalityAccent(row.cardinality)}`">{{ row.name }}</span>
              <code class="rel-key">{{ row.key }}</code>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="方向" min-width="280">
          <template #default="{ row }">
            <div class="rel-dir">
              <span class="rel-node" :class="`ac-${REL_SOURCE_ACCENT}`">
                <span class="rn-ico">{{ row.source_kind === 'document' ? '🗂️' : (row.source_icon || '📦') }}</span>
                {{ row.source_label }}
              </span>
              <el-icon class="rel-arrow"><Right /></el-icon>
              <span class="rel-node target" :class="`ac-${REL_TARGET_ACCENT}`">
                <span class="rn-ico">{{ row.target_kind === 'document' ? '🗂️' : (row.target_icon || '📦') }}</span>
                {{ row.target_label }}
              </span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="基数" width="100">
          <template #default="{ row }">
            <span class="ptag" :class="`ac-${cardinalityAccent(row.cardinality)}`">
              {{ cardLabel(row.cardinality) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="关联数" width="90" align="right">
          <template #default="{ row }">
            <span class="link-count" :class="{ zero: !row.link_count }">{{ row.link_count || 0 }}</span>
          </template>
        </el-table-column>
        <el-table-column label="说明" min-width="160">
          <template #default="{ row }">
            <span class="cell-text">{{ row.description || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.source_kind === 'document'" size="small" link type="primary"
                       @click="$router.push('/library')">
              <el-icon><Coin /></el-icon>去数据中心
            </el-button>
            <el-button v-else size="small" link type="primary"
                       @click="$router.push(`/records/${row.source_type_id}`)">
              <el-icon><Document /></el-icon>去录入
            </el-button>
            <el-button v-if="canManage" size="small" link @click="openEdit(row)">
              <el-icon><Edit /></el-icon>编辑
            </el-button>
            <el-button v-if="canManage" size="small" link type="danger" @click="del(row)">
              <el-icon><Delete /></el-icon>删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 新建 / 编辑关联定义 -->
    <DialogShell
      v-model="dialogOpen"
      :title="form.id ? '编辑关联定义' : '新建关联定义'"
      description="两端各自选择「是什么」：业务记录要指定模型，数据中心文件覆盖全部已上传文件。"
      :width="640"
    >
      <template #icon><el-icon><Connection /></el-icon></template>

      <el-form :model="form" label-width="90px">
        <el-form-item label="关联名称" required>
          <el-input v-model="form.name" placeholder="如：合同扫描件 / 项目包含任务" />
          <div class="form-hint">显示在记录详情与图谱上，建议用「A 包含 B」这种自然语序。</div>
        </el-form-item>
        <el-form-item label="标识" required>
          <el-input v-model="form.key" :disabled="!!form.id" placeholder="英文唯一标识，如 contract_file" />
        </el-form-item>

        <!-- 源端 -->
        <el-form-item label="源端" required>
          <div class="end-picker">
            <el-radio-group v-model="form.source_kind" size="default" @change="onKindChange('source')">
              <el-radio-button value="record">业务记录</el-radio-button>
              <el-radio-button value="document">数据中心文件</el-radio-button>
            </el-radio-group>
            <el-select v-if="form.source_kind === 'record'" v-model="form.source_type_id"
                       filterable placeholder="选择源端模型" style="flex:1;min-width:180px">
              <el-option v-for="t in types" :key="t.id" :label="`${t.name}（${t.key}）`" :value="t.id" />
            </el-select>
            <div v-else class="end-static">
              <span>🗂️</span>数据中心文件<span class="es-hint">（全部文件，不限类型）</span>
            </div>
          </div>
        </el-form-item>

        <!-- 目标端 -->
        <el-form-item label="目标端" required>
          <div class="end-picker">
            <el-radio-group v-model="form.target_kind" size="default" @change="onKindChange('target')">
              <el-radio-button value="record">业务记录</el-radio-button>
              <el-radio-button value="document">数据中心文件</el-radio-button>
            </el-radio-group>
            <el-select v-if="form.target_kind === 'record'" v-model="form.target_type_id"
                       filterable placeholder="选择目标端模型" style="flex:1;min-width:180px">
              <el-option v-for="t in types" :key="t.id" :label="`${t.name}（${t.key}）`" :value="t.id" />
            </el-select>
            <div v-else class="end-static">
              <span>🗂️</span>数据中心文件<span class="es-hint">（全部文件，不限类型）</span>
            </div>
          </div>
        </el-form-item>

        <el-form-item label="基数">
          <el-radio-group v-model="form.cardinality">
            <el-radio v-for="c in CARDINALITIES" :key="c.value" :value="c.value">{{ c.label }}</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">
          <el-icon><Check /></el-icon>{{ form.id ? '保存' : '创建' }}
        </el-button>
      </template>
    </DialogShell>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Api } from '../api'
import { REL_SOURCE_ACCENT, REL_TARGET_ACCENT, cardinalityAccent } from '../utils/accents'
import './pages.css'
import { useAuthStore } from '../stores/auth'
import PageTitle from '../components/PageTitle.vue'
import EmptyState from '../components/EmptyState.vue'
import DialogShell from '../components/DialogShell.vue'

const auth = useAuthStore()

const CARDINALITIES = [
  { value: 'many-to-many', label: '多对多' },
  { value: 'one-to-many', label: '一对多' },
  { value: 'many-to-one', label: '多对一' },
  { value: 'one-to-one', label: '一对一' },
]
const CARD_LABELS = Object.fromEntries(CARDINALITIES.map(c => [c.value, c.label]))
const cardLabel = (c) => CARD_LABELS[c] || c || '多对多'

const defs = ref([])
const types = ref([])
/** 卡片视图默认：关系定义数量不多，卡片能一眼看清两端 */
const viewMode = ref('card')

/** 端点图标：数据中心文件用文件夹，业务模型用后端给的图标（一般是 emoji） */
function endEmoji(kind, icon) {
  return kind === 'document' ? '🗂️' : (icon || '📦')
}
const loading = ref(false)
const dialogOpen = ref(false)
const saving = ref(false)

const canManage = computed(() => auth.can('relation_manage'))

const form = reactive({
  id: null,
  key: '', name: '',
  source_kind: 'record', source_type_id: null,
  target_kind: 'record', target_type_id: null,
  cardinality: 'many-to-many', description: '',
})

async function load() {
  loading.value = true
  try {
    const [d, t] = await Promise.all([Api.listRelationDefs(), Api.listEntityTypes()])
    defs.value = d
    types.value = t
  } catch (e) { /* 拦截器已提示 */ } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(form, {
    id: null, key: '', name: '',
    source_kind: 'record', source_type_id: types.value[0]?.id ?? null,
    target_kind: 'record', target_type_id: null,
    cardinality: 'many-to-many', description: '',
  })
  // 只有一个模型时默认两端都指向它，省一次点击
  if (types.value.length === 1) form.target_type_id = types.value[0].id
  dialogOpen.value = true
}

function openEdit(row) {
  Object.assign(form, {
    id: row.id,
    key: row.key,
    name: row.name,
    source_kind: row.source_kind || 'record',
    source_type_id: row.source_type_id ?? null,
    target_kind: row.target_kind || 'record',
    target_type_id: row.target_type_id ?? null,
    cardinality: row.cardinality || 'many-to-many',
    description: row.description || '',
  })
  dialogOpen.value = true
}

/** 切换端类型时清掉另一端已选的模型，避免残留「文件端却带着模型」 */
function onKindChange(side) {
  if (side === 'source' && form.source_kind === 'document') form.source_type_id = null
  if (side === 'target' && form.target_kind === 'document') form.target_type_id = null
  if (!form.key || !form.id) suggestKey()
}

// 名称/端变化时补一个可读的 key 建议，用户已手填过就不覆盖
function suggestKey() {
  if (form.id) return
  const sk = form.source_kind === 'document' ? 'file'
    : (types.value.find(t => t.id === form.source_type_id)?.key || '')
  const tk = form.target_kind === 'document' ? 'file'
    : (types.value.find(t => t.id === form.target_type_id)?.key || '')
  if (sk && tk) form.key = `${sk}_${tk}`
}

async function save() {
  if (!form.name?.trim() || !form.key?.trim()) {
    ElMessage.warning('请填写关联名称与标识')
    return
  }
  for (const side of ['source', 'target']) {
    if (form[`${side}_kind`] === 'record' && !form[`${side}_type_id`]) {
      ElMessage.warning(`「${side === 'source' ? '源端' : '目标端'}」选择了业务记录，请指定模型`)
      return
    }
  }
  saving.value = true
  try {
    if (form.id) {
      await Api.updateRelationDef(form.id, {
        name: form.name.trim(), description: form.description, cardinality: form.cardinality,
      })
      ElMessage.success('已保存')
    } else {
      await Api.createRelationDef({
        key: form.key.trim(), name: form.name.trim(),
        source_kind: form.source_kind, source_type_id: form.source_type_id,
        target_kind: form.target_kind, target_type_id: form.target_type_id,
        cardinality: form.cardinality, description: form.description,
      })
      ElMessage.success('已创建，可到记录详情或文件详情中添加关联')
    }
    dialogOpen.value = false
    await load()
  } catch (e) { /* 拦截器已提示 */ } finally {
    saving.value = false
  }
}

async function del(row) {
  const n = row.link_count || 0
  try {
    await ElMessageBox.confirm(
      n
        ? `删除「${row.name}」会同时移除已建立的 ${n} 条同类关联，且不可撤销。`
        : `删除「${row.name}」后不可撤销。`,
      '删除关联定义',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await Api.deleteRelationDef(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) { /* 取消 */ }
}

onMounted(load)
</script>

<style scoped>
.info-banner {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 14px 18px;
  border-radius: var(--radius);
  background: var(--primary-50);
  border: 1px solid var(--primary-200);
  color: var(--text-secondary);
  font-size: var(--text-sm);
  line-height: 1.7;
  margin-bottom: var(--space-4);
}
.info-banner .el-icon { color: var(--primary); margin-top: 2px; flex-shrink: 0; }
.info-banner b { color: var(--text-primary); }

/* 名称与标识排一行：换行会把整行撑高 */
.rel-name-cell { display: flex; align-items: center; gap: 8px; flex-wrap: nowrap; }
.rel-name-cell .ptag {
  max-width: 130px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rel-key {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.rel-dir { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
/* 两端各用一种颜色：源端蓝、目标端青，方向一眼可辨 */
.rel-node {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 3px 10px;
  border-radius: var(--radius-full);
  background: var(--ac-bg);
  border: 1px solid var(--ac-line);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--ac-fg);
}
.rel-node.target { background: var(--ac-bg); color: var(--ac-fg); }
.rn-ico { font-size: 13px; line-height: 1; }
.rel-arrow { color: var(--text-tertiary); }

.link-count { font-variant-numeric: tabular-nums; font-weight: 600; color: var(--text-primary); }

/* ============ 卡片视图 ============ */
.rel-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}
.rel-toolbar .toolbar-count { margin-left: auto; }

.rel-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: var(--space-3);
}
.rel-card { gap: var(--space-3); }

.rel-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
}
.rel-card-title { min-width: 0; }
.rel-card-name {
  display: block;
  font-size: var(--text-lg);
  font-weight: 650;
  color: var(--text-primary);
  letter-spacing: -0.2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* 两端：源端蓝、目标端青 */
.rel-flow {
  display: flex;
  align-items: stretch;
  gap: var(--space-2);
  padding: var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--bg-subtle);
}
.rel-end {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px 10px;
  border-radius: var(--radius-sm);
  /* 端点用同色淡底 + 描边：源端一块蓝、目标端一块青，方向一眼可辨 */
  background: var(--ac-bg);
  border: 1px solid var(--ac-line);
}
.rel-end-tag {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: 700;
  line-height: 1;
  padding: 3px 5px;
  border-radius: var(--radius-xs);
  background: var(--ac-bg);
  color: var(--ac-text);
}
.rel-end-icon { flex-shrink: 0; font-size: 15px; line-height: 1; }
.rel-end-name {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rel-flow-arrow {
  align-self: center;
  flex-shrink: 0;
  color: var(--text-tertiary);
  font-size: 16px;
}
.rel-card-desc {
  margin: 0;
  font-size: var(--text-sm);
  line-height: 1.6;
  color: var(--text-secondary);
  min-height: 22px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.rel-card-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding-top: var(--space-3);
  border-top: 1px solid var(--border-light);
}
.rel-card-count {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}
.rel-card-count.zero { color: var(--text-disabled); font-weight: 400; }
.rel-card-actions { display: flex; align-items: center; gap: var(--space-1); }
.link-count.zero { color: var(--text-disabled); font-weight: 400; }
.cell-text { color: var(--text-secondary); font-size: var(--text-sm); }
.form-hint {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  margin-top: 6px;
  display: block;
}

.end-picker { display: flex; align-items: center; gap: 10px; width: 100%; flex-wrap: wrap; }
.end-static {
  display: inline-flex; align-items: center; gap: 7px;
  flex: 1; min-width: 180px; height: 32px; padding: 0 12px;
  border: 1px dashed var(--border-strong); border-radius: var(--radius-sm);
  background: var(--bg-subtle); font-size: var(--text-base); color: var(--text-secondary);
}
.es-hint { font-size: var(--text-xs); color: var(--text-tertiary); }

@media (max-width: 768px) {
  .end-picker { flex-direction: column; align-items: stretch; }
}
</style>
