<template>
  <el-drawer
    v-model="visible"
    title="AI 助理 · 对话即操作"
    size="560px"
    direction="rtl"
    :append-to-body="true"
    class="agent-drawer"
    @open="onOpen"
  >
    <div class="agent-wrap">
      <el-alert v-if="configLoaded && !configEnabled" type="warning" :closable="false" class="cfg-alert"
        title="AI 未启用，对话式查询需要先配置 AI 服务">
        <el-link type="primary" @click="$router.push('/ai-settings')">前往 AI 设置</el-link>
      </el-alert>

      <div ref="listEl" class="agent-list">
        <div v-if="!messages.length" class="agent-empty">
          <div class="empty-icon">🤖</div>
          <p>问我任何关于系统数据的问题，我会调用工具查真实数据再回答。<br>
             也可以让我替你记账、改记录——动手前会先把改动列给你确认。</p>
          <div class="chips">
            <el-tag v-for="c in suggestions" :key="c" class="chip" effect="plain"
              @click="input = c; send()">{{ c }}</el-tag>
          </div>
        </div>

        <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
          <div class="bubble">
            <!-- 工具调用轨迹：AI 为这个回答实际做了什么 -->
            <div v-if="m.tools?.length" class="tools">
              <div v-for="(t, j) in m.tools" :key="j" class="tool-card" :class="{ 'is-write': t.write }">
                <div class="tool-head" @click="t._open = !t._open">
                  <span class="tool-icon">{{ t.write ? '✍️' : '🔧' }}</span>
                  <b>{{ toolLabel(t.name) }}</b>
                  <span class="tool-args">{{ briefArgs(t.name, t.args) }}</span>
                  <el-tag v-if="t.pending" size="small" type="warning" effect="plain">待确认</el-tag>
                  <el-tag v-else-if="t.confirmed" size="small" type="success" effect="plain">已执行</el-tag>
                  <el-icon class="tool-caret" :class="{ open: t._open }"><ArrowDown /></el-icon>
                </div>
                <div v-if="t._open" class="tool-body-wrap">
                  <pre class="tool-body" :class="{ 'is-full': t._full }">{{ t._full ? toolResultText(t.result) : t._preview.text }}</pre>
                  <!-- 结果太长时必须明说，不能静默 slice：
                       用户看到半截 JSON 还以为这就是全部 -->
                  <div v-if="toolTruncationNote(t, t._preview)" class="tool-truncated">
                    <el-icon><WarningFilled /></el-icon>
                    <span>{{ toolTruncationNote(t, t._preview) }}</span>
                    <el-link v-if="t._preview.truncated" type="primary" :underline="false"
                      @click="t._full = !t._full">{{ t._full ? '收起' : '查看完整' }}</el-link>
                    <el-link type="primary" :underline="false" @click="downloadTool(t)">下载 JSON</el-link>
                  </div>
                </div>
              </div>
            </div>

            <!-- 待确认的写操作：AI 只提议，用户点确认才落库 -->
            <div v-if="m.pending" class="pending" :class="[`risk-${m.pending.risk}`, `st-${m.state}`]">
              <div class="pending-head">
                <span class="risk-badge">{{ riskLabel(m.pending.risk) }}</span>
                <b>{{ m.pending.title }}</b>
                <span class="pending-model">{{ m.pending.model.name }}</span>
              </div>

              <div v-if="m.pending.record_label && m.pending.risk !== 'create'" class="pending-target">
                目标记录：<b>{{ m.pending.record_label }}</b>
                <span class="rid">#{{ m.pending.record_id }}</span>
              </div>

              <table v-if="m.pending.fields?.length" class="pending-fields">
                <tr v-for="f in m.pending.fields.filter(x => x.changed || x.value || x.old)" :key="f.key">
                  <td class="fname">{{ f.name }}</td>
                  <td class="fval">
                    <template v-if="f.old !== undefined && f.old !== null && f.old !== ''">
                      <span class="old">{{ f.old }}</span>
                      <span class="arrow">→</span>
                    </template>
                    <span class="new">{{ f.value || '（留空）' }}</span>
                  </td>
                </tr>
              </table>
              <div v-else-if="m.pending.risk === 'delete'" class="pending-del">
                这条记录将被移入回收站（可在「回收站」页恢复）
              </div>

              <ul v-if="m.pending.warnings?.length" class="pending-warn">
                <li v-for="(w, k) in m.pending.warnings" :key="k">{{ w }}</li>
              </ul>

              <div class="pending-actions">
                <template v-if="m.state === 'idle'">
                  <el-button size="small" @click="cancelPending(m)">取消</el-button>
                  <el-button size="small" :type="m.pending.risk === 'delete' ? 'danger' : 'primary'"
                    @click="confirmPending(m)">
                    <el-icon><Check /></el-icon>确认执行
                  </el-button>
                </template>
                <template v-else-if="m.state === 'running'">
                  <span class="st-text"><el-icon class="is-loading"><Loading /></el-icon> 正在执行…</span>
                </template>
                <template v-else-if="m.state === 'done'">
                  <span class="st-text ok"><el-icon><CircleCheck /></el-icon> 已执行</span>
                  <el-link v-if="m.pending.model?.id" type="primary" :underline="false"
                    @click="goRecords(m.pending.model.id)">
                    去记录页看看
                  </el-link>
                </template>
                <template v-else-if="m.state === 'failed'">
                  <span class="st-text bad"><el-icon><WarningFilled /></el-icon> 未执行成功</span>
                </template>
                <template v-else>
                  <span class="st-text muted">已取消，未做任何改动</span>
                </template>
              </div>
            </div>

            <!-- AI 回答按 Markdown 排版（表格/列表/代码块）；用户发言保持纯文本原样 -->
            <MarkdownText v-if="m.role === 'assistant'" class="msg-text" :content="m.content" />
            <div v-else class="msg-text">{{ m.content }}</div>

            <!-- 回答被长度上限切断时必须明说，并给一键续写入口：
                 用户只看到半截内容、却不知道发生了什么，是最糟的体验 -->
            <div v-if="m.truncated" class="msg-truncated">
              <el-icon><WarningFilled /></el-icon>
              <span class="trunc-text">{{ noticeOf(m).text }}</span>
              <el-button size="small" type="primary" plain :loading="m._continuing"
                @click="continueAnswer(m, i)">{{ noticeOf(m).action }}</el-button>
            </div>
            <div v-if="m.truncated" class="trunc-hint">{{ noticeOf(m).hint }}</div>
          </div>
        </div>

        <div v-if="thinking" class="msg assistant">
          <div class="bubble">
            <div class="thinking">
              <el-icon class="is-loading"><Loading /></el-icon>
              <span>{{ thinkingText }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="agent-input">
        <el-input
          v-model="input"
          type="textarea"
          :rows="2"
          resize="none"
          placeholder="例如：帮我在费用管理里记一笔，今天差旅 380 元"
          @keydown.enter.exact.prevent="send"
        />
        <el-button type="primary" :loading="thinking" :disabled="!input.trim()" @click="send">
          <el-icon><Promotion /></el-icon>发送
        </el-button>
      </div>
      <div class="agent-foot">
        查询直接执行；增删改会先列出改动清单，你点确认才落库
      </div>
    </div>
  </el-drawer>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Api } from '../api'
