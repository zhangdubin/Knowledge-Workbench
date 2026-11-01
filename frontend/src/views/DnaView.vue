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

    <!-- 章节目录：报告有七节，滚动找太慢，钉在顶上 -->
    <nav v-if="overview" class="sec-nav" aria-label="报告目录">
      <button
        v-for="s in SECTIONS"
        :key="s.id"
        type="button"
        class="sec-nav-item"
        :class="{ active: activeSection === s.id }"
        @click="jumpTo(s.id)"
      >
        <span class="sec-nav-no">{{ s.no }}</span>{{ s.title }}
      </button>
    </nav>

    <!-- 页头装饰：一条碱基测序条带 -->
    <div class="seq-band" aria-hidden="true">
      <span
        v-for="(c, i) in bandCells"
        :key="i"
        class="seq-cell"
        :style="{ background: c }"
      />
    </div>

    <el-alert v-if="error" type="error" :closable="false" show-icon class="dna-alert">
      {{ error }}
    </el-alert>

    <div v-loading="loading && !overview" class="dna-body">
      <!-- ============ 01 测序概览 ============ -->
      <section v-if="overview" id="sec-overview" class="section">
        <div class="sec-head">
          <span class="sec-no">01</span>
          <h3 class="sec-title">测序概览</h3>
          <span class="sec-note">这批资料被测过一遍的样子</span>
          <span class="sec-rule" />
        </div>

        <div class="ov-card">
          <div class="ov-left">
            <div class="ring-cov" :style="covStyle">
              <div class="ring-hole">
                <div class="ring-score" :style="ringStyle">
                  <div class="ring-core">
                    <span class="ring-num" :style="{ color: scoreColor }">{{ overview.score }}</span>
                    <span class="ring-max">质量分</span>
                  </div>
                </div>
              </div>
            </div>
            <div class="ov-side">
              <div class="ov-title">健康分{{ scoreText }}</div>
              <div class="ov-desc">{{ scoreDesc }}</div>
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

          <div class="ov-metrics">
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
      </section>

      <!-- ============ 02 基因缺陷检测 ============ -->
      <section v-if="overview" id="sec-defects" class="section">
        <div class="sec-head">
          <span class="sec-no">02</span>
          <h3 class="sec-title">基因缺陷检测</h3>
          <span class="sec-note">体检结论 —— 每一条都是一个突变位点</span>
          <span class="sec-rule" />
          <span v-if="errCount" class="ptag" style="--ac-fg: var(--danger); --ac-bg: var(--danger-bg); --ac-line: var(--danger)">
            {{ errCount }} 严重
          </span>
          <span v-if="warnCount" class="ptag" style="--ac-fg: var(--warning); --ac-bg: var(--warning-bg); --ac-line: var(--warning)">
            {{ warnCount }} 警告
          </span>
        </div>

        <div v-if="!overview.checks.length" class="ok-row">
          <el-icon class="ok-icon"><CircleCheckFilled /></el-icon>
          <div>
            <div class="ok-title">一切正常</div>
            <div class="ok-sub">没有检出问题：正文齐、向量齐、索引一致、没有重复内容。</div>
          </div>
        </div>

        <ul v-else class="mut-list">
          <li v-for="(c, i) in overview.checks" :key="c.key" class="mut" :class="c.level">
            <span class="mut-no">{{ mutNo(i) }}</span>
            <span class="mut-dot" />
            <div class="mut-body">
              <div class="mut-title">
                <el-icon class="mut-icon"><component :is="levelIcon(c.level)" /></el-icon>
                {{ c.title }}
              </div>
              <div class="mut-detail">{{ c.detail }}</div>
              <div class="mut-hint">
                <el-icon><InfoFilled /></el-icon><span>{{ c.hint }}</span>
              </div>
            </div>
            <div v-if="c.action === 'reindex' && c.doc_ids && c.doc_ids.length" class="mut-actions">
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
          </li>
        </ul>

        <div class="sec-foot">生成于 {{ formatTime(overview.generated_at) }}</div>
      </section>

      <!-- ============ 03 + 04 指纹与成分 ============ -->
      <div v-if="overview" class="two-col">
        <section id="sec-fingerprint" class="section">
          <div class="sec-head">
            <span class="sec-no">03</span>
            <h3 class="sec-title">碱基测序图谱</h3>
            <span class="sec-rule" />
            <span class="sec-note">反复出现的词</span>
          </div>
          <div class="panel">
            <div v-if="!overview.fingerprint.length" class="empty">还没有可统计的正文</div>
            <div v-else class="read-list">
              <div v-for="(f, i) in overview.fingerprint" :key="f.term" class="read">
                <span class="read-no">{{ pad2(i + 1) }}</span>
                <div class="read-band">
                  <span
                    v-for="(c, j) in readCells(f, i)"
                    :key="j"
                    class="read-cell"
                    :style="{ background: c }"
                  />
                  <span class="read-tip">
                    <b>{{ f.term }}</b>
                    <span>权重 {{ f.weight.toFixed(1) }} · {{ f.docs }} 篇</span>
                  </span>
                </div>
                <span class="read-docs">{{ f.docs }} 篇</span>
              </div>
            </div>
          </div>
        </section>

        <section id="sec-composition" class="section">
          <div class="sec-head">
            <span class="sec-no">04</span>
            <h3 class="sec-title">碱基组成统计</h3>
            <span class="sec-rule" />
            <span class="sec-note">资料都是哪来的</span>
          </div>
          <div class="panel">
            <div v-for="g in compGroups" :key="g.key" class="comp-group">
              <div class="comp-label">
                {{ g.label }}<span class="comp-total">{{ g.total }}</span>
              </div>
              <div class="comp-matrix">
                <div v-for="(it, i) in g.items" :key="it.key" class="comp-item">
                  <span class="comp-blocks">
                    <i
                      v-for="n in Math.min(it.count, 24)"
                      :key="n"
                      class="comp-cell"
                      :style="{ background: baseColors[(i + n) % 4] }"
                    />
                  </span>
                  <span class="comp-name">{{ it.name }} · {{ it.count }}</span>
                </div>
              </div>
            </div>
          </div>
        </section>
      </div>

      <!-- ============ 05 DNA 双螺旋图谱 ============ -->
      <section v-if="overview" id="sec-helix" class="section">
        <div class="sec-head">
          <span class="sec-no">05</span>
          <h3 class="sec-title">DNA 双螺旋图谱</h3>
          <span class="sec-note">知识链 ↔ 证据链，双击文件节点可去数据中心</span>
          <span class="sec-rule" />
        </div>
        <div class="panel panel-flush">
          <DnaGraph :graph="graph" :focus-id="focusNodeId" @select="onGraphSelect" />
        </div>
      </section>

      <!-- ============ 06 染色体清单 ============ -->
      <section v-if="overview" id="sec-chromosomes" class="section">
        <div class="sec-head">
          <span class="sec-no">06</span>
          <h3 class="sec-title">染色体清单</h3>
          <span class="sec-note">点标题展开这篇的结构与切块</span>
          <span class="sec-rule" />
        </div>
        <div class="chr-list">
          <div
            v-for="doc in documents"
            :key="doc.id"
            class="chr"
            :class="{ 'is-sel': selDocId === doc.id }"
          >
            <button class="chr-head" type="button" @click="toggleDoc(doc)">
              <span class="chr-code">chr-{{ pad2(doc.id) }}</span>
              <span class="chr-title">{{ doc.title }}</span>
              <span class="chr-bar" :title="`${doc.embedded ?? 0}/${doc.chunks ?? 0} 已向量化`">
                <i
                  v-for="n in chromSegs(doc)"
                  :key="n"
                  class="chr-cell"
                  :class="{ on: n <= (doc.embedded ?? 0) }"
                />
              </span>
              <span class="chr-meta">{{ doc.words ?? 0 }} 字 · {{ doc.chunks ?? 0 }} 块</span>
              <span class="chr-acts" @click.stop>
                <el-button size="small" text @click="locateInHelix(doc)">
                  <el-icon><Aim /></el-icon>双螺旋定位
                </el-button>
                <el-button size="small" text @click="openInLibrary(doc)">
                  <el-icon><Document /></el-icon>打开
                </el-button>
                <el-button
                  size="small" text :loading="reindexing === doc.id"
                  @click="reindex(doc.id)"
                >
                  <el-icon><Refresh /></el-icon>重建索引
                </el-button>
              </span>
              <el-icon class="chr-arrow" :class="{ open: isOpen(doc.id) }"><ArrowRight /></el-icon>
            </button>
            <div v-if="isOpen(doc.id)" class="chr-detail">
              <el-skeleton v-if="detailFor(doc.id).loading" :rows="3" animated />
              <template v-else-if="detailFor(doc.id).data">
                <div class="detail-cols">
                  <div class="detail-col">
                    <div class="detail-head">结构树</div>
                    <div v-if="!detailFor(doc.id).data.outline.length" class="empty small">没有标题层级</div>
                    <ul v-else class="tree">
                      <li v-for="(n, i) in detailFor(doc.id).data.outline" :key="i">
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
                    <div class="detail-head">切块（{{ detailFor(doc.id).data.chunks.length }}）</div>
                    <div class="chunk-list">
                      <div v-for="c in detailFor(doc.id).data.chunks" :key="c.id" class="chunk">
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
                      <span v-for="t in detailFor(doc.id).data.terms" :key="t.term" class="ptag ptag-plain">
                        {{ t.term }} · {{ t.count }}
                      </span>
                    </div>
                    <template v-if="detailFor(doc.id).data.links.length">
                      <div class="detail-head">关联</div>
                      <div class="comp-tags">
                        <span v-for="l in detailFor(doc.id).data.links" :key="l.id" class="ptag ptag-plain">
                          {{ l.title }}
                        </span>
                      </div>
                    </template>
                    <template v-if="detailFor(doc.id).data.issues.length">
                      <div class="detail-head">这篇的问题</div>
                      <div v-for="(is, i) in detailFor(doc.id).data.issues" :key="i" class="issue">
                        {{ is.title }}：{{ is.detail }}
                      </div>
                    </template>
                  </div>
                </div>
              </template>
              <div v-else class="empty small">读不到这篇的详情</div>
            </div>
          </div>
        </div>
      </section>

      <!-- ============ 07 基因骨架 ============ -->
      <section v-if="overview" id="sec-skeleton" class="section">
        <div class="sec-head">
          <span class="sec-no">07</span>
          <h3 class="sec-title">基因骨架</h3>
          <span class="sec-note">每篇文档的标题层级 —— 人和模型都能当目录用</span>
          <span class="sec-rule" />
        </div>
        <!--
          骨架默认是**收起的**：
          以前一上来就把每篇文档的完整目录铺开，页面拉到几千像素高，
          真正想看的东西被埋在下面。
          现在默认是一张列表（每篇一行），点开一行才展开那一篇的层级；
          想大窗看，点「弹窗」。
        -->
        <div class="skel-list">
          <div
            v-for="t in tree"
            :key="t.id"
            class="skel-row"
            :class="{ 'is-open': isSkelOpen(t.id) }"
          >
            <button
              type="button"
              class="skel-row-main"
              :aria-expanded="isSkelOpen(t.id)"
              @click="toggleSkel(t.id)"
            >
              <el-icon class="skel-caret" :class="{ 'is-open': isSkelOpen(t.id) }">
                <ArrowRight />
              </el-icon>
              <span class="skel-rail" />
              <span class="skel-title">{{ t.title }}</span>
              <span v-if="t.ext" class="skel-ext">{{ t.ext }}</span>
              <span class="skel-badge">{{ t.structure || '整篇' }}</span>
              <span class="skel-meta">{{ outlineCount(t) }} 个节点 · {{ t.words }} 字</span>
            </button>
            <button
              type="button"
              class="skel-row-open"
              title="在弹窗里看完整层级"
              @click.stop="openSkelDialog(t)"
            >
              <el-icon><FullScreen /></el-icon>
            </button>

            <div v-if="isSkelOpen(t.id)" class="skel-detail">
              <ul v-if="t.outline && t.outline.length" class="tree">
                <li v-for="(n, i) in t.outline" :key="i">
                  <span class="tree-title">{{ n.title }}</span>
                  <span v-if="n.snippet" class="tree-snip">{{ n.snippet }}</span>
                  <ul v-if="n.children && n.children.length">
                    <li v-for="(c, j) in n.children" :key="j">
                      <span class="tree-title">{{ c.title }}</span>
                      <span v-if="c.snippet" class="tree-snip">{{ c.snippet }}</span>
                      <ul v-if="c.children && c.children.length">
                        <li v-for="(g, k) in c.children" :key="k">
                          <span class="tree-title">{{ g.title }}</span>
                          <span v-if="g.snippet" class="tree-snip">{{ g.snippet }}</span>
                        </li>
                      </ul>
                    </li>
                  </ul>
                </li>
              </ul>
              <div v-else class="empty small">这篇没有结构（正文型文件）</div>
              <div v-if="t.summary" class="skel-sum">{{ t.summary }}</div>
            </div>
          </div>
          <div v-if="!tree.length" class="empty">还没有资料</div>
        </div>

        <!-- 弹窗看完整层级：大屏比页内展开好读 -->
        <el-dialog
          v-model="skelDialog.visible"
          :title="skelDialog.doc?.title || '基因骨架'"
          width="760px"
          top="8vh"
          class="skel-dialog"
        >
          <div v-if="skelDialog.doc">
            <div class="skel-dlg-meta">
              <span v-if="skelDialog.doc.ext" class="skel-ext">{{ skelDialog.doc.ext }}</span>
              <span class="skel-badge">{{ skelDialog.doc.structure || '整篇' }}</span>
              <span class="skel-meta">
                {{ outlineCount(skelDialog.doc) }} 个节点 · {{ skelDialog.doc.words }} 字
              </span>
            </div>
            <ul v-if="skelDialog.doc.outline && skelDialog.doc.outline.length" class="tree tree-lg">
              <li v-for="(n, i) in skelDialog.doc.outline" :key="i">
                <span class="tree-title">{{ n.title }}</span>
                <span v-if="n.snippet" class="tree-snip">{{ n.snippet }}</span>
                <ul v-if="n.children && n.children.length">
                  <li v-for="(c, j) in n.children" :key="j">
                    <span class="tree-title">{{ c.title }}</span>
                    <span v-if="c.snippet" class="tree-snip">{{ c.snippet }}</span>
                    <ul v-if="c.children && c.children.length">
                      <li v-for="(g, k) in c.children" :key="k">
                        <span class="tree-title">{{ g.title }}</span>
                        <span v-if="g.snippet" class="tree-snip">{{ g.snippet }}</span>
                      </li>
                    </ul>
                  </li>
                </ul>
              </li>
            </ul>
            <div v-else class="empty small">这篇没有结构（正文型文件）</div>
            <div v-if="skelDialog.doc.summary" class="skel-sum">{{ skelDialog.doc.summary }}</div>
          </div>
        </el-dialog>
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
 * 视觉上，整页是一份「测序报告」：
 *   页头条带 → 测序概览 → 基因缺陷检测 → 碱基测序图谱 →
 *   碱基组成统计 → DNA 双螺旋图谱 → 染色体清单 → 基因骨架
 * 结构树借鉴的是 OpenKB 的 PageIndex：
 * 把文档编成标题树，靠结构定位，而不是只靠相似度。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import PageTitle from '../components/PageTitle.vue'
