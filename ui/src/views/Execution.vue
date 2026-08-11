<template>
  <div class="execution-page">
    <WorkspaceRequired v-if="auth.role !== 'admin' && !wsStore.currentId" />
    <template v-else>

      <!-- ── 页头 ── -->
      <div class="ex-header">
        <div class="ex-header-left">
          <span class="ex-page-title">测试执行</span>
          <el-tooltip :content="wsConnected ? 'WebSocket 已连接' : 'WebSocket 未连接'">
            <span class="ws-pill" :class="wsConnected ? 'ws-on' : 'ws-off'">
              <span class="ws-dot-inner"></span>
              {{ wsConnected ? '已连接' : '未连接' }}
            </span>
          </el-tooltip>
        </div>
        <div class="ex-header-right">
          <el-select v-model="selectedTaskId" placeholder="选择任务" style="width:190px" @change="onTaskChange">
            <el-option v-for="task in taskStore.tasks" :key="task.id" :label="task.name" :value="task.id" />
          </el-select>
          <el-select v-model="selectedBrowser" style="width:116px">
            <el-option label="Chromium" value="chromium" />
            <el-option label="Firefox"  value="firefox"  />
            <el-option label="WebKit"   value="webkit"   />
          </el-select>
          <el-dropdown trigger="click">
            <el-button :disabled="!selectedTaskId" circle>
              <el-icon><MoreFilled /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="multiBrowserMode = true">
                  <el-icon><Connection /></el-icon>多浏览器并行执行
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button type="primary" @click="executeAll"
            :loading="taskStore.isExecuting" :disabled="!selectedTaskId" class="btn-run">
            <el-icon><VideoPlay /></el-icon>执行全部
          </el-button>
        </div>
      </div>

      <!-- 多浏览器选项条 -->
      <div v-if="multiBrowserMode" class="multi-bar">
        <el-icon style="color:var(--c-accent)"><Connection /></el-icon>
        <span class="multi-bar-label">多浏览器并行：</span>
        <el-checkbox-group v-model="selectedBrowsers" size="small">
          <el-checkbox-button value="chromium">Chromium</el-checkbox-button>
          <el-checkbox-button value="firefox">Firefox</el-checkbox-button>
          <el-checkbox-button value="webkit">WebKit</el-checkbox-button>
        </el-checkbox-group>
        <el-button link @click="multiBrowserMode = false" style="margin-left:auto;color:var(--c-muted)">关闭</el-button>
      </div>

      <!-- ── Tab 主体 ── -->
      <div class="ex-body">
        <!-- Tab 导航 -->
        <div class="ex-tabs-nav">
          <button class="ex-tab-btn" :class="{ active: activeTab === 'live' }"    @click="activeTab = 'live'">
            <span class="tab-dot" :class="taskStore.isExecuting ? 'dot-run' : 'dot-idle'"></span>
            实时执行
          </button>
          <button class="ex-tab-btn" :class="{ active: activeTab === 'history' }" @click="activeTab = 'history'; onTabChange('history')">
            执行历史
          </button>
        </div>

        <!-- ── 实时执行 ── -->
        <div v-show="activeTab === 'live'" class="ex-tab-pane">

          <!-- 进度卡 -->
          <div v-if="taskStore.isExecuting || liveResults.length > 0" class="live-card">

            <!-- 顶行：状态 + 计时 + 控制 -->
            <div class="live-top">
              <div class="live-status-group">
                <span class="live-status-dot"
                  :class="taskStore.isExecuting ? 'run' : failedCount > 0 ? 'fail' : 'pass'"></span>
                <span class="live-status-label">
                  {{ taskStore.isExecuting ? '执行中' : failedCount > 0 ? '完成（含失败）' : '全部通过' }}
                </span>
                <span class="live-progress-chip">{{ liveResults.length }} / {{ liveTotal }}</span>
              </div>
              <div class="live-right">
                <span v-if="elapsedTime !== null" class="live-elapsed">
                  <el-icon><Timer /></el-icon>{{ elapsedTime }}s
                </span>
                <template v-if="taskStore.isExecuting">
                  <el-button size="small" plain @click="pauseExecution">暂停</el-button>
                  <el-button size="small" plain @click="resumeExecution">继续</el-button>
                  <el-button size="small" type="danger" plain @click="stopExecution">停止</el-button>
                </template>
              </div>
            </div>

            <!-- 进度条 -->
            <div class="live-bar-bg">
              <div class="live-bar-fill"
                :class="progressPercentage >= 100 ? (failedCount > 0 ? 'bar-fail' : 'bar-pass') : 'bar-run'"
                :style="{ width: progressPercentage + '%' }"></div>
            </div>

            <!-- 当前步骤 -->
            <div v-if="taskStore.isExecuting" class="live-step-ticker">
              <span class="ticker-spin">
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                  <circle cx="7" cy="7" r="6" stroke="currentColor" stroke-width="1.5" stroke-dasharray="20 18" />
                </svg>
              </span>
              <span class="ticker-case">{{ currentCaseName || '准备中…' }}</span>
              <span v-if="currentStepTotal > 0" class="ticker-badge">{{ currentStepIdx }}/{{ currentStepTotal }}</span>
              <span v-if="currentStepDesc" class="ticker-step">— {{ currentStepDesc }}</span>
            </div>

            <!-- 四格统计 -->
            <div class="live-metrics">
              <div class="metric-cell metric-total">
                <span class="metric-val">{{ liveTotal }}</span>
                <span class="metric-lbl">总计</span>
              </div>
              <div class="metric-cell metric-pass">
                <span class="metric-val">{{ passedCount }}</span>
                <span class="metric-lbl">通过</span>
              </div>
              <div class="metric-cell metric-fail">
                <span class="metric-val">{{ failedCount }}</span>
                <span class="metric-lbl">失败</span>
              </div>
              <div class="metric-cell metric-rate">
                <span class="metric-val">{{ passRate }}<span class="metric-unit">%</span></span>
                <span class="metric-lbl">通过率</span>
              </div>
            </div>
          </div>

          <!-- 空态 -->
          <div v-if="!taskStore.isExecuting && liveResults.length === 0" class="live-empty">
            <svg width="52" height="52" viewBox="0 0 52 52" fill="none">
              <circle cx="26" cy="26" r="24" stroke="var(--c-border)" stroke-width="1.5" stroke-dasharray="4 4"/>
              <polyline points="16,26 22,32 36,18" stroke="var(--c-muted)" stroke-width="2"
                stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <p class="live-empty-title">选择任务后点击「执行全部」</p>
            <p class="live-empty-sub">执行结果将实时显示，也可切换至「执行历史」查看过往报告</p>
          </div>

          <!-- 结果列表 -->
          <div v-if="liveResults.length > 0" class="result-list">
            <div v-for="(row, i) in liveResults" :key="i" class="result-row"
              :class="row.status === 'passed' ? 'row-pass' : row.status === 'failed' ? 'row-fail' : 'row-skip'">
              <span class="rr-status-dot"></span>
              <span class="rr-idx">{{ i + 1 }}</span>
              <span class="rr-name" :title="row.case_name">{{ row.case_name }}</span>
              <span class="rr-tag" :class="'tag-' + row.status">
                {{ { passed:'通过', failed:'失败', skipped:'跳过' }[row.status] || row.status }}
              </span>
              <span class="rr-dur">{{ row.duration ? row.duration.toFixed(1) + 's' : '—' }}</span>
              <span class="rr-err" :title="row.error_message">{{ row.error_message || '' }}</span>
              <span class="rr-actions">
                <el-button v-if="row.screenshot_path" link size="small"
                  @click="viewScreenshot(row.screenshot_path)" style="color:var(--c-accent)">截图</el-button>
                <el-button link size="small" @click="retryCase(row)"
                  :disabled="taskStore.isExecuting" style="color:var(--c-muted)">重试</el-button>
              </span>
            </div>
          </div>

          <div v-if="liveResults.length > 0 && !taskStore.isExecuting" class="live-footer">
            <el-button size="small" @click="executeAll" :disabled="!selectedTaskId">
              <el-icon><RefreshRight /></el-icon>重新执行
            </el-button>
            <el-button v-if="failedCount > 0" size="small" type="warning" plain @click="goToCaseManagement">
              <el-icon><MagicStick /></el-icon>去用例管理修正失败用例
            </el-button>
          </div>
        </div>

        <!-- ── 执行历史 ── -->
        <div v-show="activeTab === 'history'" class="ex-tab-pane">
          <div class="history-toolbar">
            <el-button size="small" @click="fetchHistory" :loading="historyLoading" :disabled="!selectedTaskId">
              <el-icon><Refresh /></el-icon>刷新
            </el-button>
            <el-button size="small" type="danger" plain
              :disabled="historySelected.length === 0" @click="deleteHistoryBatch">
              <el-icon><Delete /></el-icon>
              批量删除{{ historySelected.length ? '(' + historySelected.length + ')' : '' }}
            </el-button>
            <!-- 全选 -->
            <el-checkbox
              v-if="historyList.length > 0"
              :model-value="historySelected.length === historyList.length && historyList.length > 0"
              :indeterminate="historySelected.length > 0 && historySelected.length < historyList.length"
              @change="v => historySelected = v ? historyList.map(r => r.report_id) : []"
              size="small" style="margin-left:4px">
              全选
            </el-checkbox>
            <span v-if="historyList.length" class="history-count">共 {{ historyList.length }} 条</span>
          </div>

          <div v-if="historyList.length === 0 && !historyLoading" class="live-empty">
            <svg width="52" height="52" viewBox="0 0 52 52" fill="none">
              <rect x="10" y="8" width="32" height="36" rx="4" stroke="var(--c-border)" stroke-width="1.5"/>
              <line x1="18" y1="18" x2="34" y2="18" stroke="var(--c-border)" stroke-width="1.5" stroke-linecap="round"/>
              <line x1="18" y1="24" x2="34" y2="24" stroke="var(--c-border)" stroke-width="1.5" stroke-linecap="round"/>
              <line x1="18" y1="30" x2="28" y2="30" stroke="var(--c-border)" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
            <p class="live-empty-title">暂无执行记录</p>
            <p class="live-empty-sub">请先在「实时执行」Tab 运行测试</p>
          </div>

          <!-- 历史卡片网格 -->
          <div v-if="historyList.length > 0" class="history-grid">
            <div v-for="row in historyList" :key="row.report_id"
              class="history-card"
              :class="{ 'hcard-selected': historySelected.includes(row.report_id) }"
              @click="viewHistoryReport(row)">

              <!-- 选择框 -->
              <span class="hcard-check" @click.stop>
                <el-checkbox
                  :model-value="historySelected.includes(row.report_id)"
                  @change="v => {
                    if (v) historySelected.push(row.report_id)
                    else historySelected = historySelected.filter(id => id !== row.report_id)
                  }" size="small"/>
              </span>

              <!-- 环形进度 -->
              <div class="hcard-ring-wrap">
                <svg class="hcard-ring" viewBox="0 0 48 48" width="56" height="56">
                  <circle cx="24" cy="24" r="19" fill="none" stroke="var(--c-border)" stroke-width="3.5"/>
                  <circle cx="24" cy="24" r="19" fill="none"
                    :stroke="row.pass_rate >= 80 ? 'var(--c-pass)' : row.pass_rate >= 50 ? 'var(--c-warn)' : 'var(--c-fail)'"
                    stroke-width="3.5"
                    stroke-linecap="round"
                    :stroke-dasharray="`${row.pass_rate * 1.194} 119.4`"
                    stroke-dashoffset="29.85"
                    style="transition:stroke-dasharray .4s ease"/>
                </svg>
                <span class="hcard-rate-label">{{ row.pass_rate }}<span style="font-size:9px">%</span></span>
              </div>

              <!-- 内容 -->
              <div class="hcard-body">
                <p class="hcard-task">{{ row.task_name }}</p>
                <p class="hcard-time">{{ formatDate(row.created_at) }}</p>
                <div class="hcard-stats">
                  <span class="hstat pass"><span class="hstat-dot"></span>{{ row.passed }} 通过</span>
                  <span class="hstat fail"><span class="hstat-dot"></span>{{ row.failed }} 失败</span>
                  <span class="hstat total">共 {{ row.total_cases }} 条</span>
                </div>
              </div>

              <!-- 操作 -->
              <div class="hcard-actions" @click.stop>
                <el-button link size="small" style="color:var(--c-accent)" @click="viewHistoryReport(row)">查看</el-button>
                <el-button link size="small" style="color:var(--c-muted)" @click="deleteHistoryOne(row)">删除</el-button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 截图弹窗 -->
      <el-dialog v-model="showScreenshotDialog" title="截图" width="820px">
        <img v-if="screenshotUrl" :src="screenshotUrl" style="width:100%;border-radius:6px" />
      </el-dialog>

    </template>
  </div>
