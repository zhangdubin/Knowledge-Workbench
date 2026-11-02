<template>
  <section class="stage-panel">
    <header class="panel-head">
      <div class="panel-head-main">
        <h3 class="panel-title">{{ stageMeta('design').title }}</h3>
        <p class="panel-sub">{{ stageMeta('design').subtitle }}</p>
      </div>
      <div class="panel-ops">
        <el-button
          v-if="stage?.status === 'pending' || !stage"
          type="primary"
          :loading="busy"
          @click="$emit('run')"
        >
          <el-icon><Connection /></el-icon>{{ stageMeta('design').action }}
        </el-button>
        <el-button v-else :loading="busy" @click="$emit('run', { force: true })">
          <el-icon><Refresh /></el-icon>{{ stageMeta('design').rerun }}
        </el-button>
      </div>
    </header>

    <EmptyState
      v-if="!stage || stage.status === 'pending'"
      icon="Connection"
      title="第三步：把规格变成可施工的设计"
      description="生成架构、模块划分、数据表、接口清单与任务拆解，任务会真的落进任务表。"
    />

    <div v-else-if="stage.status === 'running'" class="panel-state">
      <el-skeleton :rows="5" animated />
      <p class="panel-state-note">正在生成设计…</p>
    </div>

    <div v-else-if="stage.status === 'failed'" class="panel-state is-failed">
      <el-alert type="error" :closable="false" show-icon title="这一步失败了">
        <div class="fail-line">{{ stage.error || '后端没有给出失败原因' }}</div>
      </el-alert>
      <el-button type="primary" :loading="busy" @click="$emit('run', { force: true })">重试这一步</el-button>
    </div>

    <template v-else>
      <div v-for="sec in sections" :key="sec.key" class="block">
        <div class="block-head">
          <span class="block-title">{{ sec.title }}</span>
          <span class="block-note">{{ countOf(sec) }}</span>
        </div>

        <p v-if="sec.type === 'text'" class="arch-text">{{ sec.items }}</p>

        <div v-else-if="sec.type === 'modules'" class="module-list">
          <div v-for="(m, i) in sec.items" :key="m.name || i" class="module-card">
            <div class="module-name">{{ m.name || '（未命名模块）' }}</div>
            <div class="module-resp">{{ m.responsibility || '（没写职责）' }}</div>
            <div v-if="(m.depends_on || []).length" class="module-deps">
              依赖：{{ (m.depends_on || []).join('、') }}
            </div>
          </div>
        </div>

        <div v-else-if="sec.type === 'tables'" class="table-list">
          <div v-for="(t, i) in sec.items" :key="t.name || i" class="table-card">
            <div class="table-name">{{ t.name || '（未命名表）' }}</div>
            <div class="table-cols">
              <span v-for="(c, ci) in (t.columns || [])" :key="ci" class="col-chip">
                <b>{{ c.name }}</b>
                <span class="col-type">{{ c.type }}</span>
              </span>
              <span v-if="!(t.columns || []).length" class="entity-empty">没有列出字段</span>
            </div>
          </div>
        </div>

        <div v-else-if="sec.type === 'apis'" class="api-list">
          <div v-for="(a, i) in sec.items" :key="a.path || i" class="api-row">
            <span class="api-method" :class="'m-' + String(a.method || 'get').toLowerCase()">
              {{ a.method || 'GET' }}
            </span>
            <span class="api-path">{{ a.path || '—' }}</span>
            <span class="api-purpose">{{ a.purpose || '' }}</span>
          </div>
        </div>

        <ul v-else class="plain-list is-boxed">
          <li v-for="(it, i) in sec.items" :key="i">{{ it }}</li>
        </ul>
      </div>

      <!-- 任务拆解：设计阶段跑完会真的落成任务行 -->
      <div class="block">
        <div class="block-head">
          <span class="block-title">任务拆解</span>
          <span class="block-note">{{ tasks.length }} 个任务 · 可以逐个生成产出</span>
        </div>
        <div v-if="tasks.length" class="task-list">
          <div
            v-for="t in flatTasks"
            :key="t.id"
            class="task-item"
            :style="{ marginLeft: (t.depth || 0) * 16 + 'px' }"
          >
            <div class="task-main" @click="$emit('toggle-task', t)">
              <el-tag :type="taskStatus(t.status).type" size="small" effect="plain">
                {{ taskStatus(t.status).label }}
              </el-tag>
              <span class="task-title">{{ t.title }}</span>
            </div>
            <div v-if="t.description" class="task-desc">{{ t.description }}</div>
            <div v-if="t.acceptance" class="task-acc">验收：{{ t.acceptance }}</div>
            <div class="task-ops">
              <el-button size="small" text @click="$emit('gen-task', t)">生成产出</el-button>
              <el-button size="small" text @click="$emit('edit-task', t)">编辑</el-button>
              <el-button size="small" text type="danger" @click="$emit('del-task', t)">删除</el-button>
            </div>
            <div v-if="(warnings[t.id] || []).length" class="task-warn">
              <div v-for="(w, wi) in warnings[t.id]" :key="wi" class="warn-line">
                <el-tag :type="warningSeverity(w).type" size="small" effect="dark">
                  {{ warningSeverity(w).label }}
                </el-tag>
                <span>{{ describeWarning(w) }}</span>
              </div>
            </div>
          </div>
        </div>
        <EmptyState
          v-else
          compact
          icon="List"
          title="还没有任务"
          description="生成设计后，任务会自动拆解到这里。"
        />
      </div>
    </template>
  </section>
