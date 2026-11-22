<template>
  <section class="ks-panel ks-stack">
    <div class="ks-between">
      <h3>{{ kind === 'template' ? '安装知识服务模板' : '登记资料修订' }}</h3>
      <button class="ks-button ks-text" type="button" :disabled="saving.busy" @click="$emit('close')">关闭</button>
    </div>

    <template v-if="kind === 'template'">
      <p v-if="definition.busy" role="status">正在读取模板…</p>
      <p v-if="definition.error" class="ks-error" role="alert">{{ definition.error }}</p>
      <button v-if="definition.error" class="ks-button" type="button" @click="loadDefinition">重新读取</button>

      <template v-if="definition.data">
        <p class="ks-muted">填写空间名称，预览将创建的类型、字段和关系，再确认安装。</p>
        <form class="ks-form" @submit.prevent="previewTemplate">
          <label>
            <span>知识空间名称</span>
            <input v-model.trim="name" :disabled="saving.busy" required maxlength="120" placeholder="例如：培训知识" />
          </label>
          <button class="ks-button" type="submit" :disabled="preview.busy || saving.busy || Boolean(preview.data) || !name">
            {{ preview.busy ? '正在生成预览…' : preview.data ? '已生成安装预览' : '生成安装预览' }}
          </button>
        </form>
        <div class="ks-stack">
          <h4>{{ preview.data ? '安装预览' : definition.data.name }}</h4>
          <ul class="ks-rows">
            <li v-for="type in schema.types" :key="type.id" class="ks-row">
              <strong>{{ type.name }}</strong>
              <div class="ks-meta">{{ type.fields.map(field => field.name).join('、') }}</div>
            </li>
          </ul>
          <p class="ks-meta">关联 · {{ schema.relations.map(relation => relation.name).join('、') }}</p>
        </div>
        <button v-if="preview.data" class="ks-button ks-primary" type="button" :disabled="saving.busy" @click="confirmTemplate">
          {{ saving.busy ? '正在安装…' : '确认安装模板' }}
        </button>
      </template>
      <p v-if="preview.error" class="ks-error" role="alert">{{ preview.error }}</p>
    </template>

    <template v-else>
      <p v-if="!candidates.length" class="ks-muted">当前没有可选的原始资料。</p>
      <p v-if="candidatesIncomplete" class="ks-muted">仅显示检索限额内可登记的原文件。</p>
      <form v-if="candidates.length" class="ks-form" @submit.prevent="registerSource">
        <fieldset class="ks-form-grid ks-fieldset" :disabled="saving.busy">
          <label class="ks-full">
            <span>原始资料</span>
            <select v-model="form.document_id" required>
              <option value="">选择已有文件</option>
              <option v-for="doc in candidates" :key="doc.id" :value="doc.id">
                {{ doc.title }}{{ doc.filename !== doc.title ? ` · ${doc.filename}` : '' }}
              </option>
            </select>
          </label>
          <label><span>修订名称</span><input v-model.trim="form.label" required maxlength="200" placeholder="例如：维护手册第二版" /></label>
          <label><span>资料分组</span><input v-model.trim="form.group_key" required maxlength="200" placeholder="同一资料沿用同一分组" /></label>
          <label><span>适用范围</span><input v-model.trim="form.scope" maxlength="200" placeholder="例如：保障" /></label>
          <label><span>主题</span><input v-model.trim="form.topic" maxlength="200" placeholder="例如：维护" /></label>
          <label><span>生效日期</span><input v-model="form.effective_from" type="date" /></label>
          <label><span>截止日期</span><input v-model="form.effective_to" type="date" :min="form.effective_from || undefined" /></label>
          <label class="ks-full">
            <span>明确替代的资料版本</span>
            <select v-model="form.supersedes_id">
              <option value="">本次不指定替代版本</option>
              <option v-for="row in predecessors" :key="row.id" :value="row.id">{{ row.label }} · {{ effectivePeriod(row) }}</option>
            </select>
          </label>
          <div class="ks-full ks-actions">
            <button class="ks-button ks-primary" type="submit" :disabled="saving.busy || !form.document_id">
              {{ saving.busy ? '正在登记…' : '登记修订' }}
            </button>
          </div>
          <p class="ks-muted ks-full">更换适用范围或分组时，会清除已选的替代版本。</p>
        </fieldset>
      </form>
    </template>
    <p v-if="saving.error" class="ks-error" role="alert">{{ saving.error }}</p>
  </section>
</template>

<script setup>
import { effectivePeriod } from '../../utils/knowledgeService.js'
import { useKnowledgeManagement } from './useKnowledgeManagement.js'

const props = defineProps({
  kind: { type: String, required: true },
  spaceId: { type: String, default: '' },
  candidates: { type: Array, default: () => [] },
  candidatesIncomplete: Boolean,
  revisions: { type: Array, default: () => [] },
  selectedRevision: { type: Object, default: null },
})
const emit = defineEmits(['close', 'installed', 'registered', 'permission', 'saving'])
const { definition, preview, saving, name, form, schema, predecessors,
  loadDefinition, previewTemplate, confirmTemplate, registerSource } = useKnowledgeManagement(props, emit)
</script>
