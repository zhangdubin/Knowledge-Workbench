<template>
  <div ref="rootRef" class="med-root" @keydown.capture="onDialogKeydown">
    <!--
      同一个编辑器有两种形态：
      - dialog：列表页里的弹窗（el-dialog）
      - inline：路由页里的内嵌形态（TypeEditor.vue 的薄壳用它）
      用 <component :is> 共用一份内容，避免两处逻辑分叉。
    -->
    <component :is="shell" v-bind="shellProps">
      <div class="med" v-loading="loading">
        <!-- 顶部：模型身份 -->
        <div class="med-head">
          <div class="med-head-icon">
            <el-icon :size="20"><component :is="safeIcon(form.icon)" /></el-icon>
          </div>
          <div class="med-head-text">
            <div class="med-head-title">{{ isEdit ? '编辑数据模型' : '新建数据模型' }}</div>
            <div class="med-head-sub">
              <template v-if="form.name || form.key">
                <span>{{ form.name || '未命名模型' }}</span>
                <span v-if="form.key" class="med-head-key">{{ form.key }}</span>
              </template>
              <span v-else>定义字段后，列表 / 表单 / 记录页会自动按字段渲染</span>
            </div>
          </div>
          <div class="med-head-right">
            <span class="med-head-count">{{ form.fields.length }} 个字段</span>
            <button
              v-if="!isInline"
              type="button"
              class="med-close"
              aria-label="关闭"
              @click="onCancel"
            >
              <el-icon><Close /></el-icon>
            </button>
          </div>
        </div>

        <el-tabs v-model="activeTab" class="med-tabs">
          <!-- ============ 可视化：左基本信息 + 右字段定义 ============ -->
          <el-tab-pane name="visual">
            <template #label>
              <span class="med-tab-label"><el-icon><Grid /></el-icon>字段定义</span>
            </template>

            <div class="med-grid">
              <!-- 左：基本信息 -->
              <div class="med-side">
                <div class="med-side-title">基本信息</div>
                <el-form label-position="top" class="med-form" @submit.prevent>
                  <el-form-item label="模型名" :error="metaError('name')">
                    <el-input
                      v-model="form.name"
                      placeholder="如：项目、合同"
                      @blur="touchedMeta.name = true"
                    />
                  </el-form-item>

                  <el-form-item label="标识（Key）" :error="metaError('key')">
                    <el-input
                      v-model="form.key"
                      placeholder="英文唯一标识"
                      :disabled="isEdit"
                      @blur="touchedMeta.key = true"
                    />
                    <div class="med-hint">
                      {{ isEdit ? 'Key 创建后不可修改' : '字母 / 数字 / 下划线，创建后不可改' }}
                    </div>
                  </el-form-item>

                  <el-form-item label="图标">
                    <el-popover placement="bottom-start" :width="300" trigger="click">
                      <template #reference>
                        <button type="button" class="med-icon-trigger">
                          <el-icon :size="18"><component :is="safeIcon(form.icon)" /></el-icon>
                          <el-icon class="med-icon-caret"><ArrowDown /></el-icon>
                        </button>
                      </template>
                      <div class="med-icon-picker">
                        <button
                          v-for="ic in ENTITY_ICON_CHOICES"
                          :key="ic"
                          type="button"
                          class="med-icon-choice"
                          :class="{ 'is-active': form.icon === ic }"
                          :aria-label="ic"
                          @click="form.icon = ic"
                        >
                          <el-icon :size="16"><component :is="ic" /></el-icon>
                        </button>
                      </div>
                    </el-popover>
                  </el-form-item>

                  <el-form-item label="所属应用">
                    <el-select v-model="form.app" filterable class="med-full">
                      <el-option
                        v-for="a in apps"
                        :key="a.key"
                        :label="a.name"
                        :value="a.key"
                      />
                    </el-select>
                  </el-form-item>

                  <el-form-item label="排序">
                    <el-input-number v-model="form.order" :min="0" class="med-full" />
                    <div class="med-hint">同一应用内越小越靠前</div>
                  </el-form-item>

                  <el-form-item label="说明">
                    <el-input
                      v-model="form.description"
                      type="textarea"
                      :rows="3"
                      placeholder="一句话说明这个模型存什么"
                    />
                  </el-form-item>
                </el-form>
              </div>

              <!-- 右：字段定义 -->
              <div class="med-main">
                <div class="med-main-head">
                  <div class="med-main-title">
                    字段定义
                    <span class="med-badge">{{ form.fields.length }}</span>
                  </div>
                  <div class="med-main-actions">
                    <el-dropdown trigger="click" @command="addPreset">
                      <el-button>
                        <el-icon><MagicStick /></el-icon>快捷字段
                        <el-icon class="med-icon-caret"><ArrowDown /></el-icon>
                      </el-button>
                      <template #dropdown>
                        <el-dropdown-menu>
                          <el-dropdown-item v-for="p in FIELD_PRESETS" :key="p.key" :command="p">
                            <span class="med-preset-name">{{ p.name }}</span>
                            <span class="med-preset-hint">{{ presetTypeLabel(p.type) }}</span>
                          </el-dropdown-item>
                        </el-dropdown-menu>
                      </template>
                    </el-dropdown>
                    <el-button type="primary" @click="addField">
                      <el-icon><Plus /></el-icon>添加字段
                    </el-button>
                  </div>
                </div>

                <div class="med-fields">
                  <div
                    v-for="(f, idx) in form.fields"
                    :key="idx"
                    class="fld"
                    :class="{
                      'is-error': fieldErrors(idx).length,
                      'is-dragging': dragIdx === idx,
                      'is-over': dragOverIdx === idx && dragIdx !== idx,
                    }"
                    @dragover.prevent="onDragOver(idx)"
                    @drop.prevent="onDrop(idx)"
                  >
                    <div class="fld-main">
                      <button
                        type="button"
                        class="fld-handle"
                        draggable="true"
                        aria-label="拖动排序，也可用方向键移动"
                        title="拖动排序（聚焦后按 ↑ ↓ 也能移动）"
                        @dragstart="onDragStart(idx)"
                        @dragend="onDragEnd"
                        @keydown.up.prevent="moveField(idx, -1)"
                        @keydown.down.prevent="moveField(idx, 1)"
                      >
                        <el-icon><Rank /></el-icon>
                      </button>

                      <el-input
                        v-model="f.name"
                        class="fld-name"
                        placeholder="字段名（如 合同编号）"
                        @blur="touchField(idx)"
                      />

                      <el-select
                        v-model="f.type"
                        class="fld-type"
                        @change="onTypeChange(f)"
                      >
                        <el-option-group
                          v-for="g in FIELD_TYPE_GROUPS"
                          :key="g.group"
                          :label="g.group"
                        >
                          <el-option
                            v-for="t in g.types"
                            :key="t.value"
                            :label="t.label"
                            :value="t.value"
                          >
                            <div class="type-opt">
                              <span class="type-badge" :style="{ background: t.color }">{{ t.icon }}</span>
                              <span class="type-opt-text">
                                <span class="type-opt-label">{{ t.label }}</span>
                                <span class="type-opt-desc">{{ t.desc }}</span>
                              </span>
                            </div>
                          </el-option>
                        </el-option-group>
                      </el-select>

                      <div class="fld-flags">
                        <label class="fld-flag">
                          <el-switch v-model="f.required" size="small" />
                          <span>必填</span>
                        </label>
                        <el-tooltip content="唯一性会写入模型定义；记录表单侧的强制校验尚未开启" placement="top">
                          <label class="fld-flag">
                            <el-switch v-model="f.unique" size="small" />
                            <span>唯一</span>
                          </label>
                        </el-tooltip>
                      </div>

                      <button
                        type="button"
                        class="fld-del"
                        aria-label="删除字段"
                        title="删除字段"
                        @click="removeField(idx)"
                      >
                        <el-icon><Delete /></el-icon>
                      </button>
                    </div>

                    <div class="fld-sub">
                      <div class="fld-sub-item">
                        <span class="fld-sub-label">标识</span>
                        <el-input
                          v-model="f.key"
                          size="small"
                          placeholder="field_key"
                          @blur="touchField(idx)"
                        />
                      </div>

                      <div v-if="isChoiceType(f.type)" class="fld-sub-item is-wide">
                        <span class="fld-sub-label">选项</span>
                        <el-select
                          v-model="f.choices"
                          multiple
                          filterable
                          allow-create
                          default-first-option
                          collapse-tags
                          collapse-tags-tooltip
                          size="small"
                          placeholder="输入后回车添加选项"
                        />
                      </div>

                      <div v-else-if="isReferenceType(f.type)" class="fld-sub-item is-wide">
                        <span class="fld-sub-label">目标</span>
                        <el-select
                          v-model="f.target"
                          filterable
                          size="small"
                          placeholder="选择目标模型"
                        >
                          <el-option
                            v-for="t in types"
                            :key="t.key"
                            :label="`${t.name}（${t.key}）`"
                            :value="t.key"
                          />
                        </el-select>
                      </div>

                      <div class="fld-sub-item">
                        <span class="fld-sub-label">默认值</span>
                        <el-input v-model="f.defaultValue" size="small" placeholder="可选" />
                      </div>
                    </div>

                    <div class="fld-desc">
                      <el-icon><InfoFilled /></el-icon>
                      {{ fieldTypeDesc(f.type) }}
                    </div>

                    <div v-if="fieldErrors(idx).length" class="fld-err">
                      <el-icon><WarningFilled /></el-icon>
                      <span>{{ fieldErrors(idx).join('；') }}</span>
                    </div>
                    <div v-else-if="fieldWarnings(idx).length" class="fld-warn">
                      <el-icon><InfoFilled /></el-icon>
                      <span>{{ fieldWarnings(idx).join('；') }}</span>
                    </div>
                  </div>

                  <div v-if="!form.fields.length" class="med-fields-empty">
                    <div class="med-fields-empty-icon"><el-icon :size="28"><Files /></el-icon></div>
                    <div class="med-fields-empty-title">还没有字段</div>
                    <div class="med-fields-empty-desc">
                      字段决定这张「表」的结构，列表页与表单会按字段类型自动渲染。
                      建议至少保留一个「名称」字段 —— 列表页会优先显示它。
                    </div>
                    <el-button type="primary" plain @click="addField">
                      <el-icon><Plus /></el-icon>添加第一个字段
                    </el-button>
                  </div>
                </div>
              </div>
            </div>
          </el-tab-pane>

          <!-- ============ JSON 定义 ============ -->
          <el-tab-pane name="json">
            <template #label>
              <span class="med-tab-label"><el-icon><Document /></el-icon>JSON 定义</span>
            </template>

            <div class="med-json">
              <div class="med-json-head">
                <div class="med-json-head-text">
                  直接粘贴一份 JSON 就能建模型 / 改字段。
                  类型支持中文别名（字符串 / 单选 / 金额 / 外键 …），也允许 <code>//</code> 注释与尾随逗号。
                </div>
                <div class="med-json-actions">
                  <span class="med-json-state" :class="jsonStateClass">{{ jsonStateText }}</span>
                  <el-button @click="fillExample">
                    <el-icon><MagicStick /></el-icon>填入示例
                  </el-button>
                  <el-button @click="generateJson">
                    <el-icon><RefreshLeft /></el-icon>从表单生成
                  </el-button>
                  <el-button @click="applyJsonFromText()">
                    <el-icon><Download /></el-icon>应用到表单
                  </el-button>
                  <el-button :loading="checking" @click="checkJson">
                    <el-icon><CircleCheck /></el-icon>校验
                  </el-button>
                </div>
              </div>

              <div class="med-json-grid">
                <div class="med-json-col">
                  <div class="med-json-label">JSON 源</div>
                  <el-input
                    v-model="jsonText"
                    type="textarea"
                    :rows="16"
                    spellcheck="false"
                    class="med-json-input"
                    @input="onJsonInput"
                  />
                </div>
                <div class="med-json-col">
                  <div class="med-json-label">实时预览</div>
                  <JsonViewer :text="jsonText" />
                </div>
              </div>

              <div v-if="checkResult" class="med-json-check">
                <div v-if="checkResult.errors && checkResult.errors.length" class="med-json-block is-error">
                  <div class="med-json-block-title">
                    <el-icon><CircleCloseFilled /></el-icon>
                    有 {{ checkResult.errors.length }} 处需要修正
                  </div>
                  <ul><li v-for="(e, i) in checkResult.errors" :key="i">{{ e }}</li></ul>
                </div>
                <template v-else>
                  <div class="med-json-block is-ok">
                    <div class="med-json-block-title">
                      <el-icon><CircleCheckFilled /></el-icon>
                      校验通过 · 识别到 {{ checkResult.model ? checkResult.model.fields.length : 0 }} 个字段
                    </div>
                  </div>
                  <div v-if="checkResult.warnings && checkResult.warnings.length" class="med-json-block is-warn">
                    <div class="med-json-block-title">
                      <el-icon><WarningFilled /></el-icon>
                      已自动修正 {{ checkResult.warnings.length }} 处
                    </div>
                    <ul><li v-for="(w, i) in checkResult.warnings" :key="i">{{ w }}</li></ul>
                  </div>
                </template>
              </div>
            </div>
          </el-tab-pane>
        </el-tabs>

        <!-- 底部动作区 -->
        <div class="med-actions">
          <div class="med-actions-left">
            <template v-if="isEdit">
              <el-button type="danger" plain :loading="deleting" @click="removeModel">
                <el-icon><Delete /></el-icon>删除模型
              </el-button>
            </template>
            <span v-else class="med-hint">
              带 <b>*</b> 的为必填字段；保存后模型会直接出现在列表里
            </span>
          </div>
          <div class="med-actions-right">
            <el-button @click="onCancel">取消</el-button>
            <el-button type="primary" :loading="saving" @click="save">
              <el-icon><Check /></el-icon>{{ isEdit ? '保存修改' : '创建模型' }}
            </el-button>
          </div>
        </div>
      </div>
    </component>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Api } from '../api'
