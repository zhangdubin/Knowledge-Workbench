<template>
  <div class="page lib-page">
    <PageTitle
      title="养料库"
      subtitle="DNA 养料库：把资料变成可复用的基因，断网时靠它撑住整个系统"
      icon-key="DataBoard"
    >
      <el-button :loading="loading" @click="loadAll">
        <el-icon><Refresh /></el-icon>刷新
      </el-button>
      <el-button :loading="absorbing" @click="absorbAll">
        <el-icon><Download /></el-icon>全库吸收
      </el-button>
      <el-button @click="exportBundle">
        <el-icon><FolderOpened /></el-icon>导出养料库
      </el-button>
    </PageTitle>

    <!-- 离线横幅：断网时整个界面要立刻说清楚自己处在什么状态 -->
    <transition name="band">
      <div v-if="overview?.offline" class="offline-band">
        <el-icon><WarningFilled /></el-icon>
        <div class="band-text">
          <b>离线模式已开启</b>
          <span>语义检索与答案生成已关闭（它们要网络），系统改用养料库的本地索引直答。</span>
        </div>
        <el-button size="small" @click="toggleOffline(false)">退出离线模式</el-button>
      </div>
    </transition>

    <el-alert v-if="error" type="error" :closable="false" show-icon style="margin-bottom: 14px">
      {{ error }}
    </el-alert>

    <div v-loading="loading && !overview" class="lib-body">
      <!-- 一、库概览：五种碱基 -->
      <div v-if="overview" class="pcard lib-hero">
        <div class="hero-left">
          <div class="hero-num">
            <span class="num">{{ overview.total }}</span>
            <span class="unit">条基因</span>
          </div>
          <div class="hero-meta">
            <span class="chip">{{ overview.health.used }} 条被用过</span>
            <span class="chip">累计引用 {{ overview.health.usage_total }} 次</span>
            <span class="chip">冷基因 {{ overview.health.cold }}</span>
            <span class="chip">源码销毁 {{ overview.health.destroyed_sources }}</span>
          </div>
        </div>
        <div class="base-strip">
          <div
            v-for="k in overview.kinds"
            :key="k.key"
            class="base-cell"
            :class="k.key"
            :title="`${k.label}：${k.desc}`"
          >
            <div class="base-bar" :style="{ height: baseHeight(k.count) }" />
            <div class="base-num">{{ k.count }}</div>
            <div class="base-label">{{ k.label }}</div>
          </div>
        </div>
      </div>

      <div class="pgrid lib-cols">
        <!-- 二、吸收 -->
        <div class="pcard">
          <div class="card-head">
            <h3>吸收</h3>
            <span class="card-note">把资料变成基因；源码只留经验，原文销毁</span>
          </div>

          <el-tabs v-model="absorbTab" class="absorb-tabs">
            <el-tab-pane label="文本" name="text">
              <el-input
                v-model="absorbText"
                type="textarea"
                :rows="5"
                placeholder="粘一段资料（结构化、非结构化都行）。库会按「这段话的价值在哪」拆成事实/方法/经验/接口/约定。"
              />
              <div class="absorb-row">
                <el-input v-model="absorbTitle" placeholder="标题（可留空）" style="flex:1" />
                <el-button type="primary" :loading="absorbing" @click="absorbTextNow">吸收</el-button>
              </div>
            </el-tab-pane>

            <el-tab-pane label="源码（吸收后销毁）" name="code">
              <el-alert type="warning" :closable="false" show-icon class="code-alert">
                源码会被静态分析，抽出方法与经验；<b>原文不入库</b>，只留一份销毁证明（指纹 + 时间 + 文件名）。
              </el-alert>
              <el-input v-model="codeFilename" placeholder="文件名，如 utils.py" style="margin-bottom:8px" />
              <el-input
                v-model="absorbCode"
                type="textarea"
                :rows="5"
                placeholder="粘源码…"
              />
              <div class="absorb-row">
                <el-switch v-model="destroySource" active-text="蒸馏后销毁原文" />
                <el-button type="primary" :loading="absorbing" @click="absorbCodeNow">蒸馏吸收</el-button>
              </div>

              <el-divider>或：从文件库里选一份已上传的源码</el-divider>
              <div class="src-pick">
                <el-select
                  v-model="sourceDocId"
                  placeholder="选择文件库里的源码文件"
                  filterable
                  clearable
                  style="flex:1"
                >
                  <el-option
                    v-for="d in sourceDocs"
                    :key="d.id"
                    :label="`${d.title}（${d.ext || '无扩展名'}）`"
                    :value="d.id"
                  />
                </el-select>
                <el-switch v-model="destroySourceFile" active-text="销毁源文件" />
                <el-button type="danger" plain :loading="absorbing" @click="absorbSourceNow">
                  吸收并销毁
                </el-button>
              </div>
              <div class="src-hint">
                销毁顺序是固定的：先蒸馏成基因、先写销毁证明，然后才删磁盘上的源文件、清掉库里的抽取正文。
                证明没落库就不删 —— 文件没了证据也没了，等于什么都没留下。
              </div>
            </el-tab-pane>
          </el-tabs>

          <div v-if="lastAbsorb" class="absorb-result">
            <div class="ar-title">
              <el-icon><CircleCheckFilled /></el-icon>
              吸收完成：{{ lastAbsorb.genes }} 条基因
              <span v-if="lastAbsorb.destroyed" class="ar-destroy">原文已销毁</span>
            </div>
            <div v-if="lastAbsorb.summary" class="ar-line">摘要：{{ lastAbsorb.summary }}</div>
            <div v-if="lastAbsorb.attestation" class="ar-line mono">
              销毁证明：sha256={{ lastAbsorb.attestation.sha256.slice(0, 24) }}… ·
              {{ lastAbsorb.attestation.destroyed_at }}
            </div>
            <ul v-if="lastAbsorb.titles && lastAbsorb.titles.length" class="ar-list">
              <li v-for="(t, i) in lastAbsorb.titles" :key="i">{{ t }}</li>
            </ul>
          </div>
        </div>

        <!-- 三、离线 -->
        <div class="pcard">
          <div class="card-head">
            <h3>断网可用性</h3>
            <span class="card-note">断网之后系统还剩什么</span>
          </div>

          <div class="offline-switch">
            <span>离线模式</span>
            <el-switch v-model="offlineLocal" @change="toggleOffline" />
          </div>

          <ul class="cap-list">
            <li v-for="c in overview?.offline_ready?.checks || []" :key="c.key">
              <span class="cap-dot" :class="c.ok ? 'ok' : 'off'" />
              <span class="cap-key">{{ capLabel(c.key) }}</span>
              <span class="cap-detail">{{ c.detail }}</span>
            </li>
          </ul>

          <div class="drill">
            <div class="drill-head">
              <span>断网演练</span>
              <el-button size="small" :loading="drilling" @click="runDrill">跑一遍</el-button>
            </div>
            <div v-if="drillResult" class="drill-result">
              <div class="drill-score" :class="drillResult.ok ? 'ok' : 'bad'">
                {{ drillResult.passed }}/{{ drillResult.total }} 题 · {{ drillResult.ms }}ms
              </div>
              <ul class="drill-list">
                <li v-for="(r, i) in drillResult.results" :key="i">
                  <span class="cap-dot" :class="r.ok ? 'ok' : 'off'" />
                  <span class="drill-q">{{ r.question }}</span>
                  <span class="drill-ms">{{ r.ms }}ms</span>
                </li>
              </ul>
              <div class="drill-note">{{ drillResult.note }}</div>
            </div>
            <div v-else class="drill-hint">
              演练只用养料库的本地索引跑一遍问答（含一道拒答题），全程不调模型、不调 embedding。
            </div>
          </div>
        </div>
      </div>

      <!-- 四、检索与直答 -->
      <div class="pcard">
        <div class="card-head">
          <h3>基因检索与离线直答</h3>
          <span class="card-note">直答 = 不调模型，把基因与原文原样端出来</span>
        </div>
        <div class="ask-row">
          <el-input
            v-model="query"
            placeholder="问一句：比如「投标截止时间是什么时候」「有哪些经验」"
            clearable
            @keyup.enter="doSearch"
          />
          <el-button type="primary" :loading="searching" @click="doSearch">检索基因</el-button>
          <el-button :loading="searching" @click="doAnswer">离线直答</el-button>
        </div>

        <div v-if="answer" class="answer-box">
          <div class="answer-head">
            <span class="answer-tag">直答</span>
            <span class="answer-note">未调用模型，以下均为养料库中的原始记录</span>
          </div>
          <pre class="answer-text">{{ answer.text }}</pre>
          <div v-if="answer.genes && answer.genes.length" class="answer-genes">
            <span class="ag-label">命中基因</span>
            <span v-for="g in answer.genes" :key="g.gene.id" class="ag-chip" :class="g.gene.kind">
              {{ g.gene.title }}
            </span>
          </div>
        </div>

        <div v-if="hits.length" class="gene-list">
          <div v-for="h in hits" :key="h.gene.id" class="gene-row">
            <span class="gene-kind" :class="h.gene.kind">{{ kindLabel(h.gene.kind) }}</span>
            <div class="gene-main">
              <div class="gene-title">{{ h.gene.title }}</div>
              <div class="gene-sum">{{ h.gene.summary }}</div>
              <div class="gene-meta">
                <span>来源：{{ h.gene.source_title || h.gene.source_kind || '养料库' }}</span>
                <span>被用 {{ h.gene.usage_count }} 次</span>
                <span>置信 {{ h.gene.confidence }}</span>
                <span v-if="h.gene.meta?.destroyed" class="gene-destroyed">原文已销毁</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 五、基因清单 -->
      <div v-if="overview" class="pcard">
        <div class="card-head">
          <h3>基因清单</h3>
          <div class="kind-filter">
            <el-radio-group v-model="kindFilter" size="small" @change="loadGenes">
              <el-radio-button value="">全部</el-radio-button>
              <el-radio-button v-for="k in overview.kinds" :key="k.key" :value="k.key">
                {{ k.label }} {{ k.count }}
              </el-radio-button>
            </el-radio-group>
            <el-select v-model="statusFilter" size="small" class="status-filter" @change="loadGenes">
              <el-option label="当前基因" value="active" />
              <el-option label="已被取代" value="superseded" />
              <el-option label="全部" value="all" />
            </el-select>
          </div>
        </div>
        <el-table :data="genes" class="ptable" v-loading="loading && !genes.length" row-key="id">
          <el-table-column prop="kind" label="种类" width="90">
            <template #default="{ row }">
              <span class="gene-kind" :class="row.kind">{{ kindLabel(row.kind) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="title" label="标题" min-width="240">
            <template #default="{ row }">
              <div class="gene-title">{{ row.title }}</div>
              <div class="gene-sum">{{ row.summary }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="source_title" label="来源" min-width="160" />
          <el-table-column label="状态" width="94">
            <template #default="{ row }">
              <span v-if="row.status === 'superseded'" class="gene-superseded">已被取代</span>
              <span v-else-if="row.meta && row.meta.destroyed" class="gene-destroyed">已销毁源</span>
              <span v-else class="gene-live">当前</span>
            </template>
          </el-table-column>
          <el-table-column prop="usage_count" label="表达度" width="90" sortable />
          <el-table-column label="置信" width="80">
            <template #default="{ row }">{{ row.confidence }}</template>
          </el-table-column>
          <el-table-column type="expand">
            <template #default="{ row }">
              <pre class="gene-content">{{ row.content }}</pre>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup>
/**
 * 养料库 —— DNA 养料库的操作台
 *
 * 这个页面回答四个问题：
 *   库里有什���（基因清单、种类分布、表达度）
 *   怎么往里放（吸收文本 / 蒸馏源码 / 全库吸收）
 *   断网了还能用吗（离线开关 + 可用性自检 + 断网演练）
 *   怎么带走（导出养料库包）
 *
 * 视觉上刻意与「养料 DNA」页同族：那是体检报告，这是操作台。
 * 五种基因用五种碱基色（A/T/G/C + 中性色）区分，跟 DNA 页的测序风格对齐。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import PageTitle from '../components/PageTitle.vue'
import { Api } from '../api'

const loading = ref(false)
const error = ref('')
const overview = ref(null)
const genes = ref([])
const hits = ref([])
const answer = ref(null)
const drillResult = ref(null)
const lastAbsorb = ref(null)
const absorbing = ref(false)
const searching = ref(false)
const drilling = ref(false)
const offlineLocal = ref(false)
const kindFilter = ref('')
const statusFilter = ref('active')
const query = ref('')
const absorbTab = ref('text')
const absorbText = ref('')
const absorbTitle = ref('')
const absorbCode = ref('')
const codeFilename = ref('snippet.py')
const destroySource = ref(true)
const destroySourceFile = ref(false)
const sourceDocId = ref(null)
const sourceDocs = ref([])

const KIND_LABEL = {
  fact: '事实', method: '方法', experience: '经验',
  interface: '接口', policy: '约定',
}
const KIND_DESC = {
  fact: '是什么', method: '怎么做', experience: '踩过什么坑',
  interface: '怎么调', policy: '必须怎么做',
}

function kindLabel(k) {
  return KIND_LABEL[k] || k
}

function capLabel(k) {
  return {
    knowledge: '资料原文', fts: '全文检索', genes: '基因库',
    vector: '语义检索', llm: '答案生成',
  }[k] || k
}

const maxKind = computed(() => {
  const kinds = overview.value?.kinds || []
  return kinds.length ? Math.max(...kinds.map((k) => k.count), 1) : 1
})

function baseHeight(count) {
  const max = maxKind.value
  if (!max) return 4
  return Math.max(6, Math.round((count / max) * 100))
}

watch(offlineLocal, (v) => {
  if (overview.value && v !== overview.value.offline) {
    // 用户拨了开关但还没落库 —— 以服务端为准，别让界面先撒谎
    offlineLocal.value = overview.value.offline
  }
})

async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    const [ov, list] = await Promise.all([
      Api.dnaLibraryOverview(),
      Api.dnaLibraryGenes({ kind: kindFilter.value, status: statusFilter.value, limit: 200 }),
    ])
    overview.value = ov
    offlineLocal.value = !!ov.offline
    genes.value = list.items || []
  } catch (e) {
    error.value = '养料库读取失败：' + (e?.message || e)
  } finally {
    loading.value = false
  }
  await loadSourceDocs()
}

/** 可吸收的源码候选：文件库里看起来像代码的文件 */
async function loadSourceDocs() {
  try {
    const r = await Api.listDocuments({ limit: 200 })
    const items = r.items || r.documents || []
    sourceDocs.value = items.filter(
      (d) => /\.(py|js|ts|tsx|jsx|java|go|rs|rb|php|c|cc|cpp|h|hpp|sh|bash|sql|yaml|yml|json|toml|ini|conf)$/i
        .test(d.filename || d.title || '')
    )
  } catch (e) {
    sourceDocs.value = []
  }
}

async function loadGenes() {
  try {
    const list = await Api.dnaLibraryGenes({
      kind: kindFilter.value, status: statusFilter.value, limit: 200 })
    genes.value = list.items || []
  } catch (e) {
    ElMessage.error('读基因清单失败：' + (e?.message || e))
  }
}

async function absorbAll() {
  absorbing.value = true
  try {
    const r = await Api.dnaLibraryAbsorbAll()
    ElMessage.success(`吸收完成：${r.genes} 条基因（新建 ${r.created}）`)
    lastAbsorb.value = { genes: r.genes, titles: [] }
    await loadAll()
  } catch (e) {
    ElMessage.error('全库吸收失败：' + (e?.message || e))
  } finally {
    absorbing.value = false
  }
}

async function absorbTextNow() {
  if (!absorbText.value.trim()) {
    ElMessage.warning('先粘点东西')
    return
  }
  absorbing.value = true
  try {
    const r = await Api.dnaLibraryAbsorb({ text: absorbText.value, title: absorbTitle.value })
    ElMessage.success(`吸收完成：${r.genes} 条基因`)
    lastAbsorb.value = { genes: r.genes, titles: [] }
    absorbText.value = ''
    absorbTitle.value = ''
    await loadAll()
  } catch (e) {
    ElMessage.error('吸收失败：' + (e?.message || e))
  } finally {
    absorbing.value = false
  }
}

async function absorbCodeNow() {
  if (!absorbCode.value.trim()) {
    ElMessage.warning('先粘点源码')
    return
  }
  absorbing.value = true
  try {
    const r = await Api.dnaLibraryAbsorbCode({
      code: absorbCode.value,
      filename: codeFilename.value || 'snippet.py',
      destroy: destroySource.value,
    })
    ElMessage.success(`蒸馏出 ${r.genes} 条基因`)
    lastAbsorb.value = {
      genes: r.genes, summary: r.summary, destroyed: r.destroyed,
      attestation: r.attestation, titles: [],
    }
    absorbCode.value = ''
    await loadAll()
  } catch (e) {
    ElMessage.error('源码蒸馏失败：' + (e?.message || e))
  } finally {
    absorbing.value = false
  }
}

async function absorbSourceNow() {
  if (!sourceDocId.value) {
    ElMessage.warning('先选一份源码文件')
    return
  }
  absorbing.value = true
  try {
    const r = await Api.dnaLibraryAbsorbSource({
      document_id: sourceDocId.value,
      destroy: true,
      destroy_file: destroySourceFile.value,
    })
    ElMessage.success(
      `蒸馏出 ${r.genes} 条基因` +
      (r.file_deleted ? '，源文件已销毁' : '') +
      (r.document_cleared ? '，库里的抽取正文已清空' : '')
    )
    lastAbsorb.value = {
      genes: r.genes, summary: r.summary, destroyed: r.destroyed,
      attestation: r.attestation, titles: [],
    }
    await loadAll()
    await loadSourceDocs()
  } catch (e) {
    ElMessage.error('源码吸收失败：' + (e?.message || e))
  } finally {
    absorbing.value = false
  }
}

async function toggleOffline(on) {
  try {
    const r = await Api.dnaLibraryOffline({ enabled: !!on })
    overview.value = { ...(overview.value || {}), offline: r.offline }
    offlineLocal.value = !!r.offline
    ElMessage.success(r.offline ? '已进入离线模式：语义检索与生成已关闭' : '已退出离线模式')
  } catch (e) {
    offlineLocal.value = !on
    ElMessage.error('切换失败：' + (e?.message || e))
  }
}

async function runDrill() {
  drilling.value = true
  try {
    drillResult.value = await Api.dnaLibraryDrill()
  } catch (e) {
    ElMessage.error('演练失败：' + (e?.message || e))
  } finally {
    drilling.value = false
  }
}

async function doSearch() {
  if (!query.value.trim()) return
  searching.value = true
  answer.value = null
  try {
    const r = await Api.dnaLibrarySearch({ q: query.value, limit: 12 })
    hits.value = r.items || []
    if (!hits.value.length) ElMessage.info('没有命中基因')
  } catch (e) {
    ElMessage.error('检索失败：' + (e?.message || e))
  } finally {
    searching.value = false
  }
}

async function doAnswer() {
  if (!query.value.trim()) return
  searching.value = true
  hits.value = []
  try {
    answer.value = await Api.dnaLibraryAnswer({ q: query.value, limit: 5 })
  } catch (e) {
    ElMessage.error('直答失败：' + (e?.message || e))
  } finally {
    searching.value = false
  }
}

async function exportBundle() {
  try {
    const r = await Api.dnaLibraryBundle()
    ElMessage.success(`已导出：${r.info?.bytes ? Math.round(r.info.bytes / 1024) + ' KB' : ''}`)
  } catch (e) {
    ElMessage.error('导出失败：' + (e?.message || e))
  }
}

onMounted(loadAll)
</script>

<style scoped>
.lib-page { padding-bottom: 40px; }
.lib-body { min-height: 200px; }

/* 离线横幅 */
.offline-band {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  margin-bottom: 16px;
  border-radius: 10px;
  background: var(--warning-bg);
  border: 1px solid var(--warning);
  color: var(--text-primary);
}
.offline-band > .el-icon { color: var(--warning); font-size: 18px; }
.band-text { flex: 1; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.band-text b { font-size: 13.5px; }
.band-text span { font-size: 12px; color: var(--text-secondary); }
.band-enter-active, .band-leave-active { transition: opacity .2s ease; }
.band-enter-from, .band-leave-to { opacity: 0; }

/* 概览 */
.lib-hero {
  display: flex;
  align-items: center;
  gap: 28px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}
.hero-left { min-width: 260px; }
.hero-num { display: flex; align-items: baseline; gap: 6px; }
.hero-num .num {
  font-size: 40px; font-weight: 680; color: var(--text-primary);
  font-variant-numeric: tabular-nums; line-height: 1.05;
}
.hero-num .unit { font-size: 13px; color: var(--text-tertiary); }
.hero-meta { display: flex; gap: 7px; flex-wrap: wrap; margin-top: 8px; }
.chip {
  font-size: 11.5px; color: var(--text-secondary);
  background: var(--bg-subtle); border: 1px solid var(--border-light);
  border-radius: 12px; padding: 2px 9px;
}
.base-strip {
  flex: 1; min-width: 300px;
  display: grid; grid-template-columns: repeat(5, 1fr);
  gap: 10px; align-items: end;
  border-left: 1px solid var(--border-light); padding-left: 26px;
}
.base-cell { display: flex; flex-direction: column; align-items: center; gap: 3px; }
.base-bar {
  width: 100%; max-width: 46px; border-radius: 4px 4px 0 0;
  background: var(--primary-grad); min-height: 4px;
}
.base-cell.fact .base-bar { background: var(--primary); }
.base-cell.method .base-bar { background: var(--accent-green); }
.base-cell.experience .base-bar { background: var(--warning); }
.base-cell.interface .base-bar { background: var(--accent-slate); }
.base-cell.policy .base-bar { background: var(--danger); }
.base-num { font-size: 15px; font-weight: 620; color: var(--text-primary); font-variant-numeric: tabular-nums; }
.base-label { font-size: 11.5px; color: var(--text-tertiary); }

/* 两列 */
.lib-cols {
  grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
  margin-bottom: 18px;
}
.card-head {
  display: flex; align-items: baseline; gap: 10px;
  margin-bottom: 12px; flex-wrap: wrap;
}
.card-head h3 {
  font-size: 14.5px; font-weight: 600; color: var(--text-primary);
  margin: 0; padding-left: 9px; position: relative;
}
.card-head h3::before {
  content: ''; position: absolute; left: 0; top: 3px; bottom: 3px;
  width: 3px; border-radius: 2px; background: var(--primary-grad);
}
.card-note { font-size: 11.5px; color: var(--text-tertiary); }

/* 吸收 */
.absorb-tabs :deep(.el-tabs__header) { margin-bottom: 10px; }
.absorb-row { display: flex; gap: 8px; align-items: center; margin-top: 10px; }
.src-pick { display: flex; gap: 8px; align-items: center; }
.src-hint {
  font-size: 11.5px; color: var(--text-tertiary); line-height: 1.6; margin-top: 8px;
}
.code-alert { margin-bottom: 10px; }
.absorb-result {
  margin-top: 12px; padding: 10px 12px;
  border-radius: 10px; background: var(--success-bg);
  border: 1px solid transparent;
}
.ar-title { font-size: 13px; color: var(--text-primary); display: flex; align-items: center; gap: 6px; }
.ar-title .el-icon { color: var(--success); }
.ar-destroy {
  font-size: 11px; color: var(--danger);
  background: var(--danger-bg); border-radius: 4px; padding: 1px 6px;
}
.ar-line { font-size: 12px; color: var(--text-secondary); margin-top: 5px; }
.ar-line.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; }
.ar-list { margin: 6px 0 0; padding-left: 18px; font-size: 12px; color: var(--text-secondary); }

/* 离线 */
.offline-switch {
  display: flex; align-items: center; justify-content: space-between;
  padding: 9px 12px; border-radius: 10px;
  background: var(--bg-subtle); margin-bottom: 12px;
  font-size: 13px; color: var(--text-primary);
}
.cap-list { list-style: none; margin: 0; padding: 0; }
.cap-list li {
  display: flex; align-items: baseline; gap: 8px;
  padding: 6px 0; border-bottom: 1px dashed var(--border-light);
  font-size: 12.5px;
}
.cap-dot {
  width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0;
  align-self: center;
}
.cap-dot.ok { background: var(--success); }
.cap-dot.off { background: var(--text-tertiary); opacity: .6; }
.cap-key { color: var(--text-primary); font-weight: 550; width: 74px; flex-shrink: 0; }
.cap-detail { color: var(--text-tertiary); line-height: 1.5; }

.drill { margin-top: 14px; }
.drill-head {
  display: flex; align-items: center; justify-content: space-between;
  font-size: 13px; color: var(--text-primary); margin-bottom: 6px;
}
.drill-hint { font-size: 12px; color: var(--text-tertiary); line-height: 1.6; }
.drill-score { font-size: 15px; font-weight: 620; margin-bottom: 6px; }
.drill-score.ok { color: var(--success); }
.drill-score.bad { color: var(--danger); }
.drill-list { list-style: none; margin: 0; padding: 0; }
.drill-list li {
  display: flex; align-items: center; gap: 8px;
  font-size: 12px; color: var(--text-secondary); padding: 3px 0;
}
.drill-q { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.drill-ms { color: var(--text-tertiary); font-variant-numeric: tabular-nums; }
.drill-note { font-size: 11px; color: var(--text-tertiary); margin-top: 6px; }

/* 检索 */
.ask-row { display: flex; gap: 8px; margin-bottom: 12px; }
.answer-box {
  border: 1px solid var(--border); border-radius: 10px;
  padding: 12px 14px; background: var(--bg-subtle); margin-bottom: 12px;
}
.answer-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.answer-tag {
  font-size: 11px; color: var(--primary); background: var(--primary-bg);
  border: 1px solid var(--primary-100); border-radius: 5px; padding: 1px 7px;
}
.answer-note { font-size: 11.5px; color: var(--text-tertiary); }
.answer-text {
  white-space: pre-wrap; font-size: 12.5px; line-height: 1.7;
  color: var(--text-primary); margin: 0; font-family: inherit;
}
.answer-genes { margin-top: 10px; display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.ag-label { font-size: 11px; color: var(--text-tertiary); }
.ag-chip {
  font-size: 11.5px; padding: 2px 8px; border-radius: 10px;
  background: var(--bg-card); border: 1px solid var(--border-light);
  color: var(--text-secondary);
}
.ag-chip.experience { border-color: var(--warning); }
.ag-chip.method { border-color: var(--accent-green); }
.ag-chip.interface { border-color: var(--accent-slate); }
.ag-chip.policy { border-color: var(--danger); }
.ag-chip.fact { border-color: var(--primary); }

/* 基因列表 */
.gene-list { display: flex; flex-direction: column; gap: 8px; margin-top: 12px; }
.gene-row {
  display: flex; gap: 10px; align-items: flex-start;
  padding: 9px 11px; border: 1px solid var(--border-light); border-radius: 10px;
  background: var(--bg-card);
}
.gene-kind {
  font-size: 11px; padding: 2px 7px; border-radius: 5px; flex-shrink: 0;
  background: var(--bg-subtle); color: var(--text-secondary);
  border: 1px solid var(--border-light); margin-top: 1px;
}
.gene-kind.fact { color: var(--primary); border-color: var(--primary-100); background: var(--primary-bg); }
.gene-kind.method { color: var(--success-text); border-color: transparent; background: var(--success-bg); }
.gene-kind.experience { color: var(--warning-text); border-color: transparent; background: var(--warning-bg); }
.gene-kind.interface { color: var(--accent-slate); border-color: transparent; background: var(--bg-subtle); }
.gene-kind.policy { color: var(--danger-text); border-color: transparent; background: var(--danger-bg); }
.gene-main { flex: 1; min-width: 0; }
.gene-title { font-size: 13px; color: var(--text-primary); font-weight: 550; }
.gene-sum {
  font-size: 11.5px; color: var(--text-tertiary); margin-top: 2px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.gene-meta {
  display: flex; gap: 12px; flex-wrap: wrap;
  font-size: 11px; color: var(--text-tertiary); margin-top: 4px;
}
.gene-destroyed { color: var(--danger); }
.gene-content {
  white-space: pre-wrap; font-size: 12.5px; line-height: 1.7;
  color: var(--text-secondary); margin: 0; padding: 12px 16px;
  background: var(--bg-subtle);
}
.kind-filter { margin-left: auto; display: flex; gap: 8px; align-items: center; }
.status-filter { width: 116px; }
.gene-superseded {
  font-size: 11px; color: var(--text-tertiary);
  background: var(--bg-subtle); border: 1px dashed var(--border-light);
  border-radius: 5px; padding: 1px 6px;
}
.gene-live { font-size: 11px; color: var(--success-text); }

@media (max-width: 768px) {
  .base-strip { border-left: none; padding-left: 0; }
  .ask-row { flex-direction: column; }
  .kind-filter { margin-left: 0; }
}
</style>
