<template>
  <div class="ks-stack">
    <section v-if="!replay" class="ks-state" :data-tone="tone" aria-label="检索状态">
      <div class="ks-meta">适用时点 {{ result.as_of || '当日' }} <span v-if="result.scope">· {{ result.scope }}</span></div>
      <h3>{{ statusLabel(result.status) }}</h3>
      <ul v-if="result.reasons?.length" class="ks-reasons">
        <li v-for="reason in result.reasons" :key="reason">{{ reason }}</li>
      </ul>
      <p v-if="result.incomplete && result.status !== 'incomplete'" class="ks-muted">本次结果受检索上限或可用范围限制。</p>
      <p v-if="result.answer" class="ks-answer">{{ result.answer }}</p>
      <p v-if="result.revalidated" class="ks-muted">已按当前权限核对原查询的证据。</p>
      <p v-if="!result.revalidated || result.generation === 'disabled' || result.generation === 'error'" class="ks-muted">
        {{ generationLabel(result.generation) }}
      </p>
    </section>

    <section v-if="result.items?.length" class="ks-stack">
      <h4>{{ replay ? '原查询选中的条目版本' : '知识条目' }}</h4>
      <ul class="ks-rows">
        <li v-for="item in result.items" :key="item.id" class="ks-row">
          <strong>{{ item.title }}</strong>
          <p v-if="item.summary">{{ item.summary }}</p>
          <div class="ks-meta">
            <span v-if="typeNames.get(item.type_id)">{{ typeNames.get(item.type_id) }}</span>
            <span>版本 {{ item.version }}</span><span v-if="item.scope">{{ item.scope }}</span><span v-if="item.topic">{{ item.topic }}</span>
          </div>
          <div class="ks-actions">
            <button class="ks-button ks-text" type="button" @click="$emit('item', item.id)">
              {{ replay ? '查看当前条目' : '查看详情与历史' }}
            </button>
            <button v-if="allowFeedback" class="ks-button ks-text" type="button" @click="$emit('feedback', item)">
              反馈该条目版本
            </button>
          </div>
        </li>
      </ul>
    </section>

    <KnowledgeEvidence
      v-if="result.facts?.length || result.citations?.length"
      :facts="result.facts" :citations="result.citations" :items="result.items" :conflicts="result.conflicts"
      @source="(id, citation) => $emit('source', id, citation)"
    />

    <section v-if="result.conflict_facts?.length || result.conflict_citations?.length" class="ks-stack ks-conflict">
      <h4>额外冲突证据</h4>
      <p class="ks-muted">用于核对分歧，与原查询选中的条目分开列出。</p>
      <KnowledgeEvidence
        :facts="result.conflict_facts" :citations="result.conflict_citations" :conflicts="result.conflicts"
        facts-title="发生分歧的事实" citations-title="分歧引文"
        @source="(id, citation) => $emit('source', id, citation)"
      />
      <p v-if="result.conflict_incomplete" class="ks-muted">仅显示限额内的冲突证据。</p>
    </section>

    <section v-if="replay && result.terms?.length" class="ks-stack">
      <h4>原查询匹配的术语</h4>
      <ul class="ks-rows">
        <li v-for="term in result.terms" :key="term.id" class="ks-row">
          <strong>{{ term.preferred }}</strong>
          <p v-if="term.definition">{{ term.definition }}</p>
          <p v-if="term.aliases?.length" class="ks-meta">别名 · {{ term.aliases.join('、') }}</p>
          <p v-if="term.scope" class="ks-meta">{{ term.scope }}</p>
        </li>
      </ul>
    </section>

    <section v-if="result.sources?.length" class="ks-stack">
      <h4>{{ result.sources.some(source => source.verified === false) ? '原文检索线索' : '资料修订' }}</h4>
      <ul class="ks-rows">
        <li v-for="source in result.sources" :key="source.id" class="ks-row">
          <strong>{{ source.label }}</strong>
          <p v-if="source.verified === false" class="ks-meta">未经核实的线索</p>
          <blockquote v-if="source.quote" class="ks-quote">{{ source.quote }}</blockquote>
          <div class="ks-meta"><span v-if="source.scope">{{ source.scope }}</span><span>{{ effectivePeriod(source) }}</span></div>
          <button class="ks-button ks-text" type="button" @click="$emit('source', source.id)">
            查看资料快照
          </button>
        </li>
      </ul>
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import KnowledgeEvidence from './KnowledgeEvidence.vue'
import { effectivePeriod, generationLabel, statusLabel } from '../../utils/knowledgeService.js'

const props = defineProps({
  result: { type: Object, required: true },
  typeNames: { type: Map, default: () => new Map() },
  replay: Boolean,
  allowFeedback: Boolean,
})
defineEmits(['item', 'source', 'feedback'])
const tone = computed(() => {
  if (props.result.status === 'supported') return 'success'
  if (props.result.status === 'conflict') return 'danger'
  return 'warning'
})
</script>