</template>

<script setup>
defineOptions({ name: 'Execution' })
import { ref, computed, onMounted, onUnmounted, onActivated, onDeactivated, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useTaskStore } from '../stores/task'
import { useWorkspaceStore } from '../stores/workspace'
import { useAuthStore } from '../stores/auth'
import WorkspaceRequired from '../components/WorkspaceRequired.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  VideoPause, VideoPlay, Timer,
  RefreshRight, MagicStick, Refresh, Delete, Connection, MoreFilled, DocumentChecked,
} from '@element-plus/icons-vue'
import { useWebSocket } from '../composables/useWebSocket'
import { multiBrowserApi, reportApi, caseApi } from '../api/index'

const route = useRoute()
const router = useRouter()
const taskStore = useTaskStore()
const wsStore = useWorkspaceStore()
const auth = useAuthStore()

// ── 基础状态 ──
const selectedTaskId = ref(null)
const selectedBrowser = ref('chromium')
const multiBrowserMode = ref(false)
const selectedBrowsers = ref(['chromium', 'firefox', 'webkit'])
const activeTab = ref('live')

// ── 实时执行 ──
const liveResults    = ref([])
const liveTotal      = ref(0)
const liveProgress   = ref(0)
const currentCaseName = ref('')
const currentStepDesc = ref('')   // 当前执行步骤描述
const currentStepIdx  = ref(0)    // 当前步骤序号
const currentStepTotal = ref(0)   // 当前用例总步骤数
const elapsedTime    = ref(null)
const wsConnected    = ref(false)
let elapsedTimer     = null
let startTimestamp   = null
let wsReconnectTimer = null
let currentReportId  = ref(null)