import {
  FIELD_TYPE_GROUPS, FIELD_PRESETS,
  fieldTypeDesc, isChoiceType, isReferenceType, choicesOf,
  validateModelForm, buildModelPayload, buildFieldOptions, toEditorFields,
  makePresetField, makeEmptyField,
} from '../utils/modelFields'
import { ENTITY_ICON_CHOICES, entityIcon } from '../utils/icons'
import { confirmAndDeleteModel } from '../utils/modelDelete'
import {
  normalizeModel, parseLooseJson, buildModelJson, exampleModelJson,
} from '../utils/modeljson'
import JsonViewer from './JsonViewer.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  // 要编辑的模型 id；null = 新建
  modelId: { type: [Number, String], default: null },
  // 新建时预选的应用
  defaultApp: { type: String, default: '' },
  // 打开时落在哪个页签：visual（字段）/ json（JSON 定义）
  initialTab: { type: String, default: 'visual' },
  // dialog = 弹窗；inline = 内嵌在页面里（TypeEditor.vue 用）
  variant: { type: String, default: 'dialog' },
  // 其他模型已占用的 key，用于提示「标识已被占用」
  existingKeys: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'saved', 'deleted', 'cancel'])

const rootRef = ref(null)
const isInline = computed(() => props.variant === 'inline')
const isEdit = computed(() => !!props.modelId)

