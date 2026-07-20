<template>
  <div class="execution-page">
    <WorkspaceRequired v-if="auth.role !== 'admin' && !wsStore.currentId" />
    <template v-else>
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>测试执行</span>
          <div style="display:flex;align-items:center;gap:8px;">
            <el-tooltip :content="wsConnected ? 'WebSocket 已连接' : 'WebSocket 未连接，正在重试...'" placement="bottom">
              <span class="ws-dot" :class="wsConnected ? 'ws-on' : 'ws-off'"></span>
            </el-tooltip>
            <el-select v-model="selectedTaskId" placeholder="选择任务" style="width: 200px;" @change="onTaskChange">
              <el-option v-for="task in taskStore.tasks" :key="task.id" :label="task.name" :value="task.id" />
            </el-select>
            <el-select v-model="selectedBrowser" style="width: 120px;">
              <el-option label="Chromium" value="chromium" />
              <el-option label="Firefox" value="firefox" />
              <el-option label="WebKit" value="webkit" />
            </el-select>
            <el-button type="primary" @click="executeAll" :loading="taskStore.isExecuting" :disabled="!wsConnected && !taskStore.isExecuting">
              <el-icon><VideoPlay /></el-icon>
              执行全部
            </el-button>
          </div>
        </div>
      </template>

      <el-alert
        v-if="autoRunInfo"
        :title="autoRunInfo"
        type="success"
        :closable="true"
        show-icon
        style="margin-bottom: 16px;"
        @close="autoRunInfo = ''"
      />

      <!-- 执行进度面板 -->
      <div v-if="taskStore.isExecuting || liveResults.length > 0" class="progress-panel">
        <div class="progress-header">
          <div class="progress-status-row">
            <span class="status-dot" :class="taskStore.isExecuting ? 'running' : (failedCount > 0 ? 'failed' : 'done')"></span>
            <span class="status-label">
              {{ taskStore.isExecuting ? '执行中' : (failedCount > 0 ? '执行完成（含失败）' : '执行完成') }}
            </span>
            <span class="case-progress-text">已执行 {{ liveResults.length }} / 共 {{ liveTotal }} 个用例</span>
          </div>
          <div class="progress-right">
            <span v-if="elapsedTime !== null" class="elapsed-time">
              <el-icon><Timer /></el-icon> 耗时 {{ elapsedTime }}s
            </span>
            <div class="progress-controls" v-if="taskStore.isExecuting">
              <el-button size="small" type="warning" @click="pauseExecution">
                <el-icon><VideoPause /></el-icon> 暂停
              </el-button>
              <el-button size="small" type="info" @click="resumeExecution">
                <el-icon><VideoPlay /></el-icon> 继续
              </el-button>
              <el-button size="small" type="danger" @click="stopExecution">
                <el-icon><SwitchButton /></el-icon> 停止
              </el-button>
            </div>
          </div>
        </div>

        <el-progress
          :percentage="progressPercentage"
          :status="progressStatus"
          :stroke-width="18"
          :striped="taskStore.isExecuting"
          :striped-flow="taskStore.isExecuting"
          :duration="5"
          style="margin: 12px 0 8px;"
        />

        <div v-if="taskStore.isExecuting && currentCaseName" class="current-case-bar">
          <el-icon class="spin-icon"><Loading /></el-icon>
          <span>正在执行：<strong>{{ currentCaseName }}</strong></span>
        </div>

        <div class="progress-mini-stats">
          <div class="mini-stat total-stat">
            <span class="mini-val">{{ liveTotal }}</span>
            <span class="mini-lbl">总计</span>
          </div>
          <div class="mini-stat passed-stat">
            <span class="mini-val">{{ passedCount }}</span>
            <span class="mini-lbl">通过</span>
          </div>
          <div class="mini-stat failed-stat">
            <span class="mini-val">{{ failedCount }}</span>
            <span class="mini-lbl">失败</span>
          </div>
          <div class="mini-stat rate-stat">
            <span class="mini-val">{{ passRate }}%</span>
            <span class="mini-lbl">通过率</span>
          </div>
        </div>
      </div>

      <div class="command-input">
        <el-input
          v-model="commandInput"
          placeholder="输入自然语言指令控制测试，如：执行全部用例、暂停、继续、停止、重试失败用例"
          @keyup.enter="sendCommand"
        >
          <template #append>
            <el-button @click="sendCommand" :disabled="!commandInput.trim()">发送</el-button>
          </template>
        </el-input>
        <div class="command-hints">
          <el-tag size="small" @click="commandInput = '执行全部用例'">执行全部用例</el-tag>
          <el-tag size="small" @click="commandInput = '重新运行失败用例'">重试失败用例</el-tag>
          <el-tag size="small" @click="commandInput = '暂停当前测试'">暂停</el-tag>
          <el-tag size="small" @click="commandInput = '继续测试'">继续</el-tag>
          <el-tag size="small" @click="commandInput = '停止测试'">停止</el-tag>
          <el-tag size="small" @click="commandInput = '查看报告'">查看报告</el-tag>
        </div>
      </div>

      <el-table :data="liveResults" stripe style="width: 100%; margin-top: 16px;" :height="420">
        <el-table-column prop="case_name" label="用例名称" min-width="150" show-overflow-tooltip />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)">{{ getStatusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="duration" label="耗时(秒)" width="100">
          <template #default="{ row }">
            {{ row.duration ? row.duration.toFixed(2) : '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="error_message" label="错误信息" min-width="200" show-overflow-tooltip />
        <el-table-column prop="screenshot" label="截图" width="100">
          <template #default="{ row }">
            <el-button v-if="row.screenshot_path" size="small" @click="viewScreenshot(row.screenshot_path)">查看</el-button>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="retryCase(row)">重试</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="showScreenshotDialog" title="截图查看" width="800px">
      <img v-if="screenshotUrl" :src="screenshotUrl" style="width: 100%;" />
    </el-dialog>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useTaskStore } from '../stores/task'
import { useWorkspaceStore } from '../stores/workspace'
import { useAuthStore } from '../stores/auth'
import WorkspaceRequired from '../components/WorkspaceRequired.vue'
import { ElMessage } from 'element-plus'

const route = useRoute()
const taskStore = useTaskStore()
const wsStore = useWorkspaceStore()
const auth = useAuthStore()

const selectedTaskId = ref(null)
const selectedBrowser = ref('chromium')
const commandInput = ref('')
const showScreenshotDialog = ref(false)
const screenshotUrl = ref('')
const autoRunInfo = ref('')

// 实时结果列表（WebSocket 逐条追加）
const liveResults = ref([])
const liveTotal = ref(0)
const liveProgress = ref(0)
const currentCaseName = ref('')
const elapsedTime = ref(null)
const wsConnected = ref(false)
let ws = null
let elapsedTimer = null
let startTimestamp = null
let wsReconnectTimer = null
let currentReportId = ref(null)

const passedCount = computed(() => liveResults.value.filter(r => r.status === 'passed').length)
const failedCount = computed(() => liveResults.value.filter(r => r.status === 'failed').length)
const passRate = computed(() => {
  if (!liveResults.value.length) return 0
  return Math.round(passedCount.value / liveResults.value.length * 100)
})

function startElapsedTimer() {
  startTimestamp = Date.now()
  elapsedTime.value = 0
  if (elapsedTimer) clearInterval(elapsedTimer)
  elapsedTimer = setInterval(() => {
    elapsedTime.value = Math.floor((Date.now() - startTimestamp) / 1000)
  }, 1000)
}

function stopElapsedTimer() {
  if (elapsedTimer) {
    clearInterval(elapsedTimer)
    elapsedTimer = null
  }
}

function getWsUrl() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  // 开发时走 vite proxy（端口 8090→8000），生产直接连后端
  const host = import.meta.env.DEV ? location.host : location.host
  return `${proto}://${host}/ws?client_id=execution_${Date.now()}`
}

