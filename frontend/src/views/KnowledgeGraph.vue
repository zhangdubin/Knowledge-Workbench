<template>
  <div class="page">
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
    </PageTitle>

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
      height="600px"
      :color-by="colorBy"
      empty-hint="还没有笔记，或者笔记之间还没有用 [[双链]] 互相引用"
      @select="openNote"
      @recenter="recenterOn"
    />

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
import { Api } from '../api'
import PageTitle from '../components/PageTitle.vue'
import GraphCanvas from '../components/GraphCanvas.vue'

const router = useRouter()

const tagFilter = ref('')
const colorBy = ref('tag')
const tags = ref([])
const loading = ref(false)
const graph = ref({ nodes: [], edges: [], truncated: false })

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

async function load() {
  loading.value = true
  try {
    graph.value = await Api.graphForNotes(tagFilter.value || null)
  } catch (e) {
    graph.value = { nodes: [], edges: [], truncated: false }
  } finally {
    loading.value = false
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
