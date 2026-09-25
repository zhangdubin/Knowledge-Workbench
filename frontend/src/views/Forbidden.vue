<template>
  <div class="page">
    <div class="forbidden-card">
      <div class="icon"><el-icon :size="42"><Lock /></el-icon></div>
      <div class="title">没有访问权限</div>
      <div class="desc">
        当前账号（{{ auth.displayName }}）没有被授予
        <b v-if="permLabel">{{ permLabel }}</b><b v-else>该页面</b>
        的访问权限。
      </div>
      <div class="desc sub">
        如需开通，请联系管理员在「系统管理 → 角色权限」里为你所在的角色勾选对应页面。
      </div>
      <div class="actions">
        <el-button type="primary" @click="$router.replace('/')">
          <el-icon><HomeFilled /></el-icon>回到工作台
        </el-button>
        <el-button @click="$router.back()">返回上一页</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const route = useRoute()

const PAGE_LABELS = {
  dashboard: '工作台', dashboards: '可视化驾驶舱', library: '数据中心',
  notes: '知识库', apps: '应用中心', types: '数据模型', records: '业务记录',
  relations: '关联定义', graph: '关联图谱', knowledge_graph: '知识图谱',
  search: '全局搜索', guide: '使用指南', ai: 'AI 设置', system: '系统管理',
}
const permLabel = computed(() => PAGE_LABELS[route.query.perm] || '')

onMounted(() => auth.loadMeta())
</script>

<style scoped>
.forbidden-card {
  max-width: 560px;
  margin: 12vh auto 0;
  text-align: center;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 18px;
  padding: 44px 36px;
  box-shadow: var(--shadow-sm);
}
.icon {
  width: 76px; height: 76px; margin: 0 auto 18px;
  border-radius: 22px; display: flex; align-items: center; justify-content: center;
  background: var(--warning-bg); color: var(--warning);
}
.title { font-size: 20px; font-weight: 700; margin-bottom: 12px; }
.desc { color: var(--text-secondary); line-height: 1.9; font-size: var(--text-sm); }
.desc b { color: var(--text-primary); }
.desc.sub { margin-top: 8px; color: var(--text-tertiary); font-size: var(--text-xs); }
.actions { margin-top: 26px; display: flex; gap: 10px; justify-content: center; }
</style>
