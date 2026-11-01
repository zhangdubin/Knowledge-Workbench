<template>
  <div class="page dna-page">
    <PageTitle
      title="养料 DNA"
      subtitle="喂给模型的资料的体检报告与基因图谱：成分、骨架、指纹、脉络、健康度"
      icon-key="DataLine"
    >
      <el-button :loading="loading" @click="loadAll">
        <el-icon><Refresh /></el-icon>刷新
      </el-button>
      <el-button :disabled="!overview" @click="exportMarkdown">
        <el-icon><Document /></el-icon>导出 Markdown
      </el-button>
      <el-button :disabled="!overview" @click="exportJson">
        <el-icon><Download /></el-icon>下载 JSON
      </el-button>
    </PageTitle>

    <el-alert v-if="error" type="error" :closable="false" show-icon style="margin-bottom: 14px">
      {{ error }}
    </el-alert>

    <div v-loading="loading && !overview" class="dna-body">
      <!-- ============ 一、结论带：先给结论，再给细节 ============ -->
      <div v-if="overview" class="pcard hero">
        <div class="hero-score">
          <div class="score-ring" :style="ringStyle">
            <div class="score-inner">
              <span class="score-num" :style="{ color: scoreColor }">{{ overview.score }}</span>
              <span class="score-max">/ 100</span>
            </div>
          </div>
          <div class="score-side">
            <div class="score-title">健康分{{ scoreText }}</div>
            <div class="score-desc">
              {{ scoreDesc }}
            </div>
            <div class="engine-strip">
              <span class="eng-item">模型 {{ overview.engine.embed_model }}</span>
              <span class="eng-item">{{ overview.engine.embed_dim }} 维</span>
              <span class="eng-item">{{ overview.engine.vec_metric }}</span>
              <span class="eng-item">分块 {{ overview.engine.chunk_size }}+{{ overview.engine.chunk_overlap }}</span>
              <span class="eng-item" :class="overview.engine.fts_available ? 'ok' : 'bad'">
                全文 {{ overview.engine.fts_available ? '可用' : '不可用' }}
              </span>
              <span class="eng-item" :class="overview.engine.vec_available ? 'ok' : 'bad'">
                向量 {{ overview.engine.vec_available ? '可用' : '不可用' }}
              </span>
            </div>
          </div>
        </div>

        <div class="hero-metrics">
          <div class="metric">
            <div class="metric-num">{{ overview.totals.documents }}</div>
            <div class="metric-label">文档</div>
            <div class="metric-sub">另有笔记 {{ overview.totals.notes }} 篇</div>
          </div>
          <div class="metric">
            <div class="metric-num">{{ overview.totals.chunks }}</div>
            <div class="metric-label">知识块</div>
            <div class="metric-sub">平均每块 {{ avgChunkWords }} 字</div>
          </div>
          <div class="metric">
            <div class="metric-num">{{ formatNumber(overview.totals.words) }}</div>
            <div class="metric-label">总字数</div>
            <div class="metric-sub">{{ formatBytes(overview.totals.db_bytes) }} 库体积</div>
          </div>
          <div class="metric">
            <div class="metric-num">
              {{ overview.totals.embedded }}<span class="metric-den">/{{ overview.totals.vector_rows }}</span>
            </div>
            <div class="metric-label">向量覆盖</div>
            <div class="metric-sub">向量占 {{ vectorRatio }}%</div>
          </div>
          <div class="metric">
            <div class="metric-num">{{ overview.totals.links }}</div>
            <div class="metric-label">文件关联</div>
            <div class="metric-sub">{{ overview.checks.length }} 项体检结论</div>
          </div>
        </div>
      </div>

      <!-- ============ 二、体检清单（这个页面最要紧的东西） ============ -->
      <section v-if="overview" class="section">
        <div class="section-head">
          <h3 class="section-title">体检清单</h3>
          <div class="section-tags">
            <span v-if="errCount" class="ptag" style="--ac-fg: var(--danger); --ac-bg: var(--danger-bg); --ac-line: var(--danger)">
              {{ errCount }} 严重
            </span>
            <span v-if="warnCount" class="ptag" style="--ac-fg: var(--warning); --ac-bg: var(--warning-bg); --ac-line: var(--warning)">
              {{ warnCount }} 警告
            </span>
            <span class="section-note">{{ overview.checks.length }} 项结论 · 生成于 {{ formatTime(overview.generated_at) }}</span>
          </div>
        </div>

        <div v-if="!overview.checks.length" class="pcard ok-card">
          <el-icon class="ok-icon"><CircleCheckFilled /></el-icon>
          <div>
            <div class="ok-title">一切正常</div>
            <div class="ok-sub">没有检出问题：正文齐、向量齐、索引一致、没有重复内容。</div>
          </div>
        </div>

        <div v-else class="check-grid">
          <div
            v-for="c in overview.checks"
            :key="c.key"
            class="pcard check-card"
            :class="c.level"
          >
            <div class="check-bar" />
            <div class="check-main">
              <div class="check-title">
                <el-icon class="check-icon"><component :is="levelIcon(c.level)" /></el-icon>
                {{ c.title }}
              </div>
              <div class="check-detail">{{ c.detail }}</div>
              <div class="check-hint">
                <el-icon><InfoFilled /></el-icon><span>{{ c.hint }}</span>
              </div>
            </div>
            <div v-if="c.action === 'reindex' && c.doc_ids && c.doc_ids.length" class="check-actions">
              <el-button
                v-for="did in c.doc_ids"
                :key="did"
                size="small"
                :loading="reindexing === did"
                @click="reindex(did)"
              >
                重建 #{{ did }}
              </el-button>
            </div>
          </div>
        </div>
      </section>

      <!-- ============ 三、指纹 + 成分 ============ -->
      <div v-if="overview" class="pgrid two-col">
        <div class="pcard">
          <div class="section-head">
            <h3 class="section-title">主题指纹</h3>
            <span class="section-note">这批资料反复在说些什么</span>
          </div>
          <div v-if="!overview.fingerprint.length" class="empty">还没有可统计的正文</div>
          <div v-else class="fp-list">
            <div v-for="f in overview.fingerprint" :key="f.term" class="fp-row">
              <span class="fp-term" :title="f.term">{{ f.term }}</span>
              <div class="fp-bar">
                <div class="fp-fill" :style="{ width: fpWidth(f) + '%' }" />
              </div>
              <span class="fp-docs">{{ f.docs }} 篇</span>
              <span class="fp-weight">{{ f.weight.toFixed(1) }}</span>
            </div>
          </div>
        </div>

        <div class="pcard">
          <div class="section-head">
            <h3 class="section-title">成分构成</h3>
            <span class="section-note">资料都是哪来的</span>
          </div>
          <div class="comp-list">
            <div class="comp-block">
              <div class="comp-label">按类型</div>
              <div class="comp-tags">
                <span v-for="k in overview.composition.by_kind" :key="k.key" class="ptag ptag-plain">
                  {{ k.label }} · {{ k.count }}
                </span>
              </div>
            </div>
            <div class="comp-block">
              <div class="comp-label">按扩展名</div>
              <div class="comp-tags">
                <span v-for="k in overview.composition.by_ext" :key="k.key" class="ptag ptag-plain">
                  {{ k.key || '（无扩展名）' }} · {{ k.count }}
                </span>
              </div>
            </div>
            <div class="comp-block">
              <div class="comp-label">按来源</div>
              <div class="comp-tags">
                <span v-for="k in overview.composition.by_source" :key="k.key" class="ptag ptag-plain">
                  {{ sourceLabel(k.key) }} · {{ k.count }}
                </span>
              </div>
            </div>
            <div class="comp-block">
              <div class="comp-label">按月份</div>
              <div class="comp-tags">
                <span v-for="k in overview.composition.by_month" :key="k.key" class="ptag ptag-plain">
                  {{ k.month }} · {{ k.count }}
                </span>
              </div>
            </div>
            <div v-if="overview.composition.by_tag.length" class="comp-block">
              <div class="comp-label">按标签</div>
              <div class="comp-tags">
                <span v-for="k in overview.composition.by_tag" :key="k.key" class="ptag ptag-plain">
                  {{ k.key }} · {{ k.count }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ============ 四、关联脉络图 ============ -->
      <section v-if="overview" class="section">
        <div class="section-head">
          <h3 class="section-title">关联脉络图</h3>
          <span class="section-note">文件 → 章节骨架 → 挂着的记录，双击文件节点可去数据中心</span>
        </div>
        <div class="pcard graph-card">
          <DnaGraph :graph="graph" />
        </div>
      </section>

      <!-- ============ 五、文档谱系 ============ -->
      <section v-if="overview" class="section">
        <div class="section-head">
          <h3 class="section-title">文档谱系</h3>
          <span class="section-note">点标题展开这篇的结构与切块</span>
        </div>
        <div class="pcard table-card">
          <el-table
            ref="tableRef"
            :data="documents"
            v-loading="loading && !documents.length"
            class="ptable"
            @expand-change="onExpand"
            row-key="id"
          >
            <el-table-column type="expand">
              <template #default="{ row }">
                <div class="doc-detail">
                  <el-skeleton v-if="detailFor(row.id).loading" :rows="3" animated />
                  <template v-else-if="detailFor(row.id).data">
                    <div class="detail-cols">
                      <div class="detail-col">
                        <div class="detail-head">结构树</div>
                        <div v-if="!detailFor(row.id).data.outline.length" class="empty small">没有标题层级</div>
                        <ul v-else class="tree">
                          <li v-for="(n, i) in detailFor(row.id).data.outline" :key="i">
                            <span class="tree-title">{{ n.title }}</span>
                            <ul v-if="n.children && n.children.length">
                              <li v-for="(c, j) in n.children" :key="j">
                                <span class="tree-title">{{ c.title }}</span>
                                <ul v-if="c.children && c.children.length">
                                  <li v-for="(g, k) in c.children" :key="k">
                                    <span class="tree-title">{{ g.title }}</span>
                                  </li>
                                </ul>
                              </li>
                            </ul>
                          </li>
                        </ul>
                      </div>
                      <div class="detail-col">
                        <div class="detail-head">切块（{{ detailFor(row.id).data.chunks.length }}）</div>
                        <div class="chunk-list">
                          <div v-for="c in detailFor(row.id).data.chunks" :key="c.id" class="chunk">
                            <div class="chunk-head">
                              <span class="chunk-seq">#{{ c.seq }}</span>
                              <span class="chunk-chars">{{ c.chars }} 字</span>
                              <span class="ptag ptag-plain" :style="c.embedded ? embStyle : pendStyle">
                                {{ c.embedded ? '已嵌入' : '未嵌入' }}
                              </span>
                              <span v-if="c.heading" class="chunk-heading">{{ c.heading }}</span>
                            </div>
                            <div class="chunk-preview">{{ c.preview }}</div>
                          </div>
                        </div>
                      </div>
                      <div class="detail-col">
                        <div class="detail-head">主题词</div>
                        <div class="comp-tags">
                          <span v-for="t in detailFor(row.id).data.terms" :key="t.term" class="ptag ptag-plain">
                            {{ t.term }} · {{ t.count }}
                          </span>
                        </div>
                        <template v-if="detailFor(row.id).data.links.length">
                          <div class="detail-head">关联</div>
                          <div class="comp-tags">
                            <span v-for="l in detailFor(row.id).data.links" :key="l.id" class="ptag ptag-plain">
                              {{ l.title }}
                            </span>
                          </div>
                        </template>
                        <template v-if="detailFor(row.id).data.issues.length">
                          <div class="detail-head">这篇的问题</div>
                          <div v-for="(is, i) in detailFor(row.id).data.issues" :key="i" class="issue">
                            {{ is.title }}：{{ is.detail }}
                          </div>
                        </template>
                      </div>
                    </div>
                  </template>
                  <div v-else class="empty small">读不到这篇的详情</div>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="title" label="标题" min-width="230">
              <template #default="{ row }">
                <div class="doc-title doc-title-link" @click="toggleRow(row)">{{ row.title }}</div>
                <div class="doc-sum">{{ row.summary || '（没有摘要）' }}</div>
              </template>
            </el-table-column>
            <el-table-column prop="kind" label="类型" width="80">
              <template #default="{ row }">
                <span class="ptag ptag-plain">{{ kindLabel(row.kind) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="words" label="字数" width="90" sortable />
            <el-table-column prop="chunks" label="块数" width="80" sortable />
            <el-table-column label="向量" width="90">
              <template #default="{ row }">
                <span class="ptag ptag-plain" :style="row.embedded === row.chunks ? embStyle : pendStyle">
                  {{ row.embedded }}/{{ row.chunks }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="headings" label="标题数" width="90" />
            <el-table-column prop="created_at" label="入库时间" width="160" />
          </el-table>
        </div>
      </section>

      <!-- ============ 六、全库结构索引 ============ -->
      <section v-if="overview" class="section">
        <div class="section-head">
          <h3 class="section-title">全库结构索引</h3>
          <span class="section-note">每篇文档的标题层级 —— 人和模型都能当目录用</span>
        </div>
        <div class="pgrid tree-grid">
          <div v-for="t in tree" :key="t.id" class="pcard tree-card">
            <div class="tree-card-head">
              <span class="tree-card-title">{{ t.title }}</span>
              <span class="tree-card-meta">{{ t.words }} 字</span>
            </div>
            <ul v-if="t.outline && t.outline.length" class="tree">
              <li v-for="(n, i) in t.outline" :key="i">
                <span class="tree-title">{{ n.title }}</span>
                <ul v-if="n.children && n.children.length">
                  <li v-for="(c, j) in n.children" :key="j">
                    <span class="tree-title">{{ c.title }}</span>
                    <ul v-if="c.children && c.children.length">
                      <li v-for="(g, k) in c.children" :key="k">
                        <span class="tree-title">{{ g.title }}</span>
                      </li>
                    </ul>
                  </li>
                </ul>
              </li>
            </ul>
            <div v-else class="empty small">没有标题层级（正文型文件）</div>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
/**
 * 养料 DNA —— 喂给模型的资料的体检报告与基因图谱
 *
 * 这个页面只读：它回答五个问题
 *   成分（我到底喂了什么）· 骨架（这些东西长什么样）
 *   指纹（主题特征是什么）· 脉络（它们之间怎么连着）
 *   健康度（哪里有毛病）
 *
 * 唯一的写操作是体检清单里的「重建索引」——
 * 那不是 DNA 的一部分，是给体检结论配的一个修复按钮。
 *
 * 结构树借鉴的是 OpenKB 的 PageIndex：
 * 把文档编成标题树，靠结构定位，而不是只靠相似度。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import PageTitle from '../components/PageTitle.vue'
import DnaGraph from '../components/DnaGraph.vue'
import { Api } from '../api'

const loading = ref(false)
const error = ref('')
const overview = ref(null)
const documents = ref([])
const tree = ref([])
const graph = ref({ nodes: [], edges: [], stats: {} })
const details = ref({})
const reindexing = ref(0)
const tableRef = ref(null)

const embStyle = {
  '--ac-fg': 'var(--success)',
  '--ac-bg': 'var(--success-bg)',
  '--ac-line': 'var(--success)',
}
const pendStyle = {
  '--ac-fg': 'var(--warning)',
  '--ac-bg': 'var(--warning-bg)',
  '--ac-line': 'var(--warning)',
}

const errCount = computed(() =>
  (overview.value?.checks || []).filter((c) => c.level === 'error').length)
const warnCount = computed(() =>
  (overview.value?.checks || []).filter((c) => c.level === 'warn').length)

const avgChunkWords = computed(() => {
  const t = overview.value?.totals
  if (!t || !t.chunks) return 0
  return Math.round(t.words / t.chunks)
})

const scoreColor = computed(() => {
  const s = overview.value?.score ?? 0
  if (s >= 90) return 'var(--success)'
  if (s >= 70) return 'var(--warning)'
  return 'var(--danger)'
})

const ringStyle = computed(() => {
  const s = overview.value?.score ?? 0
  const c = scoreColor.value
  return {
    background: `conic-gradient(${c} ${s * 3.6}deg, var(--bg-sunken) 0deg)`,
  }
})

const scoreText = computed(() => {
  const s = overview.value?.score ?? 0
  if (s >= 95) return ' · 状态很好'
  if (s >= 90) return ' · 基本健康'
  if (s >= 70) return ' · 有些问题要处理'
  return ' · 需要尽快处理'
})

const scoreDesc = computed(() => {
  const t = overview.value?.totals
  if (!t) return ''
  const bad = errCount.value + warnCount.value
  if (!bad) return '这批资料可以直接喂给模型。'
  return `这批资料能喂给模型，但有 ${bad} 处需要注意（见下方体检清单）。`
})

const vectorRatio = computed(() => {
  const t = overview.value?.totals
  if (!t || !t.db_bytes) return 0
  return Math.round((t.vector_bytes / t.db_bytes) * 100)
})

const fpMax = computed(() => {
  const fp = overview.value?.fingerprint || []
  return fp.length ? Math.max(...fp.map((f) => f.weight)) : 0
})

function fpWidth(f) {
  const max = fpMax.value
  if (!max) return 0
  return Math.max(4, Math.round((f.weight / max) * 100))
}

function levelIcon(level) {
  if (level === 'error') return 'CircleCloseFilled'
  if (level === 'warn') return 'WarningFilled'
  return 'CircleCheckFilled'
}

function kindLabel(kind) {
  return { doc: '文档', image: '图片', video: '视频', audio: '音频' }[kind] || kind || '其他'
}

function sourceLabel(key) {
  return { upload: '上传', migrated: '历史迁移', api: '接口写入' }[key] || key || '未知'
}

function formatBytes(n) {
  if (!n) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

function formatNumber(n) {
  return (n || 0).toLocaleString('zh-CN')
}

function formatTime(iso) {
  if (!iso) return ''
  return String(iso).replace('T', ' ').slice(0, 16)
}

function detailFor(id) {
  return details.value[id] || { loading: false, data: null }
}

async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    const [ov, docs, tr] = await Promise.all([
      Api.dnaOverview(),
      Api.dnaDocuments(),
      Api.dnaTree(),
    ])
    overview.value = ov
    documents.value = ov?.documents?.items || docs?.items || []
    tree.value = tr?.items || []
  } catch (e) {
    error.value = '养料 DNA 读取失败：' + (e?.message || e)
  } finally {
    loading.value = false
  }
  // 脉络图单独拉：它比概览重，失败也不该把整页拖垮
  try {
    graph.value = await Api.dnaGraph()
  } catch (e) {
    graph.value = { nodes: [], edges: [], stats: {} }
  }
}

async function loadDetail(row) {
  if (details.value[row.id]?.data) return
  details.value = { ...details.value, [row.id]: { loading: true, data: null } }
  try {
    const data = await Api.dnaDocument(row.id)
    details.value = { ...details.value, [row.id]: { loading: false, data } }
  } catch (e) {
    details.value = { ...details.value, [row.id]: { loading: false, data: null } }
    ElMessage.error('读这篇的 DNA 失败：' + (e?.message || e))
  }
}

// el-table 的展开箭头走的是 expand-change，不是 row-click ——
// 只挂 row-click 的话，点箭头展开行里什么都不会加载（踩过）。
function onExpand(row, expanded) {
  if (expanded) loadDetail(row)
}

// 点标题也能展开：只看得到一行摘要却要点小箭头才能看详情，太绕
function toggleRow(row) {
  tableRef.value?.toggleRowExpansion(row)
}

async function reindex(id) {
  reindexing.value = id
  try {
    await Api.reindexDocument(id, true)
    ElMessage.success(`#${id} 已重建索引`)
    await loadAll()
  } catch (e) {
    ElMessage.error('重建失败：' + (e?.message || e))
  } finally {
    reindexing.value = 0
  }
}

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

async function exportMarkdown() {
  try {
    const resp = await Api.dnaReport()
    saveBlob(resp.data, '养料-DNA.md')
  } catch (e) {
    ElMessage.error('导出失败：' + (e?.message || e))
  }
}

async function exportJson() {
  try {
    const resp = await Api.dnaReportJson()
    saveBlob(
      new Blob([JSON.stringify(resp.data, null, 2)], { type: 'application/json' }),
      '养料-DNA.json'
    )
  } catch (e) {
    ElMessage.error('导出失败：' + (e?.message || e))
  }
}

onMounted(loadAll)
</script>

<style scoped>
.dna-body { min-height: 200px; }

/* ============ 结论带 ============ */
.hero {
  display: flex;
  align-items: stretch;
  gap: 26px;
  flex-wrap: wrap;
  margin-bottom: 24px;
  --ac-fg: var(--primary);
}
.hero-score { display: flex; align-items: center; gap: 16px; min-width: 320px; }
.score-ring {
  width: 92px;
  height: 92px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.score-inner {
  width: 74px;
  height: 74px;
  border-radius: 50%;
  background: var(--bg-card);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  line-height: 1.05;
}
.score-num { font-size: 25px; font-weight: 680; font-variant-numeric: tabular-nums; }
.score-max { font-size: 10.5px; color: var(--text-tertiary); }
.score-side { min-width: 0; }
.score-title { font-size: 15px; font-weight: 600; color: var(--text-primary); }
.score-desc { font-size: 12.5px; color: var(--text-secondary); margin-top: 3px; line-height: 1.55; }
.engine-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 9px;
}
.eng-item {
  font-size: 11px;
  color: var(--text-tertiary);
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  border-radius: 5px;
  padding: 1px 7px;
  font-variant-numeric: tabular-nums;
}
.eng-item.ok { color: var(--success-text); background: var(--success-bg); border-color: transparent; }
.eng-item.bad { color: var(--danger-text); background: var(--danger-bg); border-color: transparent; }

.hero-metrics {
  flex: 1;
  min-width: 320px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(112px, 1fr));
  gap: 4px 18px;
  border-left: 1px solid var(--border-light);
  padding-left: 26px;
}
.metric { padding: 2px 0; }
.metric-num {
  font-size: 21px;
  font-weight: 650;
  color: var(--text-primary);
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}
.metric-den { font-size: 13px; color: var(--text-tertiary); font-weight: 500; }
.metric-label { font-size: 12px; color: var(--text-secondary); margin-top: 1px; }
.metric-sub { font-size: 11px; color: var(--text-tertiary); margin-top: 1px; }

/* ============ 分区 ============ */
.section { margin-bottom: 26px; }
.section-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 11px;
  flex-wrap: wrap;
}
.section-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
  padding-left: 9px;
  position: relative;
}
.section-title::before {
  content: '';
  position: absolute;
  left: 0;
  top: 3px;
  bottom: 3px;
  width: 3px;
  border-radius: 2px;
  background: var(--primary-grad);
}
.section-note { font-size: 12px; color: var(--text-tertiary); }
.section-tags { margin-left: auto; display: flex; align-items: center; gap: 8px; }
.two-col {
  grid-template-columns: repeat(auto-fit, minmax(330px, 1fr));
  margin-bottom: 26px;
}
.graph-card { padding: 14px 16px 16px; }
.tree-grid { grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }

/* ============ 体检清单 ============ */
.check-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
  gap: 12px;
}
.check-card { flex-direction: row; align-items: flex-start; gap: 12px; padding-left: 16px; }
.check-card.error { --ac-fg: var(--danger); --ac-line: var(--danger); --ac-bg: var(--danger-bg); }
.check-card.warn { --ac-fg: var(--warning); --ac-line: var(--warning); --ac-bg: var(--warning-bg); }
.check-bar {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--ac-fg);
}
.check-main { flex: 1; min-width: 0; }
.check-title {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.check-icon { color: var(--ac-fg); font-size: 15px; }
.check-detail {
  font-size: 13px;
  color: var(--text-secondary);
  margin-top: 5px;
  line-height: 1.6;
}
.check-hint {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 6px;
  line-height: 1.55;
}
.check-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-width: 220px;
}
.ok-card { flex-direction: row; align-items: center; gap: 12px; }
.ok-icon { color: var(--success); font-size: 22px; }
.ok-title { font-size: 14px; font-weight: 600; color: var(--text-primary); }
.ok-sub { font-size: 12.5px; color: var(--text-tertiary); margin-top: 2px; }

