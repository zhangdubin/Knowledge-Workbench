<template>
  <div class="page">
    <PageTitle
      title="关联图谱"
      subtitle="跨模型的关系网络：关联关系、外键引用、字段挂载的文件全部连成一张网"
      icon-key="Share"
    >
      <el-select v-model="mode" style="width:150px" @change="onModeChange">
        <el-option label="全局总览" value="global" />
        <el-option label="按数据模型" value="type" />
        <el-option label="以节点为中心" value="center" />
      </el-select>

      <el-select v-if="mode === 'type'" v-model="typeId" style="width:200px" @change="load">
        <el-option v-for="t in types" :key="t.id" :label="t.name" :value="t.id" />
      </el-select>

      <el-select v-if="mode === 'center'" v-model="centerSel" filterable remote clearable
                 :remote-method="searchNodes" :loading="searching"
                 placeholder="搜索记录或文件…" style="width:280px" @change="onCenterPick">
        <el-option v-for="o in centerOptions" :key="o.id" :label="o.label" :value="o.id">
          <span class="opt-row">
            <span class="opt-ico">{{ o.icon }}</span>
            <span class="opt-label">{{ o.label }}</span>
            <span class="opt-type">{{ o.type_name }}</span>
          </span>
        </el-option>
      </el-select>

      <el-select v-if="mode === 'center'" v-model="depth" style="width:110px" @change="load">
        <el-option v-for="d in [1, 2, 3]" :key="d" :label="`深度 ${d}`" :value="d" />
      </el-select>

      <el-select v-if="mode === 'global'" v-model="nodeLimit" style="width:130px" @change="load">
        <el-option v-for="n in [120, 300, 600]" :key="n" :label="`最多 ${n} 节点`" :value="n" />
      </el-select>

      <el-button :loading="loading" @click="load">
        <el-icon><Refresh /></el-icon>刷新
      </el-button>
    </PageTitle>

    <!-- 概览 -->
    <div class="stat-grid">
      <div class="stat-card">
        <div class="icon"><el-icon><Connection /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ graph.nodes.length }}</div>
          <div class="label">当前节点</div>
        </div>
      </div>
      <div class="stat-card success">
        <div class="icon"><el-icon><Share /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ graph.edges.length }}</div>
          <div class="label">连线</div>
        </div>
      </div>
      <div class="stat-card warning">
        <div class="icon"><el-icon><Grid /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ kindCount }}</div>
          <div class="label">涉及类型</div>
        </div>
      </div>
      <div class="stat-card info">
        <div class="icon"><el-icon><Aim /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ isolated }}</div>
          <div class="label">孤立节点</div>
        </div>
      </div>
    </div>

    <GraphCanvas
      :nodes="graph.nodes"
      :edges="graph.edges"
      :loading="loading"
      :truncated="!!graph.truncated"
      height="620px"
      color-by="type"
      :empty-hint="emptyHint"
      @select="openNode"
      @recenter="recenterOn"
    />

    <div class="card tips">
      <div class="card-title">
        <span class="card-title-text"><el-icon class="title-ico"><InfoFilled /></el-icon>怎么读这张图</span>
      </div>
      <div class="tip-grid">
        <div class="tip">
          <span class="tip-k">节点颜色</span>
          <span class="tip-v">按数据模型分配，同一模型在任何视图里颜色都一样</span>
        </div>
        <div class="tip">
          <span class="tip-k">虚线方框</span>
          <span class="tip-v">数据中心文件；实线方框是业务记录</span>
        </div>
        <div class="tip">
          <span class="tip-k">实线箭头</span>
          <span class="tip-v">关联关系 / 外键引用 / 字段挂载，方向即数据流向</span>
        </div>
        <div class="tip">
          <span class="tip-k">虚线无箭头</span>
          <span class="tip-v">笔记之间的双向链接（wiki 链接），本身没有方向</span>
        </div>
        <div class="tip">
          <span class="tip-k">点图例</span>
          <span class="tip-v">按类型隐藏/显示节点，聚焦看局部</span>
        </div>
        <div class="tip">
          <span class="tip-k">点节点</span>
          <span class="tip-v">右侧展开详情与邻居列表，可「以它为中心」继续下钻</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Api } from '../api'
import PageTitle from '../components/PageTitle.vue'
import GraphCanvas from '../components/GraphCanvas.vue'

const route = useRoute()
const router = useRouter()

const mode = ref('global')
const typeId = ref(null)
const depth = ref(2)
const nodeLimit = ref(300)
const centerSel = ref(null)
const center = ref(null)          // {kind, id, type_id, label}
const centerOptions = ref([])
const types = ref([])
const searching = ref(false)
const loading = ref(false)
const graph = ref({ nodes: [], edges: [], truncated: false })

