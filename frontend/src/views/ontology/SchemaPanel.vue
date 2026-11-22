<template>
  <section class="sheet">
    <div class="bar">
      <h2>模式与修订</h2>
      <span class="muted">当前发布版本 {{ space.current_revision_id?.slice(0, 8) || '尚未发布' }}</span>
    </div>
    <fieldset :disabled="busy">
      <div class="row">
        <label
          >修订版本<select :value="selected" @change="choose($event.target.value)">
            <option v-for="r in revisions" :key="r.id" :value="r.id">
              {{ label(r.status) }} · {{ r.id.slice(0, 8) }}
            </option>
          </select></label
        >
        <button v-if="more" @click="run(loadMore)">更多历史</button>
        <button v-if="auth.can('model_manage')" @click="run(newDraft)">从当前版本新建草稿</button>
      </div>
      <p>{{ editable ? '修改只保存在草稿中，校验并确认发布后生效。' : '此修订处于只读状态。' }}</p>
      <fieldset :disabled="!editable">
        <div class="bar">
          <h3>业务类型</h3>
          <div>
            <button v-if="!schema.types.length" @click="schema = sampleSchema()">填入示例</button
            ><button @click="schema.types.push(newType())">添加类型</button>
          </div>
        </div>
        <article v-for="(t, i) in schema.types" :key="t.id">
          <div class="row">
            <label>类型名称<input v-model="t.name" /></label
            ><label>类型标识<input v-model="t.key" /></label>
            <button @click="t.fields.push(newField())">添加属性</button
            ><button @click="schema.types.splice(i, 1)">移除类型</button>
          </div>
          <div v-for="(f, j) in t.fields" :key="f.id || j" class="row">
            <label>属性名称<input v-model="f.name" /></label
            ><label>属性标识<input v-model="f.key" /></label>
            <label
              >属性类型<select v-model="f.type">
                <option v-for="k in fieldTypes" :key="k" :value="k">{{ fieldTypeLabel(k) }}</option>
              </select></label
            >
            <label>必填<input v-model="f.required" type="checkbox" /></label>
            <label v-if="['select', 'multiselect'].includes(f.type)"
              >选项（逗号分隔）<input
                :value="f.options.choices?.join(',')"
                @change="
                  f.options.choices = $event.target.value
                    .split(',')
                    .map((x) => x.trim())
                    .filter(Boolean)
                "
            /></label>
            <label v-if="f.type === 'reference'">目标模型标识<input v-model="f.options.target" /></label>
            <button :disabled="!j" @click="t.fields.splice(j - 1, 0, ...t.fields.splice(j, 1))">
              上移属性</button
            ><button @click="t.fields.splice(j, 1)">移除属性</button>
          </div>
        </article>
        <div class="bar">
          <h3>业务关系</h3>
          <button :disabled="!schema.types.length" @click="addRelation">添加关系</button>
        </div>
        <article v-for="(r, i) in schema.relations" :key="r.id || i" class="row">
          <label>关系名称<input v-model="r.name" /></label
          ><label>关系标识<input v-model="r.key" /></label>
          <label v-for="end in ['source', 'target']" :key="end"
            >{{ end === 'source' ? '起点类型' : '终点类型'
            }}<select v-model="r[end]">
              <option v-for="t in schema.types" :key="t.id" :value="t.id">{{ t.name || t.key }}</option>
            </select></label
          >
          <label
            >关系基数<select v-model="r.cardinality">
              <option v-for="c in cardinalities" :key="c" :value="c">{{ cardinalityLabels[c] }}</option>
            </select></label
          >
          <button @click="schema.relations.splice(i, 1)">移除关系</button>
        </article>
        <details>
          <summary>迁移规则与稳定标识</summary>
          <pre>{{ pretty(schema) }}</pre>
          <label class="wide"
            >迁移规则 JSON（defaults / field_map 使用属性 ID）<textarea v-model="migration" />
          </label>
        </details>
        <div class="row">
          <button @click="run(save)">保存草稿</button
          ><button @click="run(validate)">保存并校验影响</button>
          <button v-if="impact && !impact.blockers.length && !plan" @click="run(makePlan)">
            预览发布计划
          </button>
        </div>
      </fieldset>
      <p v-if="notice" role="status">{{ notice }}</p>
      <article v-if="impact">
        <h3>发布影响</h3>
        <p>{{ impactSummary(impact) }}</p>
        <ul>
          <li v-for="change in impact.changes" :key="change">{{ change }}</li>
        </ul>
        <p v-for="msg in impact.blockers" :key="msg" role="alert">{{ msg }}</p>
      </article>
      <article v-if="plan">
        <h3>确认发布此修订</h3>
        <p>计划 {{ plan.id }} · 到期 {{ plan.expires_at }}</p>
        <button class="primary" @click="run(publish)">确认发布</button>
      </article>
    </fieldset>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>
