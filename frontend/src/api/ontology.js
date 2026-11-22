import api from './index'
const base = '/api/ontologies/'
export const studio = {
  list: (path = '', params = {}) => api.get(base + path, { params, silent: true }),
  post: (path, data) => api.post(base + path, data, { silent: true, timeout: 180000 }),
  put: (path, data) => api.put(base + path, data, { silent: true }),
  confirm: (id) => api.post(base + 'changes/' + id + '/confirm', undefined, { silent: true }),
}
