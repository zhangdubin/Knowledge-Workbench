<template>
  <!--
    记录分页条：两个页面（记录页 / 应用工作台）共用一套，
    免得「每页条数」在两个入口显示得不一样。
  -->
  <div class="rpager">
    <span class="rpager-total">共 {{ total }} 条</span>
    <el-pagination
      :current-page="page"
      :page-size="pageSize"
      :page-sizes="[20, 50, 100]"
      :total="total"
      layout="sizes, prev, pager, next"
      background
      @current-change="$emit('update:page', $event)"
      @size-change="$emit('update:pageSize', $event)"
    />
  </div>
</template>

<script setup>
defineProps({
  page: { type: Number, default: 1 },
  pageSize: { type: Number, default: 50 },
  total: { type: Number, default: 0 },
})

defineEmits(['update:page', 'update:pageSize'])
</script>

<style scoped>
.rpager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
  padding: var(--space-3) 0 0;
}
.rpager-total {
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
</style>