const showScreenshotDialog = ref(false)
const screenshotUrl = ref('')

// ── 执行历史 ──
const historyList = ref([])
const historyLoading = ref(false)
const historySelected = ref([])

// ── WebSocket ──
const { connect: _wsConnect, disconnect: _wsDisconnect, isConnected: wsIsConnected } = useWebSocket((msg) => {
  if (msg.type === 'step_start') {
    // 步骤级实时进度
    currentCaseName.value  = msg.case_name || currentCaseName.value
    currentStepDesc.value  = msg.description || msg.action || ''
    currentStepIdx.value   = msg.step_idx   || 0
    currentStepTotal.value = msg.step_total || 0
  } else if (msg.type === 'case_complete') {
    if (currentReportId.value && msg.report_id && msg.report_id !== currentReportId.value) return
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
    currentStepDesc.value = ''   // 用例结束，清空步骤状态
    currentStepIdx.value = 0
  } else if (msg.type === 'execution_started') {
    if (currentReportId.value && msg.report_id && msg.report_id !== currentReportId.value) return
    liveResults.value = []
    liveTotal.value = msg.total_cases || 0
    liveProgress.value = 0
    currentCaseName.value = ''
    currentStepDesc.value = ''
    currentStepIdx.value = 0
    taskStore.isExecuting = true
    startElapsedTimer()
  } else if (msg.type === 'execution_completed') {
    if (currentReportId.value && msg.report_id && msg.report_id !== currentReportId.value) return
    stopElapsedTimer()
    taskStore.isExecuting = false
    currentCaseName.value = ''
    currentStepDesc.value = ''
    currentStepIdx.value = 0
    liveProgress.value = 100
    ElMessage.success('执行完成')
  } else if (msg.type === 'execution_stopped') {
    if (currentReportId.value && msg.report_id && msg.report_id !== currentReportId.value) return
    stopElapsedTimer()
    taskStore.isExecuting = false
    currentCaseName.value = ''
    currentStepDesc.value = ''
    currentStepIdx.value = 0
    const done = msg.executed || 0
    const total = msg.total || 0
    if (done === 0) {
      ElMessage.warning('执行已取消，未执行任何用例')
    } else {
      ElMessage.warning(`执行已停止（已完成 ${done}/${total} 条用例）`)
    }
  } else if (msg.type === 'execution_saved') {
    if (currentReportId.value && msg.report_id && msg.report_id !== currentReportId.value) return
    currentReportId.value = msg.report_id
    const s = msg.summary || {}
    ElMessage({ type: s.failed > 0 ? 'warning' : 'success', message: `${s.passed ?? '?'} 通过 / ${s.failed ?? '?'} 失败` })
  } else if (msg.type === 'execution_error') {
    if (currentReportId.value && msg.report_id && msg.report_id !== currentReportId.value) return
    stopElapsedTimer()
    taskStore.isExecuting = false
    ElMessage.error(`执行出错：${msg.error || '未知错误'}`)
  }
})

