<template>
  <div class="reports-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>测试报告</span>
          <div>
            <el-button type="primary" @click="fetchReports">
              <el-icon><Refresh /></el-icon>
              刷新列表
            </el-button>
            <el-button type="success" @click="exportReport" :disabled="!currentReport">
              <el-icon><Download /></el-icon>
              导出报告
            </el-button>
          </div>
        </div>
      </template>

      <el-row :gutter="20">
        <el-col :span="8">
          <el-card shadow="hover" class="report-list-card">
            <template #header>
              <span>报告列表</span>
            </template>
            <div v-if="reportsList.length === 0" class="empty-list">
              <el-empty description="暂无测试报告" />
            </div>
            <div v-else class="report-list">
              <div
                v-for="r in reportsList"
                :key="r.report_id"
                class="report-item"
                :class="{ active: currentReport && currentReport.report_id === r.report_id }"
                @click="selectReport(r)"
              >
                <div class="report-item-header">
                  <span class="report-name">{{ r.task_name }}</span>
                  <el-tag :type="r.pass_rate >= 80 ? 'success' : r.pass_rate >= 60 ? 'warning' : 'danger'" size="small">
                    {{ r.pass_rate }}%
                  </el-tag>
                </div>
                <div class="report-item-meta">
                  <span>任务ID: {{ r.task_id }}</span>
                  <span>{{ formatDate(r.created_at) }}</span>
                </div>
                <div class="report-item-stats">
                  <span class="stat-item">总: {{ r.total_cases }}</span>
                  <span class="stat-item passed">通过: {{ r.passed }}</span>
                  <span class="stat-item failed">失败: {{ r.failed }}</span>
                </div>
              </div>
            </div>
          </el-card>
        </el-col>

        <el-col :span="16">
          <div v-if="currentReport" class="report-content">
            <el-row :gutter="20" class="summary-cards">
              <el-col :span="6">
                <div class="summary-card total">
                  <div class="card-icon"><el-icon size="32"><Document /></el-icon></div>
                  <div class="card-info">
                    <div class="card-value">{{ currentReport.total_cases }}</div>
                    <div class="card-label">总用例数</div>
                  </div>
                </div>
              </el-col>
              <el-col :span="6">
                <div class="summary-card passed">
                  <div class="card-icon"><el-icon size="32"><CircleCheck /></el-icon></div>
                  <div class="card-info">
                    <div class="card-value">{{ currentReport.passed }}</div>
                    <div class="card-label">通过</div>
                  </div>
                </div>
              </el-col>
              <el-col :span="6">
                <div class="summary-card failed">
                  <div class="card-icon"><el-icon size="32"><CircleClose /></el-icon></div>
                  <div class="card-info">
                    <div class="card-value">{{ currentReport.failed }}</div>
                    <div class="card-label">失败</div>
                  </div>
                </div>
              </el-col>
              <el-col :span="6">
                <div class="summary-card rate">
                  <div class="card-icon"><el-icon size="32"><DataAnalysis /></el-icon></div>
                  <div class="card-info">
                    <div class="card-value">{{ currentReport.pass_rate }}%</div>
                    <div class="card-label">通过率</div>
                  </div>
                </div>
              </el-col>
            </el-row>

            <el-row :gutter="20" style="margin-top: 20px;">
              <el-col :span="12">
                <el-card shadow="hover">
                  <template #header>
                    <span>通过率分布</span>
                  </template>
                  <div ref="pieChartRef" style="height: 300px;"></div>
                </el-card>
              </el-col>
              <el-col :span="12">
                <el-card shadow="hover">
                  <template #header>
                    <span>执行状态统计</span>
                  </template>
                  <div ref="barChartRef" style="height: 300px;"></div>
                </el-card>
              </el-col>
            </el-row>

            <el-card shadow="hover" style="margin-top: 20px;">
              <template #header>
                <span>失败用例详情</span>
              </template>
              <el-table :data="failedCases" stripe style="width: 100%">
                <el-table-column prop="case_name" label="用例名称" min-width="200" />
                <el-table-column prop="error" label="错误信息" min-width="300" show-overflow-tooltip />
                <el-table-column prop="duration" label="耗时(秒)" width="100">
                  <template #default="{ row }">
                    {{ row.duration ? row.duration.toFixed(2) : '-' }}
                  </template>
                </el-table-column>
              </el-table>
              <el-empty v-if="failedCases.length === 0" description="没有失败的用例" />
            </el-card>

            <el-card shadow="hover" style="margin-top: 20px;">
              <template #header>
                <span>用例执行详情</span>
              </template>
              <el-table :data="currentReport.details" stripe style="width: 100%;" :height="400">
                <el-table-column prop="id" label="序号" width="60" />
                <el-table-column prop="case_name" label="用例名称" min-width="200" show-overflow-tooltip />
                <el-table-column prop="status" label="状态" width="80">
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
                <el-table-column label="截图" width="80">
                  <template #default="{ row }">
                    <el-button v-if="row.screenshot" size="small" @click="viewScreenshot(row.screenshot)">查看</el-button>
                    <span v-else>-</span>
                  </template>
                </el-table-column>
              </el-table>
            </el-card>
          </div>

          <el-empty v-else description="请从左侧选择报告查看详情" />
        </el-col>
      </el-row>
    </el-card>

    <el-dialog v-model="showScreenshotDialog" title="截图查看" width="800px">
      <img v-if="screenshotUrl" :src="getFullUrl(screenshotUrl)" style="width: 100%;" />
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useTaskStore } from '../stores/task'
import { reportApi } from '../api'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'

