<template>
  <!--
    记录详情抽屉
    ---------------------------------------------------------------------------
    「记录页」和「应用独立页」都要看一条记录的完整字段，
    放两份就会出现「这里显示日期、那里显示时间戳」的分裂。
    所以字段区、附件、元信息都在这里，两个页面各自往 extra 插槽里放自己的内容
    （记录页放关联关系与知识关联，应用页不放）。
  -->
  <el-drawer
    :model-value="modelValue"
    :size="size"
    direction="rtl"
    class="rdd"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <template #header>
      <div class="rdd-head">
        <div class="rdd-title">{{ record ? recordDisplayName(record) : '记录详情' }}</div>
        <div v-if="entityType" class="rdd-sub">{{ entityType.name }}</div>
      </div>
    </template>

    <div v-if="record" class="rdd-body">
      <div class="card" style="margin-bottom:12px">
        <div class="card-title">
          <span><el-icon :size="16"><Document /></el-icon> 字段</span>
        </div>
        <div class="rdd-fields">
          <div v-for="f in fields" :key="f.key" class="rdd-field">
            <div class="rdd-label">{{ f.name }}</div>
            <div class="rdd-value">
              <!-- 附件要能点开预览、关联要能点进去，单独处理；
                   其余类型统一交给 RecordCell 渲染，避免两套类型判断 -->
              <template v-if="f.type === 'file' || f.type === 'image'">
                <a
                  v-for="a in record.data?.[f.key] || []"
                  :key="a.id"
                  :href="previewUrlOf(a)"
                  target="_blank"
                  rel="noopener"
                  class="attachment-link"
                >
                  <el-icon><Paperclip /></el-icon>{{ a.filename }}
                </a>
                <span v-if="!(record.data?.[f.key] || []).length" class="cell-empty">—</span>
              </template>
              <a
                v-else-if="f.type === 'reference'"
                class="cell-reference"
                @click="$emit('open-reference', record.data?.[f.key])"
              >
                {{ referenceLabel(labels, f, record.data?.[f.key]) || `#${record.data?.[f.key]}` }}
              </a>
              <RecordCell
                v-else
                :field="f"
                :value="record.data?.[f.key]"
                :labels="labels"
              />
            </div>
          </div>
        </div>
      </div>

      <!-- 页面自己的附加内容（关联关系、知识关联…） -->
      <slot name="extra" :record="record" />

      <div class="card">
        <div class="card-title">元信息</div>
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="ID">#{{ record.id }}</el-descriptions-item>
          <el-descriptions-item v-if="entityType" label="所属模型">
            {{ entityType.name }}
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">
            {{ formatTime(record.created_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="更新时间">
            {{ formatTime(record.updated_at) }}
          </el-descriptions-item>
        </el-descriptions>
      </div>
    </div>

    <template #footer>
      <div class="rdd-foot">
        <el-button @click="$emit('update:modelValue', false)">关闭</el-button>
        <el-button
          type="primary"
          :disabled="!canEdit"
          @click="$emit('edit', record)"
        >编辑</el-button>
      </div>
    </template>
  </el-drawer>
</template>

<script setup>
import { computed } from 'vue'
import { Document, Paperclip } from '@element-plus/icons-vue'
import RecordCell from './RecordCell.vue'
import { formatTime } from '../../utils/format'
import { recordDisplayName, referenceLabel } from '../../utils/recordFields.js'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  record: { type: Object, default: null },
  // 模型定义（带 fields）
  entityType: { type: Object, default: null },
  labels: { type: Object, default: () => ({}) },
  canEdit: { type: Boolean, default: true },
  size: { type: String, default: 'min(560px, 96vw)' },
})

defineEmits(['update:modelValue', 'edit', 'open-reference'])

const fields = computed(() => props.entityType?.fields || [])

function previewUrlOf(att) {
  return att?.preview_url || `/api/attachments/${att?.id}/preview`
}
</script>

<style scoped>
.rdd-head { min-width: 0; }
.rdd-title {
  font-size: var(--text-lg);
  font-weight: 650;
  color: var(--text-primary);
  letter-spacing: -0.2px;
}
.rdd-sub {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  margin-top: 4px;
}

.rdd-body { min-width: 0; }

.rdd-fields {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 16px 24px;
}
.rdd-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.rdd-label {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  font-weight: 600;
}
.rdd-value {
  font-size: var(--text-base);
  color: var(--text-primary);
  line-height: 1.5;
  word-break: break-word;
}

.attachment-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--primary);
  text-decoration: none;
  padding: 3px 8px;
  background: var(--primary-bg);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  margin-right: 6px;
  margin-bottom: 4px;
}
.attachment-link:hover { text-decoration: underline; }

.rdd-foot {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}
</style>