function connectWS() {
  if (wsReconnectTimer) { clearTimeout(wsReconnectTimer); wsReconnectTimer = null }
  if (ws && ws.readyState < 2) ws.close()

  ws = new WebSocket(getWsUrl())

  ws.onopen = () => { wsConnected.value = true }

  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data)
      if (msg.type === 'case_complete') {
        liveResults.value.push({
          case_id: msg.case_id,
          case_name: msg.case_name,
          status: msg.status,
          duration: msg.duration,
          error_message: msg.error_message || '',
          screenshot_path: msg.screenshot_path || ''
        })
        liveTotal.value = msg.total || liveTotal.value
        liveProgress.value = msg.progress || 0
        currentCaseName.value = msg.case_name || ''
      } else if (msg.type === 'execution_started') {
        liveResults.value = []
        liveTotal.value = msg.total_cases || 0
        liveProgress.value = 0
        currentCaseName.value = ''
        startElapsedTimer()
      } else if (msg.type === 'execution_completed') {
        stopElapsedTimer()
        taskStore.isExecuting = false
        currentCaseName.value = ''
        liveProgress.value = 100
      } else if (msg.type === 'execution_saved') {
        currentReportId.value = msg.report_id
        const s = msg.summary || {}
        ElMessage({
          type: s.failed > 0 ? 'warning' : 'success',
          message: `执行完成：${s.passed ?? '?'} 通过 / ${s.failed ?? '?'} 失败`,
          duration: 4000
        })
      } else if (msg.type === 'execution_error') {
        stopElapsedTimer()
        taskStore.isExecuting = false
        ElMessage.error(`执行出错：${msg.error || '未知错误'}`)
      }
    } catch (_) {}
  }

  ws.onerror = () => {
    wsConnected.value = false
  }

  ws.onclose = () => {
    wsConnected.value = false
    // 执行期间断线则 3 秒后自动重连
    if (taskStore.isExecuting) {
      wsReconnectTimer = setTimeout(connectWS, 3000)
    }
  }
}