watch(wsIsConnected, (val) => {
  wsConnected.value = val
  if (!val && taskStore.isExecuting) {
    wsReconnectTimer = setTimeout(connectWS, 3000)
  }
})

// WS client_id 在组件创建时生成一次，断线重连复用同一 ID，保证进度消息不丢失
const STABLE_WS_CLIENT_ID = `execution_${auth.username || 'u'}_${Date.now()}`

function connectWS() {
  if (wsReconnectTimer) { clearTimeout(wsReconnectTimer); wsReconnectTimer = null }
  _wsConnect(STABLE_WS_CLIENT_ID)
}

const passedCount = computed(() => liveResults.value.filter(r => r.status === 'passed').length)
const failedCount = computed(() => liveResults.value.filter(r => r.status === 'failed').length)
const passRate = computed(() => {
  if (!liveResults.value.length) return 0
  return Math.round(passedCount.value / liveResults.value.length * 100)
})

const progressPercentage = computed(() => Math.round(liveProgress.value))
const progressStatus = computed(() => {
  if (liveProgress.value >= 100) return failedCount.value > 0 ? 'exception' : 'success'
  return ''
})

function startElapsedTimer() {
  startTimestamp = Date.now()
  elapsedTime.value = 0
  if (elapsedTimer) clearInterval(elapsedTimer)
  elapsedTimer = setInterval(() => { elapsedTime.value = Math.floor((Date.now() - startTimestamp) / 1000) }, 1000)
}
function stopElapsedTimer() {
  if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null }
}

const getStatusType = (s) => ({ passed: 'success', failed: 'danger', skipped: 'warning' }[s] || 'info')
const getStatusText = (s) => ({ passed: '通过', failed: '失败', skipped: '跳过' }[s] || s)
const formatDate = (d) => {
  if (!d) return '-'
  try { return new Date(d).toLocaleString('zh-CN', { hour12: false }) } catch { return d }
}

// ── 生命周期 ──
const onTaskChange = async (taskId) => {
  if (taskId) await taskStore.fetchCases(taskId)
  // 切换到执行历史时自动拉取
  if (activeTab.value === 'history') fetchHistory()
}
const onTabChange = (tab) => { if (tab === 'history') fetchHistory() }

