<template>
  <div class="page">
    <PageTitle
      :title="isEdit ? '编辑数据模型' : '新建数据模型'"
      subtitle="定义字段类型、自动渲染动态表单 / 列表 / 详情视图"
      icon-key="Files"
    >
      <el-button v-if="isEdit" type="danger" plain :loading="deleting" @click="removeModel">
        <el-icon><Delete /></el-icon>删除模型
      </el-button>
      <el-button @click="$router.back()">取消</el-button>
      <el-button type="primary" @click="save">保存</el-button>
    </PageTitle>

    <div class="card">
      <div class="card-title">基本信息</div>
      <el-form :model="form" label-width="100px">
        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="模型名">
              <el-input v-model="form.name" placeholder="如：项目、合同" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="Key">
              <el-input
                v-model="form.key"
                placeholder="英文唯一标识"
                :disabled="isEdit"
              />
              <div v-if="isEdit" class="form-hint">Key 创建后不可修改</div>
            </el-form-item>
          </el-col>
          <el-col :span="4">
            <el-form-item label="图标">
              <el-popover placement="bottom-start" :width="300" trigger="click">
                <template #reference>
                  <button type="button" class="icon-trigger">
                    <el-icon :size="18"><component :is="safeIcon(form.icon)" /></el-icon>
                    <el-icon class="icon-caret"><ArrowDown /></el-icon>
                  </button>
                </template>
                <div class="icon-picker">
                  <button
                    v-for="ic in ENTITY_ICON_CHOICES"
                    :key="ic"
                    type="button"
                    class="icon-choice"
                    :class="{ active: form.icon === ic }"
                    @click="form.icon = ic"
                  >
                    <el-icon :size="16"><component :is="ic" /></el-icon>
                  </button>
                </div>
              </el-popover>
            </el-form-item>
          </el-col>
          <el-col :span="4">
            <el-form-item label="排序">
              <el-input-number v-model="form.order" :min="0" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="所属应用">
              <el-select v-model="form.app" filterable allow-create style="width:100%">
                <el-option v-for="a in apps" :key="a.key" :label="a.name" :value="a.key" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="说明">
              <el-input v-model="form.description" placeholder="一句话说明这个模型存什么" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
    </div>

    <div class="card">
      <div class="card-title">
        <span class="card-title-text">
          字段定义
          <span class="badge badge-ghost">{{ form.fields.length }}</span>
        </span>
        <div class="card-actions">
          <el-dropdown trigger="click" @command="addPreset">
            <el-button size="small">
              <el-icon><MagicStick /></el-icon>快捷字段
              <el-icon class="icon-caret"><ArrowDown /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-item
                v-for="p in FIELD_PRESETS"
                :key="p.key"
                :command="p"
              >
                <span class="preset-name">{{ p.name }}</span>
                <span class="preset-hint">{{ fieldTypeLabel(p.type) }}</span>
              </el-dropdown-item>
            </template>
          </el-dropdown>
          <el-button size="small" type="primary" @click="addField">
            <el-icon><Plus /></el-icon>添加字段
          </el-button>
        </div>
      </div>

      <el-alert
        v-if="!isEdit"
        type="info"
        :closable="false"
        show-icon
        class="field-alert"
      >
        <template #title>
          字段决定这张「表」的结构。列表页与表单会根据字段类型自动渲染，
          不需要写任何代码。<b>建议每个模型都保留一个「名称」字段</b>——列表页会优先显示它。
        </template>
      </el-alert>

      <div class="field-row header">
        <div>#</div>
        <div>标识 (Key)</div>
        <div>名称</div>
        <div>类型</div>
        <div>选项 / 目标</div>
        <div>必填</div>
        <div>操作</div>
      </div>
      <div v-for="(f, idx) in form.fields" :key="idx" class="field-row">
        <div class="field-order">{{ idx + 1 }}</div>
        <el-input v-model="f.key" placeholder="field_key" size="small" />
        <el-input v-model="f.name" placeholder="字段名" size="small" />
        <el-tooltip
          :content="typeHint(f.type)"
          placement="top"
          :show-after="300"
          :disabled="!typeHint(f.type)"
        >
          <el-select v-model="f.type" size="small" @change="onTypeChange(f)" class="type-select">
            <el-option v-for="t in FIELD_TYPES" :key="t.value" :value="t.value">
              <span :class="`type-badge type-${t.value}`">{{ typeIcon(t.value) }}</span>
              <span style="margin-left:6px">{{ t.label }}</span>
            </el-option>
          </el-select>
        </el-tooltip>
        <el-input
          v-if="needsChoice(f.type)"
          v-model="choicesText[f.key]"
          placeholder="逗号分隔的选项"
          size="small"
          @change="updateChoices(f)"
        />
        <el-select
          v-else-if="f.type === 'reference'"
          v-model="f.options.target"
          placeholder="选择目标实体"
          size="small"
          filterable
        >
          <el-option v-for="t in types" :key="t.key" :label="`${t.name}（${t.key}）`" :value="t.key" />
        </el-select>
        <span v-else class="dash">—</span>
        <el-switch v-model="f.required" />
        <div class="field-actions">
          <el-button
            size="small"
            text
            :disabled="idx === 0"
            @click="moveField(idx, -1)"
            title="上移"
          >
            <el-icon><Top /></el-icon>
          </el-button>
          <el-button
            size="small"
            text
            :disabled="idx === form.fields.length - 1"
            @click="moveField(idx, 1)"
            title="下移"
          >
            <el-icon><Bottom /></el-icon>
          </el-button>
          <el-button size="small" type="danger" text @click="removeField(idx)">
            <el-icon><Delete /></el-icon>
          </el-button>
        </div>
      </div>
      <div v-if="!form.fields.length" class="empty-state" style="border:none;background:transparent">
        <div class="empty-icon"><el-icon :size="32"><Files /></el-icon></div>
        <div class="empty-title">还没有字段</div>
        <div class="empty-desc">点击「快捷字段」快速添加常用字段，或「添加字段」逐一定义</div>
      </div>
    </div>

    <!-- 关联与后续 -->
    <div v-if="isEdit" class="card">
      <div class="card-title">
        <span class="card-title-text">
          <el-icon class="title-ico"><Connection /></el-icon>关联与后续
        </span>
      </div>
      <div class="rel-rows">
        <div class="rel-row">
          <div class="rel-row-label">已定义关联</div>
          <div v-if="relatedDefs.length" class="rel-row-body">
            <el-tag v-for="d in relatedDefs" :key="d.id" size="small" effect="plain">
              {{ d.name }}
            </el-tag>
          </div>
          <div v-else class="rel-row-body muted">
            该模型还没有参与任何关联定义
          </div>
          <el-button size="small" @click="$router.push('/relations')">
            <el-icon><Setting /></el-icon>去配置
          </el-button>
        </div>
        <div class="rel-row">
          <div class="rel-row-label">录入数据</div>
          <div class="rel-row-body muted">
            保存后即可按此模型录入记录，并可把记录沉淀为知识库笔记
          </div>
          <el-button size="small" type="primary" plain @click="goRecords">
            <el-icon><Document /></el-icon>打开记录列表
          </el-button>
        </div>
      </div>
    </div>

    <!-- JSON 定义：既能看，也能改，改完可以直接回写成模型 -->
    <div class="card">
      <div class="card-title">
        <span class="card-title-text">
          <el-icon class="title-ico"><Document /></el-icon>JSON 定义
        </span>
        <div class="card-actions">
          <span class="json-state" :class="jsonStateClass">{{ jsonStateText }}</span>
          <el-button size="small" @click="fillExample">
            <el-icon><MagicStick /></el-icon>填入示例
          </el-button>
          <el-button size="small" @click="generateJson">
            <el-icon><RefreshLeft /></el-icon>从表单生成
          </el-button>
          <el-button size="small" type="primary" plain @click="applyJsonFromText">
            <el-icon><Download /></el-icon>应用到表单
          </el-button>
          <el-button size="small" :loading="checking" @click="checkJson">
            <el-icon><CircleCheck /></el-icon>校验
          </el-button>
          <el-button size="small" type="primary" :loading="savingJson" @click="saveFromJson">
            <el-icon><Upload /></el-icon>{{ isEdit ? 'JSON 回写' : 'JSON 建模' }}
          </el-button>
        </div>
      </div>

      <el-alert type="info" :closable="false" show-icon class="field-alert">
        <template #title>
          直接粘贴或编辑模型定义即可建模型 / 改字段。类型支持中文别名
          （<b>字符串</b> / <b>单选</b> / <b>金额</b> / <b>外键</b> …），
          也允许 <code>//</code> 注释与尾随逗号。
          配好点「应用到表单」填进可视化编辑器，或直接点「{{ isEdit ? 'JSON 回写' : 'JSON 建模' }}」落库。
        </template>
      </el-alert>

      <div class="json-editor">
        <div class="je-col">
          <div class="je-label">JSON 源</div>
          <el-input
            v-model="jsonText"
            type="textarea"
            :rows="20"
            spellcheck="false"
            class="je-input"
            @input="onJsonInput"
          />
        </div>
        <div class="je-col">
          <div class="je-label">实时预览</div>
          <JsonViewer :text="jsonText" />
        </div>
      </div>

      <div v-if="checkResult" class="je-check">
        <div v-if="checkResult.errors && checkResult.errors.length" class="je-block is-error">
          <div class="je-block-title">
            <el-icon><CircleCloseFilled /></el-icon>
            有 {{ checkResult.errors.length }} 处需要修正
          </div>
          <ul><li v-for="(e, i) in checkResult.errors" :key="i">{{ e }}</li></ul>
        </div>
        <template v-else>
          <div class="je-block is-ok">
            <div class="je-block-title">
              <el-icon><CircleCheckFilled /></el-icon>
              校验通过 · 识别到 {{ checkResult.model ? checkResult.model.fields.length : 0 }} 个字段
              <span v-if="checkResult.action && checkResult.action !== 'none'">
                ，保存时将{{ checkResult.action === 'update' ? '覆盖同名模型' : '新建模型' }}
              </span>
            </div>
          </div>
          <div v-if="checkResult.warnings && checkResult.warnings.length" class="je-block is-warn">
            <div class="je-block-title">
              <el-icon><WarningFilled /></el-icon>
              已自动修正 {{ checkResult.warnings.length }} 处
            </div>
            <ul><li v-for="(w, i) in checkResult.warnings" :key="i">{{ w }}</li></ul>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref, computed, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Api } from '../api'