const progressPercentage = computed(() => Math.round(liveProgress.value))

const progressStatus = computed(() => {
  if (liveProgress.value >= 100) return failedCount.value > 0 ? 'exception' : 'success'
  return ''
})

const getStatusType = (status) => {
  const types = { passed: 'success', failed: 'danger', skipped: 'warning' }
  return types[status] || 'info'
}

const getStatusText = (status) => {
  const texts = { passed: '通过', failed: '失败', skipped: '跳过' }
  return texts[status] || status
}

const onTaskChange = async (taskId) => {
  if (taskId) {
    await taskStore.fetchCases(taskId)
  }
}

// 用 HTTP 响应结果填充 liveResults（WS 未能实时推送时的兜底）
function applyFallbackResults(data) {
  if (!data?.results?.length) return
  if (liveResults.value.length === 0) {
    liveResults.value = data.results.map(r => ({
      case_id: r.case_id,
      case_name: r.case_name || '',
      status: r.status || 'failed',
      duration: r.duration || 0,
      error_message: r.error_message || '',
      screenshot_path: r.screenshot_path || ''
    }))
    liveTotal.value = data.results.length
    liveProgress.value = 100
  }
}

const executeAll = async () => {
  if (!selectedTaskId.value) {
    ElMessage.warning('请先选择任务')
    return
  }
  liveResults.value = []
  liveProgress.value = 0
  currentCaseName.value = ''
  currentReportId.value = null
  liveTotal.value = taskStore.cases.length
  try {
    const data = await taskStore.executeCases(selectedTaskId.value, null, selectedBrowser.value)
    // 后端已立即返回，执行在后台进行，WS 推送进度
    if (data?.total) liveTotal.value = data.total
    ElMessage.info(`已开始执行 ${data?.total ?? liveTotal.value} 个用例`)
  } catch (error) {
    taskStore.isExecuting = false
    stopElapsedTimer()
    ElMessage.error('执行失败: ' + error.message)
  }
}

const pauseExecution = async () => {
  await taskStore.pauseExecution()
  ElMessage.info('测试已暂停')
}

const resumeExecution = async () => {
  await taskStore.resumeExecution()
  ElMessage.info('测试已继续')
}

const stopExecution = async () => {
  await taskStore.stopExecution()
  ElMessage.info('停止指令已发送')
}

const sendCommand = async () => {
  if (!commandInput.value.trim()) return

  try {
    const result = await taskStore.sendCommand(commandInput.value)
    commandInput.value = ''

    if (result.type === 'report') {
      taskStore.setReportPath(result.report?.html_path)
      ElMessage.success('报告已生成')
    }
  } catch (error) {
    ElMessage.error('命令执行失败: ' + error.message)
  }
}

const retryCase = async (row) => {
  if (!selectedTaskId.value) {
    ElMessage.warning('请先选择任务')
    return
  }
  liveResults.value = []
  liveProgress.value = 0
  currentCaseName.value = ''
  currentReportId.value = null
  liveTotal.value = 1
  try {
    const data = await taskStore.executeCases(selectedTaskId.value, [row.case_id], selectedBrowser.value)
    if (data?.total) liveTotal.value = data.total
    ElMessage.info('重试已开始')
  } catch (error) {
    taskStore.isExecuting = false
    stopElapsedTimer()
    ElMessage.error('重试失败: ' + error.message)
  }
}

