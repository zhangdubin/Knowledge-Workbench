/**
 * 软件开发模块 API 客户端
 * ---------------------------------------------------------------------------
 * 后端契约（backend/app/routers/dev.py，前缀 /api/dev）：
 *
 *   配置与体检
 *     GET  /config                   → { mode, outbound_enabled, github, local_model, web_search, model }
 *                                       密钥一律掩码返回，token_set / api_key_set 表示「有没有设过」
 *     PUT  /config                   → 同上（掩码回传视为「不修改」，保留磁盘上的真值）
 *     POST /mode            {mode}    → { mode, model, missing[], how_to_fix[] }
 *                                       切到离线但没配本地模型时，如实回「缺什么」
 *     GET  /doctor          ?mode=    → { mode, capabilities[], missing[], how_to_fix[] }
 *                                       离线模式下不发任何外网请求
 *     POST /github/probe    {repo}    → { ok, skipped, detail }（离线时 skipped=true）
 *
 *   项目 / 任务 / 产出物
 *     GET  /projects       ?mode&status&keyword → { projects: [...] }
 *     POST /projects                   → { project }
 *     GET  /projects/{id}               → { project, tasks, artifacts, sessions, citations }
 *     PATCH/DELETE /projects/{id}
 *     POST /projects/{id}/plan          → { job }   后台作业，轮询 /jobs/{id}
 *     POST /projects/{id}/tasks/generate-all → { job }
 *     POST /projects/{id}/chat   {question} → { session, answer, citations[], notices[] }
 *     POST /projects/{id}/feedback {artifact_ids?, lessons?} → { report }
 *     POST /projects/{id}/tasks    → { task }
 *     PATCH/DELETE /tasks/{id}
 *     POST /tasks/{id}/output   {force?}    → { artifacts[], blocked[], warnings[] }
 *     GET/PATCH/DELETE /artifacts/{id}
 *     POST /artifacts/{id}/import        → { document }
 *     GET  /projects/{id}/sessions|citations
 *     GET  /jobs/{id}
 *
 * 错误口径：后端在「缺配置 / 能力不可用」时返回
 *   { ok:false, detail, missing[], how_to_fix[], extra }
 * 前端不要自己猜缺什么 —— 把后端给的 missing / how_to_fix 原样显示出来。
 *
 * 这里不用 axios 拦截器的全局错误弹窗（silent），
 * 因为本模块的错误多半是「还没配好」，弹窗只会变成噪音，
 * 页面自己有专门的「缺什么、怎么配」展示区。
 */
import api from './index'