// ── 执行全部 ──
const executeAll = async () => {
  if (!selectedTaskId.value) { ElMessage.warning('请选择任务'); return }
  liveResults.value = []
  liveProgress.value = 0
  currentCaseName.value = ''
  currentReportId.value = null
  liveTotal.value = taskStore.cases.length
  activeTab.value = 'live'
  try {
    if (multiBrowserMode.value) {
      if (!selectedBrowsers.value.length) { ElMessage.warning('请至少选择一个浏览器'); return }
      const data = await multiBrowserApi.execute({ task_id: selectedTaskId.value, browsers: selectedBrowsers.value })
      if (data?.total) liveTotal.value = data.total
      if (data?.report_ids) {
        const ids = Object.values(data.report_ids)
        if (ids.length > 0) currentReportId.value = ids[0]
      }
      ElMessage.info(`已开始多浏览器并行执行（${selectedBrowsers.value.join('/')}）`)
    } else {
      const data = await taskStore.executeCases(selectedTaskId.value, null, selectedBrowser.value)
      if (data?.report_id) currentReportId.value = data.report_id
      if (data?.total) liveTotal.value = data.total
      ElMessage.info(`已开始执行 ${data?.total ?? liveTotal.value} 个用例`)
    }
  } catch (error) {
    taskStore.isExecuting = false
    stopElapsedTimer()
    ElMessage.error('执行失败: ' + error.message)
  }
}

const pauseExecution = async () => { await taskStore.pauseExecution(); ElMessage.info('已暂停') }
const resumeExecution = async () => { await taskStore.resumeExecution(); ElMessage.info('已继续') }
const stopExecution = async () => { await taskStore.stopExecution(); ElMessage.info('停止指令已发送') }

const retryCase = async (row) => {
  if (!selectedTaskId.value) return
  liveResults.value = []
  liveProgress.value = 0
  currentCaseName.value = ''
  currentReportId.value = null
  liveTotal.value = 1
  activeTab.value = 'live'
  try {
    const data = await taskStore.executeCases(selectedTaskId.value, [row.case_id], selectedBrowser.value)
    if (data?.report_id) currentReportId.value = data.report_id
    ElMessage.info('重试已开始')
  } catch (error) {
    taskStore.isExecuting = false
    stopElapsedTimer()
    ElMessage.error('重试失败: ' + error.message)
  }
}

const goToCaseManagement = () => {
  router.push({ path: '/cases', query: { taskId: selectedTaskId.value } })
}

const viewScreenshot = (path) => {
  screenshotUrl.value = path.startsWith('/') ? path : '/' + path
  showScreenshotDialog.value = true
}

// ── 执行历史 ──
const fetchHistory = async () => {
  if (!selectedTaskId.value) {
    historyList.value = []
    return
  }
  historyLoading.value = true
  try {
    const data = await reportApi.list(wsStore.currentId, selectedTaskId.value)
    historyList.value = data || []
  } catch (e) {
    ElMessage.error('获取历史记录失败')
    historyList.value = []
  } finally {
    historyLoading.value = false
  }
}

const onHistorySelectionChange = (rows) => { historySelected.value = rows.map(r => r.report_id) }

const deleteHistoryOne = async (row) => {
  try {
    await ElMessageBox.confirm(`删除 ID 为 ${row.report_id} 的执行记录？`, '确认', { type: 'warning' })
    await reportApi.delete(row.report_id)
    ElMessage.success('已删除')
    fetchHistory()
  } catch (e) { /* cancelled */ }
}

const deleteHistoryBatch = async () => {
  if (!historySelected.value.length) return
  try {
    await ElMessageBox.confirm(`删除 ${historySelected.value.length} 条执行记录？`, '批量删除', { type: 'warning' })
    await reportApi.deleteBatch(historySelected.value)
    ElMessage.success(`已删除 ${historySelected.value.length} 条`)
    historySelected.value = []
    fetchHistory()
  } catch (e) { /* cancelled */ }
}

const viewHistoryReport = (row) => {
  router.push({ path: '/reports', query: { reportId: row.report_id } })
}

// ── 生命周期 ──
onMounted(async () => {
  connectWS()
  if (wsStore.initialized) await taskStore.fetchTasks(wsStore.currentId)
  if (route.query.taskId) {
    selectedTaskId.value = parseInt(route.query.taskId)
    await taskStore.fetchCases(selectedTaskId.value)
    if (route.query.caseIds) {
      const ids = route.query.caseIds.split(',').map(Number)
      liveResults.value = []; liveProgress.value = 0; currentCaseName.value = ''; currentReportId.value = null; liveTotal.value = ids.length
      activeTab.value = 'live'
      try {
        const data = await taskStore.executeCases(selectedTaskId.value, ids, selectedBrowser.value)
        if (data?.report_id) currentReportId.value = data.report_id
      } catch { ElMessage.error('自动执行失败') }
    }
  } else if (!selectedTaskId.value && taskStore.tasks.length > 0) {
    // 没有指定任务时默认选第一个，并自动拉取历史
    selectedTaskId.value = taskStore.tasks[0].id
    await taskStore.fetchCases(selectedTaskId.value)
    if (activeTab.value === 'history') fetchHistory()
  }
})