import DnaGraph from '../components/DnaGraph.vue'
import { Api } from '../api'

/** 报告目录：七节，编号与页面上的节号一致 */
const SECTIONS = [
  { id: 'sec-overview', no: '01', title: '测序概览' },
  { id: 'sec-defects', no: '02', title: '缺陷检测' },
  { id: 'sec-fingerprint', no: '03', title: '测序图谱' },
  { id: 'sec-composition', no: '04', title: '碱基组成' },
  { id: 'sec-helix', no: '05', title: '双螺旋图谱' },
  { id: 'sec-chromosomes', no: '06', title: '染色体清单' },
  { id: 'sec-skeleton', no: '07', title: '基因骨架' },
]

const activeSection = ref('sec-overview')
/** 双螺旋里要高亮的节点（染色体清单点「定位」时用） */
const focusNodeId = ref('')

/**
 * 在双螺旋里点了一个节点 → 染色体清单里对应的那一行也点亮
 *
 * 反向定位：以前只有「清单 → 图」这一条路，
 * 在图里点一个文件，清单那边一点反应都没有 ——
 * 两边明明指的是同一份东西。
 */
const selDocId = ref(0)

function onGraphSelect(n) {
  const id = n?.id || ''
  if (n?.kind !== 'document' || !id.startsWith('doc-')) {
    selDocId.value = 0
    return
  }
  selDocId.value = Number(id.slice(4)) || 0
}

