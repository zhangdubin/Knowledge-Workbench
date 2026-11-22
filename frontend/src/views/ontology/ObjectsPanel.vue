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
            :value="object?.record_id || ''"
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
          >业务类型<select v-model="typeId" :disabled="!!object" @change="data = {}">
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
        <button class="primary" :disabled="!type" @click="run(save)">
          {{ object ? '保存对象修改' : '创建对象' }}</button
        ><button v-if="object" @click="run(() => select(object.record_id))">重新加载对象</button>
      </div>
      <template v-if="object"
        ><h3>版本历史</h3>
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
import RecordFieldInput from '../../components/record/RecordFieldInput.vue'
import { Api } from '../../api'
import { studio } from '../../api/ontology'
import { clone, pretty, versionedData } from '../../utils/ontology'
import { coerceRecordData, validateRecordData } from '../../utils/recordFields'
import { useStudioAction } from './useStudioAction'
const props = defineProps({ space: Object })
const types = props.space.schema.types,
  typeId = ref(types[0]?.id)
const type = computed(() => types.find((t) => t.id === typeId.value))
const typeName = (id) => types.find((t) => t.id === id)?.name
const objects = ref([]),
  object = ref(null),
  data = ref({}),
  models = ref([]),
  history = ref([]),
  more = ref(false),
  moreHistory = ref(false)
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
async function select(id) {
  object.value = id ? await studio.list('objects/' + id) : null
  data.value = clone(object.value?.data || {})
  typeId.value = object.value?.type_id || types[0]?.id
  history.value = []
  if (id) await loadHistory()
}
async function save() {
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