import MarkdownText from './MarkdownText.vue'
import {
  toolResultText,
  toolResultPreview,
  toolTruncationNote,
  toolDownloadFilename,
  buildContinueRequest,
  mergeContinuation,
  truncationNotice,
} from '../utils/chatTruncation'

const props = defineProps({ modelValue: Boolean })
const emit = defineEmits(['update:modelValue'])
const router = useRouter()

const visible = computed({
  get: () => props.modelValue,
  set: v => emit('update:modelValue', v),
})

// {role, content, tools?, pending?, state?, q?, hist?}
const messages = ref([])
const input = ref('')
const thinking = ref(false)
const thinkingText = ref('正在查询系统数据…')
const listEl = ref(null)
const configLoaded = ref(false)
const configEnabled = ref(false)

const suggestions = [
  '系统里现在有哪些数据模型？',
  '报销记录总共有多少条？',
  '帮我在费用管理里记一笔：今天差旅 380 元',
  '这个月费用一共花了多少钱？',
]

const TOOL_LABELS = {
  list_models: '列出数据模型',
  get_model_schema: '查看模型字段',
  search_records: '搜索业务记录',
  stats_records: '统计记录',
  search_documents: '检索文件',
  create_record: '新建记录',
  update_record: '修改记录',
  delete_record: '删除记录',
}

