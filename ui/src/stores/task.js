import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as api from '../api'

export const useTaskStore = defineStore('task', () => {
  const tasks = ref([])
  const currentTask = ref(null)
  const cases = ref([])
  const executionResults = ref([])
  const reportPath = ref('')
  const isExecuting = ref(false)
  const executionProgress = ref({
    current: 0,
    total: 0,
    caseName: '',
    status: ''
  })
  const pageElements = ref([])

  const taskCount = computed(() => tasks.value.length)
  const caseCount = computed(() => cases.value.length)
  const passedCount = computed(() =>
    executionResults.value.filter(r => r.status === 'passed').length
  )
  const failedCount = computed(() =>
    executionResults.value.filter(r => r.status === 'failed').length
  )

  async function fetchTasks() {
    const data = await api.taskApi.list()
    tasks.value = data
    return data
  }

  async function getTask(taskId) {
    const data = await api.taskApi.get(taskId)
    currentTask.value = data
    if (data.page_elements) {
      pageElements.value = data.page_elements
    }
    return data
  }

  async function createTask(taskData) {
    const data = await api.taskApi.create(taskData)
    tasks.value.unshift(data)
    return data
  }

  async function deleteTask(id) {
    await api.taskApi.delete(id)
    tasks.value = tasks.value.filter(t => t.id !== id)
  }

  async function parsePage(url, browser = 'chromium', taskId = null) {
    const data = await api.pageApi.parse(url, browser, taskId)
    pageElements.value = data.elements || []
    return data
  }

  async function uploadDocument(file) {
    const data = await api.documentApi.upload(file)
    return data
  }

  async function parseDocument(path) {
    const data = await api.documentApi.parse(path)
    return data
  }

  async function fetchCases(taskId) {
    const data = await api.caseApi.list(taskId)
    cases.value = data
    return data
  }

  async function createCase(caseData) {
    const data = await api.caseApi.create(caseData)
    cases.value.push(data)
    return data
  }

  async function updateCase(id, caseData) {
    const data = await api.caseApi.update(id, caseData)
    const index = cases.value.findIndex(c => c.id === id)
    if (index !== -1) {
      cases.value[index] = data
    }
    return data
  }

  async function deleteCase(id) {
    await api.caseApi.delete(id)
    cases.value = cases.value.filter(c => c.id !== id)
  }

  async function executeCases(taskId, caseIds = null, browser = 'chromium') {
    isExecuting.value = true
    executionResults.value = []
    try {
      const data = await api.executeApi.execute({
        task_id: taskId,
        case_ids: caseIds,
        browser
      })
      executionResults.value = data.results || []
      return data
    } finally {
      isExecuting.value = false
    }
  }

  async function pauseExecution() {
    await api.executeApi.pause()
  }

  async function resumeExecution() {
    await api.executeApi.resume()
  }

  async function stopExecution() {
    await api.executeApi.stop()
    isExecuting.value = false
  }

  async function sendCommand(message) {
    const data = await api.commandApi.send(message)
    if (data.results) {
      executionResults.value = data.results
    }
    if (data.cases) {
      cases.value = data.cases
    }
    return data
  }

  async function generateCases(taskId) {
    const data = await api.caseApi.generate(taskId)
    cases.value = data
    return data
  }

  async function fetchReport(taskId) {
    const data = await api.reportApi.get(taskId)
    return data
  }

  function addTask(task) {
    tasks.value.unshift(task)
  }

  function setCases(newCases) {
    cases.value = newCases
  }

  function setReportPath(path) {
    reportPath.value = path
  }

  function updateExecutionProgress(progress) {
    executionProgress.value = {
      current: progress.current,
      total: progress.total,
      caseName: progress.case_name,
      status: progress.status,
      progress: progress.progress
    }
  }

  return {
    tasks,
    currentTask,
    cases,
    executionResults,
    reportPath,
    isExecuting,
    executionProgress,
    pageElements,
    taskCount,
    caseCount,
    passedCount,
    failedCount,
    fetchTasks,
    getTask,
    createTask,
    deleteTask,
    parsePage,
    uploadDocument,
    parseDocument,
    fetchCases,
    createCase,
    updateCase,
    deleteCase,
    executeCases,
    pauseExecution,
    resumeExecution,
    stopExecution,
    sendCommand,
    fetchReport,
    addTask,
    setCases,
    setReportPath,
    updateExecutionProgress
  }
})
