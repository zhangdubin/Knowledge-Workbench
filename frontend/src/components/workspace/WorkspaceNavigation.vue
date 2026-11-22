<template>
  <nav class="workspace-nav" aria-label="工作区导航">
    <ul v-if="primary.length" class="nav-list">
      <li v-for="item in primary" :key="item.path">
        <RouterLink
          :to="item.path"
          class="workspace-nav-item"
          :class="{ 'is-current': item.path === activePath }"
          :aria-current="item.path === activePath ? 'location' : undefined"
          :title="compact ? item.label : undefined"
          @click="emit('select')"
        >
          <el-icon aria-hidden="true"><component :is="item.icon" /></el-icon>
          <span :class="{ 'icon-label': compact }">{{ item.label }}</span>
        </RouterLink>
      </li>
    </ul>
    <div v-if="shortcuts.length" class="nav-shortcuts">
      <p v-if="!compact" class="nav-label">快捷方式</p>
      <ul class="nav-list">
        <li v-for="item in shortcuts" :key="item.path">
          <RouterLink
            :to="item.path"
            class="workspace-nav-item"
            :class="{ 'is-current': item.path === currentLocation }"
            :title="item.label"
            @click="emit('select')"
          >
            <el-icon aria-hidden="true"><component :is="item.icon" /></el-icon>
            <span :class="{ 'icon-label': compact }">{{ item.label }}</span>
          </RouterLink>
        </li>
      </ul>
    </div>
    <button
      class="workspace-nav-item nav-catalog"
      type="button"
      aria-haspopup="dialog"
      :title="compact ? '全部功能' : undefined"
      @click="emit('catalog')"
    >
      <el-icon aria-hidden="true"><Operation /></el-icon>
      <span :class="{ 'icon-label': compact }">全部功能</span>
      <el-icon v-if="!compact" class="nav-next" aria-hidden="true"><ArrowRight /></el-icon>
    </button>
  </nav>
</template>

<script setup>
defineProps({
  primary: { type: Array, required: true },
  shortcuts: { type: Array, required: true },
  activePath: { type: String, required: true },
  currentLocation: { type: String, required: true },
  compact: Boolean,
})
const emit = defineEmits(['select', 'catalog'])
</script>

<style scoped>
.workspace-nav {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  padding: var(--space-3);
  color: var(--text-secondary);
}
.nav-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 3px; }
.nav-label {
  padding: 0 var(--space-3);
  margin: 0 0 var(--space-2);
  color: var(--text-tertiary);
  font-size: var(--text-xs);
}
.workspace-nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-height: 40px;
  padding: 0 var(--space-3);
  color: inherit;
  border: 0;
  border-radius: var(--radius);
  text-decoration: none;
  background: transparent;
  text-align: left;
  white-space: nowrap;
  font: inherit;
}
.workspace-nav-item > span { overflow: hidden; text-overflow: ellipsis; }
.workspace-nav-item .el-icon { flex: none; font-size: 17px; }
.workspace-nav-item:hover { background: var(--bg-sunken); color: var(--text-primary); }
.workspace-nav-item.is-current {
  background: var(--primary-bg-strong);
  color: var(--primary);
  font-weight: 600;
}
.nav-catalog { width: 100%; cursor: pointer; }
.nav-next { margin-left: auto; color: var(--text-tertiary); }
.nav-next.el-icon { font-size: 13px; }
.icon-label { position: absolute; width: 1px; height: 1px; clip-path: inset(50%); }
</style>
