<template>
  <div class="page">
    <PageTitle
      title="回收站"
      subtitle="删除的模型与记录都先进这里，随时可救回。彻底删除不可恢复，需输入 Key 确认"
      icon-key="Delete"
    >
      <el-button @click="load">
        <el-icon><Refresh /></el-icon>刷新
      </el-button>
    </PageTitle>

    <el-empty v-if="!loading && data.total === 0" description="回收站是空的，删除的模型和记录会出现在这里" />

    <!-- 已删除的模型 -->
    <div v-if="data.types.length" class="card">
      <div class="card-head">
        <h3>数据模型（{{ data.types.length }}）</h3>
        <span class="hint">恢复模型 = 字段、视图、关联定义原样回来；记录不受影响</span>
      </div>
      <el-table :data="data.types" row-key="id">
        <el-table-column label="模型" min-width="200">
          <template #default="{ row }">
            <span class="type-icon">{{ row.icon || '📦' }}</span>
            <b>{{ row.name }}</b>
            <code class="key">{{ row.key }}</code>
          </template>
        </el-table-column>
        <el-table-column prop="record_count" label="记录数" width="90" align="center" />
        <el-table-column label="删除时间" width="170">
          <template #default="{ row }">{{ fmt(row.deleted_at) }}</template>
        </el-table-column>
        <el-table-column label="" width="200" align="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="restoreType(row)">恢复</el-button>
            <el-button size="small" type="danger" plain @click="purgeType(row)">彻底删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 已删除的记录 -->
    <div v-if="data.records.length" class="card">
      <div class="card-head">
        <h3>记录（{{ data.records.length }}）</h3>
        <span class="hint">最多显示最近 200 条；恢复记录时若所属模型也在回收站，会一并恢复</span>
      </div>
      <el-table :data="data.records" row-key="id">
        <el-table-column label="所属模型" width="160">
          <template #default="{ row }">
            <span class="type-icon">{{ row.entity_type_icon }}</span>{{ row.entity_type_name }}
          </template>
        </el-table-column>
        <el-table-column label="内容摘要" min-width="280">
          <template #default="{ row }">{{ row.search_text || '（空记录）' }}</template>
        </el-table-column>
        <el-table-column label="删除时间" width="170">
          <template #default="{ row }">{{ fmt(row.deleted_at) }}</template>
        </el-table-column>
        <el-table-column label="" width="200" align="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="restoreRecord(row)">恢复</el-button>
            <el-button size="small" type="danger" plain @click="purgeRecord(row)">彻底删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Api } from '../../api'
import PageTitle from '../../components/PageTitle.vue'

const loading = ref(false)
const data = reactive({ types: [], records: [], total: 0 })

async function load() {
  loading.value = true
  try {
    const r = await Api.listRecycle()
    data.types = r.types || []
    data.records = r.records || []
    data.total = r.total || 0
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '加载回收站失败')
  } finally {
    loading.value = false
  }
}

function fmt(t) {
  if (!t) return ''
  const d = new Date(t)
  return Number.isNaN(d.getTime()) ? String(t) : d.toLocaleString('zh-CN')
}

async function restoreType(row) {
  try {
    await Api.restoreRecycleType(row.id)
    ElMessage.success(`模型「${row.name}」已恢复`)
    load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '恢复失败')
  }
}

async function purgeType(row) {
  // 输入确认必须用 prompt：confirm 挂 inputValidator 是不生效的（Element Plus 源码行为）
  try {
    await ElMessageBox.prompt(
      `将物理删除模型「${row.name}」及其全部字段、<b>${row.record_count}</b> 条记录与视图，<b>无法恢复</b>。<br>输入模型 Key <code>${row.key}</code> 确认：`,
      '彻底删除数据模型',
      {
        type: 'warning', dangerouslyUseHTMLString: true,
        confirmButtonText: '彻底删除', cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
        inputPlaceholder: row.key,
        inputValidator: v => (v || '').trim() === row.key || '输入与模型 Key 不一致',
        inputErrorMessage: '输入与模型 Key 不一致',
      })
  } catch { return }
  try {
    await Api.purgeRecycleType(row.id, row.key)
    ElMessage.success(`模型「${row.name}」已彻底删除`)
    load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

async function restoreRecord(row) {
  try {
    const r = await Api.restoreRecycleRecord(row.id)
    ElMessage.success(r.model_restored ? '记录已恢复（所属模型一并恢复）' : '记录已恢复')
    load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '恢复失败')
  }
}

async function purgeRecord(row) {
  try {
    await ElMessageBox.confirm(
      `这条记录将物理删除，无法恢复。确定继续？`,
      '彻底删除记录',
      { type: 'warning', confirmButtonText: '彻底删除', cancelButtonText: '取消', confirmButtonClass: 'el-button--danger' })
  } catch { return }
  try {
    await Api.purgeRecycleRecord(row.id)
    ElMessage.success('记录已彻底删除')
    load()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

onMounted(load)
</script>

<style scoped>
.page { display: flex; flex-direction: column; gap: 16px; }
.card {
  background: var(--bg-card, #fff);
  border: 1px solid var(--border-color, rgba(0,0,0,.08));
  border-radius: 10px;
  padding: 16px 18px;
}
.card-head { display: flex; align-items: baseline; gap: 12px; margin-bottom: 10px; }
.card-head h3 { margin: 0; font-size: 15px; }
.hint { font-size: 12px; color: var(--el-text-color-secondary); }
.type-icon { margin-right: 6px; }
.key {
  margin-left: 8px; padding: 1px 6px; border-radius: 4px;
  font-size: 12px; background: var(--el-fill-color-light);
}
</style>