/** 把某个文件在双螺旋里点亮并滚过去 */
async function locateInHelix(doc) {
  focusNodeId.value = ''
  await nextTick()
  focusNodeId.value = `doc-${doc.id}`
  jumpTo('sec-helix')
}

/** 去数据中心看这份文件 */
function openInLibrary(doc) {
  window.location.hash = `/library?doc=${doc.id}`
}

// ---- 基因骨架：默认收起的列表 ----

/** 展开着的文档 id（可多开） */
const skelOpen = ref(new Set())

function isSkelOpen(id) {
  return skelOpen.value.has(id)
}

function toggleSkel(id) {
  const s = new Set(skelOpen.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  skelOpen.value = s
}

/** 骨架里一共几个节点（列表上显示「N 个节点」） */
function outlineCount(t) {
  let n = 0
  const walk = (list) => {
    for (const x of list || []) {
      n += 1
      walk(x.children)
    }
  }
  walk(t?.outline)
  return n
}

/** 弹窗看完整层级 */
const skelDialog = ref({ visible: false, doc: null })

function openSkelDialog(t) {
  skelDialog.value = { visible: true, doc: t }
}

function jumpTo(id) {
  const el = document.getElementById(id)
  if (!el) return
  activeSection.value = id
  el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const loading = ref(false)
const error = ref('')
const overview = ref(null)
const documents = ref([])
const tree = ref([])
const graph = ref({ nodes: [], edges: [], stats: {} })
const details = ref({})
const reindexing = ref(0)
const openDoc = ref(0)

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

/* ------------------------------------------------------------------ *
 * 碱基四色：只在 CSS 里定义一次，这里读出来给 canvas / 内联样式用
 * ------------------------------------------------------------------ */
const BASE_VARS = ['--primary', '--accent-green', '--warning', '--accent-slate']
const baseColors = computed(() => {
  // 深色下 accent 色板没有暗色档，直接用会在深底上糊掉 —— 往正文色方向推一档
  const dark = document.documentElement.classList.contains('dark')
  const text = getComputedStyle(document.documentElement).getPropertyValue('--text-primary').trim() || '#17181d'
  return BASE_VARS.map((v) => {
    const raw = (getComputedStyle(document.documentElement).getPropertyValue(v) || '').trim()
    if (!raw) return 'var(' + v + ')'
    return dark ? mixHex(raw, text, 0.26) : mixHex(raw, text, 0.08)
  })
})

function hexToRgb(c) {
  let s = String(c).trim()
  if (s[0] === '#') {
    let h = s.slice(1)
    if (h.length === 3) h = h.split('').map((x) => x + x).join('')
    const n = parseInt(h.slice(0, 6), 16)
    return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 }
  }
  const m = s.match(/rgba?\(([^)]+)\)/)
  if (m) {
    const p = m[1].split(/[,\s/]+/).filter(Boolean).map(Number)
    return { r: p[0] || 0, g: p[1] || 0, b: p[2] || 0 }
  }
  return { r: 128, g: 128, b: 128 }
}