/* ============ 指纹 ============ */
.fp-list { display: flex; flex-direction: column; gap: 8px; }
.fp-row { display: flex; align-items: center; gap: 10px; }
.fp-term {
  width: 100px;
  flex-shrink: 0;
  font-size: 12.5px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fp-bar {
  flex: 1;
  height: 9px;
  border-radius: 5px;
  background: var(--bg-sunken);
  overflow: hidden;
}
.fp-fill {
  height: 100%;
  border-radius: 5px;
  background: var(--primary-grad);
  min-width: 4px;
}
.fp-docs {
  width: 42px;
  font-size: 11px;
  color: var(--text-tertiary);
  text-align: right;
}
.fp-weight {
  width: 34px;
  text-align: right;
  font-size: 11.5px;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}

/* ============ 成分 ============ */
.comp-list { display: flex; flex-direction: column; gap: 13px; }
.comp-label {
  font-size: 11.5px;
  color: var(--text-tertiary);
  margin-bottom: 6px;
  letter-spacing: 0.03em;
}
.comp-tags { display: flex; flex-wrap: wrap; gap: 6px; }

/* ============ 文档谱系 ============ */
.table-card { padding: 0; overflow: hidden; }
.doc-title { font-size: 13.5px; font-weight: 600; color: var(--text-primary); }
.doc-title-link { cursor: pointer; display: inline-block; }
.doc-title-link:hover { color: var(--primary); }
.doc-sum {
  font-size: 11.5px;
  color: var(--text-tertiary);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 420px;
}
.doc-detail { padding: 14px 16px; background: var(--bg-subtle); }
.detail-cols {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 18px;
}
.detail-head {
  font-size: 11.5px;
  color: var(--text-tertiary);
  margin-bottom: 7px;
  font-weight: 600;
  letter-spacing: 0.03em;
}
.chunk-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
  max-height: 340px;
  overflow-y: auto;
}
.chunk {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: 8px;
  padding: 7px 10px;
}
.chunk-head {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 11.5px;
  color: var(--text-tertiary);
}
.chunk-seq { font-weight: 600; color: var(--text-secondary); }
.chunk-heading {
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chunk-preview {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 4px;
  line-height: 1.55;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.issue { font-size: 12px; color: var(--warning); margin-bottom: 4px; }

/* ============ 结构树 ============ */
.tree-card { padding: 14px 16px; }
.tree-card-head { margin-bottom: 7px; }
.tree-card-title { font-size: 13.5px; font-weight: 600; color: var(--text-primary); }
.tree-card-meta { font-size: 11.5px; color: var(--text-tertiary); margin-left: 6px; }
.tree {
  list-style: none;
  margin: 0;
  padding-left: 15px;
  font-size: 12.5px;
  color: var(--text-secondary);
  line-height: 1.72;
}
.tree > li { position: relative; }
.tree > li::before {
  content: '';
  position: absolute;
  left: -9px;
  top: 11px;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--primary-200);
}
.tree-title { color: var(--text-secondary); }

.empty {
  font-size: 13px;
  color: var(--text-tertiary);
  padding: 18px 0;
  text-align: center;
}
.empty.small { padding: 8px 0; font-size: 12px; }

/* ============ 窄屏 ============ */
@media (max-width: 768px) {
  .hero { gap: 16px; }
  /* 分隔线在窄屏是道竖杠，横着排指标时它没有意义 */
  .hero-metrics {
    border-left: none;
    padding-left: 0;
    grid-template-columns: repeat(2, 1fr);
    gap: 10px 14px;
  }
  .hero-score { min-width: 0; }
  .check-grid { grid-template-columns: 1fr; }
  .fp-term { width: 72px; }
  .score-ring { width: 76px; height: 76px; }
  .score-inner { width: 62px; height: 62px; }
  .score-num { font-size: 21px; }
}
</style>