export const DevApi = {
  /* ---- 配置与体检 ---- */
  config: () => api.get('/api/dev/config', { silent: true }),
  saveConfig: (payload) => api.put('/api/dev/config', payload, { silent: true }),
  switchMode: (mode) => api.post('/api/dev/mode', { mode }, { silent: true }),
  doctor: (mode) => api.get('/api/dev/doctor', { params: { mode: mode || '' }, silent: true }),
  probeRepo: (repo, branch) =>
    api.post('/api/dev/github/probe', { repo: repo, branch: branch || '' }, { silent: true }),

  /* ---- 项目 ---- */
  projects: (params) => api.get('/api/dev/projects', { params: params || {}, silent: true }),
  createProject: (payload) => api.post('/api/dev/projects', payload, { silent: true }),
  project: (id) => api.get('/api/dev/projects/' + id, { silent: true }),
  patchProject: (id, payload) => api.patch('/api/dev/projects/' + id, payload, { silent: true }),
  deleteProject: (id) => api.delete('/api/dev/projects/' + id, { silent: true }),

  /* ---- 生成 ---- */
  generatePlan: (id, payload) =>
    api.post('/api/dev/projects/' + id + '/plan', payload || {}, { silent: true }),
  generateAllTasks: (id, payload) =>
    api.post('/api/dev/projects/' + id + '/tasks/generate-all', payload || {}, { silent: true }),
  generateTaskOutput: (taskId, payload) =>
    api.post('/api/dev/tasks/' + taskId + '/output', payload || {}, { silent: true }),
  chat: (id, question) =>
    api.post('/api/dev/projects/' + id + '/chat', { question: question }, { silent: true }),

  /* ---- 任务 ---- */
  createTask: (projectId, payload) =>
    api.post('/api/dev/projects/' + projectId + '/tasks', payload, { silent: true }),
  patchTask: (id, payload) => api.patch('/api/dev/tasks/' + id, payload, { silent: true }),
  deleteTask: (id) => api.delete('/api/dev/tasks/' + id, { silent: true }),

  /* ---- 产出物 ---- */
  artifact: (id) => api.get('/api/dev/artifacts/' + id, { silent: true }),
  createArtifact: (payload) => api.post('/api/dev/artifacts', payload, { silent: true }),
  patchArtifact: (id, payload) => api.patch('/api/dev/artifacts/' + id, payload, { silent: true }),
  deleteArtifact: (id) => api.delete('/api/dev/artifacts/' + id, { silent: true }),
  importArtifact: (id) => api.post('/api/dev/artifacts/' + id + '/import', {}, { silent: true }),

  /* ---- 闭环反哺 ---- */
  feedback: (id, payload) =>
    api.post('/api/dev/projects/' + id + '/feedback', payload || {}, { silent: true }),

  /* ---- 会话 / 引用 / 作业 ---- */
  sessions: (id, limit) =>
    api.get('/api/dev/projects/' + id + '/sessions', { params: { limit: limit || 30 }, silent: true }),
  citations: (id, sessionId) =>
    api.get('/api/dev/projects/' + id + '/citations',
      { params: { session_id: sessionId || 0 }, silent: true }),
  job: (id) => api.get('/api/dev/jobs/' + id, { silent: true }),

  /* ---- 四阶段流水线（契约：docs/软件开发流水线设计.md） ---- */

  /**
   * 读流水线：阶段状态 + 左栏导航用的精简视图 + 闸门。
   * 后端还没上线这个接口时，前端要显示「后端还没上线这个阶段」而不是白屏，
   * 所以这里不吞异常 —— 由调用方按 404 单独处理。
   */
  pipeline: (id) => api.get('/api/dev/projects/' + id + '/pipeline', { silent: true }),

  /**
   * 跑某个阶段（clarify / specify / design / implement）。
   * 闸门不通过时后端直接返回 409 与原因（detail / missing / how_to_fix），
   * 那是「正常的拒绝」，不是错误 —— 界面要把原因显示出来。
   */
  runStage: (id, stage, body) =>
    api.post('/api/dev/projects/' + id + '/stages/' + stage + '/run', body || {}, { silent: true }),

  /**
   * 提交澄清答案 / 编辑阶段产出。
   * clarify 用 answers，specify/design 用 notes（可带 data 覆盖产出）。
   */
  answerStage: (id, stage, body) =>
    api.post('/api/dev/projects/' + id + '/stages/' + stage + '/answer', body || {}, { silent: true }),

  /** 导出 ZIP 的地址（配合 downloadExport 用，不要单独 window.open） */
  exportUrl: (id) => '/api/dev/projects/' + id + '/export.zip',
}

/**
 * 下载导出的项目 ZIP。
 *
 * 为什么不能直接 window.open(url)：
 *   裸链不带会话 cookie —— 后端认不出是谁，导出直接 401；
 *   而且失败了浏览器只会跳一个 JSON 错误页，用户完全不知道发生了什么。
 * 所以这里用 fetch 带 credentials 拿 blob，再触发一次本地下载；
 * 失败时把后端的 detail 抛出来给界面显示。
 */
export async function downloadExport(id, filename) {
  const url = DevApi.exportUrl(id)
  const resp = await fetch(url, { credentials: 'include' })
  if (!resp.ok) {
    let detail = '导出失败（HTTP ' + resp.status + '）'
    try {
      const data = await resp.json()
      detail = data.detail || data.message || detail
      // 后端在 409 时会带 how_to_fix（「依次跑完…然后执行项目生成」），
      // 一并显示出来，用户才知道下一步该点什么
      if (Array.isArray(data.how_to_fix) && data.how_to_fix.length) {
        detail = detail + '（' + data.how_to_fix.join('；') + '）'
      }
    } catch (e) {
      // 响应不是 JSON（比如网关错误页），就用兜底文案
    }
    const err = new Error(detail)
    err.response = { status: resp.status, data: { detail: detail } }
    throw err
  }
  const blob = await resp.blob()
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = filename || 'project.zip'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  // 不 revoke 的话 blob 会一直占着内存，文件大时能吃掉不少
  setTimeout(() => URL.revokeObjectURL(href), 2000)
  return true
}

export default DevApi
