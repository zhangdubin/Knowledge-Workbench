<template>
  <div class="page dna-page">
    <PageTitle
      title="养料 DNA"
      subtitle="喂给模型的资料的体检报告与基因图谱：成分、结构、指纹、健康度"
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
      <!-- ============ 一、总量与健康分 ============ -->
      <div v-if="overview" class="pgrid stat-row">
        <div class="pcard" style="--ac-fg: var(--primary)">
          <div class="stat-label">文档</div>
          <div class="stat-value">{{ overview.totals.documents }}</div>
          <div class="stat-sub">另有笔记 {{ overview.totals.notes }} 篇</div>
        </div>
        <div class="pcard" style="--ac-fg: var(--accent-blue)">
          <div class="stat-label">知识块</div>
          <div class="stat-value">{{ overview.totals.chunks }}</div>
          <div class="stat-sub">{{ overview.totals.words }} 字 · 平均每块 {{ avgChunkWords }} 字</div>
        </div>
        <div class="pcard" style="--ac-fg: var(--accent-green)">
          <div class="stat-label">向量覆盖</div>
          <div class="stat-value">{{ overview.totals.embedded }}<span class="stat-unit">/{{ overview.totals.vector_rows }}</span></div>
          <div class="stat-sub">{{ overview.engine.embed_model }} · {{ overview.engine.embed_dim }} 维 · {{ overview.engine.vec_metric }}</div>
        </div>
        <div class="pcard" style="--ac-fg: var(--accent-amber)">
          <div class="stat-label">库体积</div>
          <div class="stat-value">{{ formatBytes(overview.totals.db_bytes) }}</div>
          <div class="stat-sub">其中向量 {{ formatBytes(overview.totals.vector_bytes) }}</div>
        </div>
        <div class="pcard score-card" :style="scoreAccent">
          <div class="stat-label">健康分</div>
          <div class="stat-value">{{ overview.score }}<span class="stat-unit">/100</span></div>
          <div class="score-bar">
            <div class="score-fill" :style="{ width: overview.score + '%' }" />
          </div>
          <div class="stat-sub">{{ scoreText }}</div>
        </div>
      </div>

      <!-- ============ 二、体检清单（这个页面最要紧的东西） ============ -->
      <div v-if="overview" class="section">
        <div class="section-head">
          <h3 class="section-title">
            体检清单
            <span class="section-badge">{{ overview.checks.length }} 项</span>
          </h3>
          <div class="section-extra">
            <span v-if="errCount" class="ptag" style="--ac-fg: var(--danger); --ac-bg: var(--danger-bg); --ac-line: var(--danger)">
              {{ errCount }} 严重
            </span>
            <span v-if="warnCount" class="ptag" style="--ac-fg: var(--warning); --ac-bg: var(--warning-bg); --ac-line: var(--warning)">
              {{ warnCount }} 警告
            </span>
          </div>
        </div>

        <div v-if="!overview.checks.length" class="pcard ok-card">
          <el-icon class="ok-icon"><CircleCheckFilled /></el-icon>
          <div>
            <div class="ok-title">一切正常</div>
            <div class="ok-sub">没有检出问题：正文齐、向量齐、索引一致。</div>
          </div>
        </div>

        <div v-else class="check-list">
          <div
            v-for="c in overview.checks"
            :key="c.key"
            class="pcard check-card"
            :class="c.level"
          >
            <div class="check-main">
              <div class="check-title">
                <el-icon class="check-icon"><component :is="levelIcon(c.level)" /></el-icon>
                {{ c.title }}
              </div>
              <div class="check-detail">{{ c.detail }}</div>
              <div class="check-hint">
                <el-icon><InfoFilled /></el-icon>{{ c.hint }}
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
      </div>

      <!-- ============ 三、主题指纹 + 成分 ============ -->
      <div v-if="overview" class="pgrid two-col">
        <div class="pcard">
          <div class="section-head">
            <h3 class="section-title">主题指纹</h3>
            <span class="section-note">这批资料反复在说些什么</span>
          </div>
          <div v-if="!overview.fingerprint.length" class="empty">还没有可统计的正文</div>
          <div v-else class="fp-list">
            <div v-for="f in overview.fingerprint" :key="f.term" class="fp-row">
              <span class="fp-term">{{ f.term }}</span>
              <div class="fp-bar">
                <div class="fp-fill" :style="{ width: fpWidth(f) + '%' }" />
              </div>
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

      <!-- ============ 四、文档谱系 ============ -->
      <div v-if="overview" class="section">
        <div class="section-head">
          <h3 class="section-title">文档谱系</h3>
          <span class="section-note">点一行看这篇的结构与切块</span>
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
            <el-table-column prop="title" label="标题" min-width="220">
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
      </div>

      <!-- ============ 五、全库结构索引 ============ -->
      <div v-if="overview" class="section">
        <div class="section-head">
          <h3 class="section-title">全库结构索引</h3>
          <span class="section-note">每篇文档的标题层级 —— 人和模型都能当目录用</span>
        </div>
        <div class="pcard">
          <div v-if="!tree.length" class="empty">没有结构信息</div>
          <div v-for="t in tree" :key="t.id" class="tree-doc">
            <div class="tree-doc-title">
              {{ t.title }}
              <span class="tree-doc-meta">{{ t.words }} 字</span>
            </div>
            <ul class="tree">
              <li v-for="(n, i) in t.outline" :key="i">
                <span class="tree-title">{{ n.title }}</span>
                <ul v-if="n.children && n.children.length">
                  <li v-for="(c, j) in n.children" :key="j">
                    <span class="tree-title">{{ c.title }}</span>
                  </li>
                </ul>
              </li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
