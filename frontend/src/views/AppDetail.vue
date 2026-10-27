<template>
  <!--
    应用详情抽屉：以前是一个独立页面，点进去就要离开列表、回退又要点一次。
    改成抽屉后，浏览列表与查看详情可以同时进行 —— 这也是 Airtable / 飞书多维表格的常见做法。

    兼容说明：旧地址 /apps/:appKey 仍然可用 —— 以路由方式打开时组件会自动
    跳回 /apps?app=xxx，由应用中心打开同一个抽屉，不会留下半截页面。
  -->
  <el-drawer
    :model-value="modelValue"
    :size="drawerSize"
    direction="rtl"
    class="ad-drawer"
    :with-header="false"
    @update:model-value="$emit('update:modelValue', $event)"
    @open="onOpen"
  >
    <div v-if="app" class="ad">
      <!-- 头部：图标 + 名称 + Key + 分组 -->
      <div class="ad-head">
        <div class="ad-icon"><el-icon :size="22"><component :is="iconName" /></el-icon></div>
        <div class="ad-head-text">
          <div class="ad-name">{{ app.name }}</div>
          <div class="ad-key">{{ app.key }}</div>
        </div>
        <span v-if="group && group !== DEFAULT_GROUP" class="ad-group">{{ group }}</span>
        <el-button class="ad-close" text aria-label="关闭详情" @click="close">
          <el-icon><Close /></el-icon>
        </el-button>
      </div>

      <p class="ad-desc">{{ description }}</p>

      <!-- 统计 -->
      <div class="ad-stats">
        <div class="ad-stat">
          <div class="ad-stat-value">{{ models.length }}</div>
          <div class="ad-stat-label">数据模型</div>
        </div>
        <div class="ad-stat">
          <div class="ad-stat-value">{{ totalRecords }}</div>
          <div class="ad-stat-label">数据记录</div>
        </div>
        <div class="ad-stat">
          <div class="ad-stat-value">{{ totalFields }}</div>
          <div class="ad-stat-label">字段总数</div>
        </div>
      </div>

      <!-- 主操作 -->
      <div class="ad-actions">
        <el-button
          type="primary"
          :disabled="!canManage"
          @click="newModel"
        >
          <el-icon><Plus /></el-icon>新建模型
        </el-button>
        <el-button :disabled="!canManage || !models.length" @click="addRecord">
          <el-icon><EditPen /></el-icon>录入记录
        </el-button>
        <el-button :disabled="!canManage" @click="$emit('edit', app)">
          <el-icon><Edit /></el-icon>编辑应用
        </el-button>
      </div>

      <!-- 数据模型 -->
      <div class="ad-section">
        <div class="ad-section-title">
          <el-icon><Files /></el-icon>数据模型
          <span class="badge badge-ghost">{{ models.length }}</span>
        </div>

        <div v-if="loading" class="ad-loading">
          <el-skeleton :rows="3" animated />
        </div>

        <div v-else-if="models.length" class="ad-models">
          <div
            v-for="m in models"
            :key="m.id"
            class="ad-model"
            role="button"
            tabindex="0"
            @click="openRecords(m)"
            @keydown.enter.prevent="openRecords(m)"
            @keydown.space.prevent="openRecords(m)"
          >
            <div class="ad-model-icon"><el-icon :size="16"><component :is="m.icon || 'Grid'" /></el-icon></div>
            <div class="ad-model-text">
              <div class="ad-model-name">{{ m.name }}</div>
              <div class="ad-model-meta">{{ m.key }} · {{ m.field_count || 0 }} 字段</div>
            </div>
            <div class="ad-model-count">
              <span class="ad-model-count-num">{{ m.record_count || 0 }}</span>
              <span class="ad-model-count-label">记录</span>
            </div>
            <el-tooltip content="编辑模型" placement="top" :show-after="400">
              <el-button
                class="ad-model-edit"
                text
                :disabled="!canManage"
                @click.stop="editModel(m)"
              >
                <el-icon><Setting /></el-icon>
              </el-button>
            </el-tooltip>
          </div>
        </div>

        <div v-else class="empty-state">
          <div class="empty-icon"><el-icon :size="30"><Files /></el-icon></div>
          <div class="empty-title">这个应用还没有数据模型</div>
          <div class="empty-desc">
            数据模型定义了这张「表」有哪些字段，建好之后就能录入和管理业务数据。
          </div>
          <div class="empty-actions">
            <el-button type="primary" :disabled="!canManage" @click="newModel">
              <el-icon><Plus /></el-icon>新建模型
            </el-button>
          </div>
        </div>
      </div>

      <!-- 关联 -->
      <div class="ad-section">
        <div class="ad-section-title">
          <el-icon><Connection /></el-icon>关联
          <span class="badge badge-ghost">{{ relations.length }}</span>
        </div>
        <div v-if="relations.length" class="ad-relations">
          <div v-for="r in relations" :key="r.id" class="ad-relation">
            <span class="ad-relation-name">{{ r.name }}</span>
            <span class="ad-relation-path">{{ r.source_label }} → {{ r.target_label }}</span>
            <span class="ad-relation-count">{{ r.link_count || 0 }} 条数据</span>
          </div>
        </div>
        <div v-else class="ad-hint">
          这个应用里的模型之间还没有关联关系。关联定义在「关联」页面维护。
        </div>
      </div>

      <!-- 最近记录 -->
      <div v-if="recent.length" class="ad-section">
        <div class="ad-section-title"><el-icon><Clock /></el-icon>最近记录</div>
        <div class="ad-recent">
          <div
            v-for="r in recent"
            :key="`${r.entity_type_id}-${r.record_id}`"
            class="ad-recent-row"
            role="button"
            tabindex="0"
            @click="openRecord(r)"
            @keydown.enter.prevent="openRecord(r)"
          >
            <span class="ad-recent-type">{{ r.entity_type_name }}</span>
            <span class="ad-recent-name">{{ recordTitle(r) }}</span>
            <span class="ad-recent-time">{{ formatTime(r.updated_at) }}</span>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="ad ad-loading">
      <el-skeleton :rows="5" animated />
    </div>
  </el-drawer>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Clock, Close, Connection, Edit, EditPen, Files, Plus, Setting,
} from '@element-plus/icons-vue'
import { Api } from '../api'
import { formatTime } from '../utils/format'
import { DEFAULT_GROUP, appDescription, resolveAppIcon } from '../utils/apps'
import { APP_ICON_CHOICES } from '../utils/icons'

