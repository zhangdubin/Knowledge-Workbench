<template>
  <div class="ks-stack">
    <section v-if="facts.length" class="ks-stack" :aria-label="factsTitle">
      <h4>{{ factsTitle }}</h4>
      <ul class="ks-rows">
        <li v-for="fact in facts" :key="fact.id" class="ks-row">
          <div class="ks-actions">
            <strong>{{ fact.title || titles.get(fact.target_id) || displayValue(fact.value) }}</strong>
            <span v-if="conflictIds.has(fact.id)" class="ks-tag" data-tone="warning">存在分歧</span>
          </div>
          <div class="ks-meta">
            <span v-if="titles.get(fact.object_id)">{{ titles.get(fact.object_id) }}</span>
            <span>{{ effectivePeriod(fact) }}</span>
          </div>
          <div v-if="fact.evidence_ids?.length" class="ks-actions">
            <button
              v-for="(citation, index) in citationsFor(fact)"
              :key="citation.id"
              class="ks-button ks-text"
              type="button"
              @click="open(citation)"
            >
              {{ citation.label || citation.title || `出处 ${index + 1}` }}
            </button>
          </div>
        </li>
      </ul>
    </section>

    <section v-if="citations.length" class="ks-stack">
      <h4>{{ citationsTitle }}</h4>
      <ul class="ks-rows">
        <li v-for="citation in citations" :key="citation.id" class="ks-row">
          <blockquote class="ks-quote">{{ citation.quote }}</blockquote>
          <p class="ks-meta">
            <span>{{ citation.label || citation.title }}</span>
            <span v-if="citation.scope">{{ citation.scope }}</span>
            <span>{{ effectivePeriod(citation) }}</span>
          </p>
          <button v-if="citation.revision_id" class="ks-button ks-text" type="button" @click="open(citation)">
            定位原文<span v-if="citation.label"> · {{ citation.label }}</span>
          </button>
        </li>
      </ul>
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { displayValue, effectivePeriod } from '../../utils/knowledgeService.js'

const props = defineProps({
  facts: { type: Array, default: () => [] },
  citations: { type: Array, default: () => [] },
  items: { type: Array, default: () => [] },
  conflicts: { type: Array, default: () => [] },
  factsTitle: { type: String, default: '已核实事实' },
  citationsTitle: { type: String, default: '证据引文' },
})
const emit = defineEmits(['source'])
const titles = computed(() => new Map(props.items.map(item => [item.id, item.title])))
const conflictIds = computed(() => new Set(props.conflicts.flat()))
const byId = computed(() => new Map(props.citations.map(citation => [citation.id, citation])))
const citationsFor = fact => (fact.evidence_ids || []).map(id => byId.value.get(id)).filter(Boolean)
function open(citation) {
  if (citation.revision_id) emit('source', citation.revision_id, citation)
}
</script>