</template>

<script setup>
/**
 * 阶段三：需求转化（design）
 *
 * 产物是架构、模块、数据表、接口清单与风险（契约 design.data）。
 * 任务拆解**不在** design.data 里 —— 它落 dev_task 表（有依赖关系、
 * 要能逐个生成产出），所以这里同时把任务列表接上。
 */
import { computed } from 'vue'
import EmptyState from '../../components/EmptyState.vue'
import {
  stageMeta, designSections, taskStatus, warningSeverity, describeWarning,
  buildTaskTree, flattenTaskTree,
} from '../../utils/dev.js'

const props = defineProps({
  stage: { type: Object, default: null },
  tasks: { type: Array, default: () => [] },
  warnings: { type: Object, default: () => ({}) },
  busy: { type: Boolean, default: false },
})

defineEmits(['run', 'gen-task', 'edit-task', 'del-task', 'toggle-task'])

const sections = computed(() => designSections(props.stage?.data))
const flatTasks = computed(() => flattenTaskTree(buildTaskTree(props.tasks)))

function countOf(sec) {
  if (sec.type === 'text') return ''
  return sec.items.length + ' 项'
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
.panel-ops { flex: 0 0 auto; }
.block { display: flex; flex-direction: column; gap: var(--space-2); }
.block-head { display: flex; align-items: baseline; gap: var(--space-3); }
.block-title { font-size: var(--text-sm); font-weight: 620; color: var(--text-primary); }
.block-note { font-size: var(--text-xs); color: var(--text-tertiary); }
.arch-text {
  margin: 0;
  padding: var(--space-4);
  background: var(--bg-subtle);
  border-radius: var(--radius-md);
  font-size: var(--text-base);
  line-height: 1.8;
  color: var(--text-primary);
  white-space: pre-wrap;
}
.module-list { display: flex; flex-direction: column; gap: var(--space-2); }
.module-card {
  display: flex; flex-direction: column; gap: 2px;
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}
.module-name { font-size: var(--text-sm); font-weight: 620; color: var(--text-primary); }
.module-resp { font-size: var(--text-xs); color: var(--text-secondary); line-height: 1.7; }
.module-deps { font-size: var(--text-xs); color: var(--text-tertiary); }
.table-list { display: flex; flex-direction: column; gap: var(--space-2); }
.table-card {
  display: flex; flex-direction: column; gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background: var(--bg-subtle);
  border-radius: var(--radius-md);
}
.table-name { font-size: var(--text-sm); font-weight: 620; color: var(--text-primary); }
.table-cols { display: flex; gap: var(--space-2); flex-wrap: wrap; }
.col-chip {
  display: inline-flex; align-items: baseline; gap: 4px;
  font-size: var(--text-xs);
  padding: 1px 6px;
  border: 1px solid var(--border);
  border-radius: var(--radius-xs);
  background: var(--bg-card);
  color: var(--text-primary);
}
.col-type { color: var(--text-tertiary); }
.api-list {
  display: flex; flex-direction: column;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
}
.api-row {
  display: flex; align-items: center; gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--border-light);
  font-size: var(--text-xs);
}
.api-row:last-child { border-bottom: none; }
.api-method {
  flex: 0 0 auto;
  min-width: 46px;
  text-align: center;
  font-weight: 700;
  padding: 1px 4px;
  border-radius: var(--radius-xs);
  background: var(--info-bg);
  color: var(--info-text);
}
.api-method.m-post { background: var(--success-bg); color: var(--success-text); }
.api-method.m-put, .api-method.m-patch { background: var(--warning-bg); color: var(--warning-text); }
.api-method.m-delete { background: var(--danger-bg); color: var(--danger-text); }
.api-path { font-family: var(--font-mono); color: var(--text-primary); }
.api-purpose { color: var(--text-tertiary); }
.plain-list {
  margin: 0; padding-left: 18px;
  font-size: var(--text-sm); line-height: 1.9; color: var(--text-secondary);
}
.plain-list.is-boxed {
  padding: var(--space-3) var(--space-4);
  background: var(--bg-subtle);
  border-radius: var(--radius-md);
}
.entity-empty { font-size: var(--text-xs); color: var(--text-tertiary); }
/* ---------- 任务 ---------- */
.task-list { display: flex; flex-direction: column; gap: var(--space-2); }
.task-item {
  display: flex; flex-direction: column; gap: var(--space-1);
  padding: var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}
.task-main { display: flex; align-items: center; gap: var(--space-2); cursor: pointer; }
.task-title { font-size: var(--text-sm); font-weight: 600; color: var(--text-primary); }
.task-desc { font-size: var(--text-xs); color: var(--text-secondary); line-height: 1.7; }
.task-acc { font-size: var(--text-xs); color: var(--text-tertiary); }
.task-ops { display: flex; gap: var(--space-1); }
.task-warn { display: flex; flex-direction: column; gap: var(--space-1); }
.warn-line { display: flex; align-items: center; gap: var(--space-2); font-size: var(--text-xs); color: var(--text-secondary); }
.panel-state { display: flex; flex-direction: column; gap: var(--space-3); }
.panel-state-note { margin: 0; font-size: var(--text-sm); color: var(--text-tertiary); }
.fail-line { font-size: var(--text-sm); line-height: 1.7; }
</style>