const visible = computed({
  get: () => props.modelValue,
  set: v => emit('update:modelValue', v),
})

// 弹窗 / 内嵌两种外壳共用一份内容：避免同一套编辑器写两遍
const shell = computed(() => (isInline.value ? 'div' : 'el-dialog'))
const shellProps = computed(() => {
  if (isInline.value) return { class: 'med-inline' }
  return {
    modelValue: props.modelValue,
    'onUpdate:modelValue': v => emit('update:modelValue', v),
    class: 'med-dialog',
    width: 'min(1120px, 94vw)',
    top: '4vh',
    // 点遮罩不关：编辑器里往往已经改了不少，误触一下全丢太冤
    closeOnClickModal: false,
    onClose: () => emit('cancel'),
  }
})

const form = reactive({
  key: '',
  name: '',
  icon: 'Document',
  description: '',
  app: 'default',
  order: 0,
  fields: [],
})

const apps = ref([])
const types = ref([])
const loading = ref(false)
const saving = ref(false)
const deleting = ref(false)
const activeTab = ref(props.initialTab)
const originalKey = ref('')

// 校验提示只在「用户碰过这个字段」或「点过保存」之后出现，
// 否则一进弹窗满屏红字，反而看不清表单长什么样
const showErrors = ref(false)
const touchedMeta = reactive({ key: false, name: false })
const touchedFields = reactive({})

