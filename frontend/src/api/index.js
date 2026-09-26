import axios from 'axios'
import { ElMessage } from 'element-plus'

const api = axios.create({
  baseURL: '',
  timeout: 30000,
  // 会话走 HttpOnly Cookie：文件预览（<img>/<iframe>）带不了自定义头，
  // 只有 Cookie 能让「鉴权」与「预览」同时成立。
  withCredentials: true,
})

// 401 时把用户送回登录页；这里只负责跳转，提示交给登录页
let redirecting = false
function toLogin(msg) {
  if (redirecting) return
  redirecting = true
  const here = window.location.hash || '#/'
  if (!here.startsWith('#/login')) {
    sessionStorage.setItem('kb_return_to', here)
  }
  ElMessage.warning(msg || '登录已失效，请重新登录')
  window.location.hash = '#/login'
  setTimeout(() => { redirecting = false }, 1200)
}

api.interceptors.response.use(
  (resp) => resp.data,
  (err) => {
    const status = err.response?.status
    const msg = err.response?.data?.detail || err.message || '请求失败'
    if (status === 401) {
      toLogin(msg)
    } else {
      ElMessage.error(msg)
    }
    return Promise.reject(err)
  }
)

export default api

// 文件 URL 工具：预览走 inline，下载走 attachment
// 优先用后端返回的 URL（历史记录里存的是 /api/attachments/... 旧路径，
// 新数据是 /api/documents/...，两者都由后端给出，前端不做拼接判断）
export const fileUrls = {
  preview: (row) => row?.preview_url
    || (row?.id ? `/api/documents/${row.id}/raw` : ''),
  download: (row) => row?.url
    || (row?.id ? `/api/documents/${row.id}/download` : ''),
}

// 预览模式判定：优先后端给出的 mode，其次按扩展名兜底（content_type 常不准）
const EXT_MODE = {
  pdf: 'pdf',
  docx: 'office', doc: 'legacy-office',
  xlsx: 'office', xls: 'legacy-office',
  pptx: 'office', ppt: 'legacy-office',
  csv: 'csv', tsv: 'csv',
}
const IMG_EXT = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg', 'ico', 'avif', 'heic']
const VIDEO_EXT = ['mp4', 'webm', 'ogv', 'mov', 'm4v', 'mkv', 'avi']
const AUDIO_EXT = ['mp3', 'wav', 'ogg', 'm4a', 'flac', 'aac', 'weba']
const TEXT_EXT = [
  'txt', 'md', 'markdown', 'log', 'json', 'xml', 'yml', 'yaml', 'ini', 'conf',
  'py', 'js', 'ts', 'sh', 'sql', 'css', 'html', 'htm', 'java', 'go', 'rs',
]

export function previewModeOf(row) {
  if (!row) return 'other'
  if (row.mode) return row.mode
  const name = (row.filename || '').toLowerCase()
  const ext = name.includes('.') ? name.split('.').pop() : ''
  const mime = (row.mime || '').toLowerCase()
  if (EXT_MODE[ext]) return EXT_MODE[ext]
  if (IMG_EXT.includes(ext) || mime.startsWith('image/')) return 'image'
  if (VIDEO_EXT.includes(ext) || mime.startsWith('video/')) return 'video'
  if (AUDIO_EXT.includes(ext) || mime.startsWith('audio/')) return 'audio'
  if (TEXT_EXT.includes(ext) || mime.startsWith('text/') ||
      mime.includes('json') || mime.includes('xml')) return 'text'
  return 'other'
}

