<template>
  <!--
    记录表单抽屉：表单由「模型字段定义」自动生成。
    为什么用抽屉不用弹窗：字段一多（十个以上），弹窗要滚动、底部按钮还会被顶出屏幕；
    抽屉能占满整列高度，字段区自己滚，保存按钮永远在右下角。
  -->
  <el-drawer
    :model-value="modelValue"
    :size="size"
    direction="rtl"
    class="rfd"
    @update:model-value="$emit('update:modelValue', $event)"
    @open="onOpen"
  >
    <template #header>
      <div class="rfd-head">
        <div class="rfd-title">{{ record ? '编辑记录' : '新建记录' }}</div>
        <div class="rfd-sub">
          {{ entityType?.name || '' }} · 表单按这个模型的字段定义自动生成
        </div>
      </div>
    </template>

    <el-form
      v-if="entityType"
      :model="data"
      label-width="112px"
      label-position="right"
      class="rfd-form"
    >
      <el-form-item
        v-for="f in fields"
        :key="f.key"
        :label="f.name + (f.required ? ' *' : '')"
        :prop="f.key"
        :error="errors[f.key]"
      >
        <RecordFieldInput
          v-model="data[f.key]"
          :field="f"
          :all-types="allTypes"
          :record-id="record?.id || null"
          @open-target="$emit('open-target', $event)"
        />
        <div v-if="f.type === 'file' || f.type === 'image'" class="rfd-tip">
          附件与记录绑定，先保存记录再上传
        </div>
        <div v-else-if="f.type === 'reference'" class="rfd-tip">
          关联到另一个模型的记录，列表里显示的是它的名称
        </div>
      </el-form-item>

      <el-form-item v-if="!fields.length">
        <div class="rfd-tip">这个模型还没有字段，先去「数据模型」里加几个字段再来录数据。</div>
      </el-form-item>
    </el-form>

    <div v-else class="rfd-empty">正在加载模型定义…</div>

    <template #footer>
      <div class="rfd-foot">
        <span v-if="errorText" class="rfd-error">{{ errorText }}</span>
        <el-button @click="close">取消</el-button>
        <el-button type="primary" :loading="saving" :disabled="!entityType" @click="save">
          保存
        </el-button>
      </div>
    </template>
  </el-drawer>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Api } from '../../api'
import RecordFieldInput from './RecordFieldInput.vue'
import { coerceRecordData, validateRecordData } from '../../utils/recordFields.js'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  // 完整的模型定义（带 fields）
  entityType: { type: Object, default: null },
  // 正在编辑的记录；为空表示新建
  record: { type: Object, default: null },
  allTypes: { type: Array, default: () => [] },
  saving: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'saved', 'open-target'])

const data = reactive({})
const errors = ref({})
const errorText = ref('')
const internalSaving = ref(false)

const fields = computed(() => props.entityType?.fields || [])
const size = computed(() => 'min(520px, 96vw)')
const saving = computed(() => props.saving || internalSaving.value)

/** 新建时的初始值：布尔给 false，其余留空 */
function defaults() {
  const out = {}
  for (const f of fields.value) {
    const d = f.options?.default
    if (d !== undefined && d !== null && d !== '') out[f.key] = d
    else if (f.type === 'boolean') out[f.key] = false
    else if (f.type === 'multiselect') out[f.key] = []
    else out[f.key] = ''
  }
  return out
}

function onOpen() {
  const fresh = props.record ? { ...(props.record.data || {}) } : defaults()
  for (const k of Object.keys(data)) delete data[k]
  Object.assign(data, fresh)
  errors.value = {}
  errorText.value = ''
}

watch(() => props.modelValue, (v) => {
  if (v) onOpen()
})

function close() {
  emit('update:modelValue', false)
}

async function save() {
  const { ok, errors: errs, messages } = validateRecordData(fields.value, data)
  errors.value = errs
  errorText.value = ok ? '' : messages[0]
  if (!ok) {
    ElMessage.warning(messages[0])
    return
  }
  const payload = coerceRecordData(fields.value, data)
  internalSaving.value = true
  try {
    if (props.record) {
      await Api.updateRecord(props.record.id, payload)
      ElMessage.success('已保存')
    } else {
      await Api.createRecord(props.entityType.id, payload)
      ElMessage.success('已创建')
    }
    emit('saved', props.record)
    close()
  } catch (e) {
    const detail = e?.response?.data?.detail
    errorText.value = detail ? `保存失败：${detail}` : '保存失败，请稍后再试'
    ElMessage.error(errorText.value)
  } finally {
    internalSaving.value = false
  }
}
</script>

<style scoped>
.rfd-head { min-width: 0; }
.rfd-title {
  font-size: var(--text-lg);
  font-weight: 650;
  color: var(--text-primary);
  letter-spacing: -0.2px;
}
.rfd-sub {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  margin-top: 4px;
}

.rfd-form { padding-right: 4px; }
.rfd-form :deep(.el-form-item) { margin-bottom: var(--space-5); }
.rfd-form :deep(.el-form-item__label) {
  color: var(--text-secondary);
  font-weight: 500;
}
.rfd-tip {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  line-height: 1.6;
  margin-top: 4px;
}
.rfd-empty {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  padding: var(--space-6) 0;
}

.rfd-foot {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
}
.rfd-error {
  flex: 1;
  min-width: 0;
  font-size: var(--text-sm);
  color: var(--danger);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
