<template>
  <section class="sheet">
    <div class="bar">
      <h2>对象与历史</h2>
      <button @click="run(() => load())">刷新对象</button>
    </div>
    <fieldset :disabled="busy">
      <div class="row">
        <label
          >选择对象<select
            :value="selectedId"
            @change="run(() => select($event.target.value))"
          >
            <option value="">新建对象</option>
            <option v-for="o in objects" :key="o.record_id" :value="o.record_id">
              #{{ o.record_id }} · {{ typeName(o.type_id) }} · {{ Object.values(o.data)[0] }}
            </option>
          </select></label
        ><button v-if="more" @click="run(() => load(true))">加载更多对象</button>
      </div>
      <div class="row">
        <label
          >业务类型<select v-model="typeId" :disabled="!!selectedId" @change="data = {}">
            <option v-for="t in types" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select></label
        >
        <router-link
          v-if="legacyId && object"
          :to="{ path: '/records/' + legacyId, query: { id: object.record_id } }"
          >打开记录 #{{ object.record_id }}</router-link
        >
      </div>
      <p v-if="object" class="muted">
        读取版本 v{{ object.version }} · 本体修订 {{ object.revision_id }}
      </p>
      <label v-for="f in type?.fields" :key="f.id" class="wide"
        >{{ f.name }}{{ f.required ? ' *' : '' }}
        <RecordFieldInput
          v-model="data[f.key]"
          :field="f"
          :all-types="models"
          :record-id="object?.record_id"
        />
      </label>
      <div class="row">
        <button class="primary" :disabled="!canSave" @click="run(save)">
          {{ selectedId ? '保存对象修改' : '创建对象' }}</button
        ><button v-if="selectedId" @click="run(() => select(selectedId))">重新加载对象</button>
      </div>
      <template v-if="object"
        >
        <h3>对象关系</h3>
        <p v-if="!context.relations.length">暂无可见关系。</p>
        <p v-for="link in context.relations" :key="link.link_id">
          {{ link.direction === 'out' ? '指向' : '来自' }} · {{ link.relation }} · {{ link.other_label }}
        </p>
        <h3>事实与证据</h3>
        <p v-if="!context.facts.length">暂无可见声明或证据。</p>
        <article v-for="fact in context.facts" :key="fact.id">
          <h4>{{ predicateName(fact.predicate_id) }} · {{ label(fact.status) }}</h4>
          <p>{{ fact.target_id ? '目标对象 #' + fact.target_id : pretty(fact.value) }}</p>
          <EvidenceCard v-for="citation in fact.evidence" :key="citation.id" :evidence="citation" />
        </article>
        <p v-if="context.facts.length === 50">显示最近 50 条可见声明。</p>
        <h3>时间线 · 版本历史</h3>
        <details v-for="h in history" :key="h.version">
          <summary>v{{ h.version }} · {{ h.created_at }} · {{ h.revision_id }}</summary>
          <pre>{{ pretty(h.data) }}</pre>
        </details>
        <button v-if="moreHistory" @click="run(() => loadHistory(true))">加载更多历史</button></template
      >
    </fieldset>
    <p role="alert" v-if="error">{{ error }}</p>
  </section>
</template>
<script setup>
import { ref, computed, onMounted } from 'vue'
import EvidenceCard from './EvidenceCard.vue'
import RecordFieldInput from '../../components/record/RecordFieldInput.vue'
import { Api } from '../../api'
import { studio } from '../../api/ontology'
import { pretty, versionedData, label, loadObjectContext } from '../../utils/ontology'
import { coerceRecordData, validateRecordData } from '../../utils/recordFields'
import { useStudioAction } from './useStudioAction'
import { useObjectSelection } from './useObjectSelection'
const props = defineProps({ space: Object })
const types = props.space.schema.types
const { selectedId, object, typeId, data, history, moreHistory, context, canSave, select } =
  useObjectSelection(types[0]?.id, async (id) => {
    const row = await studio.list('objects/' + id)
    const [history, context] = await Promise.all([
      studio.list('objects/' + id + '/history', { offset: 0, limit: 50 }),
      loadObjectContext(props.space.id, row.record_id, Api.relationsForRecord, studio.list),
    ])
    return { row, history, context }
  })
const type = computed(() => types.find((t) => t.id === typeId.value))
const typeName = (id) => types.find((t) => t.id === id)?.name
const objects = ref([]), models = ref([]), more = ref(false)
const predicateName = (id) => [...(type.value?.fields || []), ...props.space.schema.relations]
  .find(p => p.id === id)?.name || id
const legacyId = computed(() => models.value.find((m) => m.key === type.value?.key)?.id)
const { busy, error, run } = useStudioAction()
async function load(append = false) {
  const rows = await studio.list(props.space.id + '/objects', {
    offset: append ? objects.value.length : 0,
    limit: 100,
  })
  objects.value = append ? [...objects.value, ...rows] : rows
  more.value = rows.length === 100
}
async function loadHistory(append = false) {
  const rows = await studio.list('objects/' + object.value.record_id + '/history', {
    offset: append ? history.value.length : 0,
    limit: 50,
  })
  history.value = append ? [...history.value, ...rows] : rows
  moreHistory.value = rows.length === 50
}
async function save() {
  if (!canSave.value) return
  const check = validateRecordData(type.value.fields, data.value)
  if (!check.ok) throw Error(check.messages[0])
  const payload = coerceRecordData(type.value.fields, data.value)
  const row = object.value
    ? await studio.put('objects/' + object.value.record_id, versionedData(payload, object.value.version))
    : await studio.post(props.space.id + '/objects', { type_id: typeId.value, data: payload })
  await load()
  if (!objects.value.some((o) => o.record_id === row.record_id)) objects.value.push(row)
  await select(row.record_id)
}
onMounted(() =>
  run(async () => {
    await load()
    models.value = await Api.listEntityTypes()
  }),
)
</script>
