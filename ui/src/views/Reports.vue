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
              导出 HTML
            </el-button>
            <el-button type="warning" @click="exportPdf" :disabled="!currentReport" :loading="pdfLoading">
              <el-icon><Document /></el-icon>
              导出 PDF
            </el-button>
          </div>
        </div>
      </template>

      <el-row :gutter="20">
        <el-col :span="8">
          <el-card shadow="hover" class="report-list-card">
            <template #header>
              <div class="list-card-header">
                <span>报告列表</span>
                <el-button
                  type="danger"
                  size="small"
                  :disabled="selectedIds.length === 0"
                  @click="deleteBatch"
                >
                  <el-icon><Delete /></el-icon>
                  批量删除{{ selectedIds.length > 0 ? `(${selectedIds.length})` : '' }}
                </el-button>
              </div>
            </template>
            <div v-if="reportsList.length === 0" class="empty-list">
              <el-empty description="暂无测试报告" />
            </div>
            <div v-else class="report-list">
              <div
                v-for="r in reportsList"
                :key="r.report_id"
                class="report-item"
                :class="{ active: currentReport && currentReport.report_id === r.report_id, selected: selectedIds.includes(r.report_id) }"
                @click="selectReport(r)"
              >
                <div class="report-item-header">
                  <div class="report-name-row">
                    <el-checkbox
                      :model-value="selectedIds.includes(r.report_id)"
                      @change="toggleSelect(r.report_id)"
                      @click.stop
                      size="small"
                    />
                    <span class="report-name">{{ r.task_name }}</span>
                  </div>
                  <div class="report-actions">
                    <el-tag :type="r.pass_rate >= 80 ? 'success' : r.pass_rate >= 60 ? 'warning' : 'danger'" size="small">
                      {{ r.pass_rate }}%
                    </el-tag>
                    <el-button
                      type="danger"
                      size="small"
                      link
                      @click.stop="deleteOne(r)"
                    >
                      <el-icon><Delete /></el-icon>
                    </el-button>
                  </div>
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
                <el-table-column prop="error_message" label="错误信息" min-width="260" show-overflow-tooltip />
                <el-table-column prop="duration" label="耗时(秒)" width="100">
                  <template #default="{ row }">
                    {{ row.duration ? row.duration.toFixed(2) : '-' }}
                  </template>
                </el-table-column>
                <el-table-column label="截图" width="80">
                  <template #default="{ row }">
                    <el-button v-if="row.screenshot" size="small" type="danger" plain @click="viewScreenshot(row.screenshot, row.case_name)">查看</el-button>
                    <span v-else style="color:#c0c4cc;">-</span>
                  </template>
                </el-table-column>
              </el-table>
              <el-empty v-if="failedCases.length === 0" description="没有失败的用例" />
            </el-card>

            <el-card shadow="hover" style="margin-top: 20px;">
              <template #header>
                <span>用例执行详情</span>
              </template>
              <el-table :data="Array.isArray(currentReport.details) ? currentReport.details : []" stripe style="width: 100%;" :height="400">
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
                    <el-button v-if="row.screenshot" size="small" :type="row.status === 'failed' ? 'danger' : 'success'" plain @click="viewScreenshot(row.screenshot, row.case_name)">查看</el-button>
                    <span v-else style="color:#c0c4cc;">-</span>
                  </template>
                </el-table-column>
              </el-table>
            </el-card>
          </div>

          <el-empty v-else description="请从左侧选择报告查看详情" />
        </el-col>
      </el-row>
    </el-card>

    <el-dialog v-model="showScreenshotDialog" title="截图查看" width="820px">
      <div v-if="screenshotUrl" class="screenshot-viewer">
        <div v-if="screenshotTitle" class="screenshot-title">
          <el-icon><Picture /></el-icon>
          {{ screenshotTitle }}
        </div>
        <img :src="getFullUrl(screenshotUrl)" style="width: 100%; border-radius: 4px;" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useTaskStore } from '../stores/task'
import { reportApi } from '../api'
import * as echarts from 'echarts'
import { ElMessage, ElMessageBox } from 'element-plus'

const route = useRoute()
const taskStore = useTaskStore()

const reportsList = ref([])
const currentReport = ref(null)
const pieChartRef = ref(null)
const barChartRef = ref(null)
const showScreenshotDialog = ref(false)
const screenshotUrl = ref('')
const screenshotTitle = ref('')
const selectedIds = ref([])
const pdfLoading = ref(false)
let pieChartInstance = null
let barChartInstance = null

const failedCases = computed(() => {
  if (!currentReport.value) return []
  const details = currentReport.value.details
  if (!Array.isArray(details)) return []
  return details.filter(d => d.status === 'failed')
})

const getFullUrl = (path) => {
  if (!path) return ''
  if (path.startsWith('http')) return path
  // 使用相对路径，由 vite proxy 转发到后端 8000
  return path.startsWith('/') ? path : '/' + path
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
    const utc = /[Z+]/.test(dateStr) ? dateStr : dateStr + 'Z'
    return new Date(utc).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return dateStr
  }
}