const props = defineProps({
  modelValue: { type: Boolean, default: undefined },
  app: { type: Object, default: null },
  // null = 还没加载（组件自己去查）；数组 = 父级已经查好（省一次请求）
  models: { type: Array, default: null },
  group: { type: String, default: '' },
  canManage: { type: Boolean, default: true },
})

const emit = defineEmits(['update:modelValue', 'edit', 'remove'])

const route = useRoute()
const router = useRouter()

const localModels = ref([])
const relations = ref([])
const recent = ref([])
const loading = ref(false)

const drawerSize = computed(() => 'min(560px, 96vw)')

const models = computed(() => props.models ?? localModels.value)
const iconName = computed(() => resolveAppIcon(props.app, APP_ICON_CHOICES))
const description = computed(() => appDescription(props.app))
const totalRecords = computed(() => models.value.reduce((s, m) => s + (m.record_count || 0), 0))
const totalFields = computed(() => models.value.reduce((s, m) => s + (m.field_count || 0), 0))

// 独立路由打开时（老地址 /apps/xxx）：跳回应用中心并由它打开同一个抽屉
watch(() => props.modelValue, (v) => {
  if (v === undefined) {
    const key = route.params.appKey
    router.replace({ path: '/apps', query: key ? { app: key } : {} })
  }
}, { immediate: true })

async function onOpen() {
  relations.value = []
  recent.value = []
  if (props.models === null) {
    loading.value = true
    try {
      localModels.value = await Api.listEntityTypes(props.app.key)
    } catch {
      localModels.value = []
    } finally {
      loading.value = false
    }
  }
  loadRelations()
  loadRecent()
}

// 关联定义是全局的一张表，这里只挑出本应用模型之间的那些
async function loadRelations() {
  try {
    const ids = new Set(models.value.map(m => m.id))
    const defs = await Api.listRelationDefs()
    relations.value = (defs || []).filter(
      d => ids.has(d.source_type_id) || ids.has(d.target_type_id))
  } catch {
    relations.value = []
  }
}

// 最近记录：只取前几个模型、每个模型几条，避免抽屉一打开就发一堆请求
async function loadRecent() {
  const withRecords = models.value.filter(m => (m.record_count || 0) > 0).slice(0, 3)
  if (!withRecords.length) return
  const out = []
  await Promise.all(withRecords.map(async (m) => {
    try {
      const r = await Api.listRecords(m.id, { page_size: 3 })
      for (const rec of (r.items || [])) {
        out.push({
          record_id: rec.id,
          entity_type_id: m.id,
          entity_type_name: m.name,
          data: rec.data || {},
          updated_at: rec.updated_at,
        })
      }
    } catch { /* 单个模型取不到不该拖垮整个抽屉 */ }
  }))
  out.sort((a, b) => new Date(b.updated_at || 0) - new Date(a.updated_at || 0))
  recent.value = out.slice(0, 6)
}

