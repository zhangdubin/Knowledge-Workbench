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
      <div class="app-icon appc-icon">
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
    <div class="appc-actions" @click.stop @keydown.stop>
      <el-tooltip content="新建数据模型" placement="top" :show-after="400">
        <el-button class="appc-btn" text :disabled="!canManage" @click="$emit('new-model', app)">
          <el-icon><Plus /></el-icon>
        </el-button>
      </el-tooltip>

      <!-- 有多个模型时让用户选录哪个；只有一个就直接进 -->
      <el-dropdown
        v-if="models.length > 1"
        trigger="click"
        @command="(cmd) => $emit('add-record', app, cmd)"
      >
        <el-button class="appc-btn" text :disabled="!canManage" @click.stop>
          <el-icon><EditPen /></el-icon>
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item v-for="m in models" :key="m.id" :command="m">
              在「{{ m.name }}」中录入
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <el-tooltip v-else content="录入记录" placement="top" :show-after="400">
        <el-button
          class="appc-btn"
          text
          :disabled="!canManage || !models.length"
          @click="$emit('add-record', app, models[0] || null)"
        >
          <el-icon><EditPen /></el-icon>
        </el-button>
      </el-tooltip>

      <el-tooltip content="查看关联" placement="top" :show-after="400">
        <el-button class="appc-btn" text @click="$emit('view-relations', app)">
          <el-icon><Connection /></el-icon>
        </el-button>
      </el-tooltip>
      <el-tooltip content="编辑应用" placement="top" :show-after="400">
        <el-button class="appc-btn" text :disabled="!canManage" @click="$emit('edit', app)">
          <el-icon><Edit /></el-icon>
        </el-button>
      </el-tooltip>
      <el-tooltip content="删除应用" placement="top" :show-after="400">
        <el-button class="appc-btn is-danger" text :disabled="!canManage" @click="$emit('remove', app)">
          <el-icon><Delete /></el-icon>
        </el-button>
      </el-tooltip>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Clock, Connection, Delete, Document, Edit, EditPen, Files, Plus } from '@element-plus/icons-vue'
import { DEFAULT_GROUP, appDescription, resolveAppIcon } from '../utils/apps'
import { APP_ICON_CHOICES } from '../utils/icons'

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

defineEmits(['open', 'toggle', 'new-model', 'add-record', 'view-relations', 'edit', 'remove'])

const iconName = computed(() => resolveAppIcon(props.app, APP_ICON_CHOICES))
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