const getFullUrl = (path) => {
  if (!path) return ''
  if (path.startsWith('http')) return path
  return path.startsWith('/') ? path : '/' + path
}

const viewScreenshot = (path) => {
  screenshotUrl.value = getFullUrl(path)
  showScreenshotDialog.value = true
}

onMounted(async () => {
  connectWS()
  if (wsStore.initialized) {
    await taskStore.fetchTasks(wsStore.currentId)
  }

  if (route.query.taskId) {
    selectedTaskId.value = parseInt(route.query.taskId)
    await taskStore.fetchCases(selectedTaskId.value)

    // 从用例页面跳转时，自动执行指定用例
    if (route.query.caseIds) {
      const ids = route.query.caseIds.split(',').map(Number)
      autoRunInfo.value = `正在自动执行 ${ids.length} 个用例，进度通过下方面板实时显示...`
      liveResults.value = []
      liveProgress.value = 0
      currentCaseName.value = ''
      currentReportId.value = null
      liveTotal.value = ids.length
      try {
        const data = await taskStore.executeCases(selectedTaskId.value, ids, selectedBrowser.value)
        if (data?.total) liveTotal.value = data.total
      } catch (error) {
        autoRunInfo.value = ''
        taskStore.isExecuting = false
        stopElapsedTimer()
        ElMessage.error('执行失败: ' + error.message)
      }
    }
  }
})

// 切换工作空间时刷新任务列表
watch(() => wsStore.currentId, async (id) => {
  selectedTaskId.value = null
  await taskStore.fetchTasks(id)
})
watch(() => wsStore.initialized, async (ready) => {
  if (ready) await taskStore.fetchTasks(wsStore.currentId)
})

onUnmounted(() => {
  if (wsReconnectTimer) clearTimeout(wsReconnectTimer)
  if (ws) ws.close()
  stopElapsedTimer()
})
</script>

<style scoped>
.execution-page {
  padding: 0;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

/* ===== 进度面板 ===== */
.progress-panel {
  background: #f8faff;
  border: 1px solid #d0e4ff;
  border-radius: 10px;
  padding: 16px 20px;
  margin-bottom: 20px;
}

.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
  flex-wrap: wrap;
  gap: 8px;
}

.progress-status-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-dot.running {
  background: #409eff;
  animation: pulse 1.2s ease-in-out infinite;
}

.status-dot.done {
  background: #67c23a;
}

.status-dot.failed {
  background: #f56c6c;
}

@keyframes pulse {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.5); opacity: 0.6; }
}

.status-label {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
}

.case-progress-text {
  font-size: 13px;
  color: #606266;
  background: #e8f4ff;
  padding: 2px 10px;
  border-radius: 12px;
}

.progress-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.elapsed-time {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: #909399;
}

.progress-controls {
  display: flex;
  gap: 6px;
}

.current-case-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #409eff;
  background: #ecf5ff;
  border-radius: 6px;
  padding: 6px 12px;
  margin-bottom: 10px;
}

.spin-icon {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.progress-mini-stats {
  display: flex;
  gap: 10px;
  margin-top: 12px;
  flex-wrap: wrap;
}

.mini-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 18px;
  border-radius: 8px;
  min-width: 72px;
}

.mini-stat .mini-val {
  font-size: 22px;
  font-weight: bold;
  line-height: 1.2;
}

.mini-stat .mini-lbl {
  font-size: 12px;
  margin-top: 2px;
  opacity: 0.85;
}

.total-stat  { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: #fff; }
.passed-stat { background: linear-gradient(135deg, #52c41a 0%, #73d13d 100%); color: #fff; }
.failed-stat { background: linear-gradient(135deg, #ff4d4f 0%, #ff7875 100%); color: #fff; }
.rate-stat   { background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); color: #fff; }

/* ===== 命令输入 ===== */
.command-input {
  margin-top: 20px;
}

.command-hints {
  margin-top: 10px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.command-hints .el-tag {
  cursor: pointer;
}

.ws-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  display: inline-block;
}
.ws-on  { background: #67c23a; }
.ws-off { background: #f56c6c; animation: pulse 1.2s ease-in-out infinite; }

</style>