import { FIELD_TYPES, fieldTypeLabel } from '../utils/format'
import { ENTITY_ICON_CHOICES, entityIcon } from '../utils/icons'
import { confirmAndDeleteModel } from '../utils/modelDelete'
import {
  normalizeModel, parseLooseJson, buildModelJson, exampleModelJson,
} from '../utils/modeljson'
import JsonViewer from '../components/JsonViewer.vue'
import PageTitle from '../components/PageTitle.vue'

// 字段类型说明（hover 提示），帮助用户选对类型
const TYPE_HINTS = {
  text: '单行文本：名称、编号、电话等短文本',
  textarea: '多行文本：说明、备注、正文。支持 [[双链]] 可直接关联知识库笔记',
  richtext: '富文本：需要加粗/列表等格式时使用',
  number: '数字：金额、数量、百分比等，可用于排序与求和',
  date: '日期：如 2026-09-24，不带时间',
  datetime: '日期时间：需要精确到时分时使用',
  select: '单选：从固定选项中选一个，列表页会渲染为彩色标签',
  multiselect: '多选：可同时选多个，例如标签、关键词',
  boolean: '布尔：是/否开关，例如「已完成」「已归档」',
  file: '文件：可上传任意附件，支持 PDF/Word/Excel 在线预览',
  image: '图片：上传后可在列表与详情中直接显示缩略图',
  reference: '外键引用：指向另一个模型的记录，建立结构化关联',
}

