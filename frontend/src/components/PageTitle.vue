<template>
  <header class="page-header">
    <div class="page-header-main">
      <h2 class="page-header-title">
        <span class="title-icon">
          <el-icon :size="20"><component :is="icon" /></el-icon>
        </span>
        <span class="page-header-text">{{ title }}</span>
        <slot name="tag" />
      </h2>
      <!-- 描述放在标题下面而不是右边：描述是这个页面的解释，
           右边留给「操作」，两件事分开才不打架 -->
      <p v-if="descText" class="subtitle">{{ descText }}</p>
    </div>
    <div v-if="$slots.default" class="actions">
      <slot />
    </div>
  </header>
</template>

<script setup>
/**
 * 页面标题区
 *
 * 结构固定为「标题 + 描述 + 右侧动作区」三段：
 *   - 标题带一个图标底板，一眼能认出这是哪个页面
 *   - 描述解释这个页面是干什么的（可省略）
 *   - 动作区永远在右边；窄屏时整块换行到下一行，
 *     按钮不会被挤成两行或者溢出屏幕
 */
import { computed } from 'vue'
import * as ElementPlusIcons from '@element-plus/icons-vue'

// 图标直接用整个 Element Plus 图标包，不再维护 ICON_MAP。
//
// 为什么改：原来有一份 ICON_MAP + 一份 validator 数组，两处都得同步 ——
// 而「新增图标只要两处同步即可」这句注释骗了人（实际漏一处就静默回退成工作台图标）。
// 踩过：回收站与导航管理两个页面的标题图标长得一模一样（都是工作台那个表盘），
// 用户看到的是「图标一样」，不是「报错了」，这种症状比报错更难查。
//
// 现在图标本身从包里取 —— 以后用任何 Element Plus 图标都不会再漏。
//
// ⚠️ validator 里只能用**字面量**：defineProps 会被提升到 setup() 之外，
//    不能引用模块里的变量（引用了直接编译报错，整个组件 500）。
//    所以这里校验的是「图标名长得像不像图标名」，真正的存在性交给 computed 兜底。
const props = defineProps({
  title: { type: String, required: true },
  /** 描述。subtitle 是旧名字，仍然可用，两个都传时以 description 为准 */
  description: { type: String, default: '' },
  subtitle: { type: String, default: '' },
  iconKey: {
    type: String,
    default: 'Odometer',
    validator: v => typeof v === 'string' && /^[A-Z][A-Za-z0-9]*$/.test(v),
  },
})

const icon = computed(() => ElementPlusIcons[props.iconKey] || ElementPlusIcons.Odometer)
const descText = computed(() => props.description || props.subtitle)
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-4);
  flex-wrap: wrap;
  margin-bottom: var(--space-6);
}
.page-header-main {
  min-width: 0;
  flex: 1 1 auto;
}
.page-header-title {
  margin: 0;
  font-size: var(--text-2xl);
  font-weight: 650;
  letter-spacing: -0.6px;
  font-family: var(--font-display);
  display: flex;
  align-items: center;
  gap: 11px;
  color: var(--text-primary);
  flex-wrap: wrap;
}
.page-header-text { min-width: 0; }
.title-icon {
  width: 36px;
  height: 36px;
  border-radius: var(--radius);
  background: var(--primary-grad);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 18px;
  flex-shrink: 0;
  box-shadow: 0 1px 0 rgba(255, 255, 255, 0.22) inset, 0 3px 10px rgba(71, 75, 176, 0.28);
}
.subtitle {
  color: var(--text-tertiary);
  font-size: var(--text-base);
  margin: 7px 0 0;
  line-height: 1.6;
  max-width: 76ch;      /* 太长的描述会把动作区挤到屏幕外，限宽更耐看 */
}
.actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
  flex-wrap: wrap;
}

@media (max-width: 768px) {
  .page-header {
    flex-direction: column;
    align-items: stretch;
    gap: var(--space-3);
    margin-bottom: var(--space-5);
  }
  .page-header-title {
    font-size: var(--text-xl);
    letter-spacing: -0.3px;
  }
  .title-icon {
    width: 30px;
    height: 30px;
    font-size: 16px;
  }
  .subtitle {
    font-size: var(--text-sm);
  }
  /* 窄屏时动作区换行到下一行并占满宽度，
     否则「新建」这类按钮会被挤到屏幕边缘 */
  .actions {
    width: 100%;
    flex-wrap: wrap;
  }
}
</style>