// 已经被别的模型占用的 key：自己不在其中（编辑时不能拿自己的 key 去撞自己）
const localKeys = ref([])
const effectiveExistingKeys = computed(() => {
  const set = new Set([...(props.existingKeys || []), ...localKeys.value])
  return [...set]
})

// 从服务端带出来的字段：它们的「选择类型没配选项」只提醒不拦保存
// （存量模型里确实有没配选项的多选标签，用户改个描述不该被拦住）
const serverFieldKeys = ref(new Set())
const toleratedEmptyChoices = computed(() => form.fields
  .filter(f => serverFieldKeys.value.has(String(f.key || '').trim()))
  .filter(f => isChoiceType(f.type) && !choicesOf(f).length)
  .map(f => String(f.key || '').trim()))

const validation = computed(() => validateModelForm(form, {
  existingKeys: effectiveExistingKeys.value,
  allowEmptyChoices: toleratedEmptyChoices.value,
}))

function metaError(field) {
  if (!showErrors.value && !touchedMeta[field]) return ''
  return validation.value.errors[field] || ''
}

function fieldErrors(idx) {
  if (!showErrors.value && !touchedFields[idx]) return []
  const fe = validation.value.errors.fields[idx] || {}
  return [fe.key, fe.name, fe.options].filter(Boolean)
}