const route = useRoute()
const taskStore = useTaskStore()

const reportsList = ref([])
const currentReport = ref(null)
const pieChartRef = ref(null)
const barChartRef = ref(null)
const showScreenshotDialog = ref(false)
const screenshotUrl = ref('')

const API_BASE = 'http://localhost:4000'

const failedCases = computed(() => {
  if (!currentReport.value || !currentReport.value.details) return []
  return currentReport.value.details.filter(d => d.status === 'failed')
})

const getFullUrl = (path) => {
  if (!path) return ''
  if (path.startsWith('http')) return path
  return API_BASE + path
}

const getStatusType = (status) => {
  const types = { passed: 'success', failed: 'danger', skipped: 'warning' }
  return types[status] || 'info'
}

const getStatusText = (status) => {
  const texts = { passed: '通过', failed: '失败', skipped: '跳过' }
  return texts[status] || status
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  try {
    const d = new Date(dateStr)
    return d.toLocaleString('zh-CN')
  } catch {
    return dateStr
  }
}

const fetchReports = async () => {
  try {
    const data = await reportApi.list()
    reportsList.value = data || []
    if (reportsList.value.length > 0 && !currentReport.value) {
      await selectReport(reportsList.value[0])
    }
  } catch (error) {
    ElMessage.error('获取报告列表失败: ' + error.message)
    reportsList.value = []
  }
}

const selectReport = async (report) => {
  try {
    const data = await reportApi.getById(report.report_id)
    currentReport.value = data
    await nextTick()
    renderCharts()
  } catch (error) {
    ElMessage.error('获取报告详情失败: ' + error.message)
  }
}

const renderCharts = () => {
  if (!currentReport.value) return

  if (pieChartRef.value) {
    const pieChart = echarts.init(pieChartRef.value)
    const pieData = [
      { value: currentReport.value.passed, name: '通过' },
      { value: currentReport.value.failed, name: '失败' },
      { value: currentReport.value.skipped, name: '跳过' }
    ]
    pieChart.setOption({
      tooltip: { trigger: 'item' },
      legend: { bottom: '5%', left: 'center' },
      series: [{
        type: 'pie',
        radius: ['40%', '70%'],
        avoidLabelOverlap: false,
        itemStyle: { borderRadius: 10, borderColor: '#fff', borderWidth: 2 },
        label: { show: true, formatter: '{b}: {c} ({d}%)' },
        data: pieData.map((item, idx) => ({
          value: item.value,
          name: item.name,
          itemStyle: { color: ['#52c41a', '#ff4d4f', '#faad14'][idx] }
        }))
      }]
    })
  }

  if (barChartRef.value) {
    const barChart = echarts.init(barChartRef.value)
    barChart.setOption({
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: ['通过', '失败', '跳过'] },
      yAxis: { type: 'value' },
      series: [{
        type: 'bar',
        data: [
          { value: currentReport.value.passed, itemStyle: { color: '#52c41a' } },
          { value: currentReport.value.failed, itemStyle: { color: '#ff4d4f' } },
          { value: currentReport.value.skipped, itemStyle: { color: '#faad14' } }
        ],
        barWidth: '50%',
        itemStyle: { borderRadius: [4, 4, 0, 0] }
      }]
    })
  }
}

const exportReport = () => {
  if (currentReport.value && currentReport.value.html_path) {
    window.open(getFullUrl(currentReport.value.html_path), '_blank')
  } else {
    ElMessage.warning('报告路径不可用')
  }
}

const viewScreenshot = (path) => {
  screenshotUrl.value = path
  showScreenshotDialog.value = true
}

onMounted(async () => {
  await fetchReports()
  if (route.query.reportId) {
    await selectReport({ report_id: parseInt(route.query.reportId) })
  }
})
</script>

<style scoped>
.reports-page {
  padding: 0;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.report-list-card {
  min-height: 500px;
}

.empty-list {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 300px;
}

.report-list {
  max-height: 600px;
  overflow-y: auto;
}

.report-item {
  padding: 12px;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  margin-bottom: 10px;
  cursor: pointer;
  transition: all 0.3s;
}

.report-item:hover {
  border-color: #409eff;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.15);
}

.report-item.active {
  border-color: #409eff;
  background: #ecf5ff;
}

.report-item-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.report-name {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
}

.report-item-meta {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
}

.report-item-stats {
  display: flex;
  gap: 12px;
  font-size: 12px;
}

.stat-item {
  color: #606266;
}

.stat-item.passed {
  color: #52c41a;
}

.stat-item.failed {
  color: #ff4d4f;
}

.summary-cards .el-col {
  margin-bottom: 10px;
}

.summary-card {
  display: flex;
  align-items: center;
  padding: 20px;
  border-radius: 8px;
  color: #fff;
}

.summary-card.total { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
.summary-card.passed { background: linear-gradient(135deg, #52c41a 0%, #73d13d 100%); }
.summary-card.failed { background: linear-gradient(135deg, #ff4d4f 0%, #ff7875 100%); }
.summary-card.rate { background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }

.card-icon {
  margin-right: 16px;
}

.card-value {
  font-size: 28px;
  font-weight: bold;
}

.card-label {
  font-size: 14px;
  opacity: 0.9;
}
</style>
