<template>
  <div class="page">
    <PageTitle
      title="全局搜索"
      subtitle="跨所有实体类型的全文检索 · 支持笔记、记录、文件"
      icon-key="Search"
    >
      <el-input
        v-model="kw"
        placeholder="输入关键字、回车搜索…"
        size="large"
        clearable
        @keyup.enter="search"
        @clear="recordResults = []; docResults = []"
        class="hero-search"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
        <template #append>
          <el-button type="primary" @click="search">搜索</el-button>
        </template>
      </el-input>
    </PageTitle>

    <!-- 搜索建议 -->
    <div v-if="!kw && !totalCount && !loading" class="card suggest-card">
      <div class="card-title">
        <span class="card-title-text">
          <el-icon class="title-ico"><InfoFilled /></el-icon>你可以试试搜索
        </span>
      </div>
      <div class="suggest-chips">
        <el-tag
          v-for="s in SUGGESTIONS"
          :key="s"
          class="suggest-chip"
          effect="plain"
          @click="kw = s; search()"
        >
          {{ s }}
        </el-tag>
      </div>
      <div class="search-hint">
        <el-icon><InfoFilled /></el-icon>
        搜索基于标题字段和全文索引；中英文均支持
      </div>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="empty-state" style="border:none;background:transparent">
      <div class="empty-icon"><el-icon :size="28"><Loading /></el-icon></div>
      <div class="empty-title">搜索中…</div>
    </div>

    <!-- 无结果 -->
    <div v-else-if="kw && !totalCount" class="empty-state">
      <div class="empty-icon"><el-icon :size="32"><Search /></el-icon></div>
      <div class="empty-title">没有找到与「{{ kw }}」相关的结果</div>
      <div class="empty-desc">试试用更短的关键字，或检查拼写</div>
      <div class="suggest-chips" style="justify-content:center;margin-top:12px">
        <el-tag
          v-for="s in SUGGESTIONS.slice(0, 4)"
          :key="s"
          class="suggest-chip"
          effect="plain"
          @click="kw = s; search()"
        >
          {{ s }}
        </el-tag>
      </div>
    </div>

    <!-- 结果 -->
    <div v-else-if="totalCount">
      <div class="result-stats">
        共 <strong>{{ totalCount }}</strong> 条结果 ·
        记录 <strong>{{ recordResults.length }}</strong> ·
        文件 <strong>{{ docResults.length }}</strong> ·
        关键字 <strong>{{ kw }}</strong>
      </div>

      <!-- 文件命中 -->
      <div v-if="docResults.length" class="card result-group">
        <div class="card-title">
          <span class="card-title-text">
            <span class="result-type-icon" style="background:var(--warning-bg);color:var(--warning)">
              <el-icon :size="16"><Coin /></el-icon>
            </span>
            <span>文件</span>
          </span>
          <span class="badge badge-ghost">{{ docResults.length }}</span>
        </div>
        <div
          v-for="d in docResults"
          :key="'doc' + d.id"
          class="result-item"
          @click="openDoc(d)"
        >
          <div class="result-icon" style="background:var(--warning-bg);color:var(--warning)">
            <el-icon :size="18"><component :is="docIcon(d)" /></el-icon>
          </div>
          <div class="result-info">
            <div class="result-title" v-html="highlight(d.title || d.filename)"></div>
            <div class="result-snippet" v-html="highlight(d.snippet || d.summary || '')"></div>
            <div class="result-meta">
              <el-tag size="small" effect="plain">{{ d.kind || 'file' }}</el-tag>
              <el-tag
                v-for="m in (d.matched_by || [])"
                :key="m"
                size="small"
                type="info"
                effect="plain"
              >{{ m === 'semantic' ? '语义命中' : m === 'keyword' ? '关键词命中' : m }}</el-tag>
              <span class="result-id">{{ formatSize(d.size) }}</span>
            </div>
          </div>
          <el-icon class="result-arrow"><ArrowRight /></el-icon>
        </div>
      </div>

      <div
        v-for="(group, gkey) in groupedResults"
        :key="gkey"
        class="card result-group"
      >
        <div class="card-title">
          <span class="card-title-text">
            <span class="result-type-icon" :style="{ background: group.bg, color: group.color }">
              <el-icon :size="16"><component :is="group.icon" /></el-icon>
            </span>
            <span>{{ gkey }}</span>
          </span>
          <span class="badge badge-ghost">{{ group.items.length }}</span>
        </div>
        <div
          v-for="r in group.items"
          :key="r.record_id"
          class="result-item"
          @click="go(r)"
        >
          <div class="result-icon" :style="{ background: group.bg, color: group.color }">
            <el-icon :size="18"><component :is="group.icon" /></el-icon>
          </div>
          <div class="result-info">
            <div class="result-title" v-html="highlight(getDisplayName(r))"></div>
            <div class="result-snippet" v-html="highlight(r.snippet)"></div>
            <div class="result-meta">
              <el-tag size="small" effect="plain">{{ r.entity_type_name }}</el-tag>
              <span class="result-id">#{{ r.record_id }}</span>
            </div>
          </div>
          <el-icon class="result-arrow"><ArrowRight /></el-icon>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Api } from '../api'
import { formatSize } from '../utils/format'
import { entityIcon } from '../utils/icons'
import PageTitle from '../components/PageTitle.vue'

