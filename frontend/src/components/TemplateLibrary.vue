<template>
  <!--
    模板库抽屉：左侧模板列表 + 右侧「会生成什么」的预览。
    为什么要独立于「新建应用」弹窗：
    之前想看模板长什么样，必须先点开「新建应用」再切到「选模板」，
    等于把「了解产品」和「创建东西」这两件事绑死在一起。
    拆成抽屉后，看模板不要成本，套用也只多一次点击。
  -->
  <el-drawer
    :model-value="modelValue"
    :size="drawerSize"
    direction="rtl"
    class="tpl-drawer"
    :with-header="false"
    @update:model-value="$emit('update:modelValue', $event)"
    @closed="onClosed"
  >
    <div class="tpl-head">
      <div class="tpl-head-text">
        <div class="tpl-head-title">模板库</div>
        <div class="tpl-head-desc">
          选一个业务场景，系统直接生成对应的数据模型、字段与关联关系
        </div>
      </div>
      <el-button class="tpl-close" text @click="close" aria-label="关闭模板库">
        <el-icon><Close /></el-icon>
      </el-button>
    </div>

    <div v-if="loading" class="tpl-body">
      <el-skeleton :rows="6" animated />
    </div>

    <div v-else-if="loadError" class="tpl-body">
      <div class="empty-state">
        <div class="empty-icon"><el-icon :size="30"><Warning /></el-icon></div>
        <div class="empty-title">模板加载失败</div>
        <div class="empty-desc">{{ loadError }}</div>
        <div class="empty-actions">
          <el-button @click="load">重试</el-button>
        </div>
      </div>
    </div>

    <div v-else class="tpl-body">
      <!-- 左：模板列表 -->
      <div class="tpl-list" role="list">
        <div
          v-for="t in templates"
          :key="t.key"
          class="tpl-row"
          :class="{ active: t.key === currentKey }"
          role="button"
          tabindex="0"
          :aria-pressed="t.key === currentKey"
          @click="select(t)"
          @keydown.enter.prevent="select(t)"
          @keydown.space.prevent="select(t)"
        >
          <div class="tpl-row-icon"><el-icon :size="18"><component :is="t.icon" /></el-icon></div>
          <div class="tpl-row-text">
            <div class="tpl-row-name">{{ t.name }}</div>
            <div class="tpl-row-count">{{ t.type_count }} 模型 · {{ t.field_count }} 字段</div>
          </div>
        </div>
      </div>

      <!-- 右：预览 -->
      <div class="tpl-preview">
        <template v-if="current">
          <div class="tpl-preview-head">
            <div class="tpl-preview-icon"><el-icon :size="20"><component :is="current.icon" /></el-icon></div>
            <div>
              <div class="tpl-preview-name">{{ current.name }}</div>
              <div class="tpl-preview-desc">{{ current.description }}</div>
            </div>
          </div>

          <div class="tpl-stats">
            <span class="tpl-stat"><b>{{ current.type_count }}</b> 个模型</span>
            <span class="tpl-stat"><b>{{ current.field_count }}</b> 个字段</span>
            <span class="tpl-stat"><b>{{ current.relation_count || 0 }}</b> 条关联</span>
          </div>

          <div class="tpl-sub-title">会生成这些模型</div>
          <div class="tpl-models">
            <div v-for="m in current.types" :key="m.key" class="tpl-model">
              <div class="tpl-model-head">
                <el-icon :size="15"><component :is="m.icon || 'Grid'" /></el-icon>
                <span class="tpl-model-name">{{ m.name }}</span>
                <span class="tpl-model-key">{{ current.key }}_{{ m.key }}</span>
                <span class="tpl-model-count">{{ m.field_count || 0 }} 字段</span>
              </div>
              <!-- 字段明细：接口补上 fields 后这里自动展开，现在只给字段数 -->
              <div v-if="m.fields && m.fields.length" class="tpl-fields">
                <span v-for="f in m.fields" :key="f.key" class="tpl-field">{{ f.name }}</span>
              </div>
              <div v-else class="tpl-fields-hint">
                字段明细需要后端模板接口补充（当前只返回字段数量）
              </div>
            </div>
          </div>

          <div v-if="!current.types.length" class="tpl-blank">
            这是空白应用，不预置任何模型，创建后从零开始定义。
          </div>

          <!-- 套用：create 模式直接建应用，pick 模式把模板交回给新建弹窗 -->
          <div v-if="mode === 'create'" class="tpl-form">
            <div class="tpl-sub-title">创建应用</div>
            <div class="tpl-form-row">
              <label class="tpl-label" for="tpl-key">Key</label>
              <el-input id="tpl-key" v-model="form.key" placeholder="英文唯一标识，如 crm" />
            </div>
            <div class="tpl-form-row">
              <label class="tpl-label" for="tpl-name">名称</label>
              <el-input id="tpl-name" v-model="form.name" placeholder="应用名称" />
            </div>
            <div class="tpl-form-row">
              <label class="tpl-label" for="tpl-desc">说明</label>
              <el-input id="tpl-desc" v-model="form.description" type="textarea" :rows="2" placeholder="这个应用用来做什么" />
            </div>
            <div class="tpl-hint">
              Key 创建后不可修改；模型 Key 会以它为前缀生成
              <code v-if="form.key">{{ form.key }}_…</code>
            </div>
          </div>
        </template>

        <div v-else class="tpl-blank">从左侧选一个模板，看看它会生成什么</div>
      </div>
    </div>

    <template #footer>
      <div class="tpl-foot">
        <el-button @click="close">取消</el-button>
        <el-button
          v-if="mode === 'pick'"
          type="primary"
          :disabled="!current"
          @click="useTemplate"
        >使用这个模板</el-button>
        <el-button
          v-else
          type="primary"
          :loading="creating"
          :disabled="!current || !form.key.trim() || !form.name.trim()"
          @click="create"
        >按模板创建</el-button>
      </div>
    </template>
  </el-drawer>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Close, Warning } from '@element-plus/icons-vue'
