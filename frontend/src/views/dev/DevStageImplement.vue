<template>
  <section class="stage-panel">
    <header class="panel-head">
      <div class="panel-head-main">
        <h3 class="panel-title">{{ stageMeta('implement').title }}</h3>
        <p class="panel-sub">{{ stageMeta('implement').subtitle }}</p>
      </div>
      <div class="panel-ops">
        <el-button
          v-if="stage?.status === 'pending' || !stage"
          type="primary"
          :loading="busy"
          @click="$emit('run')"
        >
          <el-icon><Files /></el-icon>{{ stageMeta('implement').action }}
        </el-button>
        <el-button v-else :loading="busy" @click="$emit('run', { force: true })">
          <el-icon><Refresh /></el-icon>{{ stageMeta('implement').rerun }}
        </el-button>
        <el-button
          type="success"
          plain
          :loading="exporting"
          :disabled="!artifacts.length"
          @click="$emit('export')"
        >
          <el-icon><Download /></el-icon>导出项目 ZIP
        </el-button>
      </div>
    </header>

    <div v-if="stage && stage.status === 'running'" class="panel-state">
      <el-skeleton :rows="5" animated />
      <p class="panel-state-note">正在生成项目文件…</p>
    </div>

    <div v-else-if="stage && stage.status === 'failed'" class="panel-state is-failed">
      <el-alert type="error" :closable="false" show-icon title="这一步失败了">
        <div class="fail-line">{{ stage.error || '后端没有给出失败原因' }}</div>
      </el-alert>
      <el-button type="primary" :loading="busy" @click="$emit('run', { force: true })">重试这一步</el-button>
    </div>

    <template v-else>
      <!-- 还没有任何文件时，先把这一步是干什么的讲清楚 -->
      <EmptyState
        v-if="!artifacts.length"
        icon="Files"
        title="第四步：产出真正能跑的项目"
        description="生成源码、依赖清单、README、测试与启动脚本；跑完之后可以一键导出 ZIP。"
      />

      <div v-else class="impl-body">
        <!-- 文件树 -->
        <div class="impl-tree">
          <div class="impl-pane-head">
            <span class="impl-pane-title">项目文件</span>
            <span class="impl-pane-note">{{ artifacts.length }} 个</span>
          </div>
          <div class="impl-tree-scroll">
            <DevFileTree :nodes="tree" :active-path="activePath" @pick="pick" />
          </div>
        </div>

        <!-- 预览 -->
        <div class="impl-preview">
          <div class="impl-pane-head">
            <span class="impl-pane-title">{{ current?.path || current?.filename || '文件预览' }}</span>
            <div class="impl-pane-ops">
              <el-tag v-if="current?.language" size="small" effect="plain" type="info">
                {{ current.language }}
              </el-tag>
              <el-button
                size="small"
                text
                :loading="importing === current?.id"
                @click="$emit('import', current)"
              >入库</el-button>
              <el-button size="small" text type="danger" @click="$emit('remove', current)">删除</el-button>
            </div>
          </div>
          <pre class="code">{{ current?.content || '（这个文件没有内容）' }}</pre>
        </div>
      </div>

      <div class="panel-foot">
        <span class="foot-note">
          导出的是 ZIP（顶层一个项目目录），含 README、依赖清单、入口文件、测试与启动脚本。
        </span>
      </div>
    </template>
  </section>
</template>

<script setup>
/**
 * 阶段四：项目生成（implement）
 *
 * 产物不是一段说明文字，而是一批**文件**（dev_artifact 行，
 * path 是项目内相对路径）。所以这一阶段的界面是：
 * 左边文件树、右边内容预览，右上角导出 ZIP。
 *
 * 导出必须带会话 cookie，所以不能用 window.open 裸链 ——
 * 裸链没有会话会直接 401，浏览器还会跳一个 JSON 错误页，
 * 用户完全不知道发生了什么。见 api/dev.js 的 downloadExport。
 */
import { computed, ref, watch } from 'vue'
import EmptyState from '../../components/EmptyState.vue'
import DevFileTree from './DevFileTree.vue'
import { stageMeta, buildFileTree } from '../../utils/dev.js'

const props = defineProps({
  stage: { type: Object, default: null },
  artifacts: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
  exporting: { type: Boolean, default: false },
  importing: { type: [String, Number], default: null },
})

const emit = defineEmits(['run', 'export', 'import', 'remove'])

const activePath = ref('')
const current = ref(null)

const tree = computed(() => buildFileTree(props.artifacts))

/** 默认选中第一个文件：空着预览区会让人以为没生成 */
watch(() => props.artifacts, (list) => {
  if (!list || !list.length) {
    current.value = null
    activePath.value = ''
    return
  }
  if (!current.value || !list.find((a) => a.id === current.value.id)) {
    pick(list[0])
  }
}, { immediate: true, deep: true })

function pick(file) {
  if (!file) return
  current.value = file
  activePath.value = String(file.path || file.filename || '')
}
</script>

<style scoped>
.stage-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  padding: var(--space-5);
  min-height: 0;
  overflow: auto;
}
.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
}
.panel-title { margin: 0; font-size: var(--text-lg); font-weight: 650; color: var(--text-primary); }
.panel-sub { margin: 2px 0 0; font-size: var(--text-xs); color: var(--text-tertiary); line-height: 1.6; }
.panel-ops { display: flex; gap: var(--space-2); flex: 0 0 auto; }
.block { display: flex; flex-direction: column; gap: var(--space-2); }

/* ---------- 文件树 + 预览 ---------- */
.impl-body {
  display: grid;
  grid-template-columns: minmax(180px, 260px) minmax(0, 1fr);
  gap: var(--space-3);
  min-height: 320px;
}
.impl-tree,
.impl-preview {
  display: flex;
  flex-direction: column;
  min-width: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
}
.impl-pane-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-light);
}
.impl-pane-title {
  font-size: var(--text-xs);
  font-weight: 620;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.impl-pane-note { font-size: var(--text-xs); color: var(--text-tertiary); }
.impl-pane-ops { display: flex; align-items: center; gap: var(--space-1); }
.impl-tree-scroll { padding: var(--space-2); overflow: auto; }
.code {
  flex: 1 1 auto;
  margin: 0;
  padding: var(--space-3);
  overflow: auto;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  line-height: 1.7;
  color: var(--text-primary);
  background: var(--bg-subtle);
  white-space: pre;
}
.panel-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--border-light);
}
.foot-note { font-size: var(--text-xs); color: var(--text-tertiary); }
.panel-state { display: flex; flex-direction: column; gap: var(--space-3); }
.panel-state-note { margin: 0; font-size: var(--text-sm); color: var(--text-tertiary); }
.fail-line { font-size: var(--text-sm); line-height: 1.7; }
</style>
