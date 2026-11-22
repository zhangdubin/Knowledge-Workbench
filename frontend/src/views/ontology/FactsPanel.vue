<template>
  <section class="sheet">
    <div class="bar">
      <h2>事实与证据</h2>
      <button :disabled="busy" @click="run(list)">刷新审核列表</button>
    </div>
    <fieldset :disabled="busy">
      <form @submit.prevent="run(query)">
        <label>原文关键词<input v-model="filters.text" /></label
        ><label>主体记录 ID<input type="number" min="1" v-model.number="filters.object_id" /></label>
        <label
          >类型<select v-model="filters.type_id">
            <option value="">全部</option>
            <option v-for="t in types" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select></label
        >
        <label
          >属性或关系<select v-model="filters.predicate_id">
            <option value="">全部</option>
            <option v-for="p in predicates" :key="p.id" :value="p.id">{{ p.title }}</option>
          </select></label
        >
        <label
          >状态<select v-model="filters.status">
            <option v-for="s in statuses" :key="s" :value="s">{{ label(s) }}</option>
          </select></label
        >
        <label>有效日期<input type="date" v-model="filters.as_of" /></label
        ><label>来源文档 ID<input type="number" min="1" v-model.number="filters.document_id" /></label>
        <label
          >属性值（精确 JSON，可选）<input v-model="exactValue" placeholder='如 9 或 "文本"' /></label
        ><label
          >关系深度<select v-model.number="filters.depth">
            <option v-for="i in [0, 1, 2]" :key="i">{{ i }}</option>
          </select></label
        ><button class="primary">查询证据</button>
      </form>
      <article v-if="result" role="status">
        <h3>{{ label(result.status) }}</h3>
        <p>{{ result.facts.length }} 条返回声明 · {{ result.evidence.length }} 条引用</p>
        <p v-if="result.budget_exhausted">达到查询预算，结果可能不完整。</p>
        <p v-for="pair in result.conflicts" :key="String(pair)">冲突声明 {{ pair.join(' / ') }}</p>
        <details v-if="result.objects.length">
          <summary>匹配对象（{{ result.objects.length }}）</summary>
          <pre>{{ pretty(result.objects) }}</pre>
        </details>
        <details v-if="result.paths.length">
          <summary>关系路径</summary>
          <pre>{{ pretty(result.paths) }}</pre>
        </details>
      </article>
      <h3>{{ result ? '查询结果' : '最近的待核验与历史声明（最多 50 条）' }}</h3>
      <p v-if="!facts.length">没有符合条件的声明。</p>
      <article v-for="f in facts" :key="f.id">
        <div class="bar">
          <h3>
            对象 #{{ f.object_id }} ·
            {{ predicates.find((p) => p.id === f.predicate_id)?.title || f.predicate_id }}
          </h3>
          <b>{{ label(f.status) }}</b>
        </div>
        <p>{{ f.target_id ? '目标对象 #' + f.target_id : pretty(f.value) }}</p>
        <p class="muted">
          声明 {{ f.id }} · v{{ f.version }} · {{ f.effective_from || '起始未知' }} 至
          {{ f.effective_to || '截止未知' }} · {{ f.extractor
          }}<span v-if="f.confidence != null"> · 抽取器评分 {{ f.confidence }}</span>
        </p>
        <EvidenceCard v-for="e in f.evidence" :key="e.id" :evidence="e" />
        <div class="row">
          <template v-if="f.status !== 'superseded'"
            ><button
              v-for="[action, title] in decisions"
              :key="action"
              @click="run(() => review(f, action))"
            >
              {{ title }}
            </button></template
          >
          <button v-if="f.status !== 'superseded'" @click="run(() => beginReplacement(f))">选择替代声明</button>
          <button v-if="f.superseded_by" @click="run(() => showReplacement(f))">查看替代声明 {{f.superseded_by}}</button>
          <button @click="run(() => history(f))">查看审核历史</button>
        </div>
        <div v-if="replacing === f.id" class="row">
          <template v-if="options.length"><label>已接受的替代声明<select v-model="replacementId">
            <option value="">请选择</option><option v-for="r in options" :key="r.id" :value="r.id">{{r.id}} · {{r.target_id ? '目标对象 #'+r.target_id : pretty(r.value)}}</option>
          </select></label><button :disabled="!replacementId" @click="run(() => review(f,'supersede'))">确认替代</button></template>
          <p v-else>没有可选的同主体、同谓词已接受声明。</p>
          <button @click="replacing=null">取消替代</button>
        </div>
        <section v-if="replacementDetails[f.id]"><h4>替代声明 {{replacementDetails[f.id].id}}</h4>
          <p>{{label(replacementDetails[f.id].status)}} · {{replacementDetails[f.id].target_id ? '目标对象 #'+replacementDetails[f.id].target_id : pretty(replacementDetails[f.id].value)}}</p>
          <EvidenceCard v-for="e in replacementDetails[f.id].evidence" :key="e.id" :evidence="e"/>
        </section>
        <template v-if="histories[f.id]"
          ><p>建立候选 · {{ f.recorded_at }}</p>
          <p v-for="h in histories[f.id]" :key="h.version">
            v{{ h.version }} · {{ label(h.status) }} · {{ h.actor }} · {{ h.recorded_at }}
          </p>
          <button v-if="moreHistory[f.id]" @click="run(() => history(f, true))">
            更多审核历史
          </button></template
        >
      </article>
    </fieldset>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>
