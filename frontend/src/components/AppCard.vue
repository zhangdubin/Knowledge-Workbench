<template>
  <!--
    应用卡片：一屏之内把「这是什么、有多少内容、能立刻做什么」讲清楚。
    整块可点开详情，但同时是可聚焦的（role=button + tabindex + 键盘响应），
    不能只靠 cursor:pointer 冒充可点元素 —— 键盘用户到不了就是假按钮。
  -->
  <div
    class="app-card appc"
    :class="{ 'is-selected': selected }"
    role="button"
    tabindex="0"
    :aria-label="`应用 ${app.name}，${app.entity_count} 个模型，${app.record_count} 条记录`"
    @click="$emit('open', app)"
    @keydown.enter.prevent="$emit('open', app)"
    @keydown.space.prevent="$emit('open', app)"
  >
    <div class="appc-head">
      <el-checkbox
        v-if="multi"
        class="appc-check"
        :model-value="selected"
        :aria-label="`选中应用 ${app.name}`"
        @click.stop
        @change="$emit('toggle', app)"
        @keydown.stop
      />
      <!-- 图标底板用这个应用自己的强调色 ——
           原来全是同一个淡紫方块，六个应用长得像复制粘贴出来的 -->
      <div class="app-icon appc-icon" :class="`ac-${accent}`">
        <el-icon :size="22"><component :is="iconName" /></el-icon>
      </div>
      <div class="appc-titles">
        <div class="app-name appc-name" :title="app.name">{{ app.name }}</div>
        <div class="appc-key" :title="app.key">{{ app.key }}</div>
      </div>
      <span v-if="group && group !== DEFAULT_GROUP" class="appc-group" :title="`所属分组：${group}`">
        {{ group }}
      </span>
    </div>

    <p class="app-desc appc-desc">{{ description }}</p>

    <div class="app-meta appc-meta">
      <span><el-icon><Files /></el-icon>{{ app.entity_count || 0 }} 模型</span>
      <span><el-icon><Document /></el-icon>{{ app.record_count || 0 }} 记录</span>
      <span v-if="updatedText" class="appc-time"><el-icon><Clock /></el-icon>{{ updatedText }}</span>
    </div>

    <!-- 快捷操作常驻在卡面上：藏进「更多」菜单等于没有 -->
    <!-- 操作区
         原来每张卡底部一排 5 个灰色小图标，一屏六张卡就是一片小图标，
         看不出哪个是什么 —— 反而把卡片弄脏了。
         现在：常用的两个（录入记录 / 新建模型）做成带文字的按钮，
         剩下的（关联 / 编辑 / 删除）收进「更多」菜单。 -->
    <div class="appc-actions" @click.stop @keydown.stop>
      <!-- 录入记录：只有一个模型时直接录；有多个时用下拉让用户选 -->
      <el-button
        v-if="models.length <= 1"
        class="appc-primary-btn"
        size="small"
        :disabled="!canManage || !models.length"
        @click="$emit('add-record', app, models[0] || null)"
      >
        <el-icon><EditPen /></el-icon>录入记录
      </el-button>
      <el-button
        class="appc-primary-btn is-quiet"
        size="small"
        :disabled="!canManage"
        @click="$emit('new-model', app)"
      >
        <el-icon><Plus /></el-icon>新建模型
      </el-button>

      <!-- 多模型时「录入记录」要让用户选录哪个 -->
      <el-dropdown
        v-if="models.length > 1"
        trigger="click"
        @command="(cmd) => $emit('add-record', app, cmd)"
      >
        <el-button
          class="appc-primary-btn"
          size="small"
          :disabled="!canManage"
          @click.stop
        >
          <el-icon><EditPen /></el-icon>录入记录
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item v-for="m in models" :key="m.id" :command="m">
              在「{{ m.name }}」中录入
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>

      <!-- 其余操作收进「更多」 -->
      <el-dropdown trigger="click" @command="(cmd) => onMore(cmd, app)">
        <el-button class="appc-more-btn" size="small" text aria-label="更多操作" title="更多操作">
          <el-icon><MoreFilled /></el-icon>
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="relations">
              <el-icon><Connection /></el-icon>查看关联
            </el-dropdown-item>
            <el-dropdown-item command="edit" :disabled="!canManage">
              <el-icon><Edit /></el-icon>编辑应用
            </el-dropdown-item>
            <el-dropdown-item command="remove" divided :disabled="!canManage">
              <el-icon><Delete /></el-icon>删除应用
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Clock, Connection, Delete, Document, Edit, EditPen, Files, MoreFilled, Plus } from '@element-plus/icons-vue'
import { DEFAULT_GROUP, appDescription, resolveAppIcon } from '../utils/apps'
import { APP_ICON_CHOICES, appAccent } from '../utils/icons'

