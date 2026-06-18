import axios from 'axios'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

api.interceptors.response.use(
  response => response.data,
  error => {
    console.error('API Error:', error)
    return Promise.reject(error)
  }
)

export default api

export const taskApi = {
  create: (data) => api.post('/tasks', data),
  list: (params) => api.get('/tasks', { params }),
  get: (id) => api.get(`/tasks/${id}`),
  delete: (id) => api.delete(`/tasks/${id}`)
}

export const caseApi = {
  list: (taskId) => api.get(`/tasks/${taskId}/cases`),
  create: (data) => api.post('/cases', data),
  update: (id, data) => api.put(`/cases/${id}`, data),
  delete: (id) => api.delete(`/cases/${id}`),
  generate: (taskId) => api.post(`/cases/generate/${taskId}`)
}

export const executeApi = {
  execute: (data) => api.post('/execute', data),
  pause: () => api.post('/agent/pause'),
  resume: () => api.post('/agent/resume'),
  stop: () => api.post('/agent/stop')
}

export const documentApi = {
  upload: (file) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/upload/document', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },
  parse: (path) => api.post('/parse/document', { document_path: path })
}

export const pageApi = {
  parse: (url, browser, taskId) => api.post('/parse/page', { url, browser, task_id: taskId })
}

export const commandApi = {
  send: (message) => api.post('/command', { message })
}

export const reportApi = {
  get: (taskId) => api.get(`/tasks/${taskId}/report`),
  list: () => api.get(`/reports`),
  getById: (reportId) => api.get(`/reports/${reportId}`)
}

export const agentApi = {
  getState: () => api.get('/agent/state')
}
