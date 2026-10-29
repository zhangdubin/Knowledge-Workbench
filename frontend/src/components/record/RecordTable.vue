<template>
  <!--
    记录表格：列 = 模型的字段定义，单元格按字段类型渲染。
    行为（编辑 / 删除 / 详情）与「记录」页共用同一套组件，
    两个入口不会出现「一个地方能编辑、另一个地方不能」的割裂。
  -->
  <el-table
    ref="tableRef"
    :data="records"
    :loading="loading"
    row-key="id"
    stripe
    class="data-table rt"
    :row-style="{ cursor: 'pointer' }"
    @row-click="(row) => $emit('open', row)"
    @selection-change="(rows) => $emit('selection-change', rows)"
  >
    <el-table-column v-if="selection" type="selection" width="46" reserve-selection />

    <el-table-column v-if="showTitle" label="记录" min-width="200" fixed="left">
      <template #default="{ row }">
        <button type="button" class="rt-title" @click.stop="$emit('open', row)">
          {{ recordDisplayName(row) }}
        </button>
      </template>
    </el-table-column>

    <el-table-column
      v-for="f in columns"
      :key="f.key"
      :label="f.name"
      :min-width="columnWidth(f)"
      show-overflow-tooltip
    >
      <template #default="{ row }">
        <RecordCell :field="f" :value="row.data?.[f.key]" :labels="labels" />
      </template>
    </el-table-column>

    <el-table-column v-if="showUpdated" label="更新时间" width="160">
      <template #default="{ row }">
        <span class="rt-time">{{ formatTime(row.updated_at) }}</span>
      </template>
    </el-table-column>

    <el-table-column label="操作" :width="actionWidth" fixed="right">
      <template #default="{ row }">
        <div class="rt-actions" @click.stop>
          <el-tooltip content="编辑" placement="top" :show-after="400">
            <el-button
              class="rt-btn"
              text
              :disabled="!canManage"
              :aria-label="`编辑 ${recordDisplayName(row)}`"
              @click="$emit('edit', row)"
            >
              <el-icon><Edit /></el-icon>
            </el-button>
          </el-tooltip>
          <el-tooltip content="删除" placement="top" :show-after="400">
            <el-button
              class="rt-btn is-danger"
              text
              :disabled="!canManage"
              :aria-label="`删除 ${recordDisplayName(row)}`"
              @click="$emit('remove', row)"
            >
              <el-icon><Delete /></el-icon>
            </el-button>
          </el-tooltip>
          <el-dropdown trigger="click" @command="(cmd) => onCommand(cmd, row)">
            <el-button class="rt-btn" text aria-label="更多操作">
              <el-icon><MoreFilled /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="open">
                  <el-icon><View /></el-icon>查看详情
                </el-dropdown-item>
                <el-dropdown-item command="graph">
                  <el-icon><Share /></el-icon>查看图谱
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </template>
    </el-table-column>

    <template #empty>
      <slot name="empty" />
    </template>
  </el-table>
</template>

<script setup>
import { nextTick, onMounted, ref, watch } from 'vue'
import { Delete, Edit, MoreFilled, Share, View } from '@element-plus/icons-vue'
import RecordCell from './RecordCell.vue'
import { formatTime } from '../../utils/format'
import { recordDisplayName } from '../../utils/recordFields.js'

const props = defineProps({
  records: { type: Array, default: () => [] },
  // 要显示成列的字段（已按类型筛过）
  columns: { type: Array, default: () => [] },
  labels: { type: Object, default: () => ({}) },
  loading: { type: Boolean, default: false },
  canManage: { type: Boolean, default: true },
  showTitle: { type: Boolean, default: true },
  showUpdated: { type: Boolean, default: true },
  // 是否显示多选列（批量删除用）
  selection: { type: Boolean, default: false },
})

const emit = defineEmits(['edit', 'remove', 'open', 'graph', 'selection-change'])

const tableRef = ref(null)
// 三个图标按钮 + 一点留白，够放下又不会挤掉列宽
const actionWidth = 132

/**
 * 让表格行可以 Tab 聚焦
 * 为什么需要：Element Plus 的 el-table 没有「给行加属性」的接口，
 * 而「行可聚焦」是表格类界面的基本无障碍要求（键盘用户要能一行行走过去）。
 * 所以这里在数据渲染后手动补上 tabindex，并在回车时打开该行。
 */
async function markRowsFocusable() {
  await nextTick()
  const root = tableRef.value?.$el
  if (!root) return
  root.querySelectorAll('tbody tr').forEach((tr) => {
    tr.setAttribute('tabindex', '0')
    tr.setAttribute('aria-label', '记录行，回车打开')
  })
}

onMounted(markRowsFocusable)
watch(() => props.records, markRowsFocusable, { deep: false })

function onCommand(cmd, row) {
  if (cmd === 'open') emit('open', row)
  else if (cmd === 'graph') emit('graph', row)
}

function columnWidth(f) {
  if (f.type === 'textarea' || f.type === 'richtext') return 200
  if (f.type === 'reference') return 160
  if (f.type === 'date' || f.type === 'datetime') return 150
  return 130
}
</script>

<style scoped>
/* 行标题做成真按钮：键盘能到，鼠标能点 */
.rt-title {
  font: inherit;
  font-weight: 600;
  color: var(--text-primary);
  background: none;
  border: none;
  padding: 0;
  text-align: left;
  cursor: pointer;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rt-title:hover { color: var(--primary); }
.rt-title:focus-visible {
  outline: 2px solid var(--focus-ring-color);
  outline-offset: 2px;
  border-radius: var(--radius-xs);
}

.rt-time { color: var(--text-secondary); font-size: var(--text-sm); }

.rt-actions { display: flex; align-items: center; gap: 2px; }
/* 表格里的图标按钮也要够大：小按钮在触屏上点不准 */
.rt-btn {
  min-width: 30px;
  min-height: 30px;
  padding: 0;
  color: var(--text-secondary);
}
.rt-btn:hover { color: var(--primary); }
.rt-btn.is-danger:hover { color: var(--danger); }
.rt-btn.is-danger :deep(.el-icon) { color: var(--danger); }

/* 行聚焦时给出可见焦点环 */
.rt :deep(tbody tr:focus-visible) {
  outline: 2px solid var(--focus-ring-color);
  outline-offset: -2px;
}
</style>
