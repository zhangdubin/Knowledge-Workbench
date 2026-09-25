<template>
  <div>
    <div v-if="!readonly" class="upload-row">
      <el-upload
        :http-request="uploadFile"
        :show-file-list="false"
        :before-upload="before"
        accept="*"
      >
        <el-button size="small" type="primary" plain>
          <el-icon><Upload /></el-icon>
          {{ image ? '上传图片' : '上传文件' }}
        </el-button>
      </el-upload>
    </div>
    <div v-if="files.length" class="file-list">
      <div v-for="f in files" :key="f.id" class="file-item">
        <el-icon style="color:var(--primary)"><component :is="fileIcon(f)" /></el-icon>
        <a
          :href="previewUrlOf(f)"
          target="_blank"
          rel="noopener"
          class="filename"
          :title="f.mode && f.mode !== 'other' ? '在线预览' : '下载查看'"
        >{{ f.filename }}</a>
        <span class="size">{{ formatSize(f.size) }}</span>
        <a class="dl" :href="f.url || `/api/attachments/${f.id}/download`" download title="下载">
          <el-icon><Download /></el-icon>
        </a>
        <el-button
          v-if="!readonly"
          size="small"
          type="danger"
          text
          @click="del(f)"
        >
          <el-icon><Delete /></el-icon>
        </el-button>
      </div>
    </div>
    <div v-else-if="readonly" class="empty" style="padding:10px">无附件</div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Api, previewModeOf } from '../api'
import { formatSize } from '../utils/format'

// 预览走 inline 接口，浏览器可直接渲染 PDF / 图片 / 音视频
function previewUrlOf(f) {
  return f?.preview_url || `/api/attachments/${f?.id}/preview`
}

function fileIcon(f) {
  const mode = previewModeOf(f)
  if (mode === 'image') return 'Picture'
  if (mode === 'video') return 'VideoCamera'
  if (mode === 'audio') return 'Headset'
  if (mode === 'pdf' || mode === 'office' || mode === 'legacy-office') return 'Document'
  if (mode === 'csv') return 'Grid'
  return 'Document'
}

const props = defineProps({
  recordId: { type: Number, default: null },
  fieldKey: { type: String, required: true },
  modelValue: { type: [Array, Object], default: () => [] },
  readonly: { type: Boolean, default: false },
  image: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])

const files = ref(Array.isArray(props.modelValue) ? props.modelValue : [])

watch(() => props.modelValue, (v) => {
  files.value = Array.isArray(v) ? v : []
})

onMounted(async () => {
  if (props.recordId) {
    try {
      const list = await Api.listAttachments(props.recordId, props.fieldKey)
      files.value = list
      emit('update:modelValue', list)
    } catch {}
  }
})

function before(file) {
  if (file.size > 100 * 1024 * 1024) {
    ElMessage.warning('文件超过 100MB')
    return false
  }
  return true
}

async function uploadFile(opt) {
  if (!props.recordId) {
    ElMessage.warning('请先保存记录后再上传文件')
    return
  }
  try {
    const r = await Api.uploadAttachment(props.recordId, props.fieldKey, opt.file)
    files.value = [...files.value, r]
    emit('update:modelValue', files.value)
    ElMessage.success('上传成功')
  } catch (e) {}
}

async function del(f) {
  try {
    await Api.deleteAttachment(f.id)
    files.value = files.value.filter(x => x.id !== f.id)
    emit('update:modelValue', files.value)
  } catch (e) {}
}
</script>

<style scoped>
.upload-row { margin-bottom: 8px; }
.file-list { display: flex; flex-direction: column; gap: 6px; }
.file-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: var(--bg);
  border-radius: 4px;
  font-size: 13px;
}
.filename { flex: 1; color: var(--primary); text-decoration: none; }
.filename:hover { text-decoration: underline; }
.size { color: var(--text-tertiary); font-size: 12px; }
.dl {
  display: inline-flex;
  align-items: center;
  color: var(--text-tertiary);
  text-decoration: none;
}
.dl:hover { color: var(--primary); }
</style>