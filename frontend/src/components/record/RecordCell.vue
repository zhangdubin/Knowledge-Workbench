<template>
  <!--
    单个字段值的显示：同一段数据在表格和卡片里必须长得一样，
    所以显示规则集中在 displayValue（utils/recordFields.js）里，这里只负责画出来。
  -->
  <span v-if="view.kind === 'empty'" class="rc-empty">—</span>

  <span v-else-if="view.kind === 'boolean'" :class="view.text === '是' ? 'rc-yes' : 'rc-no'">
    <span class="rc-dot" :class="{ 'is-on': view.text === '是' }"></span>{{ view.text }}
  </span>

  <span v-else-if="view.kind === 'tag'" class="rc-tag">{{ view.text }}</span>

  <span v-else-if="view.kind === 'tags'" class="rc-tags">
    <span v-for="t in view.items" :key="t" class="rc-tag">{{ t }}</span>
  </span>

  <span v-else-if="view.kind === 'reference'" class="rc-ref" :title="view.text">{{ view.text }}</span>

  <span v-else-if="view.kind === 'number'" class="rc-number">{{ view.text }}</span>

  <span v-else-if="view.kind === 'date' || view.kind === 'datetime'" class="rc-time">{{ view.text }}</span>

  <span v-else class="rc-text" :title="view.text">{{ view.text }}</span>
</template>

<script setup>
import { computed } from 'vue'
import { displayValue } from '../../utils/recordFields.js'

const props = defineProps({
  field: { type: Object, required: true },
  value: { type: [String, Number, Boolean, Array, Object], default: null },
  // 外键显示名缓存：`${目标模型key}:${记录id}` → 名称
  labels: { type: Object, default: () => ({}) },
})

const view = computed(() => displayValue(props.field, props.value, props.labels))
</script>

<style scoped>
.rc-empty { color: var(--text-secondary); }
.rc-text {
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-block;
  max-width: 100%;
  vertical-align: bottom;
}
.rc-number {
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  font-weight: 500;
}
.rc-time { color: var(--text-secondary); font-variant-numeric: tabular-nums; }

.rc-yes, .rc-no {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-weight: 500;
}
.rc-yes { color: var(--success); }
.rc-no { color: var(--text-secondary); }
.rc-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--border-strong);
  flex-shrink: 0;
}
.rc-dot.is-on { background: var(--success); }

.rc-tag {
  display: inline-block;
  font-size: var(--text-xs);
  font-weight: 600;
  line-height: 18px;
  padding: 0 8px;
  border-radius: var(--radius-full);
  color: var(--primary-dark);
  background: var(--primary-bg);
  border: 1px solid var(--primary-200);
  margin: 1px 3px 1px 0;
}
.rc-tags { display: inline-flex; flex-wrap: wrap; gap: 2px; }
.rc-ref {
  color: var(--primary);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-block;
  max-width: 100%;
  vertical-align: bottom;
}
</style>
