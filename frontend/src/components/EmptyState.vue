<template>
  <div class="empty-state" :class="[`is-${variant}`, { 'is-compact': compact }]">
    <!-- 图标区：既能传 Element Plus 图标名，也能直接传 emoji -->
    <div v-if="showIcon" class="empty-icon" :style="iconStyle">
      <slot name="icon">
        <span v-if="isEmoji" class="empty-emoji">{{ icon }}</span>
        <el-icon v-else :size="iconSizePx"><component :is="iconComp" /></el-icon>
      </slot>
    </div>

    <div v-if="title" class="empty-title">{{ title }}</div>
    <div v-if="description" class="empty-desc">{{ description }}</div>

    <!-- 动作区：给「新建」「去设置」这类引导按钮 -->
    <div v-if="$slots.default" class="empty-actions">
      <slot />
    </div>
  </div>
</template>

<script setup>
/**
 * 统一空状态
 *
 * 为什么要有这个组件：项目里每个页面都自己写了一套 .empty-state，
 * 图标大小、标题字重、描述宽度、按钮间距各写各的，
 * 同一个「暂无数据」在不同页面长得都不一样。这个组件把四段
 * （图标 / 标题 / 描述 / 动作）固定成一套刻度，页面只传内容。
 *
 * 用法：
 *   <EmptyState
 *     icon="Box"
 *     title="还没有应用"
 *     description="应用把模型、记录、文件组织成一个可用的工作台。"
 *   >
 *     <el-button type="primary">新建应用</el-button>
 *   </EmptyState>
 */
import { computed } from 'vue'
import {
  Box, Document, Files, Folder, Grid, Notebook, Search,
  Share, Coin, Upload, User, Connection, MagicStick, List,
} from '@element-plus/icons-vue'
import { emptyIconSize } from '../utils/ui'

// 常用空态图标的本地表：写死在这里而不是读全局变量，
// 是因为 defineProps 会被提升到 setup() 之外。
// 表外的图标名也能用 —— Element Plus 的图标在 main.js 里是全局注册的，
// <component :is="'某个图标名'"> 能直接解析到。
const ICON_MAP = {
  Box, Document, Files, Folder, Grid, Notebook, Search,
  Share, Coin, Upload, User, Connection, MagicStick, List,
}

const props = defineProps({
  /** 图标：Element Plus 图标名，或一个 emoji */
  icon: { type: String, default: 'Box' },
  /** 标题 */
  title: { type: String, default: '' },
  /** 描述 */
  description: { type: String, default: '' },
  /** 图标尺寸：数字按 px，或 'sm' / 'md' / 'lg' 走档位 */
  iconSize: { type: [Number, String], default: 'lg' },
  /** 紧凑模式：卡片内的小空态（省纵向空间） */
  compact: { type: Boolean, default: false },
  /**
   * 形态：
   *   card    —— 有边框和底色的独立卡片（页面级空态，默认）
   *   plain   —— 无边框无底色，直接放在内容流里（表格/卡片内部）
   *   inline  —— 一行式（筛选后无结果这种，只需一句话的场景）
   */
  variant: {
    type: String,
    default: 'card',
    validator: v => ['card', 'plain', 'inline'].includes(v),
  },
})

const iconComp = computed(() => ICON_MAP[props.icon] || props.icon || null)
// emoji 直接当文字渲染，不走 <component>
const isEmoji = computed(() => !!props.icon && /[^\x00-\x7F]/.test(props.icon))
const showIcon = computed(() => !!props.icon && props.variant !== 'inline')
const iconSizePx = computed(() => emptyIconSize(props.iconSize))
const iconStyle = computed(() => {
  const size = iconSizePx.value
  return {
    width: `${size}px`,
    height: `${size}px`,
    borderRadius: props.compact ? 'var(--radius)' : 'var(--radius-lg)',
    fontSize: `${Math.round(size * 0.42)}px`,
  }
})
</script>

<style scoped>
.empty-state {
  text-align: center;
  padding: 72px 24px;
  color: var(--text-tertiary);
  background: var(--bg-card);
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-lg);
}
.empty-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-bottom: var(--space-5);
  background: var(--bg-subtle);
  color: var(--text-tertiary);
  flex-shrink: 0;
}
.empty-emoji { line-height: 1; }
.empty-title {
  font-size: var(--text-xl);
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: var(--space-2);
  letter-spacing: -0.2px;
}
.empty-desc {
  font-size: var(--text-base);
  color: var(--text-secondary);
  margin-bottom: var(--space-6);
  max-width: 420px;
  margin-left: auto;
  margin-right: auto;
  line-height: 1.65;
}
.empty-actions {
  display: flex;
  gap: var(--space-3);
  justify-content: center;
  flex-wrap: wrap;
}

/* 无边框：用在卡片内部或表格下方 */
.is-plain {
  background: transparent;
  border: none;
  padding: 48px 24px;
}
.is-plain .empty-icon {
  background: var(--bg-subtle);
}

/* 一行式：筛选无结果这种「只需一句话」的场景 */
.is-inline {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  padding: var(--space-6) var(--space-4);
  background: transparent;
  border: none;
  border-radius: var(--radius);
}
.is-inline .empty-icon {
  margin-bottom: 0;
  background: transparent;
}
.is-inline .empty-title {
  font-size: var(--text-base);
  font-weight: 600;
  margin-bottom: 0;
}
.is-inline .empty-desc {
  margin-bottom: 0;
  font-size: var(--text-sm);
  max-width: none;
}

/* 紧凑：卡片内部的小空态，纵向空间要省 */
.is-compact {
  padding: var(--space-6) var(--space-4);
}
.is-compact .empty-icon { margin-bottom: var(--space-3); }
.is-compact .empty-title { font-size: var(--text-md); }
.is-compact .empty-desc { margin-bottom: var(--space-4); font-size: var(--text-sm); }

@media (max-width: 768px) {
  .empty-state { padding: var(--space-8) var(--space-4); }
}
</style>