function recordTitle(r) {
  const d = r.data || {}
  return d.name || d.title || d.code || `#${r.record_id}`
}

function close() {
  emit('update:modelValue', false)
}

function newModel() {
  router.push({ path: '/types/new', query: { app: props.app.key } })
  close()
}

function editModel(m) {
  router.push(`/types/${m.id}/edit`)
  close()
}

function openRecords(m) {
  router.push(`/records/${m.id}`)
  close()
}

function openRecord(r) {
  router.push(`/records/${r.entity_type_id}?id=${r.record_id}`)
  close()
}

function addRecord() {
  const first = models.value.find(m => (m.record_count || 0) > 0) || models.value[0]
  if (!first) return
  router.push(`/records/${first.id}`)
  close()
}
</script>

<style scoped>
.ad { display: flex; flex-direction: column; gap: var(--space-4); }

.ad-head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.ad-icon {
  width: 42px;
  height: 42px;
  flex-shrink: 0;
  border-radius: var(--radius);
  background: var(--primary-bg);
  color: var(--primary-dark);
  display: flex;
  align-items: center;
  justify-content: center;
}
.ad-head-text { flex: 1; min-width: 0; }
.ad-name {
  font-size: var(--text-lg);
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ad-key {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  margin-top: 2px;
}
.ad-group {
  flex-shrink: 0;
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--primary-dark);
  background: var(--primary-bg);
  border: 1px solid var(--primary-200);
  padding: 2px 8px;
  border-radius: var(--radius-full);
}
.ad-close {
  min-width: 30px;
  min-height: 30px;
  padding: 0;
  color: var(--text-secondary);
}

.ad-desc {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  line-height: 1.7;
}

.ad-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-2);
}
.ad-stat {
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  padding: var(--space-3);
}
.ad-stat-value {
  font-size: var(--text-xl);
  font-weight: 700;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}
.ad-stat-label {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  margin-top: 2px;
}

.ad-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }

.ad-section { margin-top: var(--space-2); }
.ad-section-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: var(--space-3);
}
.ad-section-title .el-icon { color: var(--primary); }

.ad-models { display: flex; flex-direction: column; gap: var(--space-2); }
.ad-model {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out), border-color var(--duration-fast) var(--ease-out);
}
.ad-model:hover { background: var(--surface-hover); border-color: var(--border); }
.ad-model:focus-visible {
  outline: 2px solid var(--focus-ring-color);
  outline-offset: 2px;
}
.ad-model-icon {
  width: 30px;
  height: 30px;
  flex-shrink: 0;
  border-radius: var(--radius-sm);
  background: var(--primary-bg);
  color: var(--primary-dark);
  display: flex;
  align-items: center;
  justify-content: center;
}
.ad-model-text { flex: 1; min-width: 0; }
.ad-model-name {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ad-model-meta {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ad-model-count { text-align: right; flex-shrink: 0; }
.ad-model-count-num {
  display: block;
  font-size: var(--text-md);
  font-weight: 700;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
}
.ad-model-count-label { font-size: var(--text-xs); color: var(--text-secondary); }
.ad-model-edit {
  min-width: 30px;
  min-height: 30px;
  padding: 0;
  color: var(--text-secondary);
  flex-shrink: 0;
}

.ad-relations { display: flex; flex-direction: column; gap: var(--space-2); }
.ad-relation {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  font-size: var(--text-sm);
}
.ad-relation-name { font-weight: 600; color: var(--text-primary); }
.ad-relation-path { color: var(--text-secondary); }
.ad-relation-count { margin-left: auto; color: var(--text-secondary); font-size: var(--text-xs); }
.ad-hint {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  line-height: 1.7;
}

.ad-recent { display: flex; flex-direction: column; gap: var(--space-1); }
.ad-recent-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius);
  cursor: pointer;
  font-size: var(--text-sm);
}
.ad-recent-row:hover { background: var(--surface-hover); }
.ad-recent-row:focus-visible {
  outline: 2px solid var(--focus-ring-color);
  outline-offset: 2px;
}
.ad-recent-type {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  background: var(--bg-subtle);
  padding: 1px 8px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}
.ad-recent-name {
  color: var(--text-primary);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ad-recent-time {
  margin-left: auto;
  font-size: var(--text-xs);
  color: var(--text-secondary);
  flex-shrink: 0;
}

.ad-loading { padding: var(--space-2); }
</style>