/**
 * 养料 DNA —— 喂给模型的资料的体检报告与基因图谱
 *
 * 这个页面只读：它回答四个问题
 *   成分（我到底喂了什么）· 骨架（这些东西长什么样）
 *   指纹（主题特征是什么）· 健康度（哪里有毛病）
 *
 * 唯一的写操作是体检清单里的「重建索引」——
 * 那不是 DNA 的一部分，是给体检结论配的一个修复按钮。
 *
 * 结构树那一块借鉴的是 OpenKB 的 PageIndex：
 * 把文档编成标题树，靠结构定位，而不是只靠相似度。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import PageTitle from '../components/PageTitle.vue'
import { Api } from '../api'

const loading = ref(false)
const error = ref('')
const overview = ref(null)
const documents = ref([])
const tree = ref([])
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

const scoreAccent = computed(() => {
  const s = overview.value?.score ?? 0
  const color = s >= 90 ? 'var(--success)' : s >= 70 ? 'var(--warning)' : 'var(--danger)'
  return { '--ac-fg': color }
})

const scoreText = computed(() => {
  const s = overview.value?.score ?? 0
  if (s >= 95) return '状态很好'
  if (s >= 90) return '基本健康'
  if (s >= 70) return '有些问题要处理'
  return '需要尽快处理'
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

/* ---- 统计卡 ---- */
.stat-row {
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  margin-bottom: 22px;
}
.stat-label {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  letter-spacing: 0.04em;
}
.stat-value {
  font-size: 26px;
  font-weight: 650;
  color: var(--text-primary);
  line-height: 1.25;
  margin-top: 2px;
}
.stat-unit {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-tertiary);
  margin-left: 2px;
}
.stat-sub {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  margin-top: 2px;
}
.score-bar {
  height: 5px;
  border-radius: 3px;
  background: var(--bg-sunken);
  overflow: hidden;
  margin: 7px 0 4px;
}
.score-fill {
  height: 100%;
  border-radius: 3px;
  background: var(--ac-fg, var(--primary));
  transition: width 0.4s var(--ease-out);
}

/* ---- 分区 ---- */
.section { margin-bottom: 24px; }
.section-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 10px;
}
.section-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}
.section-badge {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  font-weight: 500;
}
.section-note {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
.section-extra { margin-left: auto; display: flex; gap: 6px; }
.two-col {
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  margin-bottom: 24px;
}

/* ---- 体检清单 ---- */
.check-list { display: flex; flex-direction: column; gap: 10px; }
.check-card { flex-direction: row; align-items: flex-start; gap: 14px; }
.check-card.error { --ac-fg: var(--danger); --ac-line: var(--danger); --ac-bg: var(--danger-bg); }
.check-card.warn { --ac-fg: var(--warning); --ac-line: var(--warning); --ac-bg: var(--warning-bg); }
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
  margin-top: 5px;
  line-height: 1.55;
}
.check-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-width: 260px;
}
.ok-card { flex-direction: row; align-items: center; gap: 12px; }
.ok-icon { color: var(--success); font-size: 22px; }
.ok-title { font-size: 14px; font-weight: 600; color: var(--text-primary); }
.ok-sub { font-size: 12.5px; color: var(--text-tertiary); margin-top: 2px; }

/* ---- 指纹 ---- */
.fp-list { display: flex; flex-direction: column; gap: 7px; }
.fp-row { display: flex; align-items: center; gap: 10px; }
.fp-term {
  width: 104px;
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
.fp-weight {
  width: 38px;
  text-align: right;
  font-size: 11.5px;
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
}

/* ---- 成分 ---- */
.comp-list { display: flex; flex-direction: column; gap: 12px; }
.comp-label {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  margin-bottom: 6px;
}
.comp-tags { display: flex; flex-wrap: wrap; gap: 6px; }

/* ---- 文档谱系 ---- */
.table-card { padding: 0; overflow: hidden; }
.doc-title { font-size: 13.5px; font-weight: 600; color: var(--text-primary); }
.doc-title-link {
  cursor: pointer;
  display: inline-block;
}
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
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  margin-bottom: 7px;
  font-weight: 600;
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
.issue {
  font-size: 12px;
  color: var(--warning);
  margin-bottom: 4px;
}

/* ---- 结构树 ---- */
.tree-doc { padding: 10px 0; border-bottom: 1px solid var(--border-light); }
.tree-doc:last-child { border-bottom: none; }
.tree-doc-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 5px;
}
.tree-doc-meta { font-size: 11.5px; color: var(--text-tertiary); font-weight: 400; margin-left: 6px; }
.tree {
  list-style: none;
  margin: 0;
  padding-left: 16px;
  font-size: 12.5px;
  color: var(--text-secondary);
  line-height: 1.75;
}
.tree > li { position: relative; }
.tree > li::before {
  content: '';
  position: absolute;
  left: -10px;
  top: 11px;
  width: 5px;
  height: 5px;
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
</style>