import { Api } from '../api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  // create = 抽屉里直接建应用；pick = 把选中的模板交回给「新建应用」弹窗
  mode: { type: String, default: 'create' },
  // 已存在的应用 Key，用来在建之前就拦住重名
  existingKeys: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:modelValue', 'pick', 'created'])

const templates = ref([])
const loading = ref(false)
const loadError = ref('')
const creating = ref(false)
const currentKey = ref('')
const form = ref({ key: '', name: '', description: '' })

// 小屏用相对宽度，避免抽屉在窄屏上把内容挤成一条缝
const drawerSize = computed(() => 'min(940px, 96vw)')

const current = computed(() => templates.value.find(t => t.key === currentKey.value) || null)

watch(() => props.modelValue, (open) => {
  if (!open) return
  // 每次打开都重置表单：上次填了一半的 Key 不该留到下一次
  form.value = { key: '', name: '', description: '' }
  if (!templates.value.length) load()
}, { immediate: true })

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    templates.value = await Api.listAppTemplates()
    if (!currentKey.value && templates.value.length) {
      select(templates.value.find(t => t.key !== 'blank') || templates.value[0])
    }
  } catch (e) {
    loadError.value = e?.response?.data?.detail || '模板服务暂时不可用，请稍后再试'
    templates.value = []
  } finally {
    loading.value = false
  }
}

function select(t) {
  currentKey.value = t.key
  if (props.mode !== 'create') return
  // 模板的风格先带进表单，用户能少打几个字
  form.value.name = t.name
  form.value.description = t.description || ''
  form.value.key = t.key === 'blank' ? '' : t.key
}

function close() {
  emit('update:modelValue', false)
}

function onClosed() {
  /* 抽屉关闭动画结束后不需要额外清理，状态下次打开时重置 */
}

function useTemplate() {
  if (!current.value) return
  emit('pick', current.value)
  close()
}

