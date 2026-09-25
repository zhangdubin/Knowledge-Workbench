<template>
  <div class="page-header">
    <div>
      <h2>
        <span class="title-icon">
          <el-icon :size="20"><component :is="icon" /></el-icon>
        </span>
        <span>{{ title }}</span>
      </h2>
      <div v-if="subtitle" class="subtitle">{{ subtitle }}</div>
    </div>
    <div class="actions">
      <slot />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import {
  Odometer, Notebook, Coin, Grid, Files, Share, DataAnalysis,
  Search, MagicStick, Document, EditPen, UserFilled, Lock, Key,
  Monitor, DataLine, Connection, Setting,
} from '@element-plus/icons-vue'

// 允许的图标集合 = ICON_MAP 的键；新增图标只要两处同步即可。
// 白名单写死在这里（而不是引用模块变量）是因为 defineProps 会被提升到
// setup() 之外，validator 里只能出现字面量。
const ICON_MAP = {
  Odometer, Notebook, Coin, Grid, Files, Share, DataAnalysis, Search, MagicStick,
  Document, EditPen, UserFilled, Lock, Key, Monitor, DataLine, Connection, Setting,
}

const props = defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
  iconKey: {
    type: String,
    default: 'Odometer',
    validator: v => [
      'Odometer', 'Notebook', 'Coin', 'Grid', 'Files', 'Share',
      'DataAnalysis', 'Search', 'MagicStick', 'Document', 'EditPen',
      'UserFilled', 'Lock', 'Key', 'Monitor', 'DataLine', 'Connection',
      'Setting',
    ].includes(v),
  },
})
const icon = computed(() => ICON_MAP[props.iconKey] || 'Odometer')
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
  gap: 16px;
  flex-wrap: wrap;
}
h2 {
  margin: 0;
  font-size: 22px;
  font-weight: 650;
  letter-spacing: -0.6px;
  display: flex;
  align-items: center;
  gap: 11px;
  color: var(--text-primary);
  font-family: var(--font-display);
}
.title-icon {
  width: 36px;
  height: 36px;
  border-radius: var(--radius);
  background: var(--primary-grad);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: white;
  box-shadow: 0 1px 0 rgba(255, 255, 255, 0.22) inset, 0 3px 10px rgba(71, 75, 176, 0.28);
}
.subtitle {
  color: var(--text-tertiary);
  font-size: 14px;
  margin-top: 7px;
  line-height: 1.6;
}
.actions { display: flex; gap: 8px; flex-shrink: 0; }

@media (max-width: 768px) {
  .page-header {
    flex-direction: column;
    gap: 12px;
    margin-bottom: 20px;
  }
  h2 {
    font-size: 18px;
    letter-spacing: -0.3px;
  }
  .title-icon {
    width: 30px;
    height: 30px;
  }
  .actions {
    width: 100%;
    flex-wrap: wrap;
  }
}

</style>