// keep-alive 激活：切回执行页时确保 WS 已连接，计时器已在跑
// 同时处理从 Cases 页 router.push 带来的 taskId / caseIds query 参数
onActivated(async () => {
  if (!wsIsConnected.value) connectWS()
  // 如果正在执行但计时器已停，重新启动
  if (taskStore.isExecuting && !elapsedTimer) {
    startTimestamp = Date.now() - (elapsedTime.value || 0) * 1000
    elapsedTimer = setInterval(() => {
      elapsedTime.value = Math.floor((Date.now() - startTimestamp) / 1000)
    }, 1000)
  }

  // 处理 query 参数（keep-alive 时 onMounted 不再执行，需在此补齐）
  if (route.query.taskId) {
    const queryTaskId = parseInt(route.query.taskId)
    // 任务切换：重新加载用例列表
    if (queryTaskId !== selectedTaskId.value) {
      selectedTaskId.value = queryTaskId
      await taskStore.fetchCases(queryTaskId)
    }
    // 带了 caseIds 说明是从用例列表点「执行」跳来的，自动触发执行
    if (route.query.caseIds) {
      const ids = route.query.caseIds.split(',').map(Number)
      liveResults.value = []; liveProgress.value = 0; currentCaseName.value = ''; currentReportId.value = null; liveTotal.value = ids.length
      activeTab.value = 'live'
      // 清除 caseIds，避免下次切回此页面时重复触发执行；保留 taskId 供页面显示
      router.replace({ query: { taskId: queryTaskId } })
      try {
        const data = await taskStore.executeCases(queryTaskId, ids, selectedBrowser.value)
        if (data?.report_id) currentReportId.value = data.report_id
      } catch { ElMessage.error('自动执行失败') }
    }
  }

  // 切回执行历史 tab 时，若有选中任务则刷新历史列表
  if (activeTab.value === 'history' && selectedTaskId.value && historyList.value.length === 0) {
    fetchHistory()
  }
})

// keep-alive 停用：切走时不断 WS，保留连接接收推送
onDeactivated(() => {
  // 不断开 WS，执行中的消息继续在后台接收
  // 只清掉重连定时器避免重复连接
  if (wsReconnectTimer) { clearTimeout(wsReconnectTimer); wsReconnectTimer = null }
})

watch(() => wsStore.currentId, async (id) => {
  selectedTaskId.value = null
  liveResults.value = []; liveProgress.value = 0; liveTotal.value = 0; currentCaseName.value = ''; currentReportId.value = null
  historyList.value = []; historySelected.value = []
  stopElapsedTimer()
  if (taskStore.isExecuting) taskStore.isExecuting = false
  await taskStore.fetchTasks(id)
  // 切换工作空间后默认选第一个任务并恢复历史
  if (taskStore.tasks.length > 0) {
    selectedTaskId.value = taskStore.tasks[0].id
    if (activeTab.value === 'history') fetchHistory()
  }
})
watch(() => wsStore.initialized, async (ready) => { if (ready) await taskStore.fetchTasks(wsStore.currentId) })

onUnmounted(() => {
  if (wsReconnectTimer) clearTimeout(wsReconnectTimer)
  stopElapsedTimer()
})
</script>

<style scoped>
/* ── 设计令牌 ─────────────────────────────────────────────────── */
:root, .execution-page {
  --c-accent:  #4a80f5;
  --c-pass:    #22c57e;
  --c-fail:    #f05960;
  --c-warn:    #f59e10;
  --c-surface: #ffffff;
  --c-raised:  #f4f6fb;
  --c-border:  #e2e7f0;
  --c-text:    #1a1f2e;
  --c-sub:     #4e5769;
  --c-muted:   #8c95a8;
  --c-accent15: rgba(74,128,245,.12);
  --c-pass12:   rgba(34,197,126,.12);
  --c-fail12:   rgba(240,89,96,.12);
  --c-warn12:   rgba(245,158,16,.12);
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --c-surface: #111827;
    --c-raised:  #1a2336;
    --c-border:  #2a3550;
    --c-text:    #e8edf5;
    --c-sub:     #9daabf;
    --c-muted:   #5a6882;
  }
}
:root[data-theme="dark"] {
  --c-surface: #111827;
  --c-raised:  #1a2336;
  --c-border:  #2a3550;
  --c-text:    #e8edf5;
  --c-sub:     #9daabf;
  --c-muted:   #5a6882;
}

/* ── 页面基底 ──────────────────────────────────────────────────── */
.execution-page {
  padding: 0;
  background: var(--c-surface);
  min-height: 100%;
  color: var(--c-text);
}

/* ── 页头 ──────────────────────────────────────────────────────── */
.ex-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  padding: 16px 20px 12px;
  border-bottom: 1px solid var(--c-border);
  background: var(--c-surface);
}
.ex-header-left  { display: flex; align-items: center; gap: 10px; }
.ex-header-right { display: flex; align-items: center; gap: 8px;  flex-wrap: wrap; }

.ex-page-title {
  font-size: 16px;
  font-weight: 700;
  letter-spacing: -.01em;
  color: var(--c-text);
}

/* WS 连接状态胶囊 */
.ws-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 9px 2px 6px;
  border-radius: 20px;
  letter-spacing: .01em;
}
.ws-on  { background: var(--c-pass12); color: var(--c-pass); }
.ws-off { background: var(--c-fail12); color: var(--c-fail); }
.ws-dot-inner {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
}
.ws-off .ws-dot-inner { animation: dot-pulse 1.2s ease-in-out infinite; }

