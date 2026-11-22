<template>
  <section class="sheet">
    <div class="bar">
      <h2>资料加工</h2>
      <router-link to="/library?action=upload">导入资料</router-link>
    </div>
    <fieldset :disabled="busy">
      <div class="row">
        <label
          >来源文档<select :value="doc?.id || ''" @change="run(() => chooseDoc($event.target.value))">
            <option value="">请选择资料</option>
            <option v-for="d in documents" :key="d.id" :value="d.id">{{ d.title }} · #{{ d.id }}</option>
          </select></label
        >
        <button v-if="moreDocs" @click="run(loadDocs)">更多资料</button>
        <button
          :disabled="!doc || ['unavailable', 'denied'].includes(ai)"
          @click="run(() => submit('ai'))"
        >
          AI 抽取</button
        ><span v-if="ai === 'unavailable'" class="muted">AI 未配置，仍可人工录入。</span
        ><span v-if="ai === 'denied'" class="muted">当前账户没有 AI 权限。</span>
      </div>
      <template v-if="doc">
        <details>
          <summary>查看抽取原文</summary>
          <pre>{{ doc.extracted_text || doc.extract_error || '无可用原文' }}</pre>
        </details>
        <h3>手动候选</h3>
        <div class="row">
          <label
            >主体类型<select
              v-model="typeId"
              @change="resetSubject"
            >
              <option v-for="t in types" :key="t.id" :value="t.id">{{ t.name }}</option>
            </select></label
          >
          <label
            >主体对象<select v-model="subject">
              <option value="">提议新对象</option>
              <option
                v-for="o in objects.filter((o) => o.type_id === typeId)"
                :key="o.record_id"
                :value="o.record_id"
              >
                #{{ o.record_id }} · {{ Object.values(o.data)[0] }}
              </option>
            </select></label
          >
          <button v-if="moreObjects" @click="run(loadObjects)">更多对象</button>
        </div>
        <template v-if="!subject"
          ><label class="wide"
            >新对象属性 JSON<textarea v-model="objectData" placeholder='{"name":"对象名称"}' />
          </label>
          <label>来源唯一标识（可选）<input v-model="sourceId" /></label
        ></template>
        <div class="row">
          <label
            >声明属性或关系<select v-model="predicate">
              <option value="">选择谓词</option>
              <option v-for="p in predicates" :key="p.id" :value="p.id">
                {{ p.name }} · {{ p.key }}
              </option>
            </select></label
          >
          <label v-if="relation"
            >目标对象<select v-model="target">
              <option value="">选择目标</option>
              <option
                v-for="o in objects.filter((o) => o.type_id === relation.target)"
                :key="o.record_id"
                :value="o.record_id"
              >
                #{{ o.record_id }} · {{ Object.values(o.data)[0] }}
              </option>
            </select></label
          >
          <label v-else>声明值<input v-model="value" placeholder="按属性类型填写" /></label>
        </div>
        <div class="row">
          <label>原文引句<input v-model="quote" /></label
          ><label>第几次出现<input v-model.number="occurrence" type="number" min="1" /></label>
        </div>
        <div class="row">
          <label>起始日期（可选）<input v-model="from" type="date" /></label
          ><label>截止日期（可选）<input v-model="to" type="date" /></label>
        </div>
        <button class="primary" @click="run(() => submit('manual'))">生成手动候选</button>
      </template>
      <h3>加工记录</h3>
      <label
        >最近作业（最多 50 项）<select
          :value="job?.id || ''"
          @change="run(() => openJob($event.target.value))"
        >
          <option value="">请选择</option>
          <option v-for="j in jobs" :key="j.id" :value="j.id">
            {{ label(j.status) }} · 文档 #{{ j.document_id }} · {{ j.created_at }}
          </option>
        </select></label
      >
      <article v-if="job">
        <h3>{{ label(job.status) }}</h3>
        <p>文档 #{{ job.document_id }} · 抽取器 {{ job.extractor }}</p>
        <p v-if="job.error" role="alert">{{ job.error }}</p>
        <details open>
          <summary>候选对象、关系和声明</summary>
          <pre>{{ pretty(job.candidates) }}</pre>
        </details>
        <pre v-if="job.result && Object.keys(job.result).length">{{ pretty(job.result) }}</pre>
        <button v-if="job.status === 'ready' && !plan" @click="run(preview)">预览加工计划</button>
      </article>
      <article v-if="plan">
        <h3>确认写入候选</h3>
        <p>计划 {{ plan.id }} · 确认后仍需逐条核验声明。</p>
        <pre>{{ pretty(plan.payload.candidates) }}</pre>
        <button class="primary" @click="run(confirm)">确认写入候选</button>
      </article>
    </fieldset>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>
