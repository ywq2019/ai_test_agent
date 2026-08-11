<template>
  <div class="reports-page">
    <WorkspaceRequired v-if="auth.role !== 'admin' && !wsStore.currentId" />
    <template v-else>
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span class="page-title">测试报告</span>
          <div class="header-actions">
            <el-select v-model="filterTaskId" placeholder="按任务筛选" clearable filterable style="width: 180px;" size="small" @change="onTaskFilter">
              <el-option v-for="t in taskStore.tasks" :key="t.id" :label="t.name" :value="t.id" />
            </el-select>
            <el-button type="primary" size="small" @click="fetchReports">
              <el-icon><Refresh /></el-icon>刷新
            </el-button>
            <el-button type="success" size="small" @click="exportReport" :disabled="!currentReport">
              <el-icon><Download /></el-icon>导出 HTML
            </el-button>
            <el-button type="danger" size="small" :disabled="selectedIds.length === 0" @click="deleteBatch">
              <el-icon><Delete /></el-icon>批量删除{{ selectedIds.length ? '(' + selectedIds.length + ')' : '' }}
            </el-button>
          </div>
        </div>
      </template>

      <el-row :gutter="16">
        <!-- 左侧：报告列表 -->
        <el-col :span="7">
          <div class="report-list-panel">
            <el-empty v-if="reportsList.length === 0" description="暂无测试报告" style="margin-top: 60px;" />
            <div v-else class="report-list">
              <!-- 全选栏 -->
              <div class="report-select-all-bar">
                <el-checkbox
                  :model-value="isAllSelected"
                  :indeterminate="isIndeterminate"
                  @change="toggleSelectAll"
                  size="small"
                >全选（{{ selectedIds.length }}/{{ reportsList.length }}）</el-checkbox>
              </div>
              <div
                v-for="r in reportsList"
                :key="r.report_id"
                class="report-item"
                :class="{ active: currentReport && currentReport.report_id === r.report_id, selected: selectedIds.includes(r.report_id) }"
                @click="selectReport(r)"
              >
                <div class="report-item-top">
                  <el-checkbox
                    :model-value="selectedIds.includes(r.report_id)"
                    @change="toggleSelect(r.report_id)"
                    @click.stop
                    size="small"
                  />
                  <span class="report-name">{{ r.task_name }}</span>
                  <el-tag :type="r.pass_rate >= 80 ? 'success' : r.pass_rate >= 60 ? 'warning' : 'danger'" size="small">
                    {{ r.pass_rate }}%
                  </el-tag>
                </div>
                <div class="report-item-meta">
                  <span title="报告 ID">#{{ r.report_id }}</span>
                  <span>{{ formatDate(r.created_at) }}</span>
                </div>
                <div class="report-item-stats">
                  <span class="stat-item">通过 <b style="color:#67c23a">{{ r.passed }}</b></span>
                  <span class="stat-item">失败 <b style="color:#f56c6c">{{ r.failed }}</b></span>
                  <span class="stat-item">总计 {{ r.total_cases }}</span>
                  <el-button type="danger" link size="small" @click.stop="deleteOne(r)" class="item-delete-btn">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </div>
              </div>
            </div>
          </div>
        </el-col>

        <!-- 右侧：报告详情 -->
        <el-col :span="17">
          <div v-if="currentReport">
            <!-- 摘要卡片 -->
            <el-row :gutter="12" class="summary-cards">
              <el-col :span="6">
                <div class="summary-card total"><div class="sc-val">{{ currentReport.total_cases }}</div><div class="sc-lbl">总用例</div></div>
              </el-col>
              <el-col :span="6">
                <div class="summary-card passed"><div class="sc-val">{{ currentReport.passed }}</div><div class="sc-lbl">通过</div></div>
              </el-col>
              <el-col :span="6">
                <div class="summary-card failed"><div class="sc-val">{{ currentReport.failed }}</div><div class="sc-lbl">失败</div></div>
              </el-col>
              <el-col :span="6">
                <div class="summary-card rate"><div class="sc-val">{{ currentReport.pass_rate }}%</div><div class="sc-lbl">通过率</div></div>
              </el-col>
            </el-row>

            <!-- 执行详情表格（含状态过滤） -->
            <div style="margin-top: 14px;">
              <div class="detail-toolbar">
                <span class="toolbar-title">用例执行详情</span>
                <el-radio-group v-model="detailFilter" size="small">
                  <el-radio-button label="all">全部</el-radio-button>
                  <el-radio-button label="failed">失败</el-radio-button>
                  <el-radio-button label="passed">通过</el-radio-button>
                </el-radio-group>
              </div>
              <el-table :data="filteredDetails" stripe max-height="440" size="small" row-key="id">
                <el-table-column type="expand">
                  <template #default="{ row }">
                    <div v-if="row.steps && row.steps.length" class="step-panel">
                      <div class="step-title">执行步骤（共 {{ row.steps.length }} 步）</div>
                      <div v-for="(s, si) in row.steps" :key="si" class="step-item" :class="{ 'step-fail': !s.passed, 'step-warn': s.warning }">
                        <span class="step-num">{{ si + 1 }}</span>
                        <span class="step-icon">{{ s.passed ? '✅' : '❌' }}</span>
                        <span class="step-action">{{ s.action }}</span>
                        <span class="step-desc">{{
                          s.description ||
                          (s.action === 'navigate' ? s.url :
                           s.action === 'assert_url' || s.action === 'assert_title' ? s.expected :
                           s.selector ? s.selector + (s.value ? ' = ' + s.value : '') :
                           s.value || '-')
                        }}</span>
                        <span class="step-dur">{{ s.duration_ms }}ms</span>
                        <span v-if="s.warning" class="step-msg step-warn-text">⚠ {{ s.warning }}</span>
                        <span v-if="s.error" class="step-msg step-err-text">{{ s.error }}</span>
                      </div>
                    </div>
                    <div v-else class="step-panel" style="color:#909399;text-align:center;padding:12px;">暂无步骤记录</div>
                  </template>
                </el-table-column>
                <el-table-column type="index" label="#" width="45" />
                <el-table-column prop="case_name" label="用例名称" min-width="180" show-overflow-tooltip />
                <el-table-column prop="status" label="状态" width="75" align="center">
                  <template #default="{ row }">
                    <el-tag :type="getStatusType(row.status)" size="small">{{ getStatusText(row.status) }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="duration" label="耗时" width="70" align="center">
                  <template #default="{ row }">{{ row.duration ? row.duration.toFixed(1) + 's' : '-' }}</template>
                </el-table-column>
                <el-table-column prop="error_message" label="错误信息" min-width="200" show-overflow-tooltip>
                  <template #default="{ row }">
                    <span :style="{ color: row.status === 'failed' ? '#f56c6c' : '' }">{{ row.error_message || '-' }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="截图" width="75" align="center">
                  <template #default="{ row }">
                    <el-button v-if="row.screenshot" type="primary" link size="small" @click="viewScreenshot(row.screenshot, row.case_name)">查看</el-button>
                    <span v-else style="color:#c0c4cc;">-</span>
                  </template>
                </el-table-column>
              </el-table>
            </div>

            <!-- 失败用例快捷操作 -->
            <div v-if="failedDetails.length > 0" style="margin-top: 10px;">
              <el-button type="warning" size="small" @click="goToCaseFix">
                <el-icon><MagicStick /></el-icon>去用例管理修正 {{ failedDetails.length }} 条失败用例
              </el-button>
            </div>
          </div>

          <el-empty v-else description="请从左侧选择报告查看详情" style="margin-top: 60px;" />
        </el-col>
      </el-row>
    </el-card>

    <!-- 截图 dialog -->
    <el-dialog v-model="showScreenshotDialog" title="截图" width="820px">
      <div v-if="screenshotTitle" class="screenshot-title-bar">
        <el-icon><Picture /></el-icon>{{ screenshotTitle }}
      </div>
      <img v-if="screenshotUrl" :src="getFullUrl(screenshotUrl)" style="width: 100%; border-radius: 4px;" />
    </el-dialog>

    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useTaskStore } from '../stores/task'
import { useAuthStore } from '../stores/auth'
import { useWorkspaceStore } from '../stores/workspace'
import WorkspaceRequired from '../components/WorkspaceRequired.vue'
import { reportApi } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

const route = useRoute()
const router = useRouter()
const taskStore = useTaskStore()
const wsStore = useWorkspaceStore()
const auth = useAuthStore()

const reportsList = ref([])
const currentReport = ref(null)
const showScreenshotDialog = ref(false)
const screenshotUrl = ref('')
const screenshotTitle = ref('')
const selectedIds = ref([])
const filterTaskId = ref(null)
const detailFilter = ref('all')

// ── 辅助 ──
const getFullUrl = (path) => {
  if (!path) return ''
  if (path.startsWith('http')) return path
  return path.startsWith('/') ? path : '/' + path
}
const getStatusType = (s) => ({ passed: 'success', failed: 'danger', skipped: 'warning' }[s] || 'info')
const getStatusText = (s) => ({ passed: '通过', failed: '失败', skipped: '跳过' }[s] || s)
const formatDate = (d) => {
  if (!d) return '-'
  try { return new Date(d).toLocaleString('zh-CN', { hour12: false }) } catch { return d }
}

// ── 详情过滤 ──
const allDetails = computed(() => {
  if (!currentReport.value) return []
  return Array.isArray(currentReport.value.details) ? currentReport.value.details : []
})
const failedDetails = computed(() => allDetails.value.filter(d => d.status === 'failed'))
const filteredDetails = computed(() => {
  if (detailFilter.value === 'failed') return failedDetails.value
  if (detailFilter.value === 'passed') return allDetails.value.filter(d => d.status === 'passed')
  return allDetails.value
})

// ── 选择 ──
const toggleSelect = (id) => {
  const idx = selectedIds.value.indexOf(id)
  if (idx === -1) selectedIds.value.push(id)
  else selectedIds.value.splice(idx, 1)
}

const isAllSelected = computed(
  () => reportsList.value.length > 0 && selectedIds.value.length === reportsList.value.length
)
const isIndeterminate = computed(
  () => selectedIds.value.length > 0 && selectedIds.value.length < reportsList.value.length
)
const toggleSelectAll = () => {
  if (isAllSelected.value) {
    selectedIds.value = []
  } else {
    selectedIds.value = reportsList.value.map(r => r.report_id)
  }
}

// ── CRUD ──
const fetchReports = async () => {
  try {
    const data = await reportApi.list(wsStore.currentId)
    reportsList.value = data || []
    // 应用任务筛选
    if (filterTaskId.value) {
      reportsList.value = reportsList.value.filter(r => r.task_id === filterTaskId.value)
    }
    if (reportsList.value.length > 0 && !currentReport.value) {
      await selectReport(reportsList.value[0])
    }
  } catch {
    ElMessage.error('获取报告列表失败')
    reportsList.value = []
  }
}

const onTaskFilter = () => {
  currentReport.value = null
  selectedIds.value = []
  fetchReports()
}

const selectReport = async (report) => {
  try {
    const data = await reportApi.getById(report.report_id)
    currentReport.value = data
    detailFilter.value = (data.failed > 0 && data.passed === 0) ? 'failed' : 'all'
  } catch {
    ElMessage.error('获取报告详情失败')
  }
}

const deleteOne = async (report) => {
  try {
    await ElMessageBox.confirm(`删除报告「${report.task_name}」？`, '删除确认', { type: 'warning' })
    await reportApi.delete(report.report_id)
    ElMessage.success('已删除')
    if (currentReport.value?.report_id === report.report_id) currentReport.value = null
    selectedIds.value = selectedIds.value.filter(id => id !== report.report_id)
    fetchReports()
  } catch (e) { /* cancelled */ }
}

const deleteBatch = async () => {
  if (!selectedIds.value.length) return
  try {
    await ElMessageBox.confirm(`删除 ${selectedIds.value.length} 条报告？`, '批量删除', { type: 'warning' })
    await reportApi.deleteBatch(selectedIds.value)
    ElMessage.success(`已删除 ${selectedIds.value.length} 条`)
    if (currentReport.value && selectedIds.value.includes(currentReport.value.report_id)) currentReport.value = null
    selectedIds.value = []
    fetchReports()
  } catch (e) { /* cancelled */ }
}

const exportReport = () => {
  if (!currentReport.value) return
  window.open(`/api/v1/reports/${currentReport.value.report_id}/export`, '_blank')
}

const viewScreenshot = (path, title = '') => {
  screenshotUrl.value = path
  screenshotTitle.value = title
  showScreenshotDialog.value = true
}

const goToCaseFix = () => {
  router.push({ path: '/cases', query: { taskId: currentReport.value?.task_id } })
}

// ── 生命周期 ──
watch(() => wsStore.currentId, () => {
  currentReport.value = null
  selectedIds.value = []
  fetchReports()
})
onMounted(async () => {
  if (wsStore.initialized) await taskStore.fetchTasks(wsStore.currentId)
  await fetchReports()
  if (route.query.reportId) {
    await selectReport({ report_id: parseInt(route.query.reportId) })
  }
})
</script>

<style scoped>
.reports-page { padding: 0; }
.page-title { font-weight: 600; font-size: 16px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.header-actions { display: flex; align-items: center; gap: 8px; }

/* 报告列表 */
.report-list-panel { max-height: 600px; overflow-y: auto; }
.report-select-all-bar {
  padding: 6px 10px 6px 12px;
  background: var(--el-fill-color-light, #f5f7fa);
  border-radius: 6px;
  margin-bottom: 6px;
  font-size: 13px;
  color: #606266;
}
.report-list { display: flex; flex-direction: column; gap: 8px; }
.report-item {
  padding: 10px 12px; border: 1px solid #e0e0e0; border-radius: 6px;
  cursor: pointer; transition: all 0.2s;
}
.report-item:hover { border-color: #409eff; box-shadow: 0 2px 6px rgba(64,158,255,0.12); }
.report-item.active { border-color: #409eff; background: #ecf5ff; }
.report-item.selected { border-color: #f56c6c; background: #fff5f5; }

.report-item-top { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.report-name { font-weight: 600; font-size: 13px; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.report-item-meta { display: flex; justify-content: space-between; font-size: 12px; color: #909399; margin-bottom: 4px; }
.report-item-stats { display: flex; align-items: center; gap: 10px; font-size: 12px; }
.stat-item { color: #606266; }
.item-delete-btn { margin-left: auto; }

/* 摘要卡片 */
.summary-cards { margin-bottom: 6px; }
.summary-card { text-align: center; padding: 14px 8px; border-radius: 8px; color: #fff; }
.sc-val { font-size: 26px; font-weight: bold; line-height: 1.3; }
.sc-lbl { font-size: 12px; opacity: 0.9; margin-top: 2px; }
.summary-card.total { background: linear-gradient(135deg, #667eea, #764ba2); }
.summary-card.passed { background: linear-gradient(135deg, #52c41a, #73d13d); }
.summary-card.failed { background: linear-gradient(135deg, #ff4d4f, #ff7875); }
.summary-card.rate { background: linear-gradient(135deg, #11998e, #38ef7d); }

/* 详情表格 */
.detail-toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.toolbar-title { font-weight: 600; font-size: 14px; }

/* 截图 */
.screenshot-title-bar {
  display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600;
  color: #303133; background: #f5f7fa; border-left: 4px solid #409eff;
  padding: 8px 14px; border-radius: 0 6px 6px 0; margin-bottom: 10px;
}

/* 步骤面板 */
.step-panel { padding: 8px 16px 12px; background: #fafbfc; }
.step-title { font-size: 13px; font-weight: 600; color: #303133; margin-bottom: 8px; border-bottom: 1px solid #e4e7ed; padding-bottom: 6px; }
.step-item {
  display: flex; align-items: center; gap: 10px; padding: 6px 8px; font-size: 12px;
  border-radius: 4px; margin-bottom: 4px; background: #fff; border: 1px solid #ebeef5;
}
.step-item.step-fail { background: #fef0f0; border-color: #fde2e2; }
.step-item.step-warn { background: #fdf6ec; border-color: #faecd8; }
.step-num { width: 20px; height: 20px; border-radius: 50%; background: #e6f0ff; color: #337ecc; display: flex; align-items: center; justify-content: center; font-weight: 600; font-size: 11px; flex-shrink: 0; }
.step-fail .step-num { background: #fde2e2; color: #e05252; }
.step-icon { flex-shrink: 0; }
.step-action {
  font-weight: 600; color: #606266; background: #ecf5ff; padding: 2px 8px; border-radius: 3px;
  font-size: 11px; white-space: nowrap; flex-shrink: 0;
}
.step-fail .step-action { background: #fde2e2; color: #e05252; }
.step-desc { color: #606266; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.step-dur { color: #909399; font-size: 11px; white-space: nowrap; flex-shrink: 0; }
.step-msg { font-size: 11px; word-break: break-all; flex-shrink: 0; max-width: 300px; }
.step-warn-text { color: #e6a23c; }
.step-err-text { color: #f56c6c; }
</style>