/** 提醒（不拦保存）：存量模型里没配选项的选择字段 */
function fieldWarnings(idx) {
  const f = form.fields[idx]
  if (!f) return []
  const key = String(f.key || '').trim()
  if (!serverFieldKeys.value.has(key)) return []
  if (!isChoiceType(f.type) || choicesOf(f).length) return []
  return ['这个选择字段还没有选项，录入时可以不选']
}

function touchField(idx) {
  touchedFields[idx] = true
}

function presetTypeLabel(type) {
  const g = FIELD_TYPE_GROUPS.flatMap(x => x.types).find(t => t.value === type)
  return g ? g.label : type
}

// 图标兜底：历史数据里存的是 emoji，无法渲染为组件
function safeIcon(name) {
  return ENTITY_ICON_CHOICES.includes(name) ? name : entityIcon(form.key)
}

// ---------- 字段增删改排 ----------
function addField() {
  form.fields.push(makeEmptyField(form.fields))
}

function addPreset(p) {
  form.fields.push(makePresetField(p, form.fields))
  ElMessage.success(`已添加字段「${p.name}」`)
}

function removeField(idx) {
  form.fields.splice(idx, 1)
}

function moveField(idx, dir) {
  const target = idx + dir
  if (target < 0 || target >= form.fields.length) return
  const tmp = form.fields[idx]
  form.fields[idx] = form.fields[target]
  form.fields[target] = tmp
}

function onTypeChange(f) {
  if (isChoiceType(f.type) && !Array.isArray(f.choices)) f.choices = []
  if (!isReferenceType(f.type)) f.target = ''
}

// ---------- 拖拽排序 ----------
const dragIdx = ref(-1)
const dragOverIdx = ref(-1)

function onDragStart(idx) {
  dragIdx.value = idx
}

function onDragOver(idx) {
  if (dragIdx.value >= 0) dragOverIdx.value = idx
}

function onDrop(idx) {
  const from = dragIdx.value
  dragIdx.value = -1
  dragOverIdx.value = -1
  if (from < 0 || from === idx) return
  const moved = form.fields.splice(from, 1)[0]
  form.fields.splice(idx, 0, moved)
}

function onDragEnd() {
  dragIdx.value = -1
  dragOverIdx.value = -1
}

