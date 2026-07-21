import axios from 'axios'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// ── 请求拦截器：自动附加 token ────────────────────────────────────────────────
api.interceptors.request.use(config => {
  const token = localStorage.getItem('token')
  if (token) config.headers['Authorization'] = `Bearer ${token}`
  return config
})

// ── 响应拦截器：401 跳登录页，其他错误统一提示 ───────────────────────────────
api.interceptors.response.use(
  response => response.data,
  error => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('username')
      localStorage.removeItem('role')
      const redirect = encodeURIComponent(window.location.pathname)
      window.location.href = `/login?redirect=${redirect}`
      return Promise.reject(error)
    }
    // 其他错误：取后端 detail 字段展示，没有则用通用提示
    const msg = error.response?.data?.detail || error.message || '请求失败，请稍后重试'
    // 不在登录页时才弹提示（避免循环）
    if (!window.location.pathname.includes('/login')) {
      import('element-plus').then(({ ElMessage }) => ElMessage.error(msg))
    }
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
  generate: (taskId, options = {}) => api.post(`/cases/generate/${taskId}`, options, { timeout: 600000 }),
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
  list: (workspaceId = null) => api.get(`/reports`, { params: workspaceId ? { workspace_id: workspaceId } : {} }),
  getById: (reportId) => api.get(`/reports/${reportId}`),
  delete: (reportId) => api.delete(`/reports/${reportId}`),
  deleteBatch: (reportIds) => api.delete(`/reports`, { data: reportIds }),
  exportHtml: (reportId) => window.open(`/api/v1/reports/${reportId}/export`, '_blank'),
  exportPdf: (reportId) => window.open(`/api/v1/reports/${reportId}/pdf`, '_blank'),
}

export const agentApi = {
  getState: () => api.get('/agent/state')
}

export const aiCaseApi = {
  generate: (data, signal) => api.post('/ai-cases/generate', data, { timeout: 420000, signal }),
  optimize: (id, signal) => api.post(`/ai-cases/${id}/optimize`, {}, { timeout: 420000, signal }),
  coverage: (id) => api.get(`/ai-cases/${id}/coverage`),
  list: (workspaceId = null) => api.get('/ai-cases', { params: workspaceId ? { workspace_id: workspaceId } : {} }),
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
  // 需求追踪矩阵
  extractRequirements: (id) => api.post(`/ai-cases/${id}/extract-requirements`, {}, { timeout: 180000 }),
  mapCasesToReqs: (id) => api.post(`/ai-cases/${id}/map-cases-to-reqs`, {}, { timeout: 300000 }),
  getTraceability: (id) => api.get(`/ai-cases/${id}/traceability`),
  analyzeGap: (id, data) => api.post(`/ai-cases/${id}/analyze-gap`, data, { timeout: 120000 }),
  supplementCases: (id, data) => api.post(`/ai-cases/${id}/supplement-cases`, data, { timeout: 30000 }),
}

export const apiTestApi = {
  listProjects: (workspaceId = null) => api.get('/api-test/projects', { params: workspaceId ? { workspace_id: workspaceId } : {} }),
  createProject: (data) => api.post('/api-test/projects', data),
  updateProject: (id, data) => api.put(`/api-test/projects/${id}`, data),
  deleteProject: (id) => api.delete(`/api-test/projects/${id}`),
  listAllCasesGrouped: (workspaceId = null) => api.get('/api-test/all-cases', {
    params: workspaceId ? { workspace_id: workspaceId } : {}
  }),
  listCases: (projectId) => api.get(`/api-test/projects/${projectId}/cases`),
  createCase: (data) => api.post('/api-test/cases', data),
  updateCase: (id, data) => api.put(`/api-test/cases/${id}`, data),
  deleteCases: (ids) => api.delete('/api-test/cases', { data: ids }),
  generateCases: (projectId, data) => api.post(`/api-test/projects/${projectId}/cases/generate`, data, { timeout: 300000 }),
  // 代码分析
  generateFromCode: (projectId, data) => api.post(`/api-test/projects/${projectId}/cases/generate-from-code`, data, { timeout: 300000 }),
  codeAnalyze: (projectId, data) => api.post(`/api-test/projects/${projectId}/code-analyze`, data, { timeout: 180000 }),
  saveAnalyzeCases: (projectId, data) => api.post(`/api-test/projects/${projectId}/code-analyze/save-cases`, data),
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
  list: (workspaceId = null) => api.get('/global-vars', {
    params: workspaceId ? { workspace_id: workspaceId } : {}
  }),
  create: (data, workspaceId = null) => api.post(
    '/global-vars' + (workspaceId ? `?workspace_id=${workspaceId}` : ''), data
  ),
  update: (id, data) => api.put(`/global-vars/${id}`, data),
  delete: (id) => api.delete(`/global-vars/${id}`),
}

export const userApi = {
  list: () => api.get('/auth/users'),
  create: (data) => api.post('/auth/users', data),
  delete: (username) => api.delete(`/auth/users/${username}`),
  resetPassword: (username, newPassword) => api.put(`/auth/users/${username}/password`, { new_password: newPassword }),
}

export const workspaceApi = {
  list: () => api.get('/workspaces'),
  create: (data) => api.post('/workspaces', data),
  get: (id) => api.get(`/workspaces/${id}`),
  update: (id, data) => api.put(`/workspaces/${id}`, data),
  delete: (id) => api.delete(`/workspaces/${id}`),
  listMembers: (id) => api.get(`/workspaces/${id}/members`),
  inviteMember: (id, data) => api.post(`/workspaces/${id}/members`, data),
  removeMember: (id, username) => api.delete(`/workspaces/${id}/members/${username}`),
}
