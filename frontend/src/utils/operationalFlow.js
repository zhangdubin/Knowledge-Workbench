export const FLOW_STAGES = [
  { key: 'source', label: '资料来源', hint: '选择获准的知识空间与资料版本' },
  { key: 'scope', label: '适用筛选', hint: '按范围、主题和适用日期收敛' },
  { key: 'evidence', label: '证据核验', hint: '核对版本、原文和逐字引文' },
  { key: 'feedback', label: '反馈闭环', hint: '提交疑问并交由授权人员处理' },
]

export const FLOW_STATUS = {
  done: { label: '已完成', tone: 'success' },
  running: { label: '进行中', tone: 'primary' },
  ready: { label: '可操作', tone: 'info' },
  pending: { label: '待开始', tone: 'muted' },
  blocked: { label: '需处理', tone: 'warning' },
}

export function flowState({ busy = false, result = null, error = '' } = {}) {
  if (error) return { source: 'done', scope: 'blocked', evidence: 'pending', feedback: 'pending' }
  if (busy) return { source: 'done', scope: 'running', evidence: 'pending', feedback: 'pending' }
  if (!result) return { source: 'done', scope: 'ready', evidence: 'pending', feedback: 'pending' }
  const evidence = result.status === 'supported' ? 'done' : result.status === 'conflict' ? 'blocked' : 'pending'
  return { source: 'done', scope: 'done', evidence, feedback: evidence === 'done' ? 'ready' : 'pending' }
}

export function flowSummary({ busy = false, result = null, error = '' } = {}) {
  if (error) return { label: '检索失败', tone: 'warning', detail: error }
  if (busy) return { label: '正在核对', tone: 'primary', detail: '正在按授权范围筛选资料并准备证据。' }
  if (!result) return { label: '等待查询', tone: 'muted', detail: '提交中文问题后，流程会从适用筛选开始。' }
  const labels = { supported: '有依据', conflict: '存在冲突', insufficient: '信息不足', incomplete: '结果不完整', ambiguous: '需要澄清' }
  return { label: labels[result.status] || '已返回', tone: result.status === 'supported' ? 'success' : 'warning', detail: result.answer || '请查看下方结果与证据。' }
}