const props = defineProps({
  app: { type: Object, required: true },
  // 该应用下的数据模型：录入记录要指到具体模型上，所以由父级一次查好传进来
  models: { type: Array, default: () => [] },
  group: { type: String, default: '' },
  selected: { type: Boolean, default: false },
  multi: { type: Boolean, default: false },
  canManage: { type: Boolean, default: true },
  updatedText: { type: String, default: '' },
})

const emit = defineEmits(['open', 'toggle', 'new-model', 'add-record', 'view-relations', 'edit', 'remove'])

/** 「更多」菜单里的动作 */
function onMore(cmd, app) {
  if (cmd === 'relations') emit('view-relations', app)
  else if (cmd === 'edit') emit('edit', app)
  else if (cmd === 'remove') emit('remove', app)
}

const iconName = computed(() => resolveAppIcon(props.app, APP_ICON_CHOICES))
/** 这个应用自己的强调色 */
const accent = computed(() => appAccent(props.app?.key))
const description = computed(() => appDescription(props.app))
</script>

<style scoped>
.appc {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  cursor: pointer;
}
/* 焦点环交给设计系统的全局规则，这里只保证不被自己的样式盖掉 */
.appc:focus-visible {
  outline: 2px solid var(--focus-ring-color);
  outline-offset: 2px;
}

.appc.is-selected {
  border-color: var(--primary);
  background: var(--primary-bg);
}

.appc-head {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
}
.appc-check { margin-top: 10px; }
.appc-icon { flex-shrink: 0; }
.appc-titles { flex: 1; min-width: 0; }
.appc-name {
  margin-bottom: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.appc-key {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.appc-group {
  flex-shrink: 0;
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--primary-dark);
  background: var(--primary-bg);
  border: 1px solid var(--primary-200);
  padding: 2px 8px;
  border-radius: var(--radius-full);
  max-width: 96px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.appc-desc {
  margin: 0;
  min-height: 38px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  color: var(--text-secondary);
}
.appc-meta { gap: var(--space-4); }
.appc-time { margin-left: auto; color: var(--text-secondary); }

/* 快捷操作区：图标按钮的命中区域至少 28×28，否则在触屏上点不准 */
/* 顶部强调色带 */
.appc-accent {
  position: absolute;
  left: 0; right: 0; top: 0;
  height: 3px;
  background: var(--ac-fg, var(--primary));
  opacity: 0.85;
  border-radius: var(--radius-md) var(--radius-md) 0 0;
}

/* 操作区
   原来是 5 个灰色小图标排一行，一屏六张卡就是一片小图标。
   现在两个带文字的按钮 + 一个「更多」，卡片干净多了。 */
.appc-primary-btn {
  --el-button-bg-color: var(--ac-bg, var(--primary-bg));
  --el-button-border-color: var(--ac-line, var(--primary-200));
  --el-button-text-color: var(--ac-fg, var(--primary-dark));
  --el-button-hover-bg-color: var(--ac-edge, var(--primary-bg-strong));
  --el-button-hover-border-color: var(--ac-fg, var(--primary));
  --el-button-hover-text-color: var(--ac-fg, var(--primary-dark));
  font-weight: 550;
}
.appc-primary-btn.is-quiet {
  --el-button-bg-color: transparent;
  --el-button-border-color: var(--border);
  --el-button-text-color: var(--text-secondary);
  --el-button-hover-bg-color: var(--bg-subtle);
  --el-button-hover-border-color: var(--border-strong);
  --el-button-hover-text-color: var(--text-primary);
}
.appc-more-btn {
  color: var(--text-tertiary);
  width: 28px;
  padding: 0;
}

.appc-actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding-top: var(--space-3);
  border-top: 1px solid var(--border-light);
}
.appc-btn {
  min-width: 30px;
  min-height: 30px;
  padding: 0;
  color: var(--text-secondary);
}
.appc-btn:hover { color: var(--primary); }
.appc-btn.is-danger:hover { color: var(--danger); }
.appc-btn.is-danger :deep(.el-icon) { color: var(--danger); }
</style>