<script setup>
import { ref, computed, onMounted } from 'vue'
import { Api } from '../../api'
import { useAuthStore } from '../../stores/auth'
import { studio } from '../../api/ontology'
import { label, pretty, quoteRange } from '../../utils/ontology'
import { useStudioAction } from './useStudioAction'
const auth = useAuthStore()
const props = defineProps({ space: Object })
const types = props.space.schema.types,
  typeId = ref(types[0]?.id),
  subject = ref(''),
  target = ref(''),
  predicate = ref('')
const type = computed(() => types.find((t) => t.id === typeId.value)),
  relations = computed(() => props.space.schema.relations.filter((r) => r.source === typeId.value))
const predicates = computed(() => [...(type.value?.fields || []), ...relations.value]),
  relation = computed(() => relations.value.find((r) => r.id === predicate.value))
const doc = ref(null),
  documents = ref([]),
  docPage = ref(0),
  moreDocs = ref(false),
  objects = ref([]),
  moreObjects = ref(false),
  ai = ref('unknown')
const job = ref(null),
  jobs = ref([]),
  plan = ref(null),
  quote = ref(''),
  occurrence = ref(1),
  objectData = ref('{}'),
  sourceId = ref(''),
  value = ref(''),
  from = ref(''),
  to = ref('')
const { busy, error, run } = useStudioAction()
function resetSubject() {
  subject.value = ''
  predicate.value = ''
  target.value = ''
}
async function loadDocs() {
  const page = await Api.listDocuments({ page: docPage.value + 1, page_size: 100 })
  documents.value.push(...page.items)
  docPage.value++
  moreDocs.value = documents.value.length < page.total
}
async function loadObjects() {
  const rows = await studio.list(props.space.id + '/objects', {
    limit: 100,
    offset: objects.value.length,
  })
  objects.value.push(...rows)
  moreObjects.value = rows.length === 100
}
async function chooseDoc(id) {
  doc.value = id ? await Api.getDocument(Number(id), true) : null
  quote.value = ''
  occurrence.value = 1
  plan.value = null
  job.value = null
}
function candidates() {
  if (!predicate.value) throw Error('请选择声明属性或关系')
  const evidence = [
    {
      document_id: doc.value.id,
      ...quoteRange(doc.value.extracted_text || '', quote.value, occurrence.value),
    },
  ]
  const claim = {
    predicate_id: predicate.value,
    evidence,
    ...(subject.value ? { object_id: subject.value } : { object_ref: 'subject' }),
  }
  if (from.value) claim.effective_from = from.value
  if (to.value) claim.effective_to = to.value
  const rows = { objects: [], relationships: [], claims: [] }
  if (!subject.value)
    rows.objects.push({
      ref: 'subject',
      type_id: typeId.value,
      data: JSON.parse(objectData.value),
      ...(sourceId.value ? { source_id: sourceId.value } : {}),
    })
  if (relation.value) {
    if (!target.value) throw Error('请选择目标对象')
    rows.relationships.push({ ...claim, target_id: target.value })
  } else {
    const field = type.value.fields.find((f) => f.id === predicate.value)
    const typed = ['number', 'reference', 'boolean', 'multiselect', 'file', 'image'].includes(field.type)
      ? JSON.parse(value.value)
      : value.value
    rows.claims.push({ ...claim, value: typed })
  }
  return rows
}
async function submit(mode) {
  const body = { document_id: doc.value.id, mode }
  if (mode === 'manual') body.candidates = candidates()
  plan.value = null
  job.value = await studio.post(props.space.id + '/ingestions', body)
  jobs.value = await studio.list(props.space.id + '/ingestions')
}
async function openJob(id) {
  plan.value = null
  job.value = id ? await studio.list('ingestions/' + id) : null
}
async function preview() {
  const row = await studio.post('ingestions/' + job.value.id + '/plan')
  plan.value = await studio.list('changes/' + row.id)
}
async function confirm() {
  await studio.confirm(plan.value.id)
  await openJob(job.value.id)
  jobs.value = await studio.list(props.space.id + '/ingestions')
}
onMounted(() =>
  run(async () => {
    await Promise.all([
      loadDocs(),
      loadObjects(),
      studio.list(props.space.id + '/ingestions').then((rows) => (jobs.value = rows)),
    ])
    if (!auth.can('ai')) {
      ai.value = 'denied'
      return
    }
    try {
      const config = await Api.getAIConfig()
      ai.value = config.enabled && config.base_url && config.api_key ? 'ready' : 'unavailable'
    } catch {
      ai.value = 'unknown'
    }
  }),
)
</script>