// ---------- 载入 ----------
async function load() {
  loading.value = true
  try {
    const [a, t] = await Promise.all([Api.listApps(), Api.listEntityTypes()])
    apps.value = a || []
    types.value = t || []
    localKeys.value = (t || [])
      .filter(x => Number(x.id) !== Number(props.modelId))
      .map(x => x.key)
    if (props.modelId) {
      const et = await Api.getEntityType(props.modelId)
      Object.assign(form, {
        key: et.key,
        name: et.name,
        icon: et.icon || 'Document',
        description: et.description || '',
        app: et.app || 'default',
        order: et.order || 0,
        fields: toEditorFields(et.fields),
      })
      originalKey.value = et.key
      // 记下哪些字段来自服务端：它们的「没配选项」只提醒，不拦保存
      serverFieldKeys.value = new Set(form.fields.map(f => String(f.key || '').trim()))
    } else {
      Object.assign(form, {
        key: '',
        name: '',
        icon: 'Document',
        description: '',
        app: props.defaultApp || 'default',
        order: 0,
        fields: [makeEmptyField([])],
      })
      originalKey.value = ''
      serverFieldKeys.value = new Set()
    }
    showErrors.value = false
    touchedMeta.key = false
    touchedMeta.name = false
    Object.keys(touchedFields).forEach(k => delete touchedFields[k])
    generateJson()
    // JSON 新建入口：给一份能直接跑的样例，用户改两处就能用
    if (activeTab.value === 'json' && !isEdit.value) await fillExample()
  } catch (e) {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

watch(() => props.modelValue, (v) => {
  if (!v || isInline.value) return
  activeTab.value = props.initialTab
  load()
})

watch(() => props.modelId, () => {
  if (isInline.value) load()
})

onMounted(() => {
  if (isInline.value) load()
})

// ---------- 保存 ----------
async function save() {
  showErrors.value = true

  // JSON 页签被手改过：以 JSON 为准先回写表单，避免「改了 JSON 却保存了旧字段」
  if (activeTab.value === 'json' && jsonDirty.value) {
    const warnings = applyJsonFromText({ silent: true })
    if (warnings === null) {
      ElMessage.error('JSON 有误，请先修正，或点「从表单生成」还原')
      return
    }
    if (warnings.length) ElMessage.info(`已按 JSON 同步表单（自动修正 ${warnings.length} 处）`)
  }

  const v = validateModelForm(form, {
    existingKeys: effectiveExistingKeys.value,
    allowEmptyChoices: toleratedEmptyChoices.value,
  })
  if (!v.ok) {
    ElMessage.warning(v.messages[0] || '请检查表单后再保存')
    // 滚到第一处出错的字段：不然用户只看到一句提示，不知道错在哪
    nextTick(() => {
      rootRef.value?.querySelector('.is-error, .med-form .el-form-item.is-error')
        ?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    })
    return
  }

  const payload = buildModelPayload(form)
  saving.value = true
  try {
    const saved = isEdit.value
      ? await Api.updateEntityType(props.modelId, payload)
      : await Api.createEntityType(payload)
    ElMessage.success(isEdit.value ? '模型已更新' : '模型已创建')
    emit('saved', saved)
    if (!isInline.value) visible.value = false
  } catch (e) {
    // 拦截器已提示
  } finally {
    saving.value = false
  }
}

function onCancel() {
  emit('cancel')
  if (!isInline.value) visible.value = false
}

/**
 * Esc 关闭弹窗
 *
 * Element Plus 的对话框本身监听 Esc，但它挂在 document 上（冒泡阶段）；
 * 而下拉框（el-select）会在自己的键盘处理里 stopPropagation，
 * 结果就是「焦点停在选择框里时按 Esc 关不掉弹窗」。
 * 这里用捕获阶段兜一层：下拉/弹层开着时把 Esc 让给它们，其余情况自己关。
 */
function onDialogKeydown(e) {
  if (e.key !== 'Escape') return
  if (isInline.value) return
  const popperOpen = [...document.querySelectorAll('.el-popper')]
    .some(p => p.offsetParent !== null)
  if (popperOpen) return
  visible.value = false
  emit('cancel')
}

/** 删除当前模型：影响范围（字段数 / 记录数）由 modelDelete 统一提示 */
async function removeModel() {
  const row = types.value.find(t => t.id === Number(props.modelId)) || {}
  deleting.value = true
  let ok = false
  try {
    ok = await confirmAndDeleteModel({
      id: Number(props.modelId),
      key: form.key,
      name: form.name,
      field_count: form.fields.length,
      record_count: row.record_count || 0,
      relation_count: 0,
    })
  } finally {
    deleting.value = false
  }
  if (ok) {
    emit('deleted')
    if (!isInline.value) visible.value = false
  }
}

// ---------- JSON 定义 ↔ 表单 双向同步 ----------
const jsonText = ref('')
const jsonDirty = ref(false)
const jsonError = ref('')
const checkResult = ref(null)
const checking = ref(false)
let skipSync = false

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

/** 编辑器表单 → JSON 用的中间结构 */
function formToJsonModel() {
  return {
    key: form.key,
    name: form.name,
    icon: form.icon,
    description: form.description,
    app: form.app,
    order: form.order,
    fields: form.fields.map(f => ({
      key: f.key,
      name: f.name,
      type: f.type,
      required: f.required,
      options: buildFieldOptions(f),
    })),
  }
}

/** 表单 → JSON（用户没动过 JSON 时才自动覆盖） */
function generateJson() {
  jsonText.value = buildModelJson(formToJsonModel())
  jsonDirty.value = false
  jsonError.value = ''
  checkResult.value = null
}

// 表单改动实时反映到 JSON，让「预览」名副其实
watch(form, () => {
  if (skipSync) { skipSync = false; return }
  if (!jsonDirty.value) jsonText.value = buildModelJson(formToJsonModel())
}, { deep: true, flush: 'post' })

function onJsonInput() {
  jsonDirty.value = true
  checkResult.value = null
  const r = parseLooseJson(jsonText.value)
  jsonError.value = r.ok ? '' : r.error
}

async function fillExample() {
  try {
    const r = await Api.entityTypeExample()
    jsonText.value = r?.json || exampleModelJson()
  } catch (e) {
    jsonText.value = exampleModelJson()
  }
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
      fields: toEditorFields(model.fields),
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
      target_id: isEdit.value ? Number(props.modelId) : null,
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
</script>

<style scoped>
.med-root { width: 100%; }

.med {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

/* ---------- 顶部 ---------- */
.med-head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--border-light);
}
.med-head-icon {
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  border-radius: var(--radius-md);
  background: var(--primary-bg);
  color: var(--primary);
  display: flex;
  align-items: center;
  justify-content: center;
}
.med-head-text { flex: 1; min-width: 0; }
.med-head-title {
  font-size: var(--text-lg);
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.2px;
}
.med-head-sub {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  margin-top: 2px;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}
.med-head-key {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  background: var(--bg-subtle);
  color: var(--text-secondary);
  padding: 1px 8px;
  border-radius: var(--radius-full);
}
.med-head-right {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}
.med-head-count {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}
.med-close {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: var(--radius);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background var(--duration-fast) var(--ease-out);
}
.med-close:hover { background: var(--bg-subtle); color: var(--text-primary); }

/* ---------- 页签 ---------- */
.med-tabs { margin-top: var(--space-2); }
.med-tabs :deep(.el-tabs__header) { margin-bottom: var(--space-3); }
.med-tabs :deep(.el-tabs__item) { font-weight: 600; }
.med-tab-label { display: inline-flex; align-items: center; gap: 6px; }

/* ---------- 左右分栏 ---------- */
.med-grid {
  display: grid;
  grid-template-columns: 268px minmax(0, 1fr);
  gap: var(--space-5);
  align-items: start;
  max-height: min(58vh, 560px);
  overflow-y: auto;
  padding-right: 4px;
}
.med-side {
  position: sticky;
  top: 0;
}
.med-side-title {
  font-size: var(--text-sm);
  font-weight: 700;
  color: var(--text-secondary);
  letter-spacing: 0.3px;
  margin-bottom: var(--space-3);
}
.med-form :deep(.el-form-item) { margin-bottom: var(--space-4); }
.med-form :deep(.el-form-item__label) {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-secondary);
  line-height: 1.6;
  padding-bottom: 4px;
}
.med-full { width: 100%; }
.med-hint {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  line-height: 1.6;
  margin-top: 4px;
}
.med-icon-trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-card);
  color: var(--text-primary);
  cursor: pointer;
}
.med-icon-trigger:hover { border-color: var(--primary); color: var(--primary); }
.med-icon-caret { font-size: 12px; color: var(--text-secondary); }
.med-icon-picker {
  display: grid;
  grid-template-columns: repeat(8, 1fr);
  gap: 4px;
}
.med-icon-choice {
  width: 30px;
  height: 30px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: var(--bg-subtle);
  color: var(--text-secondary);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.med-icon-choice:hover { background: var(--primary-bg); color: var(--primary); }
.med-icon-choice.is-active {
  background: var(--primary-bg-strong);
  border-color: var(--primary);
  color: var(--primary);
}

/* ---------- 字段区 ---------- */
.med-main { min-width: 0; }
.med-main-head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}
.med-main-title {
  font-size: var(--text-sm);
  font-weight: 700;
  color: var(--text-secondary);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.med-badge {
  background: var(--bg-subtle);
  color: var(--text-secondary);
  border-radius: var(--radius-full);
  padding: 0 8px;
  font-size: var(--text-xs);
  font-weight: 600;
}
.med-main-actions {
  margin-left: auto;
  display: flex;
  gap: var(--space-2);
}
.med-preset-name { font-weight: 600; }
.med-preset-hint {
  margin-left: 10px;
  font-size: var(--text-xs);
  color: var(--text-secondary);
}

.med-fields { display: flex; flex-direction: column; gap: var(--space-2); }

.fld {
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--bg-card);
  padding: var(--space-3);
  transition: border-color var(--duration-fast) var(--ease-out), box-shadow var(--duration-fast) var(--ease-out);
}
.fld:hover { border-color: var(--border-strong); }
.fld.is-error { border-color: var(--danger); }
.fld.is-dragging { opacity: 0.5; }
.fld.is-over { border-color: var(--primary); box-shadow: var(--focus-ring-soft); }