/* 执行按钮 */
.btn-run { font-weight: 600; }

/* 多浏览器条 */
.multi-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 20px;
  background: var(--c-accent15);
  border-bottom: 1px solid var(--c-border);
  font-size: 13px;
  flex-wrap: wrap;
}
.multi-bar-label { color: var(--c-sub); font-weight: 500; }

/* ── 主体区 ─────────────────────────────────────────────────────── */
.ex-body {
  padding: 0 20px 24px;
  background: var(--c-surface);
}

/* ── 自定义 Tab 导航 ─────────────────────────────────────────────── */
.ex-tabs-nav {
  display: flex;
  gap: 0;
  border-bottom: 2px solid var(--c-border);
  margin-bottom: 20px;
}
.ex-tab-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 12px 18px;
  font-size: 13px;
  font-weight: 500;
  color: var(--c-muted);
  background: none;
  border: none;
  cursor: pointer;
  transition: color .2s;
  outline: none;
}
.ex-tab-btn:hover { color: var(--c-sub); }
.ex-tab-btn.active {
  color: var(--c-accent);
  font-weight: 700;
}
.ex-tab-btn.active::after {
  content: '';
  position: absolute;
  bottom: -2px; left: 12px; right: 12px;
  height: 2px;
  background: var(--c-accent);
  border-radius: 1px;
}

/* 实时执行状态点（tab 上） */
.tab-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.dot-run  { background: var(--c-accent); animation: dot-pulse 1.2s ease-in-out infinite; }
.dot-idle { background: var(--c-border); }

.ex-tab-pane { min-height: 200px; }

/* ── 进度卡 ─────────────────────────────────────────────────────── */
.live-card {
  background: var(--c-raised);
  border: 1px solid var(--c-border);
  border-radius: 12px;
  padding: 16px 20px;
  margin-bottom: 16px;
}

.live-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.live-status-group { display: flex; align-items: center; gap: 8px; }

.live-status-dot {
  width: 10px; height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.live-status-dot.run  { background: var(--c-accent); animation: dot-pulse 1.2s ease-in-out infinite; }
.live-status-dot.pass { background: var(--c-pass); }
.live-status-dot.fail { background: var(--c-fail); }

.live-status-label {
  font-size: 14px;
  font-weight: 700;
  color: var(--c-text);
}
.live-progress-chip {
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  color: var(--c-sub);
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: 20px;
  padding: 1px 10px;
}
.live-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.live-elapsed {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  color: var(--c-muted);
}

/* 进度条 */
.live-bar-bg {
  height: 6px;
  background: var(--c-border);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 12px;
}
.live-bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width .5s cubic-bezier(.4,0,.2,1);
  min-width: 4px;
}
.bar-run  { background: linear-gradient(90deg, var(--c-accent) 0%, #7da8ff 100%);
            background-size: 200% 100%; animation: bar-flow 1.6s linear infinite; }
.bar-pass { background: var(--c-pass); }
.bar-fail { background: var(--c-fail); }

@keyframes bar-flow {
  0%   { background-position: 0 0 }
  100% { background-position: -200% 0 }
}

/* 步骤走马灯 */
.live-step-ticker {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: 8px;
  margin-bottom: 14px;
  font-size: 12.5px;
  min-width: 0;
  overflow: hidden;
}
.ticker-spin {
  color: var(--c-accent);
  flex-shrink: 0;
  animation: spin 1.2s linear infinite;
}
.ticker-case {
  font-weight: 600;
  color: var(--c-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 260px;
}
.ticker-badge {
  flex-shrink: 0;
  font-size: 11px;
  background: var(--c-accent15);
  color: var(--c-accent);
  border-radius: 10px;
  padding: 1px 8px;
  font-variant-numeric: tabular-nums;
  font-weight: 700;
}
.ticker-step {
  color: var(--c-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  min-width: 0;
}

/* 四格统计 */
.live-metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}
@media (max-width: 540px) {
  .live-metrics { grid-template-columns: repeat(2, 1fr); }
}
.metric-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 10px 8px;
  border-radius: 8px;
  border: 1px solid transparent;
}
.metric-val {
  font-size: 22px;
  font-weight: 800;
  line-height: 1.15;
  font-variant-numeric: tabular-nums;
  letter-spacing: -.02em;
}
.metric-unit { font-size: 13px; font-weight: 600; }
.metric-lbl  { font-size: 11px; margin-top: 2px; opacity: .75; letter-spacing: .03em; text-transform: uppercase; }

.metric-total { background: var(--c-raised);   border-color: var(--c-border); color: var(--c-sub); }
.metric-pass  { background: var(--c-pass12);   border-color: rgba(34,197,126,.25); color: var(--c-pass); }
.metric-fail  { background: var(--c-fail12);   border-color: rgba(240,89,96,.25);  color: var(--c-fail); }
.metric-rate  { background: var(--c-accent15); border-color: rgba(74,128,245,.25); color: var(--c-accent); }

/* ── 空态 ─────────────────────────────────────────────────────── */
.live-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  gap: 10px;
  text-align: center;
}
.live-empty-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--c-sub);
  margin: 0;
}
.live-empty-sub {
  font-size: 12.5px;
  color: var(--c-muted);
  margin: 0;
  max-width: 340px;
  line-height: 1.6;
}

