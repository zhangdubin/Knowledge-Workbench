import api from './index.js'

const base = '/api/knowledge-service'
const get = (path, params, isCurrent) => api.get(base + path, { params, silent: true, isCurrent })
const post = (path, data, isCurrent) => api.post(base + path, data, { silent: true, timeout: 180000, isCurrent })
const member = (path, id) => `${path}/${encodeURIComponent(id)}`

export const knowledgeService = {
  catalog: isCurrent => get('/catalog', undefined, isCurrent),
  template: isCurrent => get('/template', undefined, isCurrent),
  previewTemplate: (data, isCurrent) => post('/template', data, isCurrent),
  confirmTemplate: (id, isCurrent) => post(member('/template', id) + '/confirm', {}, isCurrent),
  listSources: (params, isCurrent) => get('/sources', params, isCurrent),
  registerSource: (data, isCurrent) => post('/sources', data, isCurrent),
  source: (id, isCurrent) => get(member('/sources', id), undefined, isCurrent),
  terms: (params, isCurrent) => get('/terms', params, isCurrent),
  query: (data, isCurrent) => post('/query', data, isCurrent),
  item: (id, isCurrent) => get(member('/items', id), undefined, isCurrent),
  run: (id, isCurrent) => get(member('/runs', id), undefined, isCurrent),
  submitFeedback: (data, isCurrent) => post('/feedback', data, isCurrent),
  listFeedback: (params, isCurrent) => get('/feedback', params, isCurrent),
  feedback: (id, isCurrent) => get(member('/feedback', id), undefined, isCurrent),
  resolveFeedback: (id, data, isCurrent) => post(member('/feedback', id) + '/resolve', data, isCurrent),
}
