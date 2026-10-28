<template>
  <!--
    分组徽标：小色点 + 组名。
    列表项与详情页页头都用它 —— 颜色是分组自己的数据，
    文字仍走设计变量，深浅色主题下都读得清。
  -->
  <span class="ng-badge" :class="{ 'is-muted': muted }" :title="`分组：${name}`">
    <span
      class="ng-dot"
      :style="color ? { backgroundColor: color } : null"
      aria-hidden="true"
    ></span>
    <span class="ng-badge-name">{{ name }}</span>
  </span>
</template>

<script setup>
defineProps({
  name: { type: String, default: '未分组' },
  color: { type: String, default: '' },
  // 未分组：色点用中性色，整体弱化
  muted: { type: Boolean, default: false },
})
</script>

<style scoped>
.ng-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: var(--text-xs);
  color: var(--text-secondary);
  max-width: 160px;
}
.ng-badge-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ng-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--text-disabled);
}
.ng-badge.is-muted { color: var(--text-tertiary); }
</style>
