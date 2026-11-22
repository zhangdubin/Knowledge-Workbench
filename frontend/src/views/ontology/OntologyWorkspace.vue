<template>
  <main class="studio page">
    <PageTitle title="本体工作室" subtitle="管理业务概念、对象与有出处的事实" icon-key="Connection" />
    <section class="sheet">
      <div class="bar">
        <h2>本体空间</h2>
        <button v-if="auth.can('model_manage')" @click="creating = !creating">
          {{ creating ? '收起' : '新建或接管' }}
        </button>
      </div>
      <fieldset :disabled="busy">
        <form v-if="creating" @submit.prevent="run(create)">
          <label>空间名称<input v-model.trim="name" required /></label>
          <label>空间标识<input v-model.trim="key" required /></label>
          <button class="primary">创建空白本体</button>
        </form>
        <form v-if="creating" @submit.prevent="run(adopt)">
          <label
            >已有业务模型<select v-model="model" required>
              <option value="">选择模型</option>
              <option v-for="m in models" :key="m.id" :value="m.id">{{ m.name }} · {{ m.key }}</option>
            </select></label
          >
          <button>创建接管草稿</button>
        </form>
        <label v-if="spaces.length"
          >选择空间<select :value="space?.id" @change="run(() => open($event.target.value))">
            <option v-for="s in spaces" :key="s.id" :value="s.id">{{ s.name }} · {{ s.key }}</option>
          </select></label
        >
        <p v-else-if="!busy">还没有可见的本体空间。</p>
        <button v-if="more" @click="run(() => list(true))">加载更多空间</button>
      </fieldset>
      <p v-if="error" role="alert">{{ error }}</p>
    </section>
    <template v-if="space">
      <nav aria-label="本体工作区" class="studio-tabs">
        <button
          v-for="(title, i) in tabs"
          :key="title"
          :aria-current="tab === i ? 'page' : undefined"
          :disabled="i > 0 && !space.current_revision_id"
          @click="tab = i"
        >
          {{ title }}
        </button>
      </nav>
      <component
        :is="panels[tab]"
        :key="space.id + '-' + tab + '-' + generation"
        :space="space"
        @refresh="run(() => open(space.id))"
      />
    </template>
  </main>
</template>
<script setup>
import { ref, onMounted, watch } from 'vue'
import PageTitle from '../../components/PageTitle.vue'
import { Api } from '../../api'
import { useAuthStore } from '../../stores/auth'
import { studio } from '../../api/ontology'
import { useStudioAction } from './useStudioAction'
import SchemaPanel from './SchemaPanel.vue'
import ObjectsPanel from './ObjectsPanel.vue'
import IngestionPanel from './IngestionPanel.vue'
import FactsPanel from './FactsPanel.vue'
const auth = useAuthStore()
const panels = [SchemaPanel, ObjectsPanel, IngestionPanel, FactsPanel]
const tabs = ['模式与修订', '对象与历史', '资料加工', '事实与证据']
const tab = ref(0),
  generation = ref(0),
  spaces = ref([]),
  space = ref(null),
  more = ref(false)
const creating = ref(false),
  name = ref(''),
  key = ref(''),
  models = ref([]),
  model = ref('')
const { busy, error, run } = useStudioAction()
async function list(append = false) {
  const rows = await studio.list('', { offset: append ? spaces.value.length : 0, limit: 50 })
  spaces.value = append ? [...spaces.value, ...rows] : rows
  more.value = rows.length === 50
}
async function open(id) {
  space.value = await studio.list(id)
  if (!space.value.current_revision_id) tab.value = 0
  generation.value++
}
async function created(row) {
  if (!spaces.value.some((s) => s.id === row.id)) spaces.value.push(row)
  creating.value = false
  key.value = name.value = ''
  tab.value = 0
  await open(row.id)
}
async function create() {
  await created(await studio.post('', { key: key.value, name: name.value }))
}
async function adopt() {
  await created(await studio.post('from-model/' + model.value))
}
watch(creating, async (value) => {
  if (value)
    try {
      models.value = (await Api.listEntityTypes()).filter((t) => t.key !== 'note')
    } catch {
      models.value = []
    }
})
onMounted(() =>
  run(async () => {
    await list()
    if (spaces.value.length) await open(spaces.value[0].id)
    else creating.value = auth.can('model_manage')
  }),
)
</script>
<style src="./studio.css"></style>