function typeHint(t) {
  return TYPE_HINTS[t] || ''
}

// 快捷字段：一次点击补上 key / 名称 / 类型 / 选项
const FIELD_PRESETS = [
  { key: 'name', name: '名称', type: 'text', required: true, options: {} },
  { key: 'code', name: '编号', type: 'text', required: false, options: {} },
  { key: 'status', name: '状态', type: 'select', required: false,
    options: { choices: ['未开始', '进行中', '已完成', '已暂停'] } },
  { key: 'owner', name: '负责人', type: 'text', required: false, options: {} },
  { key: 'priority', name: '优先级', type: 'select', required: false,
    options: { choices: ['低', '中', '高', '紧急'] } },
  { key: 'amount', name: '金额（元）', type: 'number', required: false, options: {} },
  { key: 'start_date', name: '开始日期', type: 'date', required: false, options: {} },
  { key: 'end_date', name: '结束日期', type: 'date', required: false, options: {} },
  { key: 'tags', name: '标签', type: 'multiselect', required: false, options: { choices: [] } },
  { key: 'files', name: '附件', type: 'file', required: false, options: {} },
  { key: 'images', name: '图片', type: 'image', required: false, options: {} },
  { key: 'description', name: '说明', type: 'textarea', required: false, options: {} },
]