const kindCount = computed(() => new Set(graph.value.nodes.map(n => n.type_name)).size)

const isolated = computed(() => {
  const linked = new Set()
  for (const e of graph.value.edges) { linked.add(e.source); linked.add(e.target) }
  return graph.value.nodes.filter(n => !linked.has(n.id)).length
})

const emptyHint = computed(() => {
  if (mode.value === 'type') return '该模型下还没有记录，或这些记录之间没有建立关联'
  if (mode.value === 'center') return '这个节点没有正向或反向关联，换一个试试'
  return '还没有任何关联。先到「关联定义」里定义关系，再到记录详情里挂上具体对象'
})

async function loadTypes() {
  try {
    types.value = await Api.listEntityTypes()
    if (types.value.length && !typeId.value) typeId.value = types.value[0].id
  } catch (e) { /* 拦截器已提示 */ }
}

async function searchNodes(q = '') {
  const kw = (q || '').trim()
  if (!kw) { centerOptions.value = []; return }
  searching.value = true
  try {
    const r = await Api.graphSearch(kw, 20)
    centerOptions.value = r.items || []
  } catch (e) {
    centerOptions.value = []
  } finally {
    searching.value = false
  }
}

function onCenterPick(id) {
  const hit = centerOptions.value.find(x => x.id === id)
  if (!hit) return
  center.value = { kind: hit.kind, id: hit.ref_id, type_id: hit.type_id, label: hit.label }
  load()
}

async function load() {
  loading.value = true
  try {
    let data = { nodes: [], edges: [], truncated: false }
    if (mode.value === 'global') {
      data = await Api.graphGlobal({ limit: nodeLimit.value })
    } else if (mode.value === 'type' && typeId.value) {
      data = await Api.graphForType(typeId.value)
    } else if (mode.value === 'center' && center.value) {
      data = center.value.kind === 'document'
        ? await Api.graphForDocument(center.value.id, depth.value)
        : await Api.graphForRecord(center.value.id, depth.value)
    }
    graph.value = data || { nodes: [], edges: [], truncated: false }
  } catch (e) { /* 拦截器已提示 */ } finally {
    loading.value = false
  }
}

async function onModeChange() {
  centerSel.value = null
  if (mode.value === 'center' && !center.value) {
    // 还没选中心节点：先给个空图，避免屏幕上留着上一个视图的残留
    graph.value = { nodes: [], edges: [], truncated: false }
    return
  }
  await load()
}

function openNode(node) {
  if (node.kind === 'document') {
    router.push({ path: '/library', query: { id: node.ref_id } })
    return
  }
  if (node.type_id) router.push({ path: `/records/${node.type_id}`, query: { id: node.ref_id } })
  else ElMessage.info('该节点缺少模型信息，无法跳转')
}

function recenterOn(node) {
  center.value = { kind: node.kind, id: node.ref_id, type_id: node.type_id, label: node.label }
  centerSel.value = node.id
  centerOptions.value = [node]
  mode.value = 'center'
  load()
}

onMounted(async () => {
  await loadTypes()
  // URL 参数：?global=1 / ?type=1 / ?record=12 / ?document=3
  if (route.query.record) {
    // 兼容旧链接：记录 id 需要反查所属模型，统一走搜索接口拿 type_id
    mode.value = 'center'
    try {
      const r = await Api.graphSearch(String(route.query.record), 20)
      const hit = (r.items || []).find(x => x.kind === 'record' && String(x.ref_id) === String(route.query.record))
      if (hit) {
        center.value = { kind: 'record', id: hit.ref_id, type_id: hit.type_id, label: hit.label }
        centerSel.value = hit.id
        centerOptions.value = [hit]
      }
    } catch { /* 忽略，退化为空图 */ }
  } else if (route.query.document) {
    mode.value = 'center'
    center.value = { kind: 'document', id: Number(route.query.document), type_id: null, label: `文件 #${route.query.document}` }
  } else if (route.query.type) {
    mode.value = 'type'
    typeId.value = Number(route.query.type)
  }
  await load()
})
</script>

<style scoped>
.opt-row { display: flex; align-items: center; gap: 8px; }
.opt-ico { flex-shrink: 0; }
.opt-label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.opt-type { font-size: var(--text-xs); color: var(--text-tertiary); flex-shrink: 0; }

.tips { margin-top: var(--space-4); }
.tip-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 10px 20px; }
.tip { display: flex; gap: 10px; font-size: var(--text-sm); line-height: 1.6; }
.tip-k { flex-shrink: 0; width: 74px; font-weight: 600; color: var(--text-primary); }
.tip-v { color: var(--text-tertiary); }
</style>
