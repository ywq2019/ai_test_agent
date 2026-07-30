import { ref, computed, onMounted, watch } from 'vue'
import { caseApi } from '@/api'

export function useFailedCases(taskIdRef) {
  const lastExecutionFailed = ref([])
  const lastExecutionResults = ref([])
  const lastExecutionSummary = ref(null)
  const loading = ref(false)

  const failedCount = computed(() => lastExecutionFailed.value.length)
  const hasFailed = computed(() => failedCount.value > 0)
  const executionResultMap = computed(() => {
    const map = {}
    for (const r of lastExecutionResults.value) {
      if (r.case_id) {
        map[r.case_id] = { status: r.status, error: r.error_message }
      }
      if (r.case_name && !map['_name_' + r.case_name]) {
        map['_name_' + r.case_name] = { status: r.status, error: r.error_message }
      }
    }
    return map
  })

  async function fetchLatestFailed() {
    const tid = taskIdRef?.value
    if (!tid) {
      lastExecutionFailed.value = []
      lastExecutionResults.value = []
      lastExecutionSummary.value = null
      return
    }
    loading.value = true
    try {
      const res = await caseApi.latestFailedCases(tid)
      lastExecutionFailed.value = res.failed_cases || []
      lastExecutionResults.value = res.execution_results || []
      lastExecutionSummary.value = res.summary || null
    } catch {
      lastExecutionFailed.value = []
      lastExecutionResults.value = []
    } finally {
      loading.value = false
    }
  }

  function removeResult(caseId) {
    lastExecutionFailed.value = lastExecutionFailed.value.filter(c => c.case_id !== caseId)
    lastExecutionResults.value = lastExecutionResults.value.filter(r => r.case_id !== caseId)
  }

  function removeResults(caseIds) {
    const ids = new Set(caseIds)
    lastExecutionFailed.value = lastExecutionFailed.value.filter(c => !ids.has(c.case_id))
    lastExecutionResults.value = lastExecutionResults.value.filter(r => !ids.has(r.case_id))
  }

  // Auto-fetch when taskId changes
  if (taskIdRef) {
    onMounted(() => { fetchLatestFailed() })
    watch(taskIdRef, () => { fetchLatestFailed() }, { immediate: true })
  }

  return {
    lastExecutionFailed,
    lastExecutionResults,
    lastExecutionSummary,
    loading,
    failedCount,
    hasFailed,
    executionResultMap,
    fetchLatestFailed,
    removeResult,
    removeResults,
  }
}