<script setup>
import { ref, reactive, onMounted } from 'vue'
import { studio } from '../../api/ontology'
import { label, pretty, reviewBody, eligibleReplacements } from '../../utils/ontology'
import { useStudioAction } from './useStudioAction'
import EvidenceCard from './EvidenceCard.vue'
const props = defineProps({ space: Object })
const types = props.space.schema.types
const predicates = [
  ...types.flatMap((t) => t.fields.map((f) => ({ ...f, title: t.name + ' · ' + f.name }))),
  ...props.space.schema.relations.map((r) => ({ ...r, title: r.name })),
]
const exactValue = ref('')
const filters = reactive({
  text: '',
  status: 'accepted',
  object_id: '',
  type_id: '',
  predicate_id: '',
  as_of: '',
  document_id: '',
  depth: 0,
})
const statuses = ['accepted', 'candidate', 'rejected', 'disputed', 'superseded']
const decisions = [
  ['accept', '接受声明'],
  ['reject', '拒绝声明'],
  ['dispute', '标记争议'],
]
const result = ref(null),
  facts = ref([]),
  histories = ref({}),
  moreHistory = ref({})
const replacing = ref(null)
const replacementId = ref('')
const options = ref([])
const replacementDetails = ref({})
const { busy, error, run } = useStudioAction()
async function list() {
  const rows = await studio.list(props.space.id + '/claims')
  facts.value = rows
  result.value = null
  histories.value = {}
  replacing.value = null
  replacementDetails.value = {}
}
async function query() {
  const payload = Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== ''))
  if (exactValue.value.trim()) payload.value = JSON.parse(exactValue.value)
  result.value = await studio.post(props.space.id + '/query', payload)
  facts.value = result.value.facts
  histories.value = {}
  replacing.value = null
  replacementDetails.value = {}
}
async function history(f, append = false) {
  const previous = append ? histories.value[f.id] : []
  const rows = await studio.list('claims/' + f.id + '/history', { offset: previous.length, limit: 50 })
  histories.value[f.id] = [...previous, ...rows]
  moreHistory.value[f.id] = rows.length === 50
}
async function beginReplacement(f) {
  replacing.value = null
  replacementId.value = ''
  const matches = await studio.post(props.space.id + '/query', {
    object_id:f.object_id, predicate_id:f.predicate_id, status:'accepted', limit:50,
  })
  options.value = eligibleReplacements(f, matches.facts)
  replacing.value = f.id
}
async function showReplacement(f) {
  delete replacementDetails.value[f.id]
  replacementDetails.value[f.id] = await studio.list('claims/' + f.superseded_by)
}
async function review(f, action) {
  await studio.post('claims/' + f.id + '/review', reviewBody(action, f, replacementId.value))
  if (result.value) await query()
  else await list()
}
onMounted(() => run(list))
</script>
