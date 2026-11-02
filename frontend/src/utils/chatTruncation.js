/**
 * AI 回答「被截断」的纯逻辑
 *
 * 背景：模型有长度上限，回答写到一半被切断时，
 * 用户看到的就是半截内容，而且没有任何提示 ——
 * 界面根本不知道这件事，用户只能自己猜是不是系统坏了。
 *
 * 这里把三件事抽成纯函数（好测、好复用）：
 *   1. 工具结果的「预览 + 截断标记」—— 不能静默 slice；
 *   2. 「继续写」的请求体与提示词 —— 续写要带上已有内容，避免重复；
 *   3. 消息底部的截断提示文案。
 */

/** 工具结果在界面上默认只展示这么多字符 */
export const TOOL_PREVIEW_CHARS = 1500

/** 一次续写最多把多少已有内容回灌给模型 */
export const CONTINUATION_TAIL_CHARS = 2000

/** 工具结果转成可读文本 */
export function toolResultText(result) {
  if (result == null) return ''
  try {
    return JSON.stringify(result, null, 2)
  } catch {
    return String(result)
  }
}

/**
 * 工具结果预览：明确告诉用户「这里被截断了」，而不是静默砍掉
 *
 * 返回 {text, truncated, total}
 */
export function toolResultPreview(result, limit = TOOL_PREVIEW_CHARS) {
  const full = toolResultText(result)
  const total = full.length
  if (total <= limit) return { text: full, truncated: false, total }
  return { text: full.slice(0, limit), truncated: true, total }
}

/**
 * 工具结果的截断说明
 *
 * 两个来源要分开说：
 *   · 服务端截断（result_truncated）—— 完整结果超过后端上限；
 *   · 界面预览截断（preview.truncated）—— 只显示前 N 字符。
 */
export function toolTruncationNote(tool, preview) {
  const parts = []
  if (tool && tool.result_truncated) {
    const chars = tool.result_chars != null ? tool.result_chars : '未知'
    parts.push(`完整结果 ${chars} 字符，超过后端上限已截断`)
  }
  if (preview && preview.truncated) {
    parts.push(`界面只显示前 ${preview.total} 字符中的前 ${TOOL_PREVIEW_CHARS} 字符`)
  }
  return parts.join('；')
}

/** 工具结果的下载文件名 */
export function toolDownloadFilename(name) {
  return `ai-tool-${name || 'result'}.json`
}

/**
 * 续写时回灌给模型的已有内容：留尾巴，断点不能丢
 *
 * 为什么只留尾巴：全文可能好几千 token，回灌一遍就把预算吃光了；
 * 但续写必须接在最后一句的断点上，所以尾巴最不能丢。
 */
export function continuationTail(content, limit = CONTINUATION_TAIL_CHARS) {
  const t = (content || '').trim()
  if (!t) return ''
  if (t.length <= limit) return t
  return '…（前文已省略）\n' + t.slice(-limit)
}

/** 续写指令：明确「从断点接着写，不要重复」 */
export function continuationPrompt() {
  return '【继续写作】上面那段回答因为长度上限被截断了。'
    + '请从它最后一句被切断的地方接着往下写，'
    + '不要重复已经写过的内容，也不要重新开头。'
}

/**
 * 组装续写请求
 *
 * history 里不要放正在续写的那条消息 —— 同一段内容回灌两次，
 * 模型会以为自己说过两遍，续写就变成重复。
 */
export function buildContinueRequest({ question, history = [], content = '', continuation = '' }) {
  return {
    question: question || '',
    history: (history || []).filter(h => h && h.role && h.content),
    continuation: continuationTail(continuation || content),
  }
}

/** 合并续写内容：直接接在已有回答后面 */
export function mergeContinuation(base, more) {
  const a = (base || '').replace(/\s+$/, '')
  const b = (more || '').replace(/^\s+/, '')
  if (!a) return b
  if (!b) return a
  return a + '\n\n' + b
}

/** 消息底部的截断提示；没被截断返回 null */
export function truncationNotice(truncated, finishReason) {
  if (!truncated) return null
  const reason = finishReason ? `（${finishReason}）` : ''
  return {
    text: `本次回答因长度上限被截断${reason}`,
    action: '继续写完',
    hint: '点「继续写完」让 AI 从断点接着写，已写的内容不会重复。',
  }
}
