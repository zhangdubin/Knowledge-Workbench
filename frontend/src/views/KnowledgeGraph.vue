<template>
  <div
    class="page"
    data-print-root
    :data-print-empty="printEmpty ? 'true' : 'false'"
  >
    <!-- data-print-root：这一块是要打印的正文。
         data-print-empty：一篇笔记都没有时为 true —— 打印脚本会先说一声，
         而不是默默打出一张白纸。

         这段说明必须放在根元素「里面」：放在外面的话，模板就变成多根节点，
         开发模式下 Vue 会把它编译成 Fragment，而 Fragment 被卸载时不会回调
         transition 的 afterLeave —— 路由切换的淡入淡出就永远卡在空白页。 -->

    <PageTitle
      title="知识图谱"
      subtitle="所有笔记与它们之间的双向链接。按标签着色，一眼看出知识聚成了哪几团"
      icon-key="Notebook"
    >
      <el-select v-model="tagFilter" clearable placeholder="全部标签" style="width:180px" @change="load">
        <el-option v-for="t in tags" :key="t" :label="`#${t}`" :value="t" />
      </el-select>
      <el-select v-model="colorBy" style="width:150px">
        <el-option label="按标签着色" value="tag" />
        <el-option label="统一着色" value="type" />
      </el-select>
      <el-button :loading="loading" @click="load">
        <el-icon><Refresh /></el-icon>刷新
      </el-button>
      <!-- 打印：图标 + 文字（只有一个图标的按钮出了纸面就没人认得） -->
      <el-button data-print-trigger @click="onPrint">
        <el-icon><Printer /></el-icon>打印
      </el-button>
    </PageTitle>

    <!-- 打印页眉：屏幕上不显示，纸上要看得清「打印的是什么、什么时候打的」 -->
    <div class="print-title-bar" data-print-only>
      <span>知识图谱 · {{ graph.nodes.length }} 篇笔记 / {{ graph.edges.length }} 条双向链接</span>
      <span class="print-title-bar-time" data-print-time></span>
    </div>

    <div class="stat-grid">
      <div class="stat-card">
        <div class="icon"><el-icon><Notebook /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ graph.nodes.length }}</div>
          <div class="label">笔记</div>
        </div>
      </div>
      <div class="stat-card success">
        <div class="icon"><el-icon><Link /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ graph.edges.length }}</div>
          <div class="label">双向链接</div>
        </div>
      </div>
      <div class="stat-card warning">
        <div class="icon"><el-icon><Collection /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ tagCount }}</div>
          <div class="label">标签数</div>
        </div>
      </div>
      <div class="stat-card info">
        <div class="icon"><el-icon><Aim /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ isolated }}</div>
          <div class="label">孤立笔记</div>
        </div>
      </div>
    </div>

    <GraphCanvas
      :nodes="graph.nodes"
      :edges="graph.edges"
      :loading="loading"
      :truncated="!!graph.truncated"
      height="calc(100vh - 340px)"
      :color-by="colorBy"
      title="知识图谱"
      empty-hint="还没有笔记，或者笔记之间还没有用 [[双链]] 互相引用"
      @select="openNote"
      @recenter="recenterOn"
    />

    <!--
      打印用的图谱清单：
      交互图画在 canvas 上，印出来是一张白纸（或者一堆断掉的线），
      所以纸上改给「笔记清单 + 链接清单」——
      至少「有哪些笔记、谁链着谁」在纸上看得见。
      画布本身在 print.css 里被藏掉了。
    -->
    <div class="print-block" data-print-only>
      <div class="print-block-title">笔记清单（共 {{ graph.nodes.length }} 篇）</div>
      <ul v-if="graph.nodes.length" class="print-node-list">
        <li v-for="n in graph.nodes" :key="n.id" class="print-node-item">
          {{ n.label }}<span v-if="(n.tags || []).length" class="print-node-type">（{{ (n.tags || []).map(t => '#' + t).join(' ') }}）</span>
        </li>
      </ul>
      <div v-else class="print-empty-note">当前视图没有笔记。</div>
    </div>
    <div class="print-block" data-print-only>
      <div class="print-block-title">链接清单（共 {{ graph.edges.length }} 条）</div>
      <ul v-if="graph.edges.length" class="print-node-list">
        <li v-for="(e, i) in graph.edges" :key="i" class="print-node-item">
          {{ nodeLabel(e.source) }} — {{ e.relation || '链接' }} → {{ nodeLabel(e.target) }}
        </li>
      </ul>
      <div v-else class="print-empty-note">当前视图没有链接。</div>
    </div>

    <div class="card tips">
      <div class="card-title">
        <span class="card-title-text"><el-icon class="title-ico"><InfoFilled /></el-icon>怎么读这张图</span>
      </div>
      <div class="tip-grid">
        <div class="tip">
          <span class="tip-k">节点</span>
          <span class="tip-v">一条笔记。颜色对应它的第一个标签，没有标签的统一归到「未分类」</span>
        </div>
        <div class="tip">
          <span class="tip-k">连线</span>
          <span class="tip-v">在正文里写 [[笔记标题]] 就会生成双向链接，虚线表示它没有方向</span>
        </div>
        <div class="tip">
          <span class="tip-k">看关系名</span>
          <span class="tip-v">把鼠标放到节点或连线上，关系名会浮出来；一屏全挂反而看不清</span>
        </div>
        <div class="tip">
          <span class="tip-k">孤立节点</span>
          <span class="tip-v">没有任何链接的笔记，通常值得补上引用</span>
        </div>
        <div class="tip">
          <span class="tip-k">点图例</span>
          <span class="tip-v">只保留某几个标签的笔记，看单个主题</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
