<template>
  <!--
    分组选择器
    ---------------------------------------------------------------------------
    语义：0 = 未分组，>0 = 具体分组 id。
    列表页（新建笔记时选归属）和详情页（改笔记的归属）都用它。
  -->
  <el-select
    :model-value="modelValue"
    class="ng-select"
    :placeholder="placeholder"
    :aria-label="ariaLabel"
    @update:model-value="onChange"
  >
    <el-option :value="0" label="未分组">
      <span class="ng-opt">
        <el-icon class="ng-opt-ico"><FolderOpened /></el-icon>
        <span class="ng-opt-name">未分组</span>
      </span>
    </el-option>
    <el-option
      v-for="g in groups"
      :key="g.id"
      :value="g.id"
      :label="g.name"
    >
      <span class="ng-opt">
        <span class="ng-dot" :style="{ backgroundColor: g.color }" aria-hidden="true"></span>
        <span class="ng-opt-name">{{ g.name }}</span>
        <span class="ng-opt-num">{{ g.count }}</span>
      </span>
    </el-option>
  </el-select>
</template>

<script setup>
import { FolderOpened } from '@element-plus/icons-vue'

defineProps({
  // 0 = 未分组；>0 = 分组 id
  modelValue: { type: Number, default: 0 },
  groups: { type: Array, default: () => [] },
  placeholder: { type: String, default: '选择分组' },
  ariaLabel: { type: String, default: '所属分组' },
})
const emit = defineEmits(['update:modelValue', 'change'])

function onChange(v) {
  const val = Number(v) || 0
  emit('update:modelValue', val)
  emit('change', val)
}
</script>

<style scoped>
.ng-select { width: 180px; }
.ng-opt { display: flex; align-items: center; gap: 8px; }
.ng-opt-ico { color: var(--text-tertiary); }
.ng-opt-name { flex: 1; }
.ng-opt-num { font-size: var(--text-xs); color: var(--text-tertiary); }
.ng-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex-shrink: 0;
}
</style>
