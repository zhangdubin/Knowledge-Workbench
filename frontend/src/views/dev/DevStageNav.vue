<template>
  <aside class="stage-nav">
    <div class="nav-head">
      <span class="nav-title">开发流水线</span>
      <span class="nav-note">四个阶段，按顺序推进</span>
    </div>

    <ol class="stage-list">
      <li
        v-for="(s, i) in stages"
        :key="s.key"
        class="stage-item"
        :class="{
          'is-active': s.key === active,
          'is-current': s.key === currentStage,
          'is-done': s.status === 'done',
          'is-blocked': !gateOf(s.key).ok && s.status !== 'done',
        }"
      >
        <button class="stage-btn" type="button" @click="$emit('select', s.key)">
          <span class="stage-index" :class="'st-' + s.status">{{ i + 1 }}</span>
          <span class="stage-main">
            <span class="stage-line">
              <span class="stage-name">{{ stageMeta(s.key).title }}</span>
              <el-tag :type="stageStatus(s.status).type" size="small" effect="light">
                {{ stageStatus(s.status).label }}
              </el-tag>
              <el-tag v-if="s.key === currentStage" size="small" type="primary" effect="plain">
                当前
              </el-tag>
            </span>
            <span class="stage-summary">{{ summaryOf(s) }}</span>
            <span v-if="!gateOf(s.key).ok && s.status !== 'done'" class="stage-gate">
              {{ gateOf(s.key).reason }}
            </span>
          </span>
        </button>
      </li>
    </ol>

    <div class="nav-foot">
      <div class="nav-foot-title">每一步的交付物</div>
      <div class="nav-foot-item" v-for="k in STAGE_KEYS" :key="k">
        <span class="nav-foot-name">{{ stageMeta(k).title }}</span>
        <span class="nav-foot-desc">{{ stageMeta(k).deliverable }}</span>
      </div>
    </div>
  </aside>
</template>

<script setup>
/**
 * 左栏：四阶段导航
 *
 * 为什么左栏放「阶段」而不是「方案 + 任务」：
 * 专业开发是一条有先后依赖的流水线 —— 用户最需要知道的是
 * 「我现在在哪一步、这一步该做什么、为什么下一步还不能跑」。
 * 原来的三栏把方案、任务、对话平铺在一起，看着内容多，
 * 实际看不出流程，走到哪一步全靠猜。
 *
 * 这一栏只做三件事：
 *   1) 让人看见四个阶段与它们的顺序；
 *   2) 标出当前阶段与每个阶段的状态；
 *   3) 说清「为什么这一步现在还不能跑」（闸门原因）——
 *      闸门判定在后端（gates），前端只负责显示。
 */
import { computed } from 'vue'
import {
  STAGE_KEYS, stageMeta, stageStatus, stageSummary, stageGate,
} from '../../utils/dev.js'

const props = defineProps({
  stages: { type: Array, default: () => [] },
  currentStage: { type: String, default: '' },
  active: { type: String, default: '' },
  gates: { type: Object, default: () => ({}) },
})

defineEmits(['select'])

/** 后端给的精简视图优先；后端还没上线时用本地元数据兜底，保证导航不空 */
const stageList = computed(() => {
  const list = STAGE_KEYS.map((key) => {
    const hit = (props.stages || []).find((s) => s.key === key)
    return {
      key: key,
      title: stageMeta(key).title,
      status: (hit && hit.status) || 'pending',
      summary: (hit && hit.summary) || '',
    }
  })
  return list
})

function summaryOf(s) {
  if (s.summary) return s.summary
  return stageSummary({ key: s.key, status: s.status })
}

function gateOf(key) {
  return stageGate(key, props.gates)
}
</script>

<style scoped>
.stage-nav {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  padding: var(--space-4);
  overflow: auto;
}
.nav-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.nav-title {
  font-size: var(--text-sm);
  font-weight: 620;
  color: var(--text-primary);
}
.nav-note {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

/* ---------- 阶段列表 ---------- */
.stage-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.stage-item {
  border-radius: var(--radius-md);
  transition: background .15s ease;
}
.stage-item.is-active {
  background: var(--primary-bg);
}
.stage-btn {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  width: 100%;
  padding: var(--space-3);
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  text-align: left;
  cursor: pointer;
  font: inherit;
  color: inherit;
}
.stage-btn:hover {
  background: var(--bg-subtle);
}
.stage-item.is-active .stage-btn:hover {
  background: transparent;
}
.stage-index {
  flex: 0 0 auto;
  width: 22px;
  height: 22px;
  margin-top: 1px;
  border-radius: var(--radius-full);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-xs);
  font-weight: 600;
  background: var(--bg-subtle);
  color: var(--text-tertiary);
  border: 1px solid var(--border);
}
.stage-index.st-done {
  background: var(--success-bg);
  color: var(--success-text);
  border-color: transparent;
}
.stage-index.st-running {
  background: var(--primary-bg-strong);
  color: var(--primary);
  border-color: transparent;
}
.stage-index.st-needs_input {
  background: var(--warning-bg);
  color: var(--warning-text);
  border-color: transparent;
}
.stage-index.st-failed {
  background: var(--danger-bg);
  color: var(--danger-text);
  border-color: transparent;
}
.stage-main {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.stage-line {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.stage-name {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
}
.stage-summary {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  line-height: 1.6;
}
.stage-gate {
  font-size: var(--text-xs);
  color: var(--warning-text);
  line-height: 1.6;
}
.stage-item.is-blocked .stage-summary {
  color: var(--text-tertiary);
}

/* ---------- 底部：交付物 ---------- */
.nav-foot {
  border-top: 1px solid var(--border-light);
  padding-top: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.nav-foot-title {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  font-weight: 600;
}
.nav-foot-item {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.nav-foot-name {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  font-weight: 600;
}
.nav-foot-desc {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  line-height: 1.6;
}
</style>