// 直接用 axios 实例（而不是 Api.graphForNotes 包装）：
// 只有拿到实例才能挂 AbortController，换标签时把上一个请求取消掉。
import api, { Api } from '../api'
import { createSearchRequest } from '../utils/searchRequest'
import PageTitle from '../components/PageTitle.vue'
import { printPage } from '../utils/print'
import GraphCanvas from '../components/GraphCanvas.vue'

const router = useRouter()

const tagFilter = ref('')
const colorBy = ref('tag')
const tags = ref([])
const loading = ref(false)
const graph = ref({ nodes: [], edges: [], truncated: false })

// ===== 打印 =====
// 打印用的节点名索引：链接清单里要用「节点 id → 名字」
const nodeLabelMap = computed(() => {
  const m = new Map()
  for (const n of graph.value.nodes) m.set(n.id, n.label)
  return m
})
function nodeLabel(id) {
  return nodeLabelMap.value.get(id) || String(id)
}

// 一篇笔记都没有的时候，纸上只有一块空白 —— 先说一声
const printEmpty = computed(() => !graph.value.nodes.length)

function onPrint() {
  printPage()
}

const tagCount = computed(() => {
  const s = new Set()
  for (const n of graph.value.nodes) for (const t of (n.tags || [])) s.add(t)
  return s.size
})

const isolated = computed(() => {
  const linked = new Set()
  for (const e of graph.value.edges) { linked.add(e.source); linked.add(e.target) }
  return graph.value.nodes.filter(n => !linked.has(n.id)).length
})

async function loadTags() {
  try {
    const nt = await Api.getEntityTypeByKey('note')
    const all = await Api.listRecords(nt.id, { page_size: 500 })
    const s = new Set()
    for (const n of (all.items || [])) {
      // tags 可能是数组，也可能是逗号串（早期数据），两种都要认
      const raw = n.data?.tags
      const list = Array.isArray(raw) ? raw : String(raw || '').split(',')
      for (const t of list) if (String(t).trim()) s.add(String(t).trim())
    }
    tags.value = [...s].sort()
  } catch { /* 拦截器已提示 */ }
}

/**
 * 加载图谱
 *
 * 换标签就取消上一个请求：图谱重建不便宜（后端要查连接、前端要重排版），
 * 而且先发后到的那个会把新图盖掉 —— 用户看到的是上一个标签的图，
 * 却以为是刚点的那个。用序号做兜底，取消没赶上也不认旧结果。
 */
const request = createSearchRequest()

async function load() {
  // 换标签就取消上一个请求（图谱重建不便宜，且旧结果会盖掉新图）
  const key = tagFilter.value || ''
  const { seq: mySeq, controller, duplicated } = request.begin(key)
  if (duplicated) return
  loading.value = true
  try {
    // silent：取消是正常流程，不是错误
    const g = await api.get('/api/graph/notes', {
      params: { tag: tagFilter.value || null, limit: 300 },
      signal: controller.signal,
      silent: true,
    })
    if (!request.isCurrent(mySeq)) return
    graph.value = g
  } catch (e) {
    // 被取消不算错
    if (e?.code === 'ERR_CANCELED' || e?.name === 'CanceledError') return
    if (!request.isCurrent(mySeq)) return
    graph.value = { nodes: [], edges: [], truncated: false }
  } finally {
    if (request.isCurrent(mySeq)) {
      request.end(mySeq)
      loading.value = false
    }
  }
}

function openNote(node) {
  router.push(`/notes/${node.ref_id}`)
}

function recenterOn(node) {
  router.push(`/notes/${node.ref_id}`)
}

onMounted(async () => {
  await Promise.all([loadTags(), load()])
})
</script>

<style scoped>
.tips { margin-top: var(--space-4); }
.tip-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px 20px; }
.tip { display: flex; gap: 10px; font-size: var(--text-sm); line-height: 1.6; }
.tip-k { flex-shrink: 0; width: 70px; font-weight: 600; color: var(--text-primary); }
.tip-v { color: var(--text-tertiary); }
</style>