const toggleSelect = (id) => {
  const idx = selectedIds.value.indexOf(id)
  if (idx === -1) selectedIds.value.push(id)
  else selectedIds.value.splice(idx, 1)
}

const deleteOne = async (report) => {
  try {
    await ElMessageBox.confirm(`确认删除报告「${report.task_name}」？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger'
    })
    await reportApi.delete(report.report_id)
    ElMessage.success('删除成功')
    if (currentReport.value?.report_id === report.report_id) currentReport.value = null
    selectedIds.value = selectedIds.value.filter(id => id !== report.report_id)
    await fetchReports()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('删除失败: ' + e.message)
  }
}

const deleteBatch = async () => {
  if (selectedIds.value.length === 0) return
  try {
    await ElMessageBox.confirm(`确认批量删除 ${selectedIds.value.length} 条报告？此操作不可恢复。`, '批量删除确认', {
      type: 'warning',
      confirmButtonText: '全部删除',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger'
    })
    await reportApi.deleteBatch(selectedIds.value)
    ElMessage.success(`已删除 ${selectedIds.value.length} 条报告`)
    if (currentReport.value && selectedIds.value.includes(currentReport.value.report_id)) {
      currentReport.value = null
    }
    selectedIds.value = []
    await fetchReports()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('批量删除失败: ' + e.message)
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
    if (pieChartInstance) pieChartInstance.dispose()
    pieChartInstance = echarts.init(pieChartRef.value)
    const allPieData = [
      { value: currentReport.value.passed, name: '通过', color: '#52c41a' },
      { value: currentReport.value.failed, name: '失败', color: '#ff4d4f' },
      { value: currentReport.value.skipped, name: '跳过', color: '#faad14' }
    ]
    // 过滤掉 0 值，避免空扇形标签重叠
    const pieData = allPieData.filter(item => item.value > 0)
    pieChartInstance.setOption({
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: { orient: 'horizontal', bottom: 0, left: 'center' },
      series: [{
        type: 'pie',
        radius: ['35%', '60%'],
        center: ['50%', '45%'],
        avoidLabelOverlap: true,
        itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
        label: { show: true, formatter: '{b}\n{c}个 ({d}%)', fontSize: 12 },
        labelLine: { length: 10, length2: 10 },
        data: pieData.map(item => ({
          value: item.value,
          name: item.name,
          itemStyle: { color: item.color }
        }))
      }]
    })
  }

  if (barChartRef.value) {
    if (barChartInstance) barChartInstance.dispose()
    barChartInstance = echarts.init(barChartRef.value)
    barChartInstance.setOption({
      tooltip: { trigger: 'axis' },
      grid: { left: '10%', right: '5%', top: '10%', bottom: '15%' },
      xAxis: { type: 'category', data: ['通过', '失败', '跳过'] },
      yAxis: { type: 'value', minInterval: 1 },
      series: [{
        type: 'bar',
        data: [
          { value: currentReport.value.passed, itemStyle: { color: '#52c41a' } },
          { value: currentReport.value.failed, itemStyle: { color: '#ff4d4f' } },
          { value: currentReport.value.skipped, itemStyle: { color: '#faad14' } }
        ],
        barWidth: '50%',
        itemStyle: { borderRadius: [4, 4, 0, 0] },
        label: { show: true, position: 'top' }
      }]
    })
  }
}

const handleResize = () => {
  pieChartInstance?.resize()
  barChartInstance?.resize()
}

const exportReport = () => {
  if (!currentReport.value) return
  const reportId = currentReport.value.report_id
  // 通过后端 /api/v1/reports/{id}/export 提供下载，避免服务器本地路径 404
  window.open(`/api/v1/reports/${reportId}/export`, '_blank')
}

const exportPdf = async () => {
  if (!currentReport.value) return
  const reportId = currentReport.value.report_id
  pdfLoading.value = true
  try {
    // PDF 由 Playwright 渲染，耗时较长，先提示再打开
    ElMessage.info('正在生成 PDF，请稍候...')
    window.open(`/api/v1/reports/${reportId}/pdf`, '_blank')
  } finally {
    // 延迟关闭 loading，给用户一点视觉反馈
    setTimeout(() => { pdfLoading.value = false }, 2000)
  }
}

const viewScreenshot = (path, title = '') => {
  screenshotUrl.value = path
  screenshotTitle.value = title
  showScreenshotDialog.value = true
}

onMounted(async () => {
  window.addEventListener('resize', handleResize)
  await fetchReports()
  if (route.query.reportId) {
    await selectReport({ report_id: parseInt(route.query.reportId) })
  }
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  pieChartInstance?.dispose()
  barChartInstance?.dispose()
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

.list-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.report-item-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.report-name-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
}

.report-name {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.report-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.report-item.selected {
  border-color: #f56c6c;
  background: #fff5f5;
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

.screenshot-viewer {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.screenshot-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  background: #f5f7fa;
  border-left: 4px solid #409eff;
  padding: 8px 14px;
  border-radius: 0 6px 6px 0;
}

</style>