.fld-main {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.fld-handle {
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  cursor: grab;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.fld-handle:hover { background: var(--bg-subtle); color: var(--text-primary); }
.fld-handle:active { cursor: grabbing; }

.fld-name { flex: 1; min-width: 120px; }
.fld-type { width: 150px; flex-shrink: 0; }
.fld-flags {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-shrink: 0;
}
.fld-flag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  cursor: pointer;
  white-space: nowrap;
}
.fld-del {
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.fld-del:hover { background: var(--danger-bg); color: var(--danger); }

.fld-sub {
  display: flex;
  gap: var(--space-3);
  margin-top: var(--space-2);
  padding-left: 36px;
  flex-wrap: wrap;
}
.fld-sub-item {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 180px;
}
.fld-sub-item.is-wide { flex: 1; min-width: 240px; }
.fld-sub-label {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  flex-shrink: 0;
  font-weight: 600;
}
.fld-desc {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  margin-top: var(--space-2);
  padding-left: 36px;
  font-size: var(--text-xs);
  line-height: 1.6;
  color: var(--text-secondary);
}
.fld-err {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 6px;
  padding-left: 36px;
  font-size: var(--text-xs);
  color: var(--danger);
  line-height: 1.6;
}
.fld-warn {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 6px;
  padding-left: 36px;
  font-size: var(--text-xs);
  color: var(--warning);
  line-height: 1.6;
}

/* 类型下拉里的说明文案：选型时最有用的信息 */
.type-opt { display: flex; align-items: center; gap: 8px; padding: 2px 0; }
.type-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 18px;
  border-radius: var(--radius-xs);
  font-size: var(--text-xs);
  font-weight: 700;
  color: #fff;
  flex-shrink: 0;
}
.type-opt-text { display: flex; flex-direction: column; line-height: 1.4; }
.type-opt-label { font-size: var(--text-sm); color: var(--text-primary); font-weight: 600; }
.type-opt-desc { font-size: var(--text-xs); color: var(--text-secondary); }

.med-fields-empty {
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-lg);
  padding: var(--space-8) var(--space-5);
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
}
.med-fields-empty-icon { color: var(--text-secondary); }
.med-fields-empty-title { font-weight: 700; color: var(--text-primary); }
.med-fields-empty-desc {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  line-height: 1.7;
  max-width: 460px;
  margin-bottom: var(--space-2);
}