<script setup>
import { fieldTypeLabel } from '../../utils/format'
const cardinalityLabels = { 'one-to-one': '一对一', 'one-to-many': '一对多', 'many-to-one': '多对一', 'many-to-many': '多对多' }
import { ref, computed, watch } from 'vue'
import { studio } from '../../api/ontology'
import { useAuthStore } from '../../stores/auth'
import {
  initialRevision,
  draftSchema,
  impactSummary,
  label,
  pretty,
  newType,
  newField,
  sampleSchema,
  validateSchema,
  fieldTypes,
  cardinalities,
} from '../../utils/ontology'
import { useStudioAction } from './useStudioAction'
const auth = useAuthStore()
const props = defineProps({ space: Object }),
  emit = defineEmits(['refresh'])
const revisions = ref([...props.space.revisions]),
  more = ref(revisions.value.length === 25)
const selected = ref(''),
  schema = ref({ types: [], relations: [] }),
  migration = ref('{}'),
  impact = ref(null),
  plan = ref(null),
  notice = ref('')
const { busy, error, run } = useStudioAction()
const revision = computed(() => revisions.value.find((r) => r.id === selected.value))
const editable = computed(
  () => auth.can('model_manage') && ['draft', 'validated'].includes(revision.value?.status),
)
const path = computed(() => props.space.id + '/revisions/' + selected.value)
function choose(id) {
  selected.value = id
  schema.value = draftSchema(revision.value)
  migration.value = '{}'
  notice.value = ''
  error.value = ''
}
const firstRevision = initialRevision(props.space)
let historyOffset = revisions.value.length
if (!revisions.value.some(r => r.id === firstRevision.id)) revisions.value.unshift(firstRevision)
choose(firstRevision.id)
watch(
  [schema, migration],
  () => {
    impact.value = null
    plan.value = null
    notice.value = ''
  },
  { deep: true, flush: 'sync' },
)
function addRelation() {
  const id = schema.value.types[0].id
  schema.value.relations.push({ key: '', name: '', source: id, target: id, cardinality: 'many-to-many' })
}
async function loadMore() {
  const page = await studio.list(props.space.id, { offset: historyOffset })
  historyOffset += page.revisions.length
  revisions.value.push(...page.revisions.filter(r => !revisions.value.some(existing => existing.id === r.id)))
  more.value = page.revisions.length === 25
}
async function newDraft() {
  const r = await studio.post(props.space.id + '/revisions', { schema: props.space.schema })
  historyOffset++
  revisions.value.unshift(r)
  choose(r.id)
}
async function save() {
  validateSchema(schema.value)
  const r = await studio.put(path.value, { schema: schema.value })
  Object.assign(revision.value, r)
  schema.value = draftSchema(r)
  notice.value = '已保存草稿'
}
async function validate() {
  await save()
  impact.value = await studio.post(path.value + '/validate', { migration: JSON.parse(migration.value) })
  notice.value = '校验完成'
}
async function makePlan() {
  const row = await studio.post(path.value + '/plan', { migration: JSON.parse(migration.value) })
  plan.value = await studio.list('changes/' + row.id)
  impact.value = plan.value.preconditions
}
async function publish() {
  await studio.confirm(plan.value.id)
  emit('refresh')
}
</script>
