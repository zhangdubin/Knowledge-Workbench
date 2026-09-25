<template>
  <div class="page">
    <PageTitle
      title="存储与备份"
      subtitle="文件原文外置在文件目录，库里只装元数据与索引 —— 这里看体积花在哪、离红线还有多远、备份有没有真的做成"
      icon-key="DataLine"
    >
      <el-button :loading="loading" @click="reload">
        <el-icon><Refresh /></el-icon>刷新
      </el-button>
      <el-button type="primary" :loading="backing" @click="doBackup">
        <el-icon><FolderAdd /></el-icon>立即备份
      </el-button>
    </PageTitle>

    <!-- 加载失败提示：宁可吵，也不要让「打不开」看起来像「空库」 -->
    <el-alert v-if="loadError" type="error" show-icon :closable="false" class="load-err">
      <template #title>{{ loadError }}</template>
    </el-alert>

    <!-- 概览 -->
    <div class="stat-grid">
      <div class="stat-card" :class="levelClass(worst.level)">
        <div class="icon"><el-icon><Coin /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ fmtBytes(rep.bytes) }}</div>
          <div class="label">单库文件体积</div>
        </div>
      </div>
      <div class="stat-card info">
        <div class="icon"><el-icon><Files /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ fmtBytes(fsTotal) }}</div>
          <div class="label">
            文件原文总量（{{ rep.documents?.count || 0 }} 个）
            <span v-if="rep.documents?.trash_bytes" class="sub-warn">
              ＋回收站 {{ rep.documents.trash_count }} 个 / {{ fmtBytes(rep.documents.trash_bytes) }}
            </span>
            <span v-if="fs.pending_count" class="sub-warn">
              其中 {{ fs.pending_count }} 个仍在库内（{{ fmtBytes(fs.pending_bytes) }}）
            </span>
          </div>
        </div>
      </div>
      <div class="stat-card warning">
        <div class="icon"><el-icon><DataLine /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ rep.index?.vec_ratio ?? 0 }}%</div>
          <div class="label">向量索占比 {{ fmtBytes(rep.index?.vec_alloc_bytes) }}</div>
        </div>
      </div>
      <div class="stat-card" :class="freeLevel">
        <div class="icon"><el-icon><Delete /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ fmtKb(rep.files?.free_kb) }}</div>
          <div class="label">空闲页空洞</div>
        </div>
      </div>
    </div>

    <!-- 文件原文存储 -->
    <div class="card">
      <div class="card-title">
        <span class="card-title-text">
          <el-icon class="title-ico"><FolderOpened /></el-icon>文件原文存储
          <el-tag size="small" :type="fs.enabled ? 'success' : 'warning'" effect="light" style="margin-left:8px">
            {{ fs.enabled ? '外置文件目录' : '库内 BLOB' }}
          </el-tag>
          <el-tag v-if="fs.pending_count" type="warning" size="small" effect="light" style="margin-left:6px">
            {{ fs.pending_count }} 个待外迁
          </el-tag>
        </span>
        <span class="ct-actions">
          <el-button size="small" :loading="verifying" @click="doVerify">一致性普查</el-button>
          <el-button v-if="fs.pending_count" size="small" type="primary"
                     :loading="migrating" @click="doExternalize">
            一键外迁（{{ fs.pending_count }}）
          </el-button>
        </span>
      </div>

      <div class="fs-grid">
        <div class="fs-box">
          <div class="fs-kv"><span>目录</span><b class="mono" :title="fs.root">{{ fs.root || '—' }}</b></div>
          <div class="fs-kv"><span>已存文件</span><b>{{ (fs.files || 0).toLocaleString() }} 个</b></div>
          <div class="fs-kv"><span>目录占用</span><b>{{ fmtBytes(fs.bytes) }}</b></div>
        </div>
        <div class="fs-box">
          <div class="fs-kv"><span>仍在库内的原文</span>
            <b :class="{ bad: fs.pending_count }">{{ fs.pending_count || 0 }} 个 / {{ fmtBytes(fs.pending_bytes) }}</b>
          </div>
          <div class="fs-kv"><span>落盘同步（fsync）</span><b>{{ fs.fsync ? '已开启' : '关闭（依赖备份保障）' }}</b></div>
          <div class="fs-kv"><span>去重方式</span><b>内容寻址（sha256 相同即同一份）</b></div>
        </div>
        <div class="fs-box">
          <div class="fs-kv"><span>磁盘剩余</span>
            <b :class="{ bad: diskLevel === 'danger', warn2: diskLevel === 'warn' }">
              {{ fmtBytes(fs.disk?.free) }} / {{ fmtBytes(fs.disk?.total) }}
            </b>
          </div>
          <div class="fs-bar"><i :class="diskLevel" :style="{ width: Math.max(2, fs.disk?.pct_used || 0) + '%' }" /></div>
          <div class="fs-kv"><span>已用</span><b>{{ fs.disk?.pct_used ?? '—' }}%</b></div>
        </div>
      </div>

      <div v-if="fs.pending_count" class="fs-note warn">
        <el-icon><WarningFilled /></el-icon>
        <span>
          还有 {{ fs.pending_count }} 个文件的原文以 BLOB 形式留在库里，占 {{ fmtBytes(fs.pending_bytes) }}。
          点「一键外迁」搬到文件目录；迁完再执行「整体重整（VACUUM）」才会真正缩小库文件。
        </span>
      </div>
      <div v-else class="fs-note ok">
        <el-icon><CircleCheck /></el-icon>
        <span>
          所有原文都已外置到文件目录。库文件从此只随元数据与索引增长，
          备份窗口与恢复时间不会再被大文件拖着走。
          <b>注意：备份必须同时包含 files 目录</b>，只备 kb.db 会得到一份「记录在、内容丢」的空壳。
        </span>
      </div>
    </div>

    <!-- 容量余量 -->
    <div class="card">
      <div class="card-title">
        <span class="card-title-text"><el-icon class="title-ico"><Odometer /></el-icon>容量余量</span>
        <span class="ct-hint">进度条以「危险线」为 100%，越靠右越接近需要迁移的量级</span>
      </div>
      <div class="cap-list">
        <div v-for="c in rep.capacity || []" :key="c.label" class="cap-row">
          <span class="cap-name" :title="c.hint">{{ c.label }}</span>
          <span class="cap-bar">
            <i :class="c.level" :style="{ width: Math.max(2, c.pct) + '%' }" />
          </span>
          <span class="cap-val">{{ fmtByUnit(c.value, c.unit) }}</span>
          <span class="cap-flag" :class="c.level">{{ LEVEL_TEXT[c.level] }}</span>
        </div>
      </div>
      <div class="cap-note">
        红线参考：单库 50 GB ｜ 文件原文 100 GB ｜ 记录 100 万行 ｜ 向量 100 万块。
        越过红线后备份窗口、VACUUM 耗时与崩溃恢复时间会一起失控。
      </div>
    </div>

    <!-- 体积构成 + 明细 -->
    <div class="dual">
      <div class="card">
        <div class="card-title">
          <span class="card-title-text"><el-icon class="title-ico"><PieChart /></el-icon>体积构成</span>
        </div>
        <EChart v-if="(rep.tables || []).length" :option="pieOption" height="240px" />
        <div v-else class="chart-empty">暂无数据</div>
      </div>
      <div class="card">
        <div class="card-title">
          <span class="card-title-text"><el-icon class="title-ico"><Histogram /></el-icon>占用明细</span>
        </div>
        <div class="tbl-wrap">
          <table class="mini-table">
            <thead><tr><th>对象</th><th class="num">体积</th><th class="num">占比</th></tr></thead>
            <tbody>
              <tr v-for="t in (rep.tables || []).slice(0, 10)" :key="t.name">
                <td class="mono" :title="t.name">{{ t.name }}</td>
                <td class="num">{{ fmtBytes(t.bytes) }}</td>
                <td class="num">{{ t.pct }}%</td>
              </tr>
              <tr v-if="!(rep.tables || []).length"><td colspan="3" class="empty">暂无数据</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- 体检结论 -->
    <div class="card">
      <div class="card-title">
        <span class="card-title-text"><el-icon class="title-ico"><Bell /></el-icon>体检结论</span>
        <span class="ct-hint">库健康：{{ rep.journal_mode }} ｜ auto_vacuum：{{ rep.auto_vacuum_label }}</span>
      </div>
      <div class="tips">
        <div v-for="(t, i) in rep.tips || []" :key="i" class="tip-row" :class="t.level">
          <el-icon class="tip-ico">
            <component :is="t.level === 'ok' ? 'CircleCheck' : t.level === 'warn' ? 'Warning' : 'InfoFilled'" />
          </el-icon>
          <span>{{ t.text }}</span>
        </div>
        <div v-if="!(rep.tips || []).length" class="chart-empty">暂无结论</div>
      </div>
    </div>

    <!-- 索引一致性 -->
    <div class="card">
      <div class="card-title">
        <span class="card-title-text">
          <el-icon class="title-ico"><Connection /></el-icon>索引一致性
          <el-tag v-if="idx.ok" type="success" size="small" effect="light" style="margin-left:8px">一致</el-tag>
          <el-tag v-else type="warning" size="small" effect="light" style="margin-left:8px">
            {{ (idx.problems || []).length }} 项待处理
          </el-tag>
        </span>
        <span class="ct-actions">
          <el-button size="small" :loading="indexLoading" @click="loadIndex">重新体检</el-button>
          <el-button size="small" type="warning" plain :loading="repairing" @click="doRepair">一键修复</el-button>
        </span>
      </div>

      <div class="idx-grid">
        <div class="idx-box">
          <div class="ix-title">全文索引 FTS5</div>
          <div class="ix-rows">
            <div class="ix-row"><span>已索引</span><b>{{ idx.fts?.indexed ?? '—' }}</b></div>
            <div class="ix-row" :class="{ bad: idx.fts?.missing }">
              <span>缺失</span><b>{{ idx.fts?.missing ?? '—' }}</b></div>
            <div class="ix-row" :class="{ bad: idx.fts?.orphan }">
              <span>残留</span><b>{{ idx.fts?.orphan ?? '—' }}</b></div>
            <div class="ix-row"><span>有效文件</span><b>{{ idx.fts?.documents ?? '—' }}</b></div>
          </div>
        </div>
        <div class="idx-box">
          <div class="ix-title">向量索引 vec0（{{ idx.vec?.chunks ?? 0 }} 块）</div>
          <div class="ix-rows">
            <div class="ix-row"><span>实际向量</span><b>{{ idx.vec?.vectors ?? '—' }}</b></div>
            <div class="ix-row" :class="{ bad: idx.vec?.marked_but_missing }">
              <span>标记了但缺失</span><b>{{ idx.vec?.marked_but_missing ?? '—' }}</b></div>
            <div class="ix-row" :class="{ bad: idx.vec?.present_but_unmarked }">
              <span>存在但未标记</span><b>{{ idx.vec?.present_but_unmarked ?? '—' }}</b></div>
            <div class="ix-row"><span>未向量化</span><b>{{ idx.vec?.unembedded ?? '—' }}</b></div>
          </div>
        </div>
        <div class="idx-box">
          <div class="ix-title">正文抽取</div>
          <div class="ix-rows">
            <div v-for="(n, k) in (idx.extract || {})" :key="k" class="ix-row" :class="{ bad: k === 'failed' && n }">
              <span>{{ EXTRACT_LABEL[k] || k }}</span><b>{{ n }}</b>
            </div>
            <div v-if="!Object.keys(idx.extract || {}).length" class="ix-row"><span>暂无</span><b>—</b></div>
          </div>
        </div>
      </div>

      <div v-if="(idx.problems || []).length" class="problems">
        <div v-for="(p, i) in idx.problems" :key="i" class="pb-row">
          <el-icon><Warning /></el-icon><span>{{ p }}</span>
        </div>
      </div>
      <div v-else class="problems none">
        <el-icon><CircleCheck /></el-icon>
        <span>业务表与两类索引完全对得上，语义检索不会静默漏检。</span>
      </div>
    </div>

    <!-- 备份 -->
    <div class="card">
      <div class="card-title">
        <span class="card-title-text"><el-icon class="title-ico"><FolderAdd /></el-icon>备份</span>
        <span class="ct-actions">
          <el-tooltip content="备份目录（生产环境应指向另一块盘或网络存储）" placement="top">
            <el-tag size="small" type="info" effect="plain" class="mono">{{ backupsDir || '/app/backups' }}</el-tag>
          </el-tooltip>
        </span>
      </div>

      <div class="bk-note">
        <p>
          一份备份 = 一个快照目录：<code>kb.db</code>（元数据与索引，VACUUM INTO 一致性副本）
          ＋ <code>files/</code>（文件原文，与上一份快照硬链接共享未变动的文件）。
          产出后自动做 <code>quick_check</code> 并核对行数 —— <b>没校验过的备份不算备份</b>。
        </p>
        <p class="warn-line">
          <el-icon><WarningFilled /></el-icon>
          <span>
            原文已外置，<b>只备份 kb.db 会得到一份「记录在、内容丢」的空壳</b>。
            请统一用 <code>backup.sh</code>；也不要 <code>cp kb.db</code> 备份 ——
            WAL 模式下最新数据可能还只在 <code>-wal</code> 里，单拷主库会得到过期副本。
          </span>
        </p>
      </div>

      <div class="bk-cli">
        <div class="bk-cli-row">
          <code>./scripts/backup.sh</code><span>完整快照（库 + 文件）并轮转保留 14 份</span>
        </div>
        <div class="bk-cli-row">
          <code>./scripts/restore.sh</code><span>服务起不来时的灾难恢复（正常运行时直接在下面列表点「还原」）</span>
        </div>
        <div class="bk-cli-row">
          <code>./scripts/healthcheck.sh</code><span>上线前自检：容器/库/文件/备份/鉴权/口令</span>
        </div>
        <div class="bk-cli-row">
          <code>0 2 * * * cd $(pwd) &amp;&amp; ./scripts/backup.sh &gt;&gt; logs/backup.log 2&gt;&amp;1</code>
          <span>crontab 每日 02:00 自动备份</span>
        </div>
      </div>

      <el-table :data="backups" size="small" class="data-table" empty-text="还没有备份，点右上角「立即备份」或跑一次 backup.sh">
        <el-table-column prop="name" label="备份" min-width="210">
          <template #default="{ row }">
            <span class="mono">{{ row.name }}</span>
            <el-tag v-if="row.kind === 'legacy'" type="warning" size="small" effect="light"
                    style="margin-left:6px">旧格式</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="库文件" width="100">
          <template #default="{ row }">{{ fmtBytes(row.db_bytes) }}</template>
        </el-table-column>
        <el-table-column label="文件原文" width="150">
          <template #default="{ row }">
            <span v-if="row.kind === 'snapshot'">
              {{ row.files_count }} 个 · {{ fmtBytes(row.files_bytes) }}
            </span>
            <span v-else class="sub-warn" style="display:inline">未包含</span>
          </template>
        </el-table-column>
        <el-table-column label="合计" width="100">
          <template #default="{ row }">{{ fmtBytes(row.bytes) }}</template>
        </el-table-column>
        <el-table-column prop="mtime" label="生成时间" width="170" />
        <el-table-column label="操作" width="76" align="center">
          <template #default="{ row }">
            <el-button v-if="row.kind === 'snapshot'" size="small" type="warning"
                       effect="plain" @click="openRestore(row)">还原</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="backups.some(b => b.kind === 'legacy')" class="fs-note warn" style="margin-top:12px">
        <el-icon><WarningFilled /></el-icon>
        <span>
          标记「旧格式」的备份只含数据库、不含文件原文，原文外置之后它们已不完整，
          只能作为历史留档，不能用来恢复。可用 <code>backup.sh</code> 做一份新快照后删除。
        </span>
      </div>

      <!-- 还原确认 -->
      <el-dialog v-model="restoreDlg" title="还原到这个快照" width="600px"
                 :close-on-click-modal="false" :close-on-press-escape="!restoring"
                 :show-close="!restoring">
        <template v-if="restoreTarget">
          <div class="rs-summary">
            <div class="rs-row">
              <span class="rs-label">快照</span>
              <span class="mono">{{ restoreTarget.name }}</span>
            </div>
            <div class="rs-row">
              <span class="rs-label">生成时间</span>
              <span>{{ restoreTarget.mtime }}</span>
            </div>
            <div class="rs-row">
              <span class="rs-label">内容</span>
              <span>库 {{ fmtBytes(restoreTarget.db_bytes) }} ·
                文件原文 {{ restoreTarget.files_count }} 个（{{ fmtBytes(restoreTarget.files_bytes) }}）</span>
            </div>
          </div>
          <el-alert type="warning" :closable="false" class="rs-alert">
            <p>系统会整体回到快照时刻 —— <b>快照之后的新增、修改、删除都会消失</b>。</p>
            <p>还原前会自动把当前状态存成一份<b>退路快照</b>（出现在下方列表里），
              后悔了随时可以再还原回来。</p>
            <p>还原期间（通常几秒，文件多时更久）其他用户的操作会被暂时挡住。</p>
            <p>若快照早于当前登录会话，还原完成后<b>需要用备份时刻的账号口令重新登录</b>。</p>
          </el-alert>
          <div class="rs-confirm">
            <span>输入快照名 <code class="mono">{{ restoreTarget.name }}</code> 确认：</span>
            <el-input v-model="restoreConfirm" size="small" class="mono"
                      placeholder="snap-…" :disabled="restoring" />
          </div>
        </template>
        <template #footer>
          <el-button :disabled="restoring" @click="restoreDlg = false">取消</el-button>
          <el-button type="danger"
                     :disabled="!restoreTarget || restoreConfirm !== restoreTarget.name"
                     :loading="restoring" @click="doRestore">
            {{ restoring ? '正在还原…' : '确认还原' }}
          </el-button>
        </template>
      </el-dialog>
    </div>

    <!-- 维护动作 -->
    <div class="card">
      <div class="card-title">
        <span class="card-title-text"><el-icon class="title-ico"><Tools /></el-icon>维护动作</span>
        <span class="ct-hint">标「会阻塞」的动作需要独占锁，请在低峰期执行</span>
      </div>
      <div class="ops">
        <div v-for="o in ops" :key="o.key" class="op-item" :class="{ blocking: o.blocking }">
          <div class="op-main">
            <div class="op-label">
              {{ o.label }}
              <el-tag v-if="o.blocking" type="danger" size="small" effect="light">会阻塞</el-tag>
            </div>
            <div class="op-desc">{{ o.desc }}</div>
          </div>
          <el-button size="small" :type="o.blocking ? 'danger' : 'default'"
                     :plain="o.blocking" :loading="running === o.key"
                     @click="runOp(o)">执行</el-button>
        </div>
      </div>
      <div v-if="lastOp" class="op-result" :class="{ bad: !lastOp.ok }">
        <b>{{ lastOp.label }}</b>：{{ lastOp.result }}
        <span class="op-ms">（{{ lastOp.elapsed_ms }} ms）</span>
      </div>
    </div>

    <!-- 增长趋势 -->
    <div class="card">
      <div class="card-title">
        <span class="card-title-text"><el-icon class="title-ico"><TrendCharts /></el-icon>近 30 天上传增长</span>
        <span class="ct-hint">用来推算照这个速度多久会碰到容量红线</span>
      </div>
      <EChart v-if="(rep.growth || []).length" :option="growthOption" height="220px" />
      <div v-else class="chart-empty">还没有数据积累</div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import PageTitle from '../../components/PageTitle.vue'