// ============ API 封装 ============
export const Api = {

  // ============ 认证与权限（v0.3）============
  authStatus: () => api.get('/api/auth/status'),
  authMeta: () => api.get('/api/auth/meta'),
  login: (username, password) => api.post('/api/auth/login', { username, password }),
  logout: () => api.post('/api/auth/logout'),
  me: () => api.get('/api/auth/me'),
  changePassword: (old_password, new_password) =>
    api.post('/api/auth/password', { old_password, new_password }),

  // ============ 系统管理：用户 / 角色 / 审计 ============
  listUsers: () => api.get('/api/system/users'),
  createUser: (d) => api.post('/api/system/users', d),
  updateUser: (id, d) => api.patch(`/api/system/users/${id}`, d),
  deleteUser: (id) => api.delete(`/api/system/users/${id}`),
  listRoles: () => api.get('/api/system/roles'),
  createRole: (d) => api.post('/api/system/roles', d),
  updateRole: (id, d) => api.patch(`/api/system/roles/${id}`, d),
  deleteRole: (id) => api.delete(`/api/system/roles/${id}`),
  listAudit: (params = {}) => api.get('/api/system/audit', { params }),
  auditStats: (days = 7) => api.get('/api/system/audit/stats', { params: { days } }),

  // ============ 存储与备份 ============
  storageReport: () => api.get('/api/system/storage'),
  storageIndex: () => api.get('/api/system/storage/index'),
  storageRepairIndex: () => api.post('/api/system/storage/index/repair'),
  storageOps: () => api.get('/api/system/storage/ops'),
  // params 目前只有 batch（外迁动作每批处理多少个文件）。
  // 后端把它做成 query 而不是 body，因为多数维护动作没有入参，
  // 一个可选的 query 参数比要求所有动作都接受空 body 更省事。
  storageRunOp: (op, params) => api.post(`/api/system/storage/ops/${op}`, null, { params }),
  storageBackup: () => api.post('/api/system/storage/backup'),
  storageBackups: () => api.get('/api/system/storage/backups'),
  // 还原可能涉及跨盘复制大量文件，全局 30s 超时对它太短；0 = 不限
  storageRestore: (name) => api.post('/api/system/storage/restore',
    { name, confirm: name }, { timeout: 0 }),

  // ============ 运行期设置（改完立即生效，不需要重启容器） ============
  settings: () => api.get('/api/system/settings'),
  // 只提交发生改动的项；后端逐项校验，任一项不过关则整体不落盘
  saveSettings: (items) => api.put('/api/system/settings', { items }),
  resetSetting: (key) => api.delete(`/api/system/settings/${key}`),
  backupTargets: () => api.get('/api/system/settings/backup-targets'),
  probePath: (path) => api.post('/api/system/settings/probe', { path }),

  // ============ 升级更新（GitHub Releases）============
  // refresh=1 跳过服务端 10 分钟缓存（「重新检查」按钮用）
  updateCheck: (refresh = false) => api.get('/api/system/update/check',
    refresh ? { params: { refresh: 1 }, timeout: 20000 } : { timeout: 20000 }),

  // ============ 可视化驾驶舱 ============
  listDashboards: () => api.get('/api/dashboards'),
  createDashboard: (d) => api.post('/api/dashboards', d),
  getDashboard: (id) => api.get(`/api/dashboards/${id}`),
  dashboardData: (id) => api.get(`/api/dashboards/${id}/data`),
  updateDashboard: (id, d) => api.put(`/api/dashboards/${id}`, d),
  deleteDashboard: (id) => api.delete(`/api/dashboards/${id}`),
  dashboardOptions: () => api.get('/api/dashboards/options'),
  dashboardTemplates: () => api.get('/api/dashboards/templates'),
  createFromTemplate: (template_key, name = '') =>
    api.post('/api/dashboards/templates', { template_key, name }),
  previewWidget: (widget) => api.post('/api/dashboards/preview', { widget }),

  // ============ 图谱扩展 ============
  graphGlobal: (params = {}) => api.get('/api/graph/global', { params }),
  graphForDocument: (id, depth = 1) =>
    api.get(`/api/graph/document/${id}`, { params: { depth } }),
  graphSearch: (keyword, limit = 20) =>
    api.get('/api/graph/search', { params: { keyword, limit } }),

  // ============ 关联（v0.3：两端支持文件）============
  updateRelationDef: (id, d) => api.patch(`/api/relations/defs/${id}`, d),
  relationPick: (defId, side, keyword = '') =>
    api.get(`/api/relations/defs/${defId}/pick`, { params: { side, keyword } }),
  relationsForDocument: (id) => api.get(`/api/relations/for-document/${id}`),
  filesOfRecord: (id) => api.get(`/api/relations/files-of-record/${id}`),

  // 健康
  health: () => api.get('/api/health'),

  // 应用（自定义 CRUD）
  listApps: () => api.get('/api/apps'),
  createApp: (data) => api.post('/api/apps', data),
  updateApp: (id, data) => api.put(`/api/apps/${id}`, data),
  deleteApp: (id) => api.delete(`/api/apps/${id}`),
  listAppTemplates: () => api.get('/api/apps/templates'),
  createAppFromTemplate: (data) => api.post('/api/apps/from-template', data),

  // 知识关联（记录 ↔ 笔记）
  getKnowledgeNoteType: () => api.get('/api/knowledge/note-type'),
  getRecordKnowledge: (recordId) => api.get(`/api/knowledge/for-record/${recordId}`),
  getNoteRecords: (noteId) => api.get(`/api/knowledge/for-note/${noteId}`),
  linkKnowledge: (recordId, noteId) =>
    api.post('/api/knowledge/link', { record_id: recordId, note_id: noteId }),
  unlinkKnowledge: (recordId, noteId) =>
    api.delete('/api/knowledge/link', { params: { record_id: recordId, note_id: noteId } }),
  noteFromRecord: (recordId) =>
    api.post('/api/knowledge/note-from-record', { record_id: recordId }),

  // 统计
  getStats: () => api.get('/api/stats'),

  // 实体类型
  listEntityTypes: (app) => api.get('/api/entity-types', { params: { app } }),
  getEntityType: (id) => api.get(`/api/entity-types/${id}`),
  getEntityTypeByKey: (key) => api.get(`/api/entity-types/by-key/${key}`),
  createEntityType: (data) => api.post('/api/entity-types', data),
  updateEntityType: (id, data) => api.put(`/api/entity-types/${id}`, data),
  deleteEntityType: (id) => api.delete(`/api/entity-types/${id}`),
  // 模型 ⇄ JSON：导出给用户编辑，导入时可按 key 新建 / 覆盖
  exportEntityType: (id) => api.get(`/api/entity-types/${id}/export`),
  importEntityType: (payload) => api.post('/api/entity-types/import', payload),
  entityTypeExample: () => api.get('/api/entity-types/example'),

  // JSON 工具
  jsonParse: (text) => api.post('/api/json/parse', { text }),
  jsonToTree: (payload) => api.post('/api/json/to-tree', payload),

  // 记录
  listRecords: (typeId, params = {}) =>
    api.get(`/api/records/type/${typeId}`, { params }),
  exportRecordsUrl: (typeId) => `/api/records/type/${typeId}/export`,
  importRecords: (typeId, content, format = 'csv') =>
    api.post(`/api/records/type/${typeId}/import`, { content, format }),

  // 回收站（模型与记录的软删除恢复）
  listRecycle: () => api.get('/api/recycle'),
  restoreRecycleType: (id) => api.post(`/api/recycle/types/${id}/restore`),
  purgeRecycleType: (id, key) => api.delete(`/api/recycle/types/${id}`, { data: { key } }),
  restoreRecycleRecord: (id) => api.post(`/api/recycle/records/${id}/restore`),
  purgeRecycleRecord: (id) => api.delete(`/api/recycle/records/${id}`),
  getRecord: (id) => api.get(`/api/records/${id}`),
  createRecord: (typeId, data) =>
    api.post(`/api/records/type/${typeId}`, { data }),
  updateRecord: (id, data) => api.put(`/api/records/${id}`, { data }),
  deleteRecord: (id) => api.delete(`/api/records/${id}`),

  // 关系
  listRelationDefs: () => api.get('/api/relations/defs'),
  createRelationDef: (data) => api.post('/api/relations/defs', data),
  deleteRelationDef: (id) => api.delete(`/api/relations/defs/${id}`),
  createRelationRecord: (data) => api.post('/api/relations/records', data),
  deleteRelationRecord: (id) => api.delete(`/api/relations/records/${id}`),
  relationsForRecord: (id) => api.get(`/api/relations/for-record/${id}`),

  // 附件
  listAttachments: (recordId, fieldKey) =>
    api.get(`/api/attachments/for-record/${recordId}`, { params: { field_key: fieldKey } }),
  listAllAttachments: (params = {}) =>
    api.get('/api/attachments/all', { params }),
  uploadAttachment: (recordId, fieldKey, file) => {
    const form = new FormData()
    form.append('record_id', recordId)
    form.append('field_key', fieldKey)
    form.append('file', file)
    return api.post('/api/attachments/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  deleteAttachment: (id) => api.delete(`/api/attachments/${id}`),
  // 内联预览（Content-Disposition: inline，可直接用于 iframe/img/video）
  extractAttachment: (id) => api.get(`/api/attachments/${id}/extract`),

  // ============ 文档（文件原文存数据库，v0.2 起的主通道）============
  listDocuments: (params = {}) => api.get('/api/documents', { params }),
  getDocument: (id, withText = false) =>
    api.get(`/api/documents/${id}`, { params: { with_text: withText } }),
  // 单个文件的结构化元数据（JSON 文本 + 节点树），展开时才按需拉取
  documentMeta: (id) => api.get(`/api/documents/${id}/meta`),
  documentStats: () => api.get('/api/documents/stats'),
  documentTags: () => api.get('/api/documents/tags'),

  // 上传：不再需要先建一条记录，文件可直接独立存在
  uploadDocument: (file, meta = {}) => {
    const form = new FormData()
    form.append('file', file)
    form.append('title', meta.title || '')
    form.append('tags', (meta.tags || []).join(','))
    form.append('description', meta.description || '')
    form.append('app', meta.app || 'default')
    form.append('embed', meta.embed === false ? 'false' : 'true')
    if (meta.record_id) form.append('record_id', meta.record_id)
    if (meta.field_key) form.append('field_key', meta.field_key)
    return api.post('/api/documents/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 180000,   // 大文件 + 正文抽取 + 向量化，需要放宽超时
    })
  },
  updateDocument: (id, data) => api.patch(`/api/documents/${id}`, data),
  deleteDocument: (id, hard = false) =>
    api.delete(`/api/documents/${id}`, { params: { hard } }),
  restoreDocument: (id) => api.post(`/api/documents/${id}/restore`),
  reindexDocument: (id, embed = true) =>
    api.post(`/api/documents/${id}/reindex`, { embed }),
  documentContent: (id) => api.get(`/api/documents/${id}/content`),
  resummarizeDocument: (id) => api.post(`/api/documents/${id}/resummarize`),
  askDocument: (id, question) =>
    api.post(`/api/documents/${id}/ask`, { question }, { timeout: 120000 }),

  // 混合检索：mode = hybrid | keyword | semantic
  searchDocuments: (q, params = {}) =>
    api.get('/api/documents/search', { params: { q, ...params } }),

  // 文档 ↔ 业务记录
  linkDocument: (docId, data) => api.post(`/api/documents/${docId}/link`, data),
  unlinkDocument: (docId, linkId) =>
    api.delete(`/api/documents/${docId}/link/${linkId}`),


  // 搜索
  search: (keyword, limit = 50) =>
    api.get('/api/search', { params: { keyword, limit } }),

  // 图谱
  graphForRecord: (id, depth = 2) =>
    api.get(`/api/graph/record/${id}`, { params: { depth } }),
  graphForType: (id, limit = 200) =>
    api.get(`/api/graph/type/${id}`, { params: { limit } }),
  graphForNotes: (tag, limit = 300) =>
    api.get('/api/graph/notes', { params: { tag, limit } }),

  // 笔记双链
  syncNoteLinks: (recordId, content) =>
    api.post(`/api/notes/${recordId}/sync-links`, { content }),
  getNoteBacklinks: (recordId) => api.get(`/api/notes/${recordId}/backlinks`),
  getNoteOutgoing: (recordId) => api.get(`/api/notes/${recordId}/outgoing`),
  extractWikilinks: (content) => api.get('/api/notes/extract', { params: { content } }),

  // AI
  getAIConfig: () => api.get('/api/ai/config'),
  updateAIConfig: (data) => api.put('/api/ai/config', data),
  testAI: () => api.post('/api/ai/test'),
  // 向量化（embedding）
  getEmbeddingStatus: () => api.get('/api/ai/embedding'),
  testEmbedding: () => api.post('/api/ai/test-embedding', {}, { timeout: 60000 }),
  aiSummarize: (text) => api.post('/api/ai/summarize', { text }),
  aiTags: (text, max_tags = 5) => api.post('/api/ai/tags', { text, max_tags }),
  aiRewrite: (text, style = 'polish') => api.post('/api/ai/rewrite', { text, style }),
  aiTitle: (content) => api.post('/api/ai/title', { content }),
  // document_ids 为空且 auto_retrieve 为真时，服务端自动混合检索相关文件与笔记
  aiAsk: (question, context, opts = {}) =>
    api.post('/api/ai/ask', {      question, context,
      document_ids: opts.document_ids || null,
      auto_retrieve: opts.auto_retrieve !== false,
    }, { timeout: 120000 }),

  // AI 操作中枢：自然语言 → 工具调用（查询当场执行，写入先出待确认清单）
  aiAgent: (question, history) =>
    api.post('/api/ai/agent', { question, history }, { timeout: 180000 }),

  // 用户点「确认执行」后真正落库；参数由后端重新校验一遍
  aiAgentConfirm: ({ question, history, pending }) =>
    api.post('/api/ai/agent/confirm', {
      question,
      history,
      tool: pending.tool,
      args: pending.args,
      digest: pending.digest || [],
    }, { timeout: 180000 }),
}