function mixHex(a, b, t) {
  const A = hexToRgb(a)
  const B = hexToRgb(b)
  const f = (x, y) => Math.round(x * t + y * (1 - t))
  return `rgb(${f(A.r, B.r)}, ${f(A.g, B.g)}, ${f(A.b, B.b)})`
}

/* ------------------------------------------------------------------ *
 * 页头条带
 * ------------------------------------------------------------------ */
const bandCells = computed(() => {
  const colors = baseColors.value
  const out = []
  // 72 格：长度按权重抖动，看起来像真的测序读段
  const weights = [3, 1, 2, 4, 1, 2, 3, 2, 1, 4, 2, 3]
  for (let i = 0; i < 72; i++) {
    const w = weights[i % weights.length]
    const c = colors[(i * 7 + Math.floor(i / 5)) % 4]
    out.push(w >= 3 ? c : mixHex(c, 'rgba(0,0,0,0)', 0.45))
  }
  return out
})

/* ------------------------------------------------------------------ *
 * 概览
 * ------------------------------------------------------------------ */
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
  return { background: `conic-gradient(${scoreColor.value} ${s * 3.6}deg, var(--bg-sunken) 0deg)` }
})

const covStyle = computed(() => {
  const r = vectorRatio.value
  const c = r >= 90 ? 'var(--primary)' : (r >= 50 ? 'var(--warning)' : 'var(--danger)')
  return { background: `conic-gradient(${c} ${r * 3.6}deg, var(--bg-sunken) 0deg)` }
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
  return `这批资料能喂给模型，但有 ${bad} 处需要注意（见基因缺陷检测）。`
})