// 字段类型 → 图标 + 颜色（低饱和一组，视觉更克制）
const TYPE_META = {
  text: { icon: 'Aa', color: '#5b5fc7' },
  textarea: { icon: '¶', color: '#7a6ad0' },
  richtext: { icon: '✎', color: '#bb5a86' },
  number: { icon: '#', color: '#b4801e' },
  date: { icon: 'D', color: '#0f9b72' },
  datetime: { icon: 'DT', color: '#0f9b72' },
  select: { icon: '▼', color: '#3f8fa8' },
  multiselect: { icon: '☷', color: '#3f8fa8' },
  boolean: { icon: '◉', color: '#6b9b3a' },
  file: { icon: 'F', color: '#c2703a' },
  image: { icon: 'I', color: '#bb5a86' },
  reference: { icon: 'R', color: '#4a7fb5' },
}

function typeIcon(t) { return TYPE_META[t]?.icon || '?' }

const route = useRoute()
const router = useRouter()

const isEdit = computed(() => !!route.params.id)
const editingId = computed(() => route.params.id ? parseInt(route.params.id) : null)

const form = reactive({
  key: '',
  name: '',
  icon: 'Document',
  description: '',
  app: 'default',
  order: 0,
  fields: [],
})

const choicesText = reactive({})
const previewData = ref({})
const apps = ref([])
const types = ref([])
const relatedDefs = ref([])

function needsChoice(t) {
  return t === 'select' || t === 'multiselect'
}

function updateChoices(f) {
  const text = choicesText[f.key] || ''
  const list = text.split(/[,，]/).map(s => s.trim()).filter(Boolean)
  f.options = { choices: list }
}

function onTypeChange(f) {
  if (f.type === 'select' || f.type === 'multiselect') {
    f.options = f.options || {}
    if (!f.options.choices) f.options.choices = []
    choicesText[f.key] = (f.options.choices || []).join(',')
  } else if (f.type === 'reference') {
    f.options = f.options || {}
  }
}

function addField() {
  const idx = form.fields.length
  form.fields.push({
    key: `field_${idx + 1}`,
    name: `字段${idx + 1}`,
    type: 'text',
    required: false,
    options: {},
    order: idx + 1,
  })
}

// 快捷字段：若 key 已存在则自动加后缀，避免字段 key 冲突
function addPreset(p) {
  let key = p.key
  let n = 2
  const used = new Set(form.fields.map(f => f.key))
  while (used.has(key)) {
    key = `${p.key}_${n++}`
  }
  form.fields.push({
    key,
    name: p.name,
    type: p.type,
    required: !!p.required,
    options: JSON.parse(JSON.stringify(p.options || {})),
    order: form.fields.length + 1,
  })
  if (needsChoice(p.type)) choicesText[key] = (p.options?.choices || []).join(',')
  ElMessage.success(`已添加字段「${p.name}」`)
}

function removeField(idx) {
  const f = form.fields[idx]
  form.fields.splice(idx, 1)
  if (f) delete choicesText[f.key]
}

// 图标兜底：历史数据里存的是 emoji，无法渲染为组件
function safeIcon(name) {
  return ENTITY_ICON_CHOICES.includes(name) ? name : entityIcon(form.key)
}

