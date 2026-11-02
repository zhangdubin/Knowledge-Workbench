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
}

export default DevApi