const vectorRatio = computed(() => {
  const t = overview.value?.totals
  if (!t || !t.db_bytes) return 0
  return Math.round((t.vector_bytes / t.db_bytes) * 100)
})

/* ------------------------------------------------------------------ *
 * 03 碱基测序图谱（主题指纹）
 * ------------------------------------------------------------------ */
function readCells(f, idx) {
  const colors = baseColors.value
  const n = Math.max(3, Math.min(26, Math.round(f.weight)))
  const out = []
  for (let i = 0; i < n; i++) out.push(colors[(idx + i) % 4])
  return out
}

/* ------------------------------------------------------------------ *
 * 04 碱基组成统计
 * ------------------------------------------------------------------ */
const compGroups = computed(() => {
  const c = overview.value?.composition || {}
  const mk = (key, label, items, nameOf) => ({
    key,
    label,
    total: items.reduce((s, i) => s + (i.count || 0), 0),
    items: (items || []).map((i) => ({ key: i.key, count: i.count || 0, name: nameOf(i) })),
  })
  const groups = [
    mk('kind', '按类型', c.by_kind, (i) => i.label || i.key),
    mk('ext', '按扩展名', c.by_ext, (i) => i.key || '（无扩展名）'),
    mk('source', '按来源', c.by_source, (i) => sourceLabel(i.key)),
    mk('month', '按月份', c.by_month, (i) => i.month || i.key),
  ]
  if (c.by_tag && c.by_tag.length) {
    groups.push(mk('tag', '按标签', c.by_tag, (i) => i.key))
  }
  return groups
})

/* ------------------------------------------------------------------ *
 * 06 染色体清单
 * ------------------------------------------------------------------ */
function chromSegs(doc) {
  const n = Math.max(1, Math.min(40, doc.chunks || doc.headings || 1))
  return Array.from({ length: n }, (_, i) => i + 1)
}

// 注意参数是 **id** 不是文档对象：
// 模板里写的是 isOpen(doc.id)。之前这里写成 isOpen(doc)，
// 于是函数体里的 doc.id 变成了 undefined —— 永远比较不相等，
// 展开面板永远不显示（点击像是没反应，其实数据都取回来了）。
function isOpen(id) {
  return openDoc.value === id
}

function toggleDoc(doc) {
  if (openDoc.value === doc.id) {
    openDoc.value = 0
    return
  }
  openDoc.value = doc.id
  loadDetail(doc)
}

/* ------------------------------------------------------------------ *
 * 工具
 * ------------------------------------------------------------------ */
function pad2(n) {
  return String(n ?? 0).padStart(2, '0')
}

function mutNo(i) {
  return `C-${pad2(i + 1)}`
}

function levelIcon(level) {
  if (level === 'error') return 'CircleCloseFilled'
  if (level === 'warn') return 'WarningFilled'
  return 'CircleCheckFilled'
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

/* ------------------------------------------------------------------ *
 * 滚动高亮：当前在第几节
 * ------------------------------------------------------------------ */
let spy = null

function setupSpy() {
  if (spy) spy.disconnect()
  if (typeof IntersectionObserver === 'undefined') return
  spy = new IntersectionObserver((entries) => {
    // 取当前贴着视口上沿的那一节
    const visible = entries
      .filter((e) => e.isIntersecting)
      .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
    if (visible.length) activeSection.value = visible[0].target.id
  }, { rootMargin: '-72px 0px -60% 0px', threshold: 0 })
  SECTIONS.forEach((s) => {
    const el = document.getElementById(s.id)
    if (el) spy.observe(el)
  })
}

onMounted(async () => {
  await loadAll()
  await nextTick()
  setupSpy()
})

onBeforeUnmount(() => {
  if (spy) spy.disconnect()
  spy = null
})
</script>

<style scoped>
.dna-body { min-height: 200px; }
.dna-alert { margin-bottom: 20px; }

/* 章节目录：报告有七节，滚动找太慢 —— 钉在顶上 */
.sec-nav {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  gap: 4px;
  overflow-x: auto;
  margin: 0 0 14px;
  padding: 7px 8px;
  border-radius: 10px;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  box-shadow: 0 1px 8px rgba(15, 18, 30, 0.04);
  scrollbar-width: none;
}
.sec-nav::-webkit-scrollbar { display: none; }
.sec-nav-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  padding: 5px 11px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12.5px;
  font-family: inherit;
  cursor: pointer;
  transition: background .15s ease, color .15s ease;
}
.sec-nav-item:hover { background: var(--bg-subtle); color: var(--text-primary); }
.sec-nav-item.active {
  background: var(--primary-bg);
  color: var(--primary);
  font-weight: 600;
}
.sec-nav-no {
  /* 全站 11px 下限：10.5px 的节号在高分屏上发虚 */
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  opacity: .65;
}