async function load() {
  const [a, t] = await Promise.all([Api.listApps(), Api.listEntityTypes()])
  apps.value = a
  types.value = t

  if (editingId.value) {
    const et = await Api.getEntityType(editingId.value)
    Object.assign(form, {
      key: et.key,
      name: et.name,
      icon: et.icon,
      description: et.description,
      app: et.app,
      order: et.order,
      fields: et.fields.map(f => ({ ...f, options: f.options || {} })),
    })
    Object.keys(choicesText).forEach(k => delete choicesText[k])
    form.fields.forEach(f => {
      if (needsChoice(f.type) && f.options?.choices) {
        choicesText[f.key] = f.options.choices.join(',')
      }
    })
    originalKey.value = et.key
    loadRelatedDefs()
    generateJson()
  } else {
    // 新建
    const qApp = route.query.app
    if (qApp) form.app = qApp
    form.icon = 'Document'
    if (route.query.mode === 'json') {
      // 从「JSON 新建」入口进来：给一份能跑的样例，用户直接改
      jsonText.value = exampleModelJson()
      jsonDirty.value = true
    } else {
      addField()
      generateJson()
    }
  }
}

async function loadRelatedDefs() {
  try {
    const all = await Api.listRelationDefs()
    relatedDefs.value = all.filter(
      d => d.source_type_id === editingId.value || d.target_type_id === editingId.value
    )
  } catch (e) {
    relatedDefs.value = []
  }
}

function goRecords() {
  router.push(`/records/${editingId.value}`)
}

async function save() {
  // JSON 面板被手改过：以 JSON 为准先回写表单，避免「改了 JSON 却保存了旧字段」
  if (jsonDirty.value) {
    const warnings = applyJsonFromText({ silent: true })
    if (warnings === null) {
      ElMessage.error('JSON 有误，请先修正，或点「从表单生成」还原')
      return
    }
    if (warnings.length) ElMessage.info(`已按 JSON 同步表单（自动修正 ${warnings.length} 处）`)
  }

  if (!form.key || !form.name) {
    ElMessage.warning('请填写模型名和 Key')
    return
  }
  if (!form.fields.length) {
    ElMessage.warning('请至少添加一个字段')
    return
  }
  // 同步 choices
  form.fields.forEach(f => {
    if (needsChoice(f.type)) updateChoices(f)
  })

  try {
    if (isEdit.value) {
      await Api.updateEntityType(editingId.value, form)
    } else {
      await Api.createEntityType(form)
    }
    ElMessage.success('保存成功')
    router.push('/types')
  } catch (e) {
    // 拦截器已提示
  }
}

onMounted(load)

const deleting = ref(false)

/**
 * 删除当前模型
 *
 * 记录数不在 getEntityType 的返回里，但列表接口带了，而 load() 本来就拉了整份列表，
 * 于是直接取用 —— 为了弹窗上的「会删掉 N 条记录」再打一次接口不值当。
 */
async function removeModel() {
  const row = types.value.find(t => t.id === editingId.value) || {}
  deleting.value = true
  let ok = false
  try {
    ok = await confirmAndDeleteModel({
      id: editingId.value,
      key: form.key,
      name: form.name,
      field_count: form.fields.length,
      record_count: row.record_count || 0,
      relation_count: relatedDefs.value.length,
    })
  } finally {
    deleting.value = false
  }
  // 删完还在编辑页上，会立刻被下面的保存请求复活成新模型，必须退回列表
  if (ok) router.push('/types')
}

function moveField(idx, dir) {
  const target = idx + dir
  if (target < 0 || target >= form.fields.length) return
  const tmp = form.fields[idx]
  form.fields[idx] = form.fields[target]
  form.fields[target] = tmp
}

// ---------- JSON 定义 ↔ 表单 双向同步 ----------
const jsonText = ref('')
const jsonDirty = ref(false)        // 用户手改过 JSON：此时以 JSON 为准，等「应用到表单」
const jsonError = ref('')
const checkResult = ref(null)
const checking = ref(false)
const savingJson = ref(false)
const originalKey = ref('')         // 编辑模式下 key 不可改，用于回写时守住原值
let skipSync = false                // 「应用到表单」后跳过一次自动重生成，保留用户写的注释