const route = useRoute()
const router = useRouter()
const kw = ref('')
const recordResults = ref([])
const docResults = ref([])
const loading = ref(false)

const totalCount = computed(() => recordResults.value.length + docResults.value.length)

const SUGGESTIONS = [
  '笔记', '项目', '合同', '客户', '任务', 'Obsidian', '知识库', '演示',
  '测试', '上传', 'Q4', '元数据',
]

function getDisplayName(r) {
  return r.data?.name || r.data?.title || r.data?.code || `#${r.record_id}`
}

function groupStyle(key) {
  const map = {
    note: { icon: 'Notebook', bg: 'var(--primary-bg)', color: 'var(--primary)' },
    project: { icon: 'Document', bg: 'rgba(59,130,246,.10)', color: '#3b82f6' },
    task: { icon: 'List', bg: 'rgba(59,130,246,.10)', color: '#3b82f6' },
    customer: { icon: 'User', bg: 'rgba(16,185,129,.10)', color: '#10b981' },
    opportunity: { icon: 'ShoppingCart', bg: 'rgba(245,158,11,.10)', color: '#f59e0b' },
    order: { icon: 'Box', bg: 'rgba(245,158,11,.10)', color: '#f59e0b' },
    contract: { icon: 'Files', bg: 'rgba(239,68,68,.10)', color: '#ef4444' },
    payment: { icon: 'Money', bg: 'rgba(6,182,212,.10)', color: '#06b6d4' },
  }
  return map[key] || { icon: 'Document', bg: 'var(--primary-bg)', color: 'var(--primary)' }
}

const groupedResults = computed(() => {
  const map = {}
  for (const r of recordResults.value) {
    const key = r.entity_type_name || r.entity_type_key
    if (!map[key]) {
      const style = groupStyle(r.entity_type_key)
      map[key] = { ...style, items: [] }
    }
    map[key].items.push(r)
  }
  return map
})

function go(r) {
  if (r.entity_type_key === 'note') {
    router.push(`/notes/${r.record_id}`)
  } else {
    router.push(`/records/${r.entity_type_id}?id=${r.record_id}`)
  }
}

function highlight(text) {
  if (!text) return ''
  const safeKw = kw.value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const re = new RegExp(`(${safeKw})`, 'gi')
  return text.replace(re, '<mark>$1</mark>')
}

async function search() {
  if (!kw.value.trim()) {
    recordResults.value = []
    docResults.value = []
    return
  }
  loading.value = true
  try {
    const r = await Api.search(kw.value.trim())
    // 兼容旧返回（数组）与新返回（{records, documents}）
    if (Array.isArray(r)) {
      recordResults.value = r
      docResults.value = []
    } else {
      recordResults.value = r.records || []
      docResults.value = r.documents || []
    }
  } finally {
    loading.value = false
  }
}

function docIcon(d) {
  const k = d.kind
  if (k === 'image') return 'Picture'
  if (k === 'video') return 'VideoCamera'
  if (k === 'audio') return 'Headset'
  return 'Document'
}

// 跳转到数据中心并自动打开该文件的预览
function openDoc(d) {
  router.push({ path: '/library', query: { doc: String(d.id) } })
}

onMounted(() => {
  if (route.query.kw) {
    kw.value = route.query.kw
    search()
  }
})
</script>

<style scoped>
.hero-search { width: 480px; }

.suggest-card { padding: 20px 24px; }
.search-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: var(--space-4);
  color: var(--text-tertiary);
  font-size: var(--text-sm);
}
.suggest-chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.suggest-chip {
  cursor: pointer;
  padding: 6px 14px;
  font-size: var(--text-sm);
  border-radius: var(--radius-full);
  transition: all var(--duration-fast) var(--ease-out);
}
.suggest-chip:hover {
  background: var(--primary-bg) !important;
  border-color: var(--primary-light) !important;
  color: var(--primary) !important;
  transform: translateY(-1px);
}

.result-stats {
  color: var(--text-secondary);
  font-size: var(--text-sm);
  margin-bottom: var(--space-4);
  padding-left: 4px;
}
.result-stats strong {
  color: var(--primary);
  font-weight: 700;
}

.result-group { padding: 16px 20px; }
.result-type-icon {
  width: 22px;
  height: 22px;
  border-radius: 5px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-right: 4px;
}

.result-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 12px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
  margin: 0 -12px;
}
.result-item + .result-item { border-top: 1px solid var(--border-light); }
.result-item:hover {
  background: var(--bg-subtle);
}
.result-icon {
  width: 38px;
  height: 38px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}
.result-info { flex: 1; min-width: 0; }
.result-title {
  font-weight: 600;
  font-size: var(--text-base);
  margin-bottom: 4px;
  color: var(--text-primary);
}
.result-snippet {
  color: var(--text-secondary);
  font-size: var(--text-sm);
  line-height: 1.5;
  margin-bottom: 6px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.result-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--text-xs);
}
.result-id { color: var(--text-tertiary); font-variant-numeric: tabular-nums; }
.result-arrow { color: var(--text-tertiary); flex-shrink: 0; }

:deep(mark) {
  background: rgba(245, 158, 11, 0.25);
  color: #92400e;
  padding: 0 2px;
  border-radius: 2px;
  font-weight: 700;
}
</style>