const RISK_LABELS = { create: '新建', update: '修改', delete: '删除' }

function toolLabel(name) { return TOOL_LABELS[name] || name }
function riskLabel(risk) { return RISK_LABELS[risk] || risk }

function briefArgs(name, args = {}) {
  if (name === 'stats_records') {
    const p = [args.model_key, args.operation]
    if (args.field_key) p.push(args.field_key)
    if (args.group_by) p.push(`按 ${args.group_by} 分组`)
    return p.filter(Boolean).join(' · ')
  }
  if (name === 'search_records' || name === 'search_documents') return args.keyword || ''
  if (name === 'get_model_schema') return args.model_key || ''
  if (name === 'create_record') return args.model_key || ''
  if (name === 'update_record' || name === 'delete_record') {
    return [args.model_key, args.record_id ? `#${args.record_id}` : ''].filter(Boolean).join(' · ')
  }
  return ''
}

/** 工具结果的预览与截断标记（在消息进列表时就算好，模板里直接用） */
function toolPreviewOf(t) {
  if (!t._preview) t._preview = toolResultPreview(t.result)
  return t._preview
}

/** 消息底部的截断提示 */
function noticeOf(m) {
  return truncationNotice(m.truncated, m.finish_reason) || { text: '', action: '', hint: '' }
}

/**
 * 下载工具完整结果
 *
 * 以前长结果只显示前 1500 字符，连「被截断了」都不说，
 * 用户既拿不到完整数据，也没法判断结果可不可信。
 */