/* ---------- JSON 页签 ---------- */
.med-json { max-height: min(58vh, 560px); overflow-y: auto; padding-right: 4px; }
.med-json-head {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
  flex-wrap: wrap;
}
.med-json-head-text {
  flex: 1;
  min-width: 240px;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  line-height: 1.7;
}
.med-json-head-text code {
  font-family: var(--font-mono);
  background: var(--bg-subtle);
  padding: 0 4px;
  border-radius: var(--radius-xs);
}
.med-json-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.med-json-state {
  font-size: var(--text-xs);
  padding: 2px 9px;
  border-radius: var(--radius-full);
  background: var(--bg-subtle);
  color: var(--text-secondary);
  white-space: nowrap;
}
.med-json-state.is-ok { background: var(--success-bg); color: var(--success); }
.med-json-state.is-dirty { background: var(--warning-bg); color: var(--warning); }
.med-json-state.is-error { background: var(--danger-bg); color: var(--danger); }
.med-json-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-4);
  align-items: start;
}
.med-json-col { min-width: 0; }
.med-json-label {
  font-size: var(--text-xs);
  font-weight: 700;
  color: var(--text-secondary);
  letter-spacing: 0.3px;
  margin-bottom: 6px;
}
.med-json-input :deep(.el-textarea__inner) {
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.7;
  tab-size: 2;
}
.med-json-check {
  margin-top: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.med-json-block {
  padding: 10px 12px;
  border-radius: var(--radius);
  font-size: var(--text-sm);
  line-height: 1.7;
}
.med-json-block-title { display: flex; align-items: center; gap: 6px; font-weight: 700; }
.med-json-block ul { margin: 6px 0 0; padding-left: 20px; }
.med-json-block.is-ok { background: var(--success-bg); color: var(--success); }
.med-json-block.is-warn { background: var(--warning-bg); color: var(--warning); }
.med-json-block.is-error { background: var(--danger-bg); color: var(--danger); }

/* ---------- 底部动作 ---------- */
.med-actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding-top: var(--space-3);
  margin-top: var(--space-3);
  border-top: 1px solid var(--border-light);
}
.med-actions-left { flex: 1; min-width: 0; }
.med-actions-right {
  display: flex;
  gap: var(--space-2);
  flex-shrink: 0;
}

/* ---------- 弹窗外壳 ---------- */
/* el-dialog 默认渲染在当前组件位置（未 append-to-body），
   所以这里能用 :deep 命中它内部的排版 */
.med-root :deep(.med-dialog .el-dialog__header) { display: none; }
.med-root :deep(.med-dialog .el-dialog__body) { padding: 20px 22px; }
.med-root :deep(.med-dialog) { border-radius: var(--radius-xl); }

.med-inline {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: var(--space-5);
}

/* 窄屏：左右分栏上下堆叠 */
@media (max-width: 900px) {
  .med-grid { grid-template-columns: 1fr; }
  .med-side { position: static; }
  .med-json-grid { grid-template-columns: 1fr; }
}
</style>
