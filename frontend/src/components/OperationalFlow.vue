<template>
  <section class="op-flow" aria-label="知识服务流程">
    <div class="op-flow-head">
      <div>
        <span class="op-eyebrow">作业链路</span>
        <h3>从资料到可执行知识</h3>
      </div>
      <span class="op-summary" :data-tone="summary.tone">{{ summary.label }}</span>
    </div>
    <ol class="op-track">
      <li v-for="(stage, index) in FLOW_STAGES" :key="stage.key" class="op-stage" :data-state="states[stage.key]">
        <div class="op-node">
          <span class="op-index">{{ index + 1 }}</span>
          <span class="op-state">{{ FLOW_STATUS[states[stage.key]].label }}</span>
        </div>
        <strong>{{ stage.label }}</strong>
        <span>{{ stage.hint }}</span>
        <i v-if="index < FLOW_STAGES.length - 1" class="op-connector" aria-hidden="true" />
      </li>
    </ol>
    <p class="op-detail">{{ summary.detail }}</p>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { FLOW_STAGES, FLOW_STATUS, flowState, flowSummary } from '../utils/operationalFlow.js'

const props = defineProps({
  busy: Boolean,
  result: { type: Object, default: null },
  error: { type: String, default: '' },
})
const states = computed(() => flowState(props))
const summary = computed(() => flowSummary(props))
</script>

<style scoped>
.op-flow { border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--bg-card); padding: var(--space-4); box-shadow: var(--shadow-card); margin-bottom: var(--space-4); }
.op-flow-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-3); }
.op-eyebrow { color: var(--primary); font-size: var(--text-xs); font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.op-flow h3 { margin: 3px 0 0; font-size: var(--text-lg); }
.op-summary { border: 1px solid var(--border); border-radius: var(--radius-full); padding: 5px 10px; font-size: var(--text-xs); font-weight: 700; white-space: nowrap; }
.op-summary[data-tone="success"] { color: var(--success); background: var(--success-bg); }
.op-summary[data-tone="warning"] { color: var(--warning); background: var(--warning-bg); }
.op-summary[data-tone="primary"] { color: var(--primary); background: var(--primary-bg); }
.op-summary[data-tone="muted"] { color: var(--text-tertiary); background: var(--bg-subtle); }
.op-track { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--space-2); list-style: none; padding: 0; margin: var(--space-4) 0 var(--space-3); }
.op-stage { position: relative; display: grid; gap: 4px; min-width: 0; padding: 10px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-subtle); }
.op-stage[data-state="running"] { border-color: var(--primary); box-shadow: 0 0 0 2px var(--primary-bg); }
.op-stage[data-state="done"] { border-color: color-mix(in srgb, var(--success) 45%, var(--border)); }
.op-stage[data-state="blocked"] { border-color: color-mix(in srgb, var(--warning) 55%, var(--border)); }
.op-node { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
.op-index { width: 22px; height: 22px; display: inline-flex; align-items: center; justify-content: center; border-radius: 50%; color: var(--primary); background: var(--primary-bg); font-size: var(--text-xs); font-weight: 700; }
.op-state { color: var(--text-tertiary); font-size: 11px; }
.op-stage strong { color: var(--text-primary); font-size: var(--text-sm); }
.op-stage > span:last-child { color: var(--text-tertiary); font-size: var(--text-xs); line-height: 1.5; }
.op-connector { position: absolute; width: 9px; height: 1px; right: -6px; top: 22px; background: var(--border-strong); z-index: 1; }
.op-detail { color: var(--text-secondary); font-size: var(--text-sm); line-height: 1.6; margin: 0; }
@media (max-width: 720px) { .op-track { grid-template-columns: repeat(2, minmax(0, 1fr)); } .op-connector { display: none; } }
@media (max-width: 460px) { .op-flow { padding: var(--space-3); } .op-flow-head { flex-direction: column; } .op-track { grid-template-columns: 1fr; } }
</style>
