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
  generate: (taskId) => api.post(`/cases/generate/${taskId}`, {}, { timeout: 180000 }),
  optimize: (taskId) => api.post(`/cases/optimize/${taskId}`, {}, { timeout: 300000 }),
  coverage: (taskId) => api.get(`/cases/coverage/${taskId}`),
  // 文档变更检测与增量更新
  docDiffCheck: (taskId, data) => api.post(`/cases/doc-diff-check/${taskId}`, data, { timeout: 120000 }),
  incrementalUpdate: (taskId, data) => api.post(`/cases/incremental-update/${taskId}`, data, { timeout: 420000 }),
}

export const executeApi = {
  execute: (data) => api.post('/execute', data, { timeout: 600000 }),
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
  getById: (reportId) => api.get(`/reports/${reportId}`),
  delete: (reportId) => api.delete(`/reports/${reportId}`),
  deleteBatch: (reportIds) => api.delete(`/reports`, { data: reportIds })
}

export const agentApi = {
  getState: () => api.get('/agent/state')
}

export const aiCaseApi = {
  generate: (data, signal) => api.post('/ai-cases/generate', data, { timeout: 420000, signal }),
  optimize: (id, signal) => api.post(`/ai-cases/${id}/optimize`, {}, { timeout: 420000, signal }),
  coverage: (id) => api.get(`/ai-cases/${id}/coverage`),
  list: () => api.get('/ai-cases'),
  getById: (id) => api.get(`/ai-cases/${id}`),
  downloadUrl: (id, format) => `/api/v1/ai-cases/${id}/download?format=${format}`,
  delete: (id) => api.delete(`/ai-cases/${id}`),
  // 单条用例 CRUD
  addCase: (recordId, data) => api.post(`/ai-cases/${recordId}/cases`, data),
  updateCase: (recordId, caseId, data) => api.put(`/ai-cases/${recordId}/cases/${caseId}`, data),
  deleteCase: (recordId, caseId) => api.delete(`/ai-cases/${recordId}/cases/${caseId}`),
  // 文档变更检测与增量更新
  diffCheck: (id, data) => api.post(`/ai-cases/${id}/diff-check`, data, { timeout: 120000 }),
  incrementalUpdate: (id, data, signal) => api.post(`/ai-cases/${id}/incremental-update`, data, { timeout: 420000, signal }),
}

export const apiTestApi = {
  listProjects: () => api.get('/api-test/projects'),
  createProject: (data) => api.post('/api-test/projects', data),
  updateProject: (id, data) => api.put(`/api-test/projects/${id}`, data),
  deleteProject: (id) => api.delete(`/api-test/projects/${id}`),
  listAllCasesGrouped: () => api.get('/api-test/all-cases'),
  listCases: (projectId) => api.get(`/api-test/projects/${projectId}/cases`),
  createCase: (data) => api.post('/api-test/cases', data),
  updateCase: (id, data) => api.put(`/api-test/cases/${id}`, data),
  deleteCases: (ids) => api.delete('/api-test/cases', { data: ids }),
  generateCases: (projectId, data) => api.post(`/api-test/projects/${projectId}/cases/generate`, data, { timeout: 300000 }),
  executeCases: (projectId, data) => api.post(`/api-test/projects/${projectId}/execute`, data, { timeout: 600000 }),
  startLoad: (projectId, data) => api.post(`/api-test/projects/${projectId}/load`, data, { timeout: 30000 }),
  stopLoad: () => api.post('/api-test/load/stop'),
  listReports: (projectId) => api.get(`/api-test/projects/${projectId}/reports`),
  analyzeReport: (reportId) => api.post(`/api-test/reports/${reportId}/analyze`, {}, { timeout: 90000 }),
  deleteReport: (reportId) => api.delete(`/api-test/reports/${reportId}`),
  deleteReportsBatch: (ids) => api.delete(`/api-test/reports/batch`, { data: ids }),
  listBuiltinFunctions: () => api.get('/api-test/builtin-functions'),
}

export const scriptApi = {
  list: (projectId) => api.get('/api-test/scripts', { params: projectId ? { project_id: projectId } : {} }),
  create: (data) => api.post('/api-test/scripts', data),
  update: (id, data) => api.put(`/api-test/scripts/${id}`, data),
  delete: (id) => api.delete(`/api-test/scripts/${id}`),
  test: (data) => api.post('/api-test/scripts/test', data),
  aiGenerate: (data) => api.post('/api-test/scripts/ai-generate', data),
}

export const gvarApi = {
  list: () => api.get('/global-vars'),
  create: (data) => api.post('/global-vars', data),
  update: (id, data) => api.put(`/global-vars/${id}`, data),
  delete: (id) => api.delete(`/global-vars/${id}`),
}