const jsonStateText = computed(() => {
  if (jsonError.value) return 'JSON 有语法错误'
  if (jsonDirty.value) return 'JSON 已改，待应用'
  return '已与表单同步'
})
const jsonStateClass = computed(() => {
  if (jsonError.value) return 'is-error'
  if (jsonDirty.value) return 'is-dirty'
  return 'is-ok'
})

/** 表单 → JSON（用户没动过 JSON 时才自动覆盖） */
function generateJson() {
  jsonText.value = buildModelJson(form)
  jsonDirty.value = false
  jsonError.value = ''
  checkResult.value = null
}

// 表单改动实时反映到 JSON，让「预览」名副其实
watch(form, () => {
  if (skipSync) { skipSync = false; return }
  if (!jsonDirty.value) jsonText.value = buildModelJson(form)
}, { deep: true, flush: 'post' })

function onJsonInput() {
  jsonDirty.value = true
  checkResult.value = null
  jsonError.value = parseLooseJson(jsonText.value).ok ? '' : parseLooseJson(jsonText.value).error
}

function fillExample() {
  jsonText.value = exampleModelJson()
  jsonDirty.value = true
  jsonError.value = ''
  checkResult.value = null
  ElMessage.info('已填入示例，改完 key / 字段后点「应用到表单」')
}

/**
 * JSON → 表单（本地归一化，即时反馈）
 * @returns {string[]|null} warnings；解析/结构有错时返回 null
 */
function applyJsonFromText({ silent = false } = {}) {
  try {
    const { model, warnings } = normalizeModel(jsonText.value)
    const extra = []
    if (isEdit.value && model.key !== originalKey.value) {
      extra.push(`编辑模式下 key 不可修改，已保留「${originalKey.value}」`)
      model.key = originalKey.value
    }
    Object.assign(form, {
      key: model.key,
      name: model.name,
      icon: model.icon,
      description: model.description,
      app: model.app,
      order: model.order,
      fields: model.fields.map(f => ({ ...f, options: f.options || {} })),
    })
    Object.keys(choicesText).forEach(k => delete choicesText[k])
    form.fields.forEach(f => {
      if (needsChoice(f.type)) choicesText[f.key] = (f.options.choices || []).join(',')
    })

    skipSync = true
    jsonDirty.value = false
    jsonError.value = ''
    const all = [...extra, ...warnings]
    if (!silent) {
      if (all.length) ElMessage.warning(`已应用到表单（自动修正 ${all.length} 处）`)
      else ElMessage.success('已应用到表单')
    }
    nextTick(() => { skipSync = false })
    return all
  } catch (e) {
    jsonError.value = e.message
    if (!silent) ElMessage.error(e.message)
    return null
  }
}

/** 服务端校验（dry-run，不落库）—— 与真正保存走同一套归一化逻辑 */
async function checkJson() {
  if (!jsonText.value.trim()) {
    ElMessage.warning('请先填写 JSON')
    return
  }
  checking.value = true
  try {
    checkResult.value = await Api.importEntityType({
      text: jsonText.value,
      target_id: isEdit.value ? editingId.value : null,
      dry_run: true,
    })
  } catch (e) {
    // 网络/服务异常也要给结论，否则用户点了按钮什么也看不到
    checkResult.value = {
      ok: false,
      errors: [e?.response?.data?.detail || e?.message || '校验请求失败'],
      warnings: [],
      model: null,
      entity_type: null,
      action: 'none',
    }
  } finally {
    checking.value = false
  }
}

