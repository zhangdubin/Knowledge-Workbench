<template>
  <el-form :model="localData" label-width="120px" label-position="right">
    <el-form-item
      v-for="f in fields"
      :key="f.key"
      :label="f.name + (f.required ? ' *' : '')"
      :prop="f.key"
    >
      <!-- 文本 -->
        <el-input
          v-if="f.type === 'text'"
          v-model="localData[f.key]"
          :disabled="readonly"
          :placeholder="`请输入${f.name}`"
        />
        <!-- 多行文本 -->
        <el-input
          v-else-if="f.type === 'textarea'"
          v-model="localData[f.key]"
          :disabled="readonly"
          type="textarea"
          :rows="3"
          :placeholder="`请输入${f.name}`"
        />
        <!-- 富文本：简化用 textarea 替代 -->
        <el-input
          v-else-if="f.type === 'richtext'"
          v-model="localData[f.key]"
          :disabled="readonly"
          type="textarea"
          :rows="5"
          :placeholder="`请输入${f.name}（支持 HTML）`"
        />
        <!-- 数字 -->
        <el-input-number
          v-else-if="f.type === 'number'"
          v-model="localData[f.key]"
          :disabled="readonly"
          style="width:100%"
        />
        <!-- 日期 -->
        <el-date-picker
          v-else-if="f.type === 'date'"
          v-model="localData[f.key]"
          :disabled="readonly"
          type="date"
          value-format="YYYY-MM-DD"
          style="width:100%"
        />
        <!-- 日期时间 -->
        <el-date-picker
          v-else-if="f.type === 'datetime'"
          v-model="localData[f.key]"
          :disabled="readonly"
          type="datetime"
          value-format="YYYY-MM-DD HH:mm:ss"
          style="width:100%"
        />
        <!-- 单选 -->
        <el-select
          v-else-if="f.type === 'select'"
          v-model="localData[f.key]"
          :disabled="readonly"
          style="width:100%"
          clearable
        >
          <el-option v-for="c in (f.options?.choices || [])" :key="c" :label="c" :value="c" />
        </el-select>
        <!-- 多选 -->
        <el-select
          v-else-if="f.type === 'multiselect'"
          v-model="localData[f.key]"
          :disabled="readonly"
          multiple
          style="width:100%"
        >
          <el-option v-for="c in (f.options?.choices || [])" :key="c" :label="c" :value="c" />
        </el-select>
        <!-- 布尔 -->
        <el-switch
          v-else-if="f.type === 'boolean'"
          v-model="localData[f.key]"
          :disabled="readonly"
        />
        <!-- 文件 -->
        <FileUploader
          v-else-if="f.type === 'file' || f.type === 'image'"
          :record-id="recordId"
          :field-key="f.key"
          :model-value="localData[f.key] || []"
          :readonly="readonly"
          :image="f.type === 'image'"
          @update:model-value="v => (localData[f.key] = v)"
        />
        <!-- 外键 -->
        <ReferenceSelect
          v-else-if="f.type === 'reference'"
          v-model="localData[f.key]"
          :target-key="f.options?.target"
          :all-types="allTypes"
          :disabled="readonly"
          @open="openTarget(f.options?.target)"
        />
        <span v-else>不支持的字段类型: {{ f.type }}</span>
      </el-form-item>
  </el-form>
</template>

<script setup>
import { computed } from 'vue'
import FileUploader from './FileUploader.vue'
import ReferenceSelect from './ReferenceSelect.vue'

const props = defineProps({
  entityType: { type: Object, required: true },
  modelValue: { type: Object, default: () => ({}) },
  allTypes: { type: Array, default: () => [] },
  readonly: { type: Boolean, default: false },
  recordId: { type: Number, default: null },
})

const emit = defineEmits(['update:modelValue', 'open-target'])

const fields = computed(() => props.entityType.fields || [])

const localData = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

function openTarget(key) {
  emit('open-target', key)
}
</script>