async function create() {
  const key = form.value.key.trim()
  const name = form.value.name.trim()
  if (!key || !name) {
    ElMessage.warning('请填写应用 Key 与名称')
    return
  }
  if (!/^[a-zA-Z][a-zA-Z0-9_]*$/.test(key)) {
    ElMessage.warning('Key 只能用英文字母、数字、下划线，且以字母开头')
    return
  }
  if (props.existingKeys.includes(key)) {
    ElMessage.warning(`应用 Key「${key}」已被占用，请换一个`)
    return
  }
  creating.value = true
  try {
    const r = await Api.createAppFromTemplate({
      template: current.value.key,
      key,
      name,
      description: form.value.description,
      icon: current.value.icon,
    })
    ElMessage.success(`已按「${current.value.name}」创建：${r.types?.length || 0} 个模型`)
    emit('created', r)
    close()
  } catch (e) {
    ElMessage.error('创建失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    creating.value = false
  }
}
</script>

<style scoped>
.tpl-head {
  display: flex;
  align-items: flex-start;
  gap: var(--space-4);
  padding-bottom: var(--space-4);
  border-bottom: 1px solid var(--border-light);
}
.tpl-head-text { flex: 1; min-width: 0; }
.tpl-head-title {
  font-size: var(--text-xl);
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.3px;
}
.tpl-head-desc {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  margin-top: 4px;
  line-height: 1.6;
}
.tpl-close {
  min-width: 30px;
  min-height: 30px;
  padding: 0;
  color: var(--text-secondary);
}

.tpl-body {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: var(--space-5);
  min-height: 380px;
}

.tpl-list {
  border-right: 1px solid var(--border-light);
  padding-right: var(--space-3);
  overflow-y: auto;
  max-height: 62vh;
}
.tpl-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  border-radius: var(--radius);
  border: 1px solid transparent;
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out), border-color var(--duration-fast) var(--ease-out);
}
.tpl-row:hover { background: var(--surface-hover); }
.tpl-row:focus-visible {
  outline: 2px solid var(--focus-ring-color);
  outline-offset: 2px;
}
.tpl-row.active {
  background: var(--primary-bg);
  border-color: var(--primary-200);
}
.tpl-row-icon {
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border-radius: var(--radius-sm);
  background: var(--primary-bg);
  color: var(--primary-dark);
  display: flex;
  align-items: center;
  justify-content: center;
}
.tpl-row-text { min-width: 0; }
.tpl-row-name {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
}
.tpl-row-count {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  margin-top: 2px;
}

.tpl-preview { min-width: 0; }
.tpl-preview-head {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}
.tpl-preview-icon {
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  border-radius: var(--radius);
  background: var(--primary-bg);
  color: var(--primary-dark);
  display: flex;
  align-items: center;
  justify-content: center;
}
.tpl-preview-name {
  font-size: var(--text-lg);
  font-weight: 700;
  color: var(--text-primary);
}
.tpl-preview-desc {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  margin-top: 3px;
  line-height: 1.6;
}

.tpl-stats {
  display: flex;
  gap: var(--space-4);
  padding: var(--space-3) 0;
  border-top: 1px solid var(--border-light);
  border-bottom: 1px solid var(--border-light);
  margin-bottom: var(--space-4);
}
.tpl-stat {
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
.tpl-stat b {
  color: var(--text-primary);
  font-size: var(--text-md);
  margin-right: 4px;
}

.tpl-sub-title {
  font-size: var(--text-sm);
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: var(--space-2);
}
.tpl-models { display: flex; flex-direction: column; gap: var(--space-2); }
.tpl-model {
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  padding: var(--space-3);
  background: var(--bg-subtle);
}
.tpl-model-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--text-secondary);
}
.tpl-model-name {
  font-weight: 600;
  color: var(--text-primary);
  font-size: var(--text-sm);
}
.tpl-model-key {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-secondary);
}
.tpl-model-count {
  margin-left: auto;
  font-size: var(--text-xs);
  color: var(--text-secondary);
}
.tpl-fields {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: var(--space-2);
}
.tpl-field {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-xs);
  padding: 1px 6px;
}
.tpl-fields-hint {
  margin-top: var(--space-2);
  font-size: var(--text-xs);
  color: var(--text-secondary);
}

.tpl-blank {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  padding: var(--space-5) 0;
}

.tpl-form { margin-top: var(--space-5); }
.tpl-form-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}
.tpl-label {
  width: 44px;
  flex-shrink: 0;
  text-align: right;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  padding-top: 7px;
}
.tpl-hint {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  line-height: 1.6;
}
.tpl-hint code {
  font-family: var(--font-mono);
  background: var(--bg-subtle);
  padding: 1px 4px;
  border-radius: 3px;
}

.tpl-foot { display: flex; justify-content: flex-end; gap: var(--space-2); }

@media (max-width: 760px) {
  .tpl-body { grid-template-columns: 1fr; }
  .tpl-list { border-right: none; border-bottom: 1px solid var(--border-light); padding-right: 0; max-height: 200px; }
}
</style>