/* ── 结果列表 ─────────────────────────────────────────────────── */
.result-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 420px;
  overflow-y: auto;
}
.result-row {
  display: grid;
  grid-template-columns: 6px 32px minmax(0,1fr) 52px 52px minmax(0,1.2fr) auto;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 7px;
  border-left: 3px solid transparent;
  background: var(--c-raised);
  font-size: 12.5px;
  transition: background .15s;
}
.result-row:hover { background: var(--c-border); }

.row-pass { border-left-color: var(--c-pass); }
.row-fail { border-left-color: var(--c-fail); }
.row-skip { border-left-color: var(--c-warn); }

.rr-status-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.row-pass .rr-status-dot { background: var(--c-pass); }
.row-fail .rr-status-dot { background: var(--c-fail); }
.row-skip .rr-status-dot { background: var(--c-warn); }

.rr-idx  { color: var(--c-muted); font-variant-numeric: tabular-nums; font-size: 11px; text-align: right; }
.rr-name { font-weight: 500; color: var(--c-text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rr-dur  { color: var(--c-muted); font-variant-numeric: tabular-nums; text-align: right; font-size: 11.5px; }
.rr-err  { color: var(--c-fail); font-size: 11.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rr-actions { display: flex; gap: 2px; }

.rr-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 10.5px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 4px;
  letter-spacing: .02em;
}
.tag-passed  { background: var(--c-pass12); color: var(--c-pass); }
.tag-failed  { background: var(--c-fail12); color: var(--c-fail); }
.tag-skipped { background: var(--c-warn12); color: var(--c-warn); }

.live-footer {
  display: flex;
  gap: 8px;
  margin-top: 14px;
  flex-wrap: wrap;
}

/* ── 历史工具栏 ──────────────────────────────────────────────── */
.history-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.history-count {
  margin-left: auto;
  font-size: 12.5px;
  color: var(--c-muted);
}

/* ── 历史卡片网格 ─────────────────────────────────────────────── */
.history-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}

.history-card {
  position: relative;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 14px 14px 16px;
  background: var(--c-raised);
  border: 1px solid var(--c-border);
  border-radius: 10px;
  cursor: pointer;
  transition: box-shadow .18s, border-color .18s, transform .18s;
  overflow: hidden;
}
.history-card::before {
  content: '';
  position: absolute;
  left: 0; top: 16px; bottom: 16px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--c-border);
  transition: background .2s;
}
.history-card:hover {
  box-shadow: 0 4px 16px rgba(0,0,0,.08);
  border-color: var(--c-accent);
  transform: translateY(-1px);
}
.history-card:hover::before { background: var(--c-accent); }
.hcard-selected {
  border-color: var(--c-accent);
  background: var(--c-accent15);
}
.hcard-selected::before { background: var(--c-accent); }

.hcard-check {
  position: absolute;
  top: 10px; right: 10px;
}

/* SVG 环形进度 */
.hcard-ring-wrap {
  position: relative;
  flex-shrink: 0;
  width: 56px; height: 56px;
  display: flex; align-items: center; justify-content: center;
}
.hcard-ring { transform: rotate(-90deg); overflow: visible; }
.hcard-rate-label {
  position: absolute;
  font-size: 12px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  color: var(--c-text);
  line-height: 1;
}

.hcard-body {
  flex: 1;
  min-width: 0;
}
.hcard-task {
  font-size: 13px;
  font-weight: 600;
  color: var(--c-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin: 0 0 3px;
  padding-right: 22px; /* 避免和复选框重叠 */
}
.hcard-time {
  font-size: 11.5px;
  color: var(--c-muted);
  margin: 0 0 6px;
  font-variant-numeric: tabular-nums;
}
.hcard-stats {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.hstat {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}
.hstat-dot {
  width: 5px; height: 5px;
  border-radius: 50%;
  flex-shrink: 0;
}
.hstat.pass { color: var(--c-pass); }
.hstat.pass .hstat-dot { background: var(--c-pass); }
.hstat.fail { color: var(--c-fail); }
.hstat.fail .hstat-dot { background: var(--c-fail); }
.hstat.total { color: var(--c-muted); }

.hcard-actions {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex-shrink: 0;
  align-items: flex-end;
  margin-right: 4px;
}

/* ── 动画 ────────────────────────────────────────────────────── */
@keyframes dot-pulse {
  0%, 100% { transform: scale(1);   opacity: 1;   }
  50%       { transform: scale(1.6); opacity: 0.5; }
}
@keyframes spin {
  from { transform: rotate(0deg);   }
  to   { transform: rotate(360deg); }
}
@media (prefers-reduced-motion: reduce) {
  .dot-run, .live-status-dot.run, .ws-off .ws-dot-inner,
  .ticker-spin, .bar-run { animation: none; }
}
</style>