function downloadTool(t) {
  const blob = new Blob([toolResultText(t.result)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = toolDownloadFilename(t.name)
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function goRecords(typeId) {
  visible.value = false
  router.push(`/records/${typeId}`)
}

async function onOpen() {
  if (!configLoaded.value) {
    try {
      const c = await Api.getAIConfig()
      configEnabled.value = !!c.enabled
    } catch { /* 忽略，发送时后端会给提示 */ }
    configLoaded.value = true
  }
}

async function scrollBottom() {
  await nextTick()
  const el = listEl.value
  if (el) el.scrollTop = el.scrollHeight
}

/** 带上最近几轮纯文本对话，支持追问；工具轨迹不进 history（占 token 且模型不需要） */
function historyOf(upto) {
  const list = upto === undefined ? messages.value : messages.value.slice(0, upto)
  return list
    .filter(m => (m.role === 'user' || m.role === 'assistant') && m.content)
    .slice(-8)
    .map(m => ({ role: m.role, content: m.content }))
}

function pushAssistant(r, q, hist) {
  const msg = {
    role: 'assistant',
    content: r.answer || '（无回答）',
    // 工具结果：预先算好预览与截断标记，模板里直接用
    tools: (r.tool_calls || []).map(t => ({
      ...t,
      _open: false,
      _full: false,
      _preview: toolResultPreview(t.result),
    })),
    // 截断信息：后端明确告诉我们「这段被长度上限切断了」，
    // 界面上要显示出来，还要给一键续写的入口
    truncated: !!r.truncated,
    finish_reason: r.finish_reason || null,
    q,
    hist,
    _continuing: false,
  }
  if (r.status === 'awaiting_confirmation' && r.pending) {
    msg.pending = r.pending
    msg.state = 'idle'
  }
  messages.value.push(msg)
}

async function send() {
  const q = input.value.trim()
  if (!q || thinking.value) return
  input.value = ''
  const hist = historyOf()
  messages.value.push({ role: 'user', content: q })
  thinking.value = true
  thinkingText.value = '正在查询系统数据…'
  scrollBottom()

  try {
    const r = await Api.aiAgent(q, hist)
    pushAssistant(r, q, hist)
  } catch (e) {
    const detail = e?.response?.data?.detail || e?.message || '调用失败'
    messages.value.push({ role: 'assistant', content: `出错了：${detail}` })
    ElMessage.error('AI 助理调用失败')
  } finally {
    thinking.value = false
    scrollBottom()
  }
}

/**
 * 一键续写：让 AI 从断点接着写
 *
 * 关键是把「已经写出来的内容」回灌进去（buildContinueRequest），
 * 并且历史里不再放这一段 —— 否则模型会从头再答一遍，
 * 用户看到的就是「刚才那段又来一次」。
 */
async function continueAnswer(m, i) {
  if (!m || m._continuing) return
  m._continuing = true
  try {
    const req = buildContinueRequest({
      question: m.q,
      // 历史到「本次提问之前」为止：正在续写的那条消息不进历史
      history: historyOf(i - 1),
      content: m.content,
    })
    const r = await Api.aiAgent(req.question, req.history, { continuation: req.continuation })
    m.content = mergeContinuation(m.content, r.answer)
    m.truncated = !!r.truncated
    m.finish_reason = r.finish_reason || null
    if (r.truncated) {
      ElMessage.warning('回答仍被长度上限截断，可再点一次「继续写完」')
    } else {
      ElMessage.success('已续写完成')
    }
  } catch (e) {
    const detail = e?.response?.data?.detail || e?.message || '调用失败'
    ElMessage.error('续写失败：' + detail)
  } finally {
    m._continuing = false
    scrollBottom()
  }
}

/** 确认执行：后端会重新校验参数，不信任前端回传 */
async function confirmPending(m) {
  if (m.state !== 'idle') return          // 防双击：状态一变就不再受理
  m.state = 'running'
  thinking.value = true
  thinkingText.value = '正在执行操作…'
  scrollBottom()
  try {
    const r = await Api.aiAgentConfirm({ question: m.q, history: m.hist, pending: m.pending })
    const first = (r.tool_calls || [])[0]
    const ok = first?.result?.ok !== false
    m.state = ok ? 'done' : 'failed'
    if (ok) ElMessage.success('操作已执行')
    pushAssistant(r, m.q, m.hist)
  } catch (e) {
    m.state = 'failed'
    const detail = e?.response?.data?.detail || e?.message || '执行失败'
    messages.value.push({ role: 'assistant', content: `执行出错：${detail}` })
    ElMessage.error('操作执行失败')
  } finally {
    thinking.value = false
    scrollBottom()
  }
}

function cancelPending(m) {
  if (m.state !== 'idle') return
  m.state = 'cancelled'
  // 让模型也知道被拒了，下一轮不会当成「还没做」
  messages.value.push({ role: 'assistant', content: '好的，已取消，本次没有改动任何数据。' })
  scrollBottom()
}
</script>

<style scoped>
.agent-wrap {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 10px;
}
.cfg-alert { margin-bottom: 4px; }
.agent-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-right: 4px;
}
.agent-empty {
  text-align: center;
  color: var(--el-text-color-secondary);
  padding: 40px 10px;
  font-size: 13.5px;
  line-height: 1.7;
}
.empty-icon { font-size: 40px; margin-bottom: 8px; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-top: 14px; }
.chip { cursor: pointer; }

.msg { display: flex; }
.msg.user { justify-content: flex-end; }
.msg .bubble {
  max-width: 88%;
  /* flex 子项默认 min-width:auto：回答里带宽表格时，
     气泡会被撑得比抽屉还宽，右侧内容直接被裁掉看不见。
     加上 min-width:0 让长内容在气泡内部换行/横向滚动。 */
  min-width: 0;
  border-radius: 12px;
  padding: 10px 13px;
  font-size: 13.5px;
  line-height: 1.65;
}
.msg.user .bubble {
  background: var(--el-color-primary);
  color: #fff;
}
.msg.assistant .bubble {
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
  max-width: 94%;              /* 回答里常带表格，给它多一点横向空间 */
}
.msg-text { word-break: break-word; }
/* 用户发言是纯文本：保留手敲的换行。AI 回答走 Markdown，不能开 pre-wrap */
.msg.user .msg-text { white-space: pre-wrap; }

.tools { margin-bottom: 8px; display: flex; flex-direction: column; gap: 6px; }
.tool-card {
  border: 1px dashed var(--el-border-color);
  border-radius: 8px;
  background: var(--el-fill-color-blank);
  font-size: 12px;
  overflow: hidden;
}
.tool-card.is-write { border-color: var(--el-color-warning-light-5); }
.tool-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 9px;
  cursor: pointer;
}
.tool-args {
  color: var(--el-text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.tool-caret { transition: transform .2s; }
.tool-caret.open { transform: rotate(180deg); }
.tool-body {
  margin: 0;
  padding: 8px 10px;
  border-top: 1px dashed var(--el-border-color);
  background: var(--el-fill-color-darker);
  font-size: 11.5px;
  max-height: 200px;
  overflow: auto;
  white-space: pre-wrap;
  font-family: var(--font-mono, monospace);
}
/* 点「查看完整」后给更大的高度，但仍可滚动，不做静默裁剪 */
.tool-body.is-full { max-height: 420px; }

/* 工具结果被截断时的说明条 */
.tool-truncated {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 5px 10px;
  border-top: 1px dashed var(--el-border-color);
  background: var(--el-color-warning-light-9);
  color: var(--el-color-warning-dark-2);
  font-size: 11.5px;
}

/* 回答被截断时的提示条 */
.msg-truncated {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding: 6px 9px;
  border-radius: 8px;
  background: var(--el-color-warning-light-9);
  border: 1px solid var(--el-color-warning-light-7);
  color: var(--el-color-warning-dark-2);
  font-size: 12px;
}
.trunc-text { flex: 1; min-width: 0; }
.trunc-hint {
  margin-top: 4px;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}

/* ---------- 待确认操作卡片 ---------- */
.pending {
  margin-bottom: 8px;
  border: 1px solid var(--el-color-primary-light-5);
  border-left: 3px solid var(--el-color-primary);
  border-radius: 8px;
  background: var(--el-fill-color-blank);
  padding: 9px 11px;
  font-size: 12.5px;
}
.pending.risk-update { border-color: var(--el-color-warning-light-5); border-left-color: var(--el-color-warning); }
.pending.risk-delete { border-color: var(--el-color-danger-light-5); border-left-color: var(--el-color-danger); }
.pending.st-done { opacity: .82; }
.pending.st-cancelled { opacity: .6; }

.pending-head { display: flex; align-items: center; gap: 7px; margin-bottom: 7px; }
.risk-badge {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  border: 1px solid var(--el-color-primary-light-7);
}
.risk-update .risk-badge {
  background: var(--el-color-warning-light-9);
  color: var(--el-color-warning);
  border-color: var(--el-color-warning-light-7);
}
.risk-delete .risk-badge {
  background: var(--el-color-danger-light-9);
  color: var(--el-color-danger);
  border-color: var(--el-color-danger-light-7);
}
.pending-model { color: var(--el-text-color-secondary); margin-left: auto; }

.pending-target { margin-bottom: 6px; color: var(--el-text-color-regular); }
.pending-target .rid { color: var(--el-text-color-placeholder); margin-left: 4px; }

.pending-fields { width: 100%; border-collapse: collapse; margin: 4px 0 6px; }
.pending-fields td { padding: 2px 0; vertical-align: top; }
.pending-fields .fname { color: var(--el-text-color-secondary); width: 38%; }
.pending-fields .fval { color: var(--el-text-color-primary); word-break: break-all; }
.pending-fields .old { color: var(--el-text-color-placeholder); text-decoration: line-through; }
.pending-fields .arrow { margin: 0 5px; color: var(--el-text-color-placeholder); }
.pending-fields .new { font-weight: 600; }
.pending-del { color: var(--el-color-danger); margin: 4px 0 6px; }

.pending-warn {
  margin: 4px 0 6px;
  padding-left: 16px;
  color: var(--el-color-warning);
  font-size: 11.5px;
  line-height: 1.6;
}

.pending-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 4px;
}
.st-text { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; }
.st-text.ok { color: var(--el-color-success); }
.st-text.bad { color: var(--el-color-danger); }
.st-text.muted { color: var(--el-text-color-placeholder); }

.thinking {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.agent-input {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}
.agent-foot {
  font-size: 11.5px;
  color: var(--el-text-color-placeholder);
  text-align: center;
}
</style>