import EChart from '../../components/EChart.vue'
// 注意必须是具名导入 { Api }：本模块的 default 是 axios 实例本身，
// 写成 `import Api from '../../api'` 拿到的是 axios，`Api.storageReport` 是
// undefined，调用即抛 TypeError —— 再被下面的 catch 一吞，页面就只剩一堆 0。
import { Api } from '../../api'
import { chartTheme, axisStyle, tooltipStyle } from '../../utils/theme'

const loading = ref(false)
const indexLoading = ref(false)
const repairing = ref(false)
const backing = ref(false)
const migrating = ref(false)
const verifying = ref(false)
const running = ref('')
const lastOp = ref(null)

const rep = ref({})
const idx = ref({})
const ops = ref([])
const backups = ref([])
const backupsDir = ref('')
// 接口失败必须显式呈现。全都 catch 成空对象的话，浏览器上看到的是「体积 0 B、
// 没有备份、没有结论」—— 看起来像一台刚装好的空库，而不是一次失败。
const loadError = ref('')

const LEVEL_TEXT = { ok: '舒适', warn: '留意', danger: '超线' }
const EXTRACT_LABEL = {
  ok: '抽取成功', pending: '待抽取', failed: '抽取失败', skipped: '已跳过',
}

function levelClass(l) {
  return l === 'danger' ? 'danger' : l === 'warn' ? 'warning' : 'success'
}
const worst = computed(() => {
  const list = rep.value.capacity || []
  if (!list.length) return { level: 'ok', pct: 0, label: '—' }
  return list.reduce((a, b) => (b.pct > a.pct ? b : a))
})
const freeLevel = computed(() => {
  const kb = rep.value.files?.free_kb || 0
  return kb > 4096 * 1024 ? 'danger' : kb > 512 * 1024 ? 'warning' : 'success'
})