/* 染色体行内快捷操作：平时藏着，悬停才出来 */
.chr-acts {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  opacity: 0;
  transition: opacity .15s ease;
}
.chr:hover .chr-acts, .chr:focus-within .chr-acts { opacity: 1; }
.chr-acts :deep(.el-button) { font-size: 12px; }
@media (hover: none) {
  .chr-acts { opacity: 1; }
}

/* ============ 页头装饰条 ============ */
.seq-band {
  display: flex;
  gap: 2px;
  height: 7px;
  margin: -6px 0 26px;
  border-radius: 4px;
  overflow: hidden;
  opacity: 0.85;
}
.seq-cell {
  flex: 1;
  border-radius: 2px;
  min-width: 2px;
}

/* ============ 分区标题 ============ */
.section { margin-bottom: 32px; }
.sec-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.sec-no {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.6px;
  color: var(--primary);
  background: var(--primary-bg);
  border: 1px solid var(--primary-100);
  border-radius: 5px;
  padding: 1px 6px;
  line-height: 16px;
}
.sec-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
  letter-spacing: -0.2px;
}
.sec-note { font-size: 12px; color: var(--text-tertiary); }
.sec-rule {
  flex: 1;
  min-width: 24px;
  height: 1px;
  background: linear-gradient(to right, var(--border), transparent);
}
.sec-foot {
  font-size: 11.5px;
  color: var(--text-tertiary);
  margin-top: 10px;
  text-align: right;
}
.two-col {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 0 28px;
  margin-bottom: 4px;
}
.two-col .section { margin-bottom: 32px; }

/* ============ 面板（统一的「纸」） ============ */
.panel {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: 12px;
  box-shadow: var(--shadow-card);
  padding: 18px 20px;
}
.panel-flush { padding: 16px 18px 18px; }

/* ============ 01 测序概览 ============ */
.ov-card {
  display: flex;
  align-items: stretch;
  gap: 28px;
  flex-wrap: wrap;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: 12px;
  box-shadow: var(--shadow-card);
  padding: 20px 22px;
}
.ov-left { display: flex; align-items: center; gap: 20px; min-width: 340px; }

.ring-cov {
  width: 104px;
  height: 104px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  padding: 4px;
}
.ring-hole {
  width: 96px;
  height: 96px;
  border-radius: 50%;
  background: var(--bg-card);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 4px;
}
.ring-score {
  width: 86px;
  height: 86px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 6px;
}
.ring-core {
  width: 74px;
  height: 74px;
  border-radius: 50%;
  background: var(--bg-card);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  line-height: 1.1;
}
.ring-num {
  font-size: 24px;
  font-weight: 680;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.5px;
}
.ring-max { font-size: 11px; color: var(--text-tertiary); margin-top: 1px; }

.ov-side { min-width: 0; }
.ov-title { font-size: 16px; font-weight: 600; color: var(--text-primary); }
.ov-desc { font-size: 13px; color: var(--text-secondary); margin-top: 4px; line-height: 1.6; }
.engine-strip { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 11px; }
.eng-item {
  font-size: 11px;
  color: var(--text-tertiary);
  background: var(--bg-subtle);
  border-radius: 5px;
  padding: 2px 8px;
  font-variant-numeric: tabular-nums;
}
.eng-item.ok { color: var(--success-text); background: var(--success-bg); }
.eng-item.bad { color: var(--danger-text); background: var(--danger-bg); }

.ov-metrics {
  flex: 1;
  min-width: 320px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(112px, 1fr));
  gap: 6px 20px;
  border-left: 1px solid var(--border-light);
  padding-left: 28px;
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

/* ============ 02 基因缺陷检测 ============ */
.mut-list { list-style: none; margin: 0; padding: 0; }
.mut {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 15px 4px 15px 2px;
  border-bottom: 1px solid var(--border-light);
  --ac-fg: var(--success);
}
.mut:last-child { border-bottom: 0; }
.mut.error { --ac-fg: var(--danger); }
.mut.warn { --ac-fg: var(--warning); }
.mut-no {
  font-family: var(--font-mono);
  font-size: 11.5px;
  font-weight: 700;
  color: var(--text-tertiary);
  letter-spacing: 0.4px;
  padding-top: 2px;
  flex-shrink: 0;
  width: 42px;
}
.mut-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--ac-fg);
  flex-shrink: 0;
  margin-top: 7px;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--ac-fg) 18%, transparent);
}
.mut-body { flex: 1; min-width: 0; }
.mut-title {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 14.5px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.5;
}
.mut-icon { color: var(--ac-fg); font-size: 15px; }
.mut-detail {
  font-size: 13px;
  color: var(--text-secondary);
  margin-top: 4px;
  line-height: 1.6;
}
.mut-hint {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 5px;
  line-height: 1.6;
}
.mut-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-width: 220px;
  flex-shrink: 0;
}
.ok-row {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 20px;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: 12px;
}
.ok-icon { color: var(--success); font-size: 24px; }
.ok-title { font-size: 14.5px; font-weight: 600; color: var(--text-primary); }
.ok-sub { font-size: 12.5px; color: var(--text-tertiary); margin-top: 3px; }

