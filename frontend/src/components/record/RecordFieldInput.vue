<template>
  <!--
    字段 → 控件的映射
    「基于数据模型人性化」的落点就在这里：模型里声明了什么类型，
    表单就自动给出对应的控件，用户不用先理解「什么是多选」再去找控件。
  -->
  <el-input
    v-if="field.type === 'text'"
    :model-value="modelValue ?? ''"
    :disabled="disabled"
    :placeholder="`请输入${field.name}`"
    @update:model-value="$emit('update:modelValue', $event)"
  />

  <el-input
    v-else-if="field.type === 'textarea'"
    :model-value="modelValue ?? ''"
    :disabled="disabled"
    type="textarea"
    :rows="3"
    :placeholder="`请输入${field.name}`"
    @update:model-value="$emit('update:modelValue', $event)"
  />

  <el-input
    v-else-if="field.type === 'richtext'"
    :model-value="modelValue ?? ''"
    :disabled="disabled"
    type="textarea"
    :rows="6"
    :placeholder="`请输入${field.name}`"
    @update:model-value="$emit('update:modelValue', $event)"
  />

  <el-input-number
    v-else-if="field.type === 'number'"
    :model-value="modelValue ?? undefined"
    :disabled="disabled"
    controls-position="right"
    style="width: 100%"
    @update:model-value="$emit('update:modelValue', $event)"
  />

  <el-date-picker
    v-else-if="field.type === 'date'"
    :model-value="modelValue ?? ''"
    :disabled="disabled"
    type="date"
    value-format="YYYY-MM-DD"
    style="width: 100%"
    @update:model-value="$emit('update:modelValue', $event)"
  />

  <el-date-picker
    v-else-if="field.type === 'datetime'"
    :model-value="modelValue ?? ''"
    :disabled="disabled"
    type="datetime"
    value-format="YYYY-MM-DD HH:mm:ss"
    style="width: 100%"
    @update:model-value="$emit('update:modelValue', $event)"
  />

  <el-select
    v-else-if="field.type === 'select'"
    :model-value="modelValue ?? ''"
    :disabled="disabled"
    clearable
    filterable
    style="width: 100%"
    :placeholder="`请选择${field.name}`"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <el-option v-for="c in choices" :key="c" :label="c" :value="c" />
  </el-select>

  <el-select
    v-else-if="field.type === 'multiselect'"
    :model-value="modelValue ?? []"
    :disabled="disabled"
    multiple
    collapse-tags
    collapse-tags-tooltip
    style="width: 100%"
    :placeholder="`请选择${field.name}`"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <el-option v-for="c in choices" :key="c" :label="c" :value="c" />
  </el-select>

  <el-switch
    v-else-if="field.type === 'boolean'"
    :model-value="modelValue === true"
    :disabled="disabled"
    active-text="是"
    inactive-text="否"
    inline-prompt
    @update:model-value="$emit('update:modelValue', $event)"
  />

  <FileUploader
    v-else-if="field.type === 'file' || field.type === 'image'"
    :record-id="recordId"
    :field-key="field.key"
    :model-value="modelValue || []"
    :readonly="disabled"
    :image="field.type === 'image'"
    @update:model-value="$emit('update:modelValue', $event)"
  />

  <ReferenceSelect
    v-else-if="field.type === 'reference'"
    :model-value="modelValue ?? null"
    :target-key="field.options?.target"
    :all-types="allTypes"
    :disabled="disabled"
    @update:model-value="$emit('update:modelValue', $event)"
    @open="$emit('open-target', $event)"
  />

  <span v-else class="rfi-unsupported">暂不支持的字段类型：{{ field.type }}</span>
</template>

<script setup>
import { computed } from 'vue'
import FileUploader from '../FileUploader.vue'
import ReferenceSelect from '../ReferenceSelect.vue'
import { fieldChoices } from '../../utils/recordFields.js'

const props = defineProps({
  field: { type: Object, required: true },
  modelValue: { type: [String, Number, Boolean, Array, Object, null], default: null },
  allTypes: { type: Array, default: () => [] },
  recordId: { type: Number, default: null },
  disabled: { type: Boolean, default: false },
})

defineEmits(['update:modelValue', 'open-target'])

const choices = computed(() => fieldChoices(props.field))
</script>

<style scoped>
.rfi-unsupported {
  font-size: var(--text-sm);
  color: var(--danger);
}
</style>
