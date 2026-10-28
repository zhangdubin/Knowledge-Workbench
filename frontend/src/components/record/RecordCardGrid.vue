<template>
  <!--
    记录卡片视图：一条记录一张卡，字段按「标签: 值」排布。
    窄屏与手机上看这个视图比表格舒服得多 —— 表格在窄屏上只能横向滚动。
  -->
  <div class="rcards">
    <div
      v-for="row in records"
      :key="row.id"
      class="rcard"
      role="button"
      tabindex="0"
      :aria-label="`记录 ${recordDisplayName(row)}`"
      @click="$emit('open', row)"
      @keydown.enter.prevent="$emit('open', row)"
      @keydown.space.prevent="$emit('open', row)"
    >
      <div class="rcard-head">
        <span class="rcard-title">{{ recordDisplayName(row) }}</span>
        <div class="rcard-actions" @click.stop @keydown.stop>
          <el-tooltip content="编辑" placement="top" :show-after="400">
            <el-button
              class="rcard-btn"
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
              class="rcard-btn is-danger"
              text
              :disabled="!canManage"
              :aria-label="`删除 ${recordDisplayName(row)}`"
              @click="$emit('remove', row)"
            >
              <el-icon><Delete /></el-icon>
            </el-button>
          </el-tooltip>
        </div>
      </div>

      <dl class="rcard-fields">
        <div v-for="f in fields" :key="f.key" class="rcard-field">
          <dt class="rcard-label">{{ f.name }}</dt>
          <dd class="rcard-value">
            <RecordCell :field="f" :value="row.data?.[f.key]" :labels="labels" />
          </dd>
        </div>
      </dl>

      <div class="rcard-foot">
        <el-icon><Clock /></el-icon>{{ formatTime(row.updated_at) }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { Clock, Delete, Edit } from '@element-plus/icons-vue'
import RecordCell from './RecordCell.vue'
import { formatTime } from '../../utils/format'
import { recordDisplayName } from '../../utils/recordFields.js'

defineProps({
  records: { type: Array, default: () => [] },
  fields: { type: Array, default: () => [] },
  labels: { type: Object, default: () => ({}) },
  canManage: { type: Boolean, default: true },
})

defineEmits(['edit', 'remove', 'open'])
</script>

<style scoped>
.rcards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--space-3);
}
.rcard {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  padding: var(--space-4);
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out), box-shadow var(--duration-fast) var(--ease-out);
}
.rcard:hover {
  border-color: var(--primary-200);
  box-shadow: var(--shadow-card-hover);
}
.rcard:focus-visible {
  outline: 2px solid var(--focus-ring-color);
  outline-offset: 2px;
}

.rcard-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}
.rcard-title {
  flex: 1;
  min-width: 0;
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rcard-actions { display: flex; gap: 2px; flex-shrink: 0; }
.rcard-btn {
  min-width: 30px;
  min-height: 30px;
  padding: 0;
  color: var(--text-secondary);
}
.rcard-btn:hover { color: var(--primary); }
.rcard-btn.is-danger:hover { color: var(--danger); }
.rcard-btn.is-danger :deep(.el-icon) { color: var(--danger); }

.rcard-fields {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.rcard-field {
  display: grid;
  grid-template-columns: 96px 1fr;
  gap: var(--space-3);
  align-items: start;
}
.rcard-label {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rcard-value {
  margin: 0;
  min-width: 0;
  font-size: var(--text-sm);
  word-break: break-word;
}

.rcard-foot {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: var(--space-3);
  padding-top: var(--space-2);
  border-top: 1px solid var(--border-light);
  font-size: var(--text-xs);
  color: var(--text-secondary);
}
</style>