/* ============ 03 碱基测序图谱 ============ */
.read-list { display: flex; flex-direction: column; gap: 11px; }
.read { display: flex; align-items: center; gap: 10px; }
.read-no {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-tertiary);
  width: 20px;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}
.read-band {
  position: relative;
  flex: 1;
  display: flex;
  gap: 2px;
  align-items: center;
  height: 16px;
  min-width: 0;
}
.read-cell {
  height: 11px;
  flex: 1;
  min-width: 3px;
  border-radius: 2px;
  transition: transform 0.16s var(--ease-out);
}
.read:hover .read-cell { transform: scaleY(1.35); }
.read-tip {
  position: absolute;
  left: 0;
  bottom: calc(100% + 8px);
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 6px 10px;
  border-radius: 8px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  box-shadow: var(--shadow-overlay);
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
  opacity: 0;
  transform: translateY(4px);
  pointer-events: none;
  transition: opacity 0.16s var(--ease-out), transform 0.16s var(--ease-out);
  z-index: 3;
}
.read-tip b { color: var(--text-primary); font-size: 12.5px; }
.read:hover .read-tip { opacity: 1; transform: translateY(0); }
.read-docs {
  font-size: 11px;
  color: var(--text-tertiary);
  width: 40px;
  text-align: right;
  flex-shrink: 0;
}

/* ============ 04 碱基组成统计 ============ */
.comp-group { margin-bottom: 16px; }
.comp-group:last-child { margin-bottom: 0; }
.comp-label {
  font-size: 11.5px;
  color: var(--text-tertiary);
  margin-bottom: 8px;
  letter-spacing: 0.04em;
  display: flex;
  align-items: center;
  gap: 7px;
}
.comp-total {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-disabled);
  background: var(--bg-subtle);
  border-radius: 4px;
  padding: 0 5px;
}
.comp-matrix { display: flex; flex-direction: column; gap: 8px; }
.comp-item { display: flex; align-items: center; gap: 10px; }
.comp-blocks { display: flex; gap: 3px; align-items: center; flex-shrink: 0; }
.comp-cell {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  display: block;
}
.comp-name {
  font-size: 12.5px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.comp-tags { display: flex; flex-wrap: wrap; gap: 6px; }

/* ============ 06 染色体清单 ============ */
.chr-list {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: 12px;
  box-shadow: var(--shadow-card);
  overflow: hidden;
}
.chr + .chr { border-top: 1px solid var(--border-light); }
/* 在双螺旋里点中的那一行：左侧一条主色轨 + 淡底 */
.chr.is-sel {
  background: var(--primary-bg);
  box-shadow: inset 3px 0 0 var(--primary);
}
.chr.is-sel .chr-title { color: var(--primary); }
.chr.is-sel .chr-head { background: transparent; }
.chr-head {
  display: flex;
  align-items: center;
  gap: 14px;
  width: 100%;
  padding: 12px 18px;
  background: none;
  border: 0;
  text-align: left;
  cursor: pointer;
  font: inherit;
  transition: background 0.15s var(--ease-out);
}
.chr-head:hover { background: var(--bg-subtle); }
.chr-code {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 700;
  color: var(--primary);
  background: var(--primary-bg);
  border: 1px solid var(--primary-100);
  border-radius: 5px;
  padding: 1px 6px;
  flex-shrink: 0;
  width: 58px;
  text-align: center;
}
.chr-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-primary);
  flex: 0 1 320px;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chr-bar {
  flex: 1;
  min-width: 80px;
  display: flex;
  gap: 2px;
  align-items: center;
  height: 14px;
}
.chr-cell {
  flex: 1;
  min-width: 3px;
  height: 9px;
  border-radius: 2px;
  background: var(--bg-sunken);
  border: 1px solid var(--border-light);
}
.chr-cell.on {
  background: var(--primary-200);
  border-color: transparent;
}
.chr-meta {
  font-size: 11.5px;
  color: var(--text-tertiary);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.chr-arrow {
  color: var(--text-tertiary);
  font-size: 14px;
  transition: transform 0.18s var(--ease-out);
  flex-shrink: 0;
}
.chr-arrow.open { transform: rotate(90deg); }
.chr-detail { padding: 4px 18px 18px; background: var(--bg-subtle); }
.detail-cols {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 20px;
  padding-top: 14px;
}
.detail-head {
  font-size: 11.5px;
  color: var(--text-tertiary);
  margin-bottom: 8px;
  font-weight: 600;
  letter-spacing: 0.04em;
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
  padding: 8px 11px;
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

/* ============ 07 基因骨架 ============ */
/* 骨架默认收起：列表一行一篇，点开才展开层级 */
.skel-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.skel-row {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: 10px;
  box-shadow: var(--shadow-card);
  overflow: hidden;
  transition: border-color 0.16s var(--ease-out), box-shadow 0.16s var(--ease-out);
}
.skel-row:hover {
  border-color: var(--border-strong);
}
.skel-row.is-open {
  border-color: var(--primary);
  box-shadow: 0 0 0 1px var(--primary-bg), var(--shadow-card);
}
.skel-row-main {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 11px 12px;
  border: 0;
  background: none;
  font: inherit;
  text-align: left;
  cursor: pointer;
  color: inherit;
  min-height: 0;
}
.skel-row-main:hover {
  background: var(--bg-subtle);
}
.skel-caret {
  color: var(--text-tertiary);
  transition: transform 0.18s var(--ease-out);
  flex-shrink: 0;
}
.skel-caret.is-open {
  transform: rotate(90deg);
  color: var(--primary);
}
.skel-row-open {
  position: absolute;
  right: 30px;
  top: 8px;
  border: 0;
  background: none;
  color: var(--text-tertiary);
  cursor: pointer;
  padding: 3px;
  border-radius: 6px;
  opacity: 0;
  transition: opacity 0.16s var(--ease-out);
}
.skel-row {
  position: relative;
}
.skel-row:hover .skel-row-open {
  opacity: 1;
}
.skel-row-open:hover {
  color: var(--primary);
  background: var(--bg-subtle);
}
.skel-detail {
  padding: 4px 16px 14px 44px;
  border-top: 1px dashed var(--border-light);
  margin-top: 2px;
}
.skel-dlg-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-light);
}
.tree-lg {
  font-size: 13px;
  max-height: 56vh;
  overflow: auto;
}
.skel-rail {
  width: 3px;
  height: 15px;
  border-radius: 2px;
  background: var(--primary-grad);
  flex-shrink: 0;
}
.skel-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.skel-meta {
  font-size: 11px;
  color: var(--text-tertiary);
  margin-left: auto;
  white-space: nowrap;
}

