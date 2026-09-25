<template>
  <div>
    <el-select
      :model-value="modelValue"
      @update:model-value="$emit('update:modelValue', $event)"
      :disabled="disabled"
      :loading="loading"
      filterable
      remote
      :remote-method="search"
      placeholder="搜索关联记录..."
      style="width:100%"
      clearable
    >
      <el-option
        v-for="r in options"
        :key="r.id"
        :label="r.label"
        :value="r.id"
      />
    </el-select>
    <div v-if="modelValue && currentLabel" style="font-size:12px;color:var(--text-tertiary);margin-top:4px">
      当前：{{ currentLabel }}
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { Api } from '../api'

const props = defineProps({
  modelValue: { type: [Number, String], default: null },
  targetKey: { type: String, default: '' },
  allTypes: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'open'])

const options = ref([])
const loading = ref(false)
const currentLabel = ref('')

let typeCache = {}

async function ensureType(key) {
  if (typeCache[key]) return typeCache[key]
  const t = props.allTypes.find(x => x.key === key)
  if (t) {
    typeCache[key] = t
    return t
  }
  try {
    const r = await Api.getEntityTypeByKey(key)
    typeCache[key] = r
    return r
  } catch {
    return null
  }
}

async function search(q = '') {
  if (!props.targetKey) {
    options.value = []
    return
  }
  const et = await ensureType(props.targetKey)
  if (!et) {
    options.value = []
    return
  }
  loading.value = true
  try {
    const res = await Api.listRecords(et.id, { keyword: q, page_size: 50 })
    options.value = (res.items || []).map(r => ({
      id: r.id,
      label: r.data?.name || r.data?.title || r.data?.code || `#${r.id}`,
    }))
  } catch {
    options.value = []
  } finally {
    loading.value = false
  }
}

watch(() => props.targetKey, () => search(''))

watch(() => props.modelValue, async (id) => {
  if (id && props.targetKey) {
    try {
      const r = await Api.getRecord(id)
      currentLabel.value = r.data?.name || r.data?.title || r.data?.code || `#${id}`
    } catch {}
  } else {
    currentLabel.value = ''
  }
}, { immediate: true })

search('')
</script>