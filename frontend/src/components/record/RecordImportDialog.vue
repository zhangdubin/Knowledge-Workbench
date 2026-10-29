<template>
  <!--
    批量导入记录
    ---------------------------------------------------------------------------
    为什么抽成组件：「记录页」和「应用独立页」都能导入记录，
    但导入这块规则不少（列头要用字段 Key、逐行校验、错误行要报位置），
    写两遍迟早两边提示不一样 —— 所以只留这一份。
  -->
  <el-dialog
    :model-value="modelValue"
    :title="`批量导入记录${typeName ? ` · ${typeName}` : ''}`"
    width="620px"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <el-alert type="info" :closable="false" style="margin-bottom:14px"
      title="CSV 列头需用字段 Key（先「导出 CSV」看一眼格式最稳）；JSON 支持数组或 {items:[]}" />
    <div style="margin-bottom:10px">
      <input type="file" accept=".csv,.json,.txt" @change="onImportFile" />
    </div>
    <el-input
      v-model="text"
      type="textarea"
      :rows="10"
      placeholder="或直接把 CSV / JSON 内容粘贴到这里…"
    />
    <template #footer>
      <span style="float:left;color:var(--el-text-color-secondary);font-size:12px">
        逐行校验：合法行照常入库，错误行会报出位置和原因
      </span>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="importing" @click="doImport">开始导入</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Api } from '../../api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  typeId: { type: [Number, String], default: null },
  typeName: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'imported'])

const text = ref('')
const format = ref('csv')
const importing = ref(false)

// 每次打开都清空上一次的残留内容，避免误把旧内容又导一遍
watch(() => props.modelValue, open => {
  if (open) {
    text.value = ''
    format.value = 'csv'
  }
})

function onImportFile(ev) {
  const file = ev.target.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    text.value = String(reader.result || '')
    format.value = file.name.toLowerCase().endsWith('.json') ? 'json' : 'csv'
  }
  reader.readAsText(file)
  ev.target.value = ''
}

async function doImport() {
  if (!text.value.trim()) {
    ElMessage.warning('内容为空')
    return
  }
  if (!props.typeId) {
    ElMessage.warning('没有选中数据模型')
    return
  }
  importing.value = true
  try {
    const r = await Api.importRecords(props.typeId, text.value, format.value)
    const parts = [`新增 ${r.created} 条`]
    if (r.failed) parts.push(`失败 ${r.failed} 行`)
    if (r.warnings?.length) parts.push(r.warnings.join('；'))
    if (r.failed) {
      ElMessage.warning({
        message: parts.join('；') + '。详情：' + r.errors.slice(0, 3).map(e => `第${e.row}行 ${e.reason}`).join(' / '),
        duration: 8000,
      })
    } else {
      ElMessage.success(parts.join('；'))
    }
    emit('update:modelValue', false)
    text.value = ''
    emit('imported', r)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '导入失败')
  } finally {
    importing.value = false
  }
}
</script>