/* 结构树：骨架式的连接线 */
.tree {
  list-style: none;
  margin: 0;
  padding-left: 14px;
  font-size: 12.5px;
  color: var(--text-secondary);
  line-height: 1.7;
}
.tree li { position: relative; }
.tree li::before {
  content: '';
  position: absolute;
  left: -9px;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--border-light);
}
.tree li:last-child::before { bottom: auto; height: 11px; }
.tree li::after {
  content: '';
  position: absolute;
  left: -9px;
  top: 11px;
  width: 8px;
  height: 1px;
  background: var(--border-light);
}
.tree > li::before { top: 4px; }
.tree-title { color: var(--text-secondary); }
.tree > li > .tree-title { color: var(--text-primary); font-weight: 500; }

.empty {
  font-size: 13px;
  color: var(--text-tertiary);
  padding: 18px 0;
  text-align: center;
}
.empty.small { padding: 8px 0; font-size: 12px; }

/* ============ 窄屏 ============ */
@media (max-width: 768px) {
  .seq-band { margin-bottom: 20px; height: 6px; }
  .ov-card { padding: 16px; gap: 18px; }
  .ov-left { min-width: 0; gap: 14px; }
  .ov-metrics {
    border-left: none;
    padding-left: 0;
    grid-template-columns: repeat(2, 1fr);
    gap: 10px 14px;
  }
  .ring-cov { width: 84px; height: 84px; }
  .ring-hole { width: 76px; height: 76px; }
  .ring-score { width: 66px; height: 66px; }
  .ring-core { width: 56px; height: 56px; }
  .ring-num { font-size: 19px; }
  .two-col { grid-template-columns: 1fr; }
  .mut { flex-wrap: wrap; gap: 10px; }
  .mut-actions { max-width: none; width: 100%; padding-left: 66px; }
  .chr-head { flex-wrap: wrap; gap: 8px 10px; padding: 12px 14px; }
  .chr-title { flex: 1 1 100%; order: 3; }
  .chr-bar { order: 4; flex-basis: 100%; }
  .chr-detail { padding: 4px 14px 16px; }
  .detail-cols { grid-template-columns: 1fr; }
}

/* 骨架卡片：结构类型徽章 + 节点摘要 */
.skel-ext {
  font-size: 11px; padding: 1px 6px; border-radius: 4px;
  background: var(--bg-subtle); color: var(--text-secondary);
  font-family: var(--font-mono, ui-monospace, monospace);
}
.skel-badge {
  display: inline-block; margin-right: 6px;
  padding: 1px 7px; border-radius: 999px;
  background: var(--primary-bg); color: var(--primary);
  font-size: 11px; font-weight: 600;
}
.tree-snip {
  display: block; margin: 1px 0 3px;
  font-size: 11.5px; line-height: 1.55; color: var(--text-secondary);
  opacity: .82;
}
.skel-sum {
  margin-top: 8px; padding-top: 8px;
  border-top: 1px dashed var(--border-light);
  font-size: 12px; line-height: 1.6; color: var(--text-secondary);
}
</style>
