import api from './index'

const base = '/api/knowledge-service'
const get = (path, params) => api.get(base + path, { params, silent: true })
const post = (path, data) => api.post(base + path, data, { silent: true, timeout: 180000 })
const member = (path, id) => `${path}/${encodeURIComponent(id)}`

export const knowledgeService = {
  catalog: () => get('/catalog'),
  template: () => get('/template'),
  previewTemplate: data => post('/template', data),
  confirmTemplate: id => post(member('/template', id) + '/confirm', {}),
  listSources: params => get('/sources', params),
  registerSource: data => post('/sources', data),
  source: id => get(member('/sources', id)),
  terms: params => get('/terms', params),
  query: data => post('/query', data),
  item: id => get(member('/items', id)),
  run: id => get(member('/runs', id)),
  submitFeedback: data => post('/feedback', data),
  listFeedback: params => get('/feedback', params),
  feedback: id => get(member('/feedback', id)),
  resolveFeedback: (id, data) => post(member('/feedback', id) + '/resolve', data),
}
