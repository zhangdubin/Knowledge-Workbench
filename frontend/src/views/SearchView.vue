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
        <button
          v-for="s in SUGGESTIONS"
          :key="s"
          class="suggest-chip"
          type="button"
          @click="kw = s; search()"
        >
          {{ s }}
        </button>
      </div>
      <div class="search-hint">
        <el-icon><InfoFilled /></el-icon>
        搜索基于标题字段和全文索引；中英文均支持
      </div>
    </div>

    <!-- 加载中：出结果之前给一块骨架，避免「点了搜索 → 页面空了 → 结果突然出现」的跳动 -->
    <div v-if="loading" class="search-skeleton" aria-busy="true" aria-live="polite">
      <div v-for="i in 4" :key="i" class="sk-row">
        <el-skeleton animated>
          <template #template>
            <el-skeleton-item variant="circle" style="width: 36px; height: 36px" />
            <div class="sk-lines">
              <el-skeleton-item variant="text" style="width: 40%" />
              <el-skeleton-item variant="text" style="width: 75%" />
            </div>
          </template>
        </el-skeleton>
      </div>
    </div>

    <!-- 无结果 -->
    <EmptyState
      v-else-if="kw && !totalCount"
      icon="Search"
      :title="`没有找到与「${kw}」相关的结果`"
      description="试试用更短的关键字，或检查拼写"
      variant="plain"
    >
      <template #default>
        <div class="suggest-chips suggest-chips--center">
          <button
            v-for="s in SUGGESTIONS.slice(0, 4)"
            :key="s"
            class="suggest-chip"
            type="button"
            @click="kw = s; search()"
          >
            {{ s }}
          </button>
        </div>
      </template>
    </EmptyState>

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
          role="button"
          tabindex="0"
          :aria-label="`文件 ${d.title || d.filename}`"
          @click="openDoc(d)"
          @keydown.enter.prevent="openDoc(d)"
          @keydown.space.prevent="openDoc(d)"
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
          role="button"
          tabindex="0"
          :aria-label="`${r.entity_type_name} ${getDisplayName(r)}`"
          @click="go(r)"
          @keydown.enter.prevent="go(r)"
          @keydown.space.prevent="go(r)"
        >
          <div class="result-icon" :style="{ background: group.bg, color: group.color }">
            <el-icon :size="18"><component :is="group.icon" /></el-icon>
          </div>
          <div class="result-info">
            <div class="result-title" v-html="highlight(getDisplayName(r))"></div>
            <div class="result-snippet" v-html="highlight(r.snippet)"></div>
            <div class="result-meta">
              <el-tag size="small" effect="plain">{{ r.entity_type_name }}</el-tag>
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
import { highlightHtml } from '../utils/md'
import PageTitle from '../components/PageTitle.vue'
import EmptyState from '../components/EmptyState.vue'

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

/**
 * 结果分组的配色。
 *
 * 之前这里是写死的十六进制（#3b82f6 / #10b981 / #f59e0b …），
 * 两个问题：一是绕开了设计令牌，深色主题下这套浅色会糊在深底上；
 * 二是这些蓝绿橙红并不在项目色板里，和别处的琥珀/靛蓝体系对不上。
 * 现在统一映射到主色 + 四个语义色，深浅色主题都由令牌自己负责。
 */
function groupStyle(key) {
  const map = {
    note: { icon: 'Notebook', bg: 'var(--primary-bg)', color: 'var(--primary)' },
    project: { icon: 'Document', bg: 'var(--info-bg)', color: 'var(--info)' },
    task: { icon: 'List', bg: 'var(--info-bg)', color: 'var(--info)' },
    customer: { icon: 'User', bg: 'var(--success-bg)', color: 'var(--success)' },
    opportunity: { icon: 'ShoppingCart', bg: 'var(--warning-bg)', color: 'var(--warning-text)' },
    order: { icon: 'Box', bg: 'var(--warning-bg)', color: 'var(--warning-text)' },
    contract: { icon: 'Files', bg: 'var(--danger-bg)', color: 'var(--danger-text)' },
    payment: { icon: 'Money', bg: 'var(--primary-bg)', color: 'var(--primary)' },
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

/**
 * 关键词高亮。
 *
 * 返回的是要交给 v-html 的 HTML，所以每一段都必须先转义 ——
 * 早先的实现直接把原文 replace 成 '<mark>$1</mark>'，于是「文件名带 HTML」
 * 就能在搜索结果里执行脚本（存成 `<img src=x onerror=...>` 的文件名一搜就中招）。
 *
 * 真正的实现在 utils/md.js 的 highlightHtml（抽出去是为了能写单测）。
 */
function highlight(text) {
  return highlightHtml(text, kw.value)
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
.suggest-chips--center { justify-content: center; margin-top: 12px; }
/* 建议词原来是 el-tag（span）+ click，鼠标能点、键盘够不着。
   换成真正的 button：天然可聚焦、可回车触发，也不用跟标签样式较劲。 */
.suggest-chip {
  cursor: pointer;
  padding: 6px 14px;
  font-size: var(--text-sm);
  font-family: inherit;
  line-height: 1.5;
  color: var(--text-secondary);
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  transition: all var(--duration-fast) var(--ease-out);
}
.suggest-chip:hover {
  background: var(--primary-bg);
  border-color: var(--primary-light);
  color: var(--primary);
  transform: translateY(-1px);
}

/* 搜索中的骨架：出结果之前占住高度，页面不会先塌下去再弹回来 */
.search-skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-5) var(--space-6);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
}
.sk-row { display: flex; align-items: center; gap: 14px; }
.sk-lines { flex: 1; display: flex; flex-direction: column; gap: 8px; }

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

/* 命中高亮：颜色来自 --highlight-bg / --highlight-color，
   深色主题下换成「暗底 + 亮字」，浅色主题下是「浅琥珀底 + 深琥珀字」，
   两边都保持 AA 以上的对比度 —— 之前写死的浅棕配深棕在深色底下等于看不见。 */
:deep(mark) {
  background: var(--highlight-bg);
  color: var(--highlight-color);
  padding: 0 2px;
  border-radius: 2px;
  font-weight: 700;
}
</style>