/** 直接用 JSON 建模型 / 回写字段 */
async function saveFromJson() {
  if (!jsonText.value.trim()) {
    ElMessage.warning('请先填写 JSON')
    return
  }
  savingJson.value = true
  try {
    let r = await Api.importEntityType({
      text: jsonText.value,
      target_id: isEdit.value ? editingId.value : null,
      dry_run: false,
      overwrite: false,
    })

    // 新建时撞上同名 key：问一下要不要覆盖
    const errText = (r.errors || []).join('')
    if (!r.ok && !isEdit.value && errText.includes('已存在标识')) {
      try {
        await ElMessageBox.confirm(
          `${(r.errors || [])[0]}\n\n是否用当前 JSON 覆盖该模型？`,
          '标识冲突',
          { confirmButtonText: '覆盖', cancelButtonText: '取消', type: 'warning' }
        )
      } catch {
        return
      }
      r = await Api.importEntityType({
        text: jsonText.value, dry_run: false, overwrite: true,
      })
    }

    checkResult.value = r
    if (!r.ok) {
      ElMessage.error((r.errors && r.errors[0]) || 'JSON 未通过校验')
      return
    }
    const warns = r.warnings || []
    ElMessage.success(r.action === 'updated' ? '已按 JSON 回写模型' : '已按 JSON 新建模型')
    if (warns.length) ElMessage.warning(`自动修正 ${warns.length} 处，例如：${warns[0]}`)

    // 回写当前模型：原地刷新，避免为了看结果又跳一次路由
    if (isEdit.value && r.entity_type && r.entity_type.id === editingId.value) {
      await load()
      generateJson()
    } else if (r.entity_type) {
      router.push(`/types/${r.entity_type.id}/edit`)
    }
  } finally {
    savingJson.value = false
  }
}
</script>

<style scoped>
.type-select { width: 100%; }
.type-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 18px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  color: #fff;
}
.type-text { background: #5b5fc7; }
.type-textarea { background: #7a6ad0; }
.type-richtext { background: #bb5a86; }
.type-number { background: #b4801e; }
.type-date, .type-datetime { background: #0f9b72; }
.type-select, .type-multiselect { background: #3f8fa8; }
.type-boolean { background: #6b9b3a; }
.type-file { background: #c2703a; }
.type-image { background: #bb5a86; }
.type-reference { background: #4a7fb5; }

.field-order {
  color: var(--text-tertiary);
  font-size: 12px;
  font-family: 'SF Mono', Menlo, monospace;
}
.dash {
  color: var(--text-tertiary);
  text-align: center;
  font-size: 13px;
}
.field-actions {
  display: flex;
  gap: 0;
  justify-content: flex-end;
}
.field-actions .el-button {
  padding: 4px 6px;
}

/* JSON 定义面板 */
.json-editor {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-4);
  align-items: start;
}
.je-col { min-width: 0; }
.je-label {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-tertiary);
  letter-spacing: 0.3px;
  margin-bottom: 6px;
}
.je-input :deep(.el-textarea__inner) {
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.7;
  tab-size: 2;
}

.json-state {
  font-size: var(--text-xs);
  padding: 2px 9px;
  border-radius: var(--radius-full);
  background: var(--bg-subtle);
  color: var(--text-secondary);
  white-space: nowrap;
}
.json-state.is-ok { background: var(--success-bg); color: var(--success); }
.json-state.is-dirty { background: var(--warning-bg); color: var(--warning); }
.json-state.is-error { background: var(--danger-bg); color: var(--danger); }

.je-check {
  margin-top: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.je-block {
  padding: 10px 12px;
  border-radius: var(--radius);
  font-size: var(--text-sm);
  border: 1px solid transparent;
}
.je-block-title { display: flex; align-items: center; gap: 6px; font-weight: 600; }
.je-block ul { margin: 6px 0 0; padding-left: 20px; line-height: 1.7; }
.je-block.is-ok { background: var(--success-bg); color: var(--success); }
.je-block.is-warn { background: var(--warning-bg); color: var(--warning); }
.je-block.is-error { background: var(--danger-bg); color: var(--danger); }

/* 字段提示条 */
.field-alert {
  margin-bottom: var(--space-3);
}
.field-alert :deep(.el-alert__title) {
  font-size: var(--text-sm);
  line-height: 1.7;
}

/* 关联与后续 */
.rel-rows { display: flex; flex-direction: column; gap: var(--space-3); }
.rel-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--bg-subtle);
  border-radius: var(--radius);
  flex-wrap: wrap;
}
.rel-row-label {
  font-weight: 700;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  min-width: 84px;
  flex-shrink: 0;
}
.rel-row-body {
  flex: 1;
  min-width: 0;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  font-size: var(--text-sm);
}
.rel-row-body.muted { color: var(--text-tertiary); }

/* 窄屏：JSON 源与预览上下堆叠 */
@media (max-width: 1100px) {
  .json-editor { grid-template-columns: 1fr; }
}
</style>