<template>
  <section class="workspace-recent" :aria-busy="state === 'loading'">
    <div class="recent-heading">
      <h2><el-icon aria-hidden="true"><component :is="icon" /></el-icon>{{ title }}</h2>
      <RouterLink v-if="more" :to="more" class="recent-more" :aria-label="moreLabel">
        {{ moreLabel }}<el-icon aria-hidden="true"><ArrowRight /></el-icon>
      </RouterLink>
    </div>
    <p v-if="state === 'loading'" class="recent-message" role="status">加载中…</p>
    <div v-else-if="state === 'error'" class="recent-message" role="status">
      {{ error }}
      <button type="button" @click="$emit('retry')">重试</button>
    </div>
    <p v-else-if="!items.length" class="recent-message">{{ empty }}</p>
    <ul v-else class="recent-list">
      <li v-for="item in items" :key="item.key">
        <RouterLink :to="item.to" class="recent-entry">
          <span class="recent-entry-icon">
            <el-icon aria-hidden="true"><component :is="item.icon" /></el-icon>
          </span>
          <span class="recent-entry-text">
            <span class="recent-entry-title" :title="item.title">{{ item.title }}</span>
            <small v-if="item.meta">{{ item.meta }}</small>
          </span>
          <el-icon class="recent-entry-arrow" aria-hidden="true"><ArrowRight /></el-icon>
        </RouterLink>
      </li>
    </ul>
  </section>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  icon: { type: String, required: true },
  items: { type: Array, required: true },
  state: { type: String, required: true },
  empty: { type: String, required: true },
  error: { type: String, required: true },
  more: { type: String, default: '' },
  moreLabel: { type: String, default: '' },
})
defineEmits(['retry'])
</script>

<style scoped>
.workspace-recent {
  min-width: 0;
  padding: var(--space-4);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}
.recent-heading, .recent-heading h2, .recent-more {
  display: flex;
  align-items: center;
}
.recent-heading { justify-content: space-between; gap: var(--space-2); margin-bottom: var(--space-3); }
.recent-heading h2 { margin: 0; gap: var(--space-2); color: var(--text-primary); font-size: var(--text-lg); font-weight: 650; }
.recent-heading h2 .el-icon { color: var(--text-tertiary); }
.recent-more { gap: var(--space-1); color: var(--text-secondary); text-decoration: none; font-size: var(--text-xs); white-space: nowrap; }
.recent-more:hover { color: var(--primary); }
.recent-list { list-style: none; margin: 0; padding: 0; }
.recent-list li + li { border-top: 1px solid var(--border-light); }
.recent-entry {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
  min-height: 55px;
  padding: var(--space-2) var(--space-1);
  color: var(--text-primary);
  text-decoration: none;
  border-radius: var(--radius);
}
.recent-entry:hover { background: var(--bg-subtle); }
.recent-entry-icon {
  flex: none;
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  background: var(--bg);
  color: var(--text-secondary);
  font-size: 16px;
}
.recent-entry-text { display: grid; flex: 1; min-width: 0; gap: 2px; }
.recent-entry-title, .recent-entry-text small { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.recent-entry-title { font-weight: 550; }
.recent-entry-text small { color: var(--text-tertiary); font-size: var(--text-xs); }
.recent-entry-arrow { flex: none; padding-right: var(--space-1); color: var(--text-tertiary); font-size: 13px; }
.recent-message { margin: 0; padding: var(--space-4) 0; border-top: 1px solid var(--border-light); color: var(--text-tertiary); }
.recent-message button { border: 0; background: transparent; color: var(--primary); font: inherit; cursor: pointer; }
.recent-message button:hover { text-decoration: underline; }
</style>
