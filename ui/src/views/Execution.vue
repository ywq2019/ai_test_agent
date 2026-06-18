<template>
  <div class="execution-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>测试执行</span>
          <div>
            <el-select v-model="selectedTaskId" placeholder="选择任务" style="width: 200px; margin-right: 10px;" @change="onTaskChange">
              <el-option v-for="task in taskStore.tasks" :key="task.id" :label="task.name" :value="task.id" />
            </el-select>
            <el-select v-model="selectedBrowser" style="width: 120px; margin-right: 10px;">
              <el-option label="Chromium" value="chromium" />
              <el-option label="Firefox" value="firefox" />
              <el-option label="WebKit" value="webkit" />
            </el-select>
            <el-button type="primary" @click="executeAll" :loading="taskStore.isExecuting">
              <el-icon><VideoPlay /></el-icon>
              执行全部
            </el-button>
          </div>
        </div>
      </template>

      <div v-if="taskStore.isExecuting" class="execution-progress">
        <el-progress :percentage="progressPercentage" :status="progressStatus" />
        <div class="progress-info">
          <span>正在执行: {{ taskStore.executionProgress.caseName }}</span>
          <span>{{ taskStore.executionProgress.current }} / {{ taskStore.executionProgress.total }}</span>
        </div>
      </div>

      <div class="execution-controls" v-if="taskStore.isExecuting">
        <el-button type="warning" @click="pauseExecution">
          <el-icon><VideoPause /></el-icon>
          暂停
        </el-button>
        <el-button type="info" @click="resumeExecution">
          <el-icon><VideoPlay /></el-icon>
          继续
        </el-button>
        <el-button type="danger" @click="stopExecution">
          <el-icon><SwitchButton /></el-icon>
          停止
        </el-button>
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

      <el-divider />

      <div class="results-summary">
        <el-row :gutter="20">
          <el-col :span="6">
            <div class="summary-item total">
              <div class="summary-value">{{ taskStore.executionResults.length }}</div>
              <div class="summary-label">总用例数</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="summary-item passed">
              <div class="summary-value">{{ taskStore.passedCount }}</div>
              <div class="summary-label">通过</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="summary-item failed">
              <div class="summary-value">{{ taskStore.failedCount }}</div>
              <div class="summary-label">失败</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="summary-item rate">
              <div class="summary-value">{{ passRate }}%</div>
              <div class="summary-label">通过率</div>
            </div>
          </el-col>
        </el-row>
      </div>

      <el-table :data="taskStore.executionResults" stripe style="width: 100%; margin-top: 20px;" :height="400">
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
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useTaskStore } from '../stores/task'
import { ElMessage } from 'element-plus'

const route = useRoute()
const taskStore = useTaskStore()

const selectedTaskId = ref(null)
const selectedBrowser = ref('chromium')
const commandInput = ref('')
const showScreenshotDialog = ref(false)
const screenshotUrl = ref('')

const progressPercentage = computed(() => {
  const p = taskStore.executionProgress
  if (p.total === 0) return 0
  return Math.round((p.current / p.total) * 100)
})

const progressStatus = computed(() => {
  const p = taskStore.executionProgress
  if (p.current === p.total && p.total > 0) return 'success'
  if (taskStore.failedCount > 0) return 'exception'
  return ''
})

const passRate = computed(() => {
  const total = taskStore.executionResults.length
  if (total === 0) return 0
  return Math.round((taskStore.passedCount / total) * 100)
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

const executeAll = async () => {
  if (!selectedTaskId.value) {
    ElMessage.warning('请先选择任务')
    return
  }

  try {
    await taskStore.executeCases(selectedTaskId.value, null, selectedBrowser.value)
    ElMessage.success('执行完成')
  } catch (error) {
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

  try {
    await taskStore.executeCases(selectedTaskId.value, [row.case_id], selectedBrowser.value)
    ElMessage.success('重试完成')
  } catch (error) {
    ElMessage.error('重试失败: ' + error.message)
  }
}

const viewScreenshot = (path) => {
  screenshotUrl.value = path
  showScreenshotDialog.value = true
}

onMounted(async () => {
  await taskStore.fetchTasks()

  if (route.query.taskId) {
    selectedTaskId.value = parseInt(route.query.taskId)
    await taskStore.fetchCases(selectedTaskId.value)
  }
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

.execution-progress {
  margin-bottom: 20px;
}

.progress-info {
  display: flex;
  justify-content: space-between;
  margin-top: 10px;
  color: #666;
  font-size: 14px;
}

.execution-controls {
  margin-bottom: 20px;
}

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

.results-summary {
  margin-top: 20px;
}

.summary-item {
  padding: 20px;
  border-radius: 8px;
  text-align: center;
}

.summary-item.total { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: #fff; }
.summary-item.passed { background: linear-gradient(135deg, #52c41a 0%, #73d13d 100%); color: #fff; }
.summary-item.failed { background: linear-gradient(135deg, #ff4d4f 0%, #ff7875 100%); color: #fff; }
.summary-item.rate { background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); color: #fff; }

.summary-value {
  font-size: 32px;
  font-weight: bold;
}

.summary-label {
  font-size: 14px;
  margin-top: 4px;
  opacity: 0.9;
}
</style>