// ---- 文件原文存储 ----
const fs = computed(() => rep.value.file_store || {})
// 「文件原文总量」要把外置目录与仍在库里的 BLOB 加起来：
// 迁移/回退过程中两者会同时存在，只看任一边都会少算
const fsTotal = computed(() =>
  Number(fs.value.bytes || 0) + Number(rep.value.documents?.blob_bytes || 0))
const diskLevel = computed(() => {
  const p = Number(fs.value.disk?.pct_used || 0)
  return p >= 95 ? 'danger' : p >= 85 ? 'warn' : 'ok'
})

// ---- 格式化 ----
function fmtBytes(b) {
  const n = Number(b || 0)
  if (n < 1024) return `${n} B`
  const u = ['KB', 'MB', 'GB', 'TB']
  let v = n / 1024
  let i = 0
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(v >= 100 ? 0 : 1)} ${u[i]}`
}
const fmtKb = (kb) => fmtBytes(Number(kb || 0) * 1024)
function fmtByUnit(v, unit) {
  if (['库文件', '文件原文', '空洞', '可用'].includes(unit)) return fmtBytes(v)
  if (v >= 10000) return `${(v / 10000).toFixed(1)} 万`
  return String(v)
}

// ---- 图表 ----
// 必须在 computed 里读一下 isDark，否则主题切换时图表不会重画
const pieOption = computed(() => {
  const t = chartTheme()
  const palette = t.colors
  return {
    tooltip: { trigger: 'item', ...tooltipStyle(), formatter: p => `${p.name}<br/>${fmtBytes(p.value)}（${p.percent}%）` },
    legend: {
      type: 'scroll', orient: 'vertical', right: 0, top: 'middle',
      itemWidth: 10, itemHeight: 10,
      textStyle: { color: t.text, fontSize: 11 },
      formatter: name => (name.length > 16 ? `${name.slice(0, 15)}…` : name),
    },
    series: [{
      type: 'pie',
      radius: ['42%', '68%'],
      center: ['34%', '50%'],
      avoidLabelOverlap: true,
      itemStyle: { borderColor: t.card, borderWidth: 2 },
      label: { show: false },
      emphasis: { label: { show: true, fontSize: 12, color: t.text, formatter: '{d}%' } },
      data: (rep.value.tables || []).slice(0, 8).map((x, i) => ({
        name: x.name, value: x.bytes,
        itemStyle: { color: palette[i % palette.length] },
      })),
    }],
  }
})

const growthOption = computed(() => {
  const t = chartTheme()
  const axis = axisStyle()
  const g = [...(rep.value.growth || [])].reverse()
  return {
    grid: { left: 4, right: 12, top: 20, bottom: 2, containLabel: true },
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' }, ...tooltipStyle(),
      formatter: p => {
        const d = p[0]
        const row = g[d.dataIndex] || {}
        return `${d.name}<br/>${d.value} 个文件 · ${fmtBytes(row.bytes)}`
      },
    },
    xAxis: { type: 'category', data: g.map(x => x.date.slice(5)), ...axis, splitLine: { show: false } },
    yAxis: { type: 'value', minInterval: 1, ...axis },
    series: [{
      name: '上传文件数', type: 'bar', barMaxWidth: 22,
      data: g.map(x => x.docs),
      itemStyle: { color: t.primary, borderRadius: [4, 4, 0, 0] },
    }],
  }
})

// ---- 数据 ----
function errText(e) {
  return e?.response?.data?.detail || e?.message || String(e)
}

async function loadReport() {
  loading.value = true
  try {
    rep.value = await Api.storageReport()
    loadError.value = ''
  } catch (e) {
    loadError.value = `存储诊断加载失败：${errText(e)}`
  } finally {
    loading.value = false
  }
}

async function loadIndex() {
  indexLoading.value = true
  try { idx.value = await Api.storageIndex() }
  catch (e) { loadError.value = `索引体检失败：${errText(e)}` }
  finally { indexLoading.value = false }
}

async function loadBackups() {
  try {
    const r = await Api.storageBackups()
    backups.value = r.items || []
    backupsDir.value = r.dir || ''
  } catch (e) { loadError.value = `备份列表加载失败：${errText(e)}` }
}

async function loadOps() {
  try { ops.value = (await Api.storageOps()).items || [] }
  catch (e) { loadError.value = `维护动作清单加载失败：${errText(e)}` }
}

function reload() {
  loadReport(); loadIndex(); loadBackups()
}

async function doBackup() {
  backing.value = true
  try {
    const r = await Api.storageBackup()
    ElMessage.success(`备份完成：${r.name}（${fmtBytes(r.bytes)}）`)
    loadBackups(); loadReport()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '备份失败')
  } finally { backing.value = false }
}

// ---- 在线还原 ----
const restoreDlg = ref(false)
const restoreTarget = ref(null)
const restoreConfirm = ref('')
const restoring = ref(false)

function openRestore(row) {
  restoreTarget.value = row
  restoreConfirm.value = ''
  restoreDlg.value = true
}

async function doRestore() {
  restoring.value = true
  try {
    const r = await Api.storageRestore(restoreTarget.value.name)
    // 成功后旧库（连同里面的会话）已被替换：提示完直接送回登录页，
    // 别再刷任何业务接口 —— 那会触发 401 的红条提示，掩盖这个更重要的结果
    restoring.value = false
    restoreDlg.value = false
    await ElMessageBox.alert(
      `已还原到 <b class="mono">${r.name}</b>（文档 ${r.restored?.document ?? '—'} 条）。` +
      `退路快照：<span class="mono">${r.safety_snapshot}</span>。<br>` +
      `若当前登录已失效，请用<b>备份时刻</b>的账号口令重新登录。`,
      '还原完成',
      { confirmButtonText: '知道了', type: 'success', dangerouslyUseHTMLString: true },
    )
    // 快照里若含当前会话则仍是登录态；若失效，下一次请求会自动跳登录页
    window.location.reload()
  } catch (e) {
    // 400 = 动手前被拦下 / 自检不过已自动回滚 —— 线上数据未动
    ElMessage.error(e?.response?.data?.detail || '还原失败')
    loadBackups()
  } finally {
    restoring.value = false
  }
}

async function doRepair() {
  repairing.value = true
  try {
    const r = await Api.storageRepairIndex()
    ElMessage.success(`修复完成：同步标记 ${r.vec_marked_synced} 项、重建全文索引 ${r.fts_rebuilt} 项`)
    loadIndex()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '修复失败')
  } finally { repairing.value = false }
}

async function runOp(op) {
  // 外迁是分批动作，直接走循环版本，否则点一次只搬 50 个，
  // 而按钮看起来「点过了」，用户会以为已经迁完
  if (op.key === 'externalize_blobs') return doExternalize()

  if (op.blocking) {
    // 独占锁的动作必须先说清楚代价再执行：在业务高峰点下去，
    // 表现就是全站请求卡住直到它跑完
    try {
      await ElMessageBox.confirm(
        `${op.label} 需要独占数据库锁，期间所有读写请求都会排队等待。` +
        '库文件越大耗时越长，请在低峰期执行。',
        '确认执行？',
        { type: 'warning', confirmButtonText: '仍要执行', cancelButtonText: '取消' },
      )
    } catch { return }
  }
  running.value = op.key
  lastOp.value = null
  try {
    lastOp.value = { ...(await Api.storageRunOp(op.key)), ok: true }
    ElMessage.success(`${op.label} 完成`)
    loadReport(); loadAll()
  } catch (e) {
    const d = e?.response?.data?.detail || '执行失败'
    lastOp.value = { label: op.label, result: d, ok: false, elapsed_ms: 0 }
    loadReport()
  } finally { running.value = '' }
}

function loadAll() { loadIndex(); loadBackups() }

/**
 * 外迁库内原文。
 *
 * 循环调用而不是一次搬完：后端每次只处理一批并提交，单个请求的耗时就有上界，
 * 不会长到被网关/代理掐断（超时中止会让用户以为「点了没反应」）。
 * 这里按批推进并实时回报进度，用户能看到它在动。
 */
async function doExternalize() {
  const total = fs.value.pending_count || 0
  try {
    await ElMessageBox.confirm(
      `将把 ${total} 个文件的原文（约 ${fmtBytes(fs.value.pending_bytes)}）从数据库搬到文件目录。` +
      '过程分批进行、不影响使用；迁完后建议再执行「整体重整」才能真正缩小库文件。',
      '确认外迁？',
      { type: 'info', confirmButtonText: '开始外迁', cancelButtonText: '取消' },
    )
  } catch { return }

  migrating.value = true
  let moved = 0
  let movedBytes = 0
  try {
    for (let i = 0; i < 200; i++) {
      const r = await Api.storageRunOp('externalize_blobs', { batch: 50 })
      moved += r.moved || 0
      movedBytes += r.moved_bytes || 0
      if (!r.remaining) break
      if (!r.moved) break          // 没有可迁的记录（都是空原文），防止死循环
    }
    ElMessage.success(
      `外迁完成：${moved} 个文件 / ${fmtBytes(movedBytes)}。` +
      '如需真正缩小库文件，请再执行「整体重整（VACUUM）」。',
    )
    loadReport()
  } catch (e) {
    ElMessage.error(`外迁中断：${errText(e)}（已迁移 ${moved} 个，可再次点击继续）`)
    loadReport()
  } finally { migrating.value = false }
}

async function doVerify() {
  verifying.value = true
  lastOp.value = null
  try {
    const r = await Api.storageRunOp('verify_files')
    lastOp.value = { ...r, ok: true }
    if (r.missing_count) {
      ElMessage.warning(`发现 ${r.missing_count} 个文件缺原文，请从备份恢复 files 目录`)
    } else {
      ElMessage.success(r.result)
    }
    if ((r.orphans || []).length) loadReport()
  } catch (e) {
    const d = errText(e)
    lastOp.value = { label: '原文完整性普查', result: d, ok: false, elapsed_ms: 0 }
    ElMessage.error(d)
  } finally { verifying.value = false }
}

onMounted(() => {
  loadReport(); loadIndex(); loadBackups(); loadOps()
})
</script>

<style scoped>
.load-err { margin-bottom: 14px; }
.sub-warn {
  display: block; margin-top: 2px; font-size: 11px;
  color: var(--warning);
}

/* ---- 容量余量 ---- */
.cap-list { display: flex; flex-direction: column; gap: 10px; }
.cap-row {
  display: grid;
  grid-template-columns: 150px 1fr 108px 56px;
  align-items: center;
  gap: 12px;
  font-size: 13px;
}
.cap-name { color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cap-bar {
  height: 8px;
  border-radius: 4px;
  background: var(--bg-subtle);
  overflow: hidden;
}
.cap-bar i { display: block; height: 100%; border-radius: 4px; transition: width .3s ease; }
.cap-bar i.ok { background: var(--success); }
.cap-bar i.warn { background: var(--warning); }
.cap-bar i.danger { background: var(--danger); }
.cap-val { text-align: right; font-variant-numeric: tabular-nums; color: var(--text-primary); }
.cap-flag { text-align: center; font-size: 12px; border-radius: 4px; padding: 1px 0; }
.cap-flag.ok { color: var(--success); background: var(--success-bg); }
.cap-flag.warn { color: var(--warning); background: var(--warning-bg); }
.cap-flag.danger { color: var(--danger); background: var(--danger-bg); }
.cap-note {
  margin-top: 14px; padding-top: 12px;
  border-top: 1px dashed var(--border);
  font-size: 12px; color: var(--text-tertiary); line-height: 1.7;
}

/* ---- 双栏 ---- */
.dual { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 1100px) { .dual { grid-template-columns: 1fr; } }

.tbl-wrap { max-height: 240px; overflow: auto; }
.mini-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.mini-table th {
  text-align: left; font-weight: 500; color: var(--text-tertiary);
  padding: 6px 8px; position: sticky; top: 0;
  background: var(--bg-card); border-bottom: 1px solid var(--border);
}
.mini-table td { padding: 6px 8px; border-bottom: 1px solid var(--border-light); }
.mini-table .num { text-align: right; font-variant-numeric: tabular-nums; }
.mini-table .empty { text-align: center; color: var(--text-tertiary); padding: 18px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }

/* ---- 结论 ---- */
.tips { display: flex; flex-direction: column; gap: 9px; }
.tip-row {
  display: flex; gap: 9px; align-items: flex-start;
  font-size: 13px; line-height: 1.65;
  padding: 9px 12px; border-radius: 8px;
}
.tip-row .tip-ico { margin-top: 3px; flex: none; }
.tip-row.ok { background: var(--success-bg); color: var(--success); }
.tip-row.warn { background: var(--warning-bg); color: var(--warning); }
.tip-row.danger { background: var(--danger-bg); color: var(--danger); }
.tip-row.info { background: var(--info-bg); color: var(--info); }

/* ---- 索引 ---- */
.idx-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
@media (max-width: 900px) { .idx-grid { grid-template-columns: 1fr; } }
.idx-box { background: var(--bg-subtle); border-radius: 10px; padding: 12px 14px; }
.ix-title { font-size: 13px; font-weight: 600; color: var(--text-primary); margin-bottom: 10px; }
.ix-rows { display: flex; flex-direction: column; gap: 6px; }
.ix-row {
  display: flex; justify-content: space-between;
  font-size: 12.5px; color: var(--text-secondary);
}
.ix-row b { font-variant-numeric: tabular-nums; color: var(--text-primary); }
.ix-row.bad b { color: var(--danger); }

.problems { margin-top: 14px; display: flex; flex-direction: column; gap: 8px; }
.pb-row {
  display: flex; gap: 8px; align-items: flex-start; font-size: 12.5px;
  padding: 8px 12px; border-radius: 8px;
  background: var(--warning-bg); color: var(--warning);
}
.problems.none .pb-row, .problems.none {
  display: flex; gap: 8px; align-items: center; flex-direction: row;
  padding: 9px 12px; border-radius: 8px;
  background: var(--success-bg); color: var(--success); font-size: 12.5px;
}
.ct-hint { font-size: 12px; color: var(--text-tertiary); font-weight: 400; }
.ct-actions { display: flex; gap: 8px; align-items: center; }

/* ---- 文件原文存储 ---- */
.fs-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}
@media (max-width: 900px) { .fs-grid { grid-template-columns: 1fr; } }
.fs-box { background: var(--bg-subtle); border-radius: 10px; padding: 12px 14px; }
.fs-kv {
  display: flex; justify-content: space-between; align-items: center; gap: 10px;
  font-size: 12.5px; color: var(--text-secondary); padding: 3px 0;
}
.fs-kv b {
  font-variant-numeric: tabular-nums; color: var(--text-primary);
  font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.fs-kv b.bad { color: var(--danger); }
.fs-kv b.warn2 { color: var(--warning); }
.fs-bar {
  height: 6px; border-radius: 3px; background: var(--bg-card);
  overflow: hidden; margin: 8px 0 4px;
}
.fs-bar i { display: block; height: 100%; border-radius: 3px; }
.fs-bar i.ok { background: var(--success); }
.fs-bar i.warn { background: var(--warning); }
.fs-bar i.danger { background: var(--danger); }
.fs-note {
  display: flex; gap: 8px; align-items: flex-start;
  margin-top: 14px; padding: 10px 13px; border-radius: 8px;
  font-size: 12.5px; line-height: 1.7;
}
.fs-note code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px; padding: 1px 5px; border-radius: 4px;
  background: var(--bg-card);
}
.fs-note.ok { background: var(--success-bg); color: var(--success); }
.fs-note.warn { background: var(--warning-bg); color: var(--warning); }
.fs-note .el-icon { margin-top: 3px; flex: none; }

/* ---- 备份 ---- */
.bk-note { font-size: 12.5px; color: var(--text-secondary); line-height: 1.8; margin-bottom: 12px; }
.bk-note p { margin: 0 0 6px; }
.bk-note code, .bk-cli code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px; padding: 1px 5px; border-radius: 4px;
  background: var(--bg-subtle); color: var(--text-primary);
}
.warn-line {
  display: flex; gap: 6px; align-items: flex-start;
  color: var(--warning); background: var(--warning-bg);
  padding: 8px 11px; border-radius: 8px; margin-top: 4px !important;
}
.bk-cli {
  display: flex; flex-direction: column; gap: 6px;
  padding: 12px 14px; border-radius: 10px;
  background: var(--bg-subtle); margin-bottom: 14px;
}
.bk-cli-row { display: flex; gap: 12px; align-items: baseline; font-size: 12.5px; }
.bk-cli-row code { background: var(--bg-card); flex: none; }
.bk-cli-row span { color: var(--text-tertiary); }

/* ---- 还原确认对话框 ---- */
.rs-summary { border: 1px solid var(--border-light); border-radius: 8px;
  padding: 10px 14px; margin-bottom: 12px; font-size: 13px; }
.rs-row { display: flex; gap: 12px; padding: 3px 0; align-items: baseline; }
.rs-label { flex: none; width: 64px; color: var(--text-tertiary); font-size: 12px; }
.rs-alert p { margin: 0 0 6px; font-size: 12.5px; line-height: 1.7; }
.rs-alert p:last-child { margin-bottom: 0; }
.rs-confirm { display: flex; flex-direction: column; gap: 8px;
  margin-top: 14px; font-size: 13px; }
.rs-confirm .el-input { margin-top: 2px; }

/* ---- 维护动作 ---- */
.ops { display: flex; flex-direction: column; gap: 10px; }
.op-item {
  display: flex; justify-content: space-between; align-items: center; gap: 14px;
  padding: 11px 14px; border-radius: 10px;
  background: var(--bg-subtle);
}
.op-item.blocking { background: var(--danger-bg); }
.op-label { font-size: 13px; font-weight: 600; color: var(--text-primary); display: flex; gap: 7px; align-items: center; }
.op-desc { font-size: 12px; color: var(--text-tertiary); margin-top: 3px; line-height: 1.5; }
.op-result {
  margin-top: 12px; padding: 10px 13px; border-radius: 8px;
  font-size: 12.5px; background: var(--success-bg); color: var(--success);
}
.op-result.bad { background: var(--danger-bg); color: var(--danger); }
.op-ms { opacity: .75; }
</style>
