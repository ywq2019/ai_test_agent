<template>
  <div class="cases-page">
    <WorkspaceRequired v-if="auth.role !== 'admin' && !wsStore.currentId" />
    <template v-else>
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <div class="header-left">
            <span>测试用例管理</span>
            <el-select v-model="filterTaskId" placeholder="选择任务" style="margin-left: 20px; width: 200px;" @change="fetchCasesByTask">
              <el-option label="全部任务" :value="null" />
              <el-option v-for="task in taskStore.tasks" :key="task.id" :label="task.name" :value="task.id" />
            </el-select>
          </div>
          <div class="header-right">
            <el-button type="primary" @click="showCreateDialog = true">
              <el-icon><Plus /></el-icon>新建用例
            </el-button>
            <el-button-group>
              <el-button type="success" @click="generateCases" :loading="generating" :disabled="!filterTaskId">
                <el-icon><MagicStick /></el-icon>AI生成用例
              </el-button>
              <el-tooltip :content="reparseBeforeGen ? '已开启：生成前重新抓取页面元素（点击关闭）' : '点击开启：生成前重新抓取页面最新元素'" placement="bottom">
                <el-button
                  :type="reparseBeforeGen ? 'success' : 'default'"
                  style="padding: 0 8px;"
                  :disabled="!filterTaskId"
                  @click.stop="reparseBeforeGen = !reparseBeforeGen"
                >
                  <el-icon><RefreshRight /></el-icon>
                  <span style="font-size:11px;margin-left:2px">{{ reparseBeforeGen ? 'ON' : 'OFF' }}</span>
                </el-button>
              </el-tooltip>
            </el-button-group>
            <el-button type="warning" @click="openDocDiffDialog" :disabled="!filterTaskId">
              <el-icon><Refresh /></el-icon>文档变更更新
            </el-button>
            <el-button type="warning" @click="optimizeCases" :loading="optimizing" :disabled="!filterTaskId">
              <el-icon><Cpu /></el-icon>优化用例
            </el-button>
            <el-button type="info" @click="showCoverage" :loading="loadingCoverage" :disabled="!filterTaskId">
              <el-icon><DataAnalysis /></el-icon>覆盖度分析
            </el-button>
            <el-tooltip
              :content="selectedCases.length === 0 ? '请先勾选用例' : `执行选中的 ${selectedCases.length} 个用例`"
              placement="bottom"
            >
              <el-button type="danger" @click="runBatch">
                <el-icon><VideoPlay /></el-icon>
                批量执行{{ selectedCases.length > 0 ? `（${selectedCases.length}）` : '' }}
              </el-button>
            </el-tooltip>
          </div>
        </div>
      </template>

      <el-table ref="tableRef" :data="filteredCases" stripe style="width: 100%" @selection-change="handleSelectionChange">
        <el-table-column type="selection" width="50" />
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="name" label="用例名称" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">
            <span :class="{ 'case-deprecated': row.deprecated }">{{ row.name }}</span>
            <el-tag v-if="row.deprecated" size="small" type="danger" effect="plain" style="margin-left:4px">废弃</el-tag>
            <el-tag v-else-if="row.is_new" size="small" type="success" effect="dark" style="margin-left:4px">NEW</el-tag>
            <el-tag v-else-if="row.is_updated" size="small" type="warning" effect="dark" style="margin-left:4px">更新</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="module" label="模块" width="120" show-overflow-tooltip />
        <el-table-column prop="priority" label="优先级" width="80">
          <template #default="{ row }">
            <el-tag :type="getPriorityType(row.priority)" size="small">{{ row.priority }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="steps" label="测试步骤" min-width="200" show-overflow-tooltip />
        <el-table-column prop="expected_results" label="预期结果" min-width="150" show-overflow-tooltip />
        <el-table-column prop="enabled" label="状态" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.deprecated" type="danger" size="small" effect="plain">已废弃</el-tag>
            <el-tag v-else :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? '启用' : '禁用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="168" fixed="right" align="center">
          <template #default="{ row }">
            <div class="row-actions">
              <el-tooltip content="执行用例" placement="top" :show-after="400">
                <el-button link type="success" size="small" @click="runSingle(row)">
                  <el-icon><VideoPlay /></el-icon>执行
                </el-button>
              </el-tooltip>
              <span class="action-sep"></span>
              <el-tooltip content="编辑用例" placement="top" :show-after="400">
                <el-button link type="primary" size="small" @click="editCase(row)">
                  <el-icon><Edit /></el-icon>编辑
                </el-button>
              </el-tooltip>
              <span class="action-sep"></span>
              <el-tooltip content="删除用例" placement="top" :show-after="400">
                <el-button link type="danger" size="small" @click="deleteCase(row)">
                  <el-icon><Delete /></el-icon>删除
                </el-button>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <div class="batch-actions">
        <el-button @click="toggleAllSelection">{{ isAllSelected ? '取消全选' : '全选' }}</el-button>
        <el-button @click="batchEnable">批量启用</el-button>
        <el-button @click="batchDisable">批量禁用</el-button>
        <el-button type="danger" :loading="batchDeleting" @click="batchDelete">
          {{ batchDeleting ? '删除中...' : '批量删除' }}
        </el-button>
      </div>
    </el-card>

    <!-- 生成/优化进度弹窗 -->
    <el-dialog v-model="showProgress" :title="progressTitle" width="500px" :close-on-click-modal="false" :show-close="false">
      <div class="progress-body">
        <el-progress :percentage="progressPct" :status="progressPct >= 100 ? 'success' : ''" :stroke-width="14" striped striped-flow :duration="10" />
        <p class="progress-stage">{{ progressStage }}</p>
      </div>
    </el-dialog>

    <!-- 覆盖度分析抽屉 -->
    <el-drawer v-model="showCoverageDrawer" title="用例覆盖度分析" size="480px" direction="rtl">
      <div v-if="coverageData" class="coverage-panel">
        <!-- 总评分 -->
        <div class="score-block">
          <el-progress type="dashboard" :percentage="coverageData.score" :color="scoreColor(coverageData.score)" :width="100" />
          <div class="score-meta">
            <div class="score-title">综合评分</div>
            <div class="score-total">共 {{ coverageData.total }} 条用例</div>
          </div>
        </div>

        <el-divider />

        <!-- 优先级分布 -->
        <div class="section-title">优先级分布</div>
        <div class="priority-bars">
          <div v-for="(count, level) in coverageData.priority_distribution" :key="level" class="priority-row">
            <el-tag :type="getPriorityType(level)" size="small" style="width:36px;text-align:center">{{ level }}</el-tag>
            <el-progress :percentage="coverageData.total ? Math.round(count / coverageData.total * 100) : 0"
              :color="priorityColor(level)" style="flex:1;margin:0 10px" :show-text="false" />
            <span class="count-label">{{ count }} 条</span>
          </div>
        </div>

        <el-divider />

        <!-- 模块分布 -->
        <div class="section-title">模块覆盖</div>
        <el-table :data="coverageData.module_distribution" size="small" border style="width:100%">
          <el-table-column prop="name" label="模块" show-overflow-tooltip />
          <el-table-column prop="total" label="总计" width="55" align="center" />
          <el-table-column prop="P0" label="P0" width="45" align="center">
            <template #default="{ row }">
              <span :class="{ 'zero-warn': row.P0 === 0 }">{{ row.P0 }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="P1" label="P1" width="45" align="center" />
          <el-table-column prop="P2" label="P2" width="45" align="center" />
        </el-table>

        <el-divider />

        <!-- 元素覆盖 -->
        <div class="section-title">元素覆盖</div>
        <div class="elem-coverage">
          <el-progress :percentage="coverageData.element_coverage.rate"
            :color="scoreColor(coverageData.element_coverage.rate)"
            :format="() => `${coverageData.element_coverage.rate}%`" />
          <p class="elem-note">{{ coverageData.element_coverage.covered }} / {{ coverageData.element_coverage.total }} 个页面元素有对应用例</p>
        </div>

        <el-divider />

        <!-- 优化建议 -->
        <div class="section-title">优化建议</div>
        <ul class="suggestions">
          <li v-for="(s, i) in coverageData.suggestions" :key="i">{{ s }}</li>
        </ul>
      </div>
      <div v-else class="coverage-empty">
        <el-empty description="暂无数据" />
      </div>
    </el-drawer>

    <!-- 新建/编辑弹窗 -->
    <el-dialog v-model="showCreateDialog" :title="editingCase ? '编辑用例' : '新建用例'" width="700px">
      <el-form :model="caseForm" label-width="100px">
        <el-form-item label="所属任务">
          <el-select v-model="caseForm.task_id" style="width:100%">
            <el-option v-for="task in taskStore.tasks" :key="task.id" :label="task.name" :value="task.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="用例名称">
          <el-input v-model="caseForm.name" placeholder="请输入用例名称" />
        </el-form-item>
        <el-form-item label="所属模块">
          <el-input v-model="caseForm.module" placeholder="请输入所属模块" />
        </el-form-item>
        <el-form-item label="优先级">
          <el-select v-model="caseForm.priority" style="width:100%">
            <el-option label="P0 - 核心必测" value="P0" />
            <el-option label="P1 - 常规测试" value="P1" />
            <el-option label="P2 - 次要场景" value="P2" />
          </el-select>
        </el-form-item>
        <el-form-item label="前置条件">
          <el-input v-model="caseForm.preconditions" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="测试步骤">
          <el-input v-model="caseForm.steps" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="预期结果">
          <el-input v-model="caseForm.expected_results" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="启用状态">
          <el-switch v-model="caseForm.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="saveCase" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- ============================================================
         文档变更 · 增量更新（两步 Dialog）
         ============================================================ -->
    <el-dialog
      v-model="docDiffDialogVisible"
      title="文档变更 · 增量更新"
      width="640px"
      :close-on-click-modal="false"
    >
      <!-- Step 1: 上传新文档 -->
      <div v-if="docDiffStep === 1">
        <el-alert
          title="上传新版需求文档后，AI 将自动对比变更范围，仅对发生变化的模块重新生成用例，未变更模块保留原有用例。"
          type="info"
          show-icon
          :closable="false"
          style="margin-bottom:16px"
        />
        <el-form label-width="80px">
          <el-form-item label="需求来源">
            <el-radio-group v-model="docDiffForm.sourceType">
              <el-radio value="file">上传文档</el-radio>
              <el-radio value="text">手动输入</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item v-if="docDiffForm.sourceType === 'file'" label="新文档">
            <el-upload
              ref="docDiffUploadRef"
              :auto-upload="false"
              :limit="1"
              :on-change="handleDocDiffFileChange"
              :on-remove="() => { docDiffUploadedFile = null; docDiffUploadError = '' }"
              accept=".pdf,.docx,.doc,.xlsx,.xls,.txt,.md,.html,.htm,.csv,.json,.pptx"
              drag
            >
              <el-icon size="40" color="#c0c4cc"><UploadFilled /></el-icon>
              <div style="font-size:14px;color:#606266;margin-top:8px">
                拖拽新版文档到此处，或 <em style="color:#409eff">点击上传</em>
              </div>
            </el-upload>
            <el-alert v-if="docDiffUploadError" :title="docDiffUploadError" type="error" show-icon :closable="false" style="margin-top:8px" />
          </el-form-item>
          <el-form-item v-else label="新文档内容">
            <el-input v-model="docDiffForm.content" type="textarea" :rows="8" placeholder="粘贴新版需求文档内容..." />
          </el-form-item>
          <el-form-item label="页面元素">
            <el-checkbox v-model="docDiffForm.reparseElements">同时重新抓取页面元素（页面 UI 也发生了变化时勾选）</el-checkbox>
          </el-form-item>
        </el-form>
        <div v-if="docDiffChecking" class="progress-body" style="margin-top:12px">
          <el-progress :percentage="50" status="striped" striped striped-flow :duration="4" :show-text="false" />
          <p class="progress-stage">AI 正在对比文档差异，请稍候...</p>
        </div>
      </div>

      <!-- Step 2: Diff 预览 + 确认 -->
      <div v-else-if="docDiffStep === 2 && docDiffResult">
        <el-alert
          :title="docDiffResult.diff_summary || '需求文档已变更'"
          :type="docDiffResult.impact_level === 'high' ? 'error' : docDiffResult.impact_level === 'medium' ? 'warning' : 'info'"
          show-icon
          :closable="false"
          style="margin-bottom:14px"
        />
        <el-row :gutter="12" style="margin-bottom:12px">
          <el-col :span="6">
            <div class="diff-stat-box diff-changed">
              <div class="diff-stat-num">{{ docDiffResult.changed?.length || 0 }}</div>
              <div class="diff-stat-label">变更模块</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="diff-stat-box diff-added">
              <div class="diff-stat-num">{{ docDiffResult.added?.length || 0 }}</div>
              <div class="diff-stat-label">新增模块</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="diff-stat-box diff-removed">
              <div class="diff-stat-num">{{ docDiffResult.removed?.length || 0 }}</div>
              <div class="diff-stat-label">删除模块</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="diff-stat-box diff-unchanged">
              <div class="diff-stat-num">{{ docDiffResult.unchanged?.length || 0 }}</div>
              <div class="diff-stat-label">未变更</div>
            </div>
          </el-col>
        </el-row>

        <el-collapse>
          <el-collapse-item v-if="docDiffResult.changed?.length" name="changed">
            <template #title>
              <el-icon color="#e6a23c"><Warning /></el-icon>
              <span style="margin-left:6px;font-weight:600">变更模块（将重新生成用例）</span>
            </template>
            <div v-for="m in docDiffResult.changed" :key="m.module" class="diff-module-row diff-changed-row">
              <strong>{{ m.module }}</strong>：{{ m.summary }}
            </div>
          </el-collapse-item>
          <el-collapse-item v-if="docDiffResult.added?.length" name="added">
            <template #title>
              <el-icon color="#67c23a"><CircleCheck /></el-icon>
              <span style="margin-left:6px;font-weight:600">新增模块（将生成全新用例）</span>
            </template>
            <div v-for="m in docDiffResult.added" :key="m.module" class="diff-module-row diff-added-row">
              <strong>{{ m.module }}</strong>：{{ m.summary }}
            </div>
          </el-collapse-item>
          <el-collapse-item v-if="docDiffResult.removed?.length" name="removed">
            <template #title>
              <el-icon color="#f56c6c"><CircleClose /></el-icon>
              <span style="margin-left:6px;font-weight:600">删除模块（旧用例将禁用）</span>
            </template>
            <div v-for="name in docDiffResult.removed" :key="name" class="diff-module-row diff-removed-row">{{ name }}</div>
          </el-collapse-item>
          <el-collapse-item v-if="docDiffResult.unchanged?.length" name="unchanged">
            <template #title>
              <el-icon color="#909399"><Document /></el-icon>
              <span style="margin-left:6px;font-weight:600">未变更模块（直接保留）</span>
            </template>
            <div v-for="name in docDiffResult.unchanged" :key="name" class="diff-module-row">{{ name }}</div>
          </el-collapse-item>
        </el-collapse>

        <div v-if="docDiffUpdating" class="progress-body" style="margin-top:14px">
          <el-progress :percentage="progressPct" :stroke-width="10" :show-text="false"
            status="striped" striped striped-flow :duration="6" />
          <p class="progress-stage">{{ progressStage }}</p>
        </div>
      </div>

      <template #footer>
        <template v-if="docDiffStep === 1">
          <el-button @click="docDiffDialogVisible = false" :disabled="docDiffChecking">取消</el-button>
          <el-button type="primary" :loading="docDiffChecking" @click="doDocDiffCheck">
            {{ docDiffChecking ? '分析中...' : '分析变更范围' }}
          </el-button>
        </template>
        <template v-else-if="docDiffStep === 2">
          <el-button @click="docDiffStep = 1" :disabled="docDiffUpdating">重新上传</el-button>
          <el-button @click="docDiffDialogVisible = false" :disabled="docDiffUpdating">取消</el-button>
          <el-button type="warning" :loading="docDiffUpdating" @click="doDocIncrementalUpdate">
            {{ docDiffUpdating ? '更新中...' : '确认增量更新' }}
          </el-button>
        </template>
      </template>
    </el-dialog>
    </template>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useTaskStore } from '../stores/task'
import { useWorkspaceStore } from '../stores/workspace'
import { useAuthStore } from '../stores/auth'
import WorkspaceRequired from '../components/WorkspaceRequired.vue'
import { caseApi, documentApi } from '../api/index'
import { ElMessage, ElMessageBox } from 'element-plus'

const route = useRoute()
const router = useRouter()
const taskStore = useTaskStore()
const wsStore = useWorkspaceStore()
const auth = useAuthStore()

const filterTaskId = ref(null)
const showCreateDialog = ref(false)
const editingCase = ref(null)
const saving = ref(false)
const generating = ref(false)
const optimizing = ref(false)
const loadingCoverage = ref(false)
const batchDeleting = ref(false)
const selectedCases = ref([])
const tableRef = ref(null)

// ── 进度弹窗 ──
const showProgress = ref(false)
const progressTitle = ref('')
const progressPct = ref(0)
const progressStage = ref('')

// ── 覆盖度抽屉 ──
const showCoverageDrawer = ref(false)
const coverageData = ref(null)

// ── 生成用例选项 ──
const reparseBeforeGen = ref(false)

// ── WebSocket ──
let ws = null

const connectWs = (clientId = 'cases_gen') => {
  if (ws && ws.readyState <= 1) ws.close()
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  ws = new WebSocket(`${proto}://${location.host}/ws?client_id=${clientId}`)
  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data)
      // 心跳 ping → 回 pong，防止服务端因超时断开连接
      if (msg.type === 'ping') { ws?.readyState === 1 && ws.send(JSON.stringify({ type: 'pong' })); return }
      if (msg.type === 'cases_gen_progress' || msg.type === 'cases_opt_progress') {
        progressPct.value = msg.percent ?? progressPct.value
        progressStage.value = msg.stage ?? progressStage.value
        if (msg.percent >= 100) {
          setTimeout(() => { showProgress.value = false }, 800)
        }
      }
    } catch {}
  }
  ws.onerror = () => {}
}

const disconnectWs = () => { try { ws?.close() } catch {} ws = null }

onMounted(async () => {
  connectWs('cases_gen')
  if (wsStore.initialized) {
    await taskStore.fetchTasks(wsStore.currentId)
  }
  if (route.query.taskId) {
    filterTaskId.value = parseInt(route.query.taskId)
    caseForm.task_id = filterTaskId.value
  }
  if (filterTaskId.value) await taskStore.fetchCases(filterTaskId.value)
})

// 切换工作空间时刷新任务列表，并清空当前选中的任务
watch(() => wsStore.currentId, async (id) => {
  filterTaskId.value = null
  taskStore.setCases([])
  await taskStore.fetchTasks(id)
})
watch(() => wsStore.initialized, async (ready) => {
  if (ready) await taskStore.fetchTasks(wsStore.currentId)
})

onUnmounted(() => disconnectWs())

const isAllSelected = computed(() =>
  filteredCases.value.length > 0 && selectedCases.value.length === filteredCases.value.length
)

const caseForm = reactive({
  task_id: null, name: '', module: '通用', priority: 'P1',
  preconditions: '', steps: '', expected_results: '', enabled: true
})

const filteredCases = computed(() => {
  if (!filterTaskId.value) return taskStore.cases
  return taskStore.cases.filter(c => c.task_id === filterTaskId.value)
})

const getPriorityType = (p) => ({ P0: 'danger', P1: 'warning', P2: 'info' }[p] || 'info')
const priorityColor = (p) => ({ P0: '#f56c6c', P1: '#e6a23c', P2: '#909399' }[p] || '#909399')
const scoreColor = (s) => s >= 70 ? '#67c23a' : s >= 40 ? '#e6a23c' : '#f56c6c'

const fetchCasesByTask = async () => {
  if (filterTaskId.value) {
    await taskStore.fetchCases(filterTaskId.value)
    await taskStore.getTask(filterTaskId.value)
  }
}

// ── AI 生成用例 ──
const generateCases = async () => {
  if (!filterTaskId.value) { ElMessage.warning('请先选择任务'); return }
  connectWs('cases_gen')
  progressTitle.value = 'AI 生成用例'
  progressPct.value = 0
  progressStage.value = reparseBeforeGen.value ? '正在重新抓取页面元素...' : '正在启动...'
  showProgress.value = true
  generating.value = true
  try {
    await taskStore.generateCases(filterTaskId.value, { reparse_page: reparseBeforeGen.value })
    await taskStore.fetchCases(filterTaskId.value)
    ElMessage.success('用例生成成功')
    taskStore.fetchTotalCaseCount()
  } catch (error) {
    showProgress.value = false
    ElMessage.error('生成失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    generating.value = false
  }
}

// ── 用例优化 ──
const optimizeCases = async () => {
  if (!filterTaskId.value) { ElMessage.warning('请先选择任务'); return }
  if (filteredCases.value.length === 0) { ElMessage.warning('当前任务没有用例，请先生成'); return }

  connectWs('cases_opt')
  progressTitle.value = '用例优化'
  progressPct.value = 0
  progressStage.value = '正在分析覆盖缺口...'
  showProgress.value = true
  optimizing.value = true

  try {
    const res = await caseApi.optimize(filterTaskId.value)
    await taskStore.fetchCases(filterTaskId.value)
    ElMessage.success(res.message || '优化完成')
    taskStore.fetchTotalCaseCount()
  } catch (error) {
    showProgress.value = false
    ElMessage.error('优化失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    optimizing.value = false
    connectWs('cases_gen')
  }
}

// ── 覆盖度分析 ──
const showCoverage = async () => {
  if (!filterTaskId.value) { ElMessage.warning('请先选择任务'); return }
  loadingCoverage.value = true
  try {
    coverageData.value = await caseApi.coverage(filterTaskId.value)
    showCoverageDrawer.value = true
  } catch (error) {
    ElMessage.error('获取覆盖度失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    loadingCoverage.value = false
  }
}

// ── 表格操作 ──
const handleSelectionChange = (sel) => { selectedCases.value = sel }
const toggleAllSelection = () => tableRef.value?.toggleAllSelection()

const batchEnable = async () => {
  if (!selectedCases.value.length) { ElMessage.warning('请先选择用例'); return }
  for (const c of selectedCases.value) await taskStore.updateCase(c.id, { enabled: true })
  ElMessage.success('批量启用成功')
}

const batchDisable = async () => {
  if (!selectedCases.value.length) { ElMessage.warning('请先选择用例'); return }
  for (const c of selectedCases.value) await taskStore.updateCase(c.id, { enabled: false })
  ElMessage.success('批量禁用成功')
}

const batchDelete = async () => {
  if (!selectedCases.value.length) { ElMessage.warning('请先选择用例'); return }
  const count = selectedCases.value.length
  try {
    await ElMessageBox.confirm(`确定要删除选中的 ${count} 个用例吗？此操作不可恢复。`, '批量删除', {
      type: 'warning', confirmButtonText: `删除 ${count} 个`,
      confirmButtonClass: 'el-button--danger', cancelButtonText: '取消'
    })
    batchDeleting.value = true
    await Promise.all(selectedCases.value.map(c => taskStore.deleteCase(c.id)))
    await nextTick()
    ElMessage.success(`已删除 ${count} 个用例`)
    taskStore.fetchTotalCaseCount()
  } catch (err) {
    if (err !== 'cancel') ElMessage.error('删除失败')
  } finally {
    batchDeleting.value = false
  }
}

const runSingle = (row) => {
  if (!row.task_id) { ElMessage.warning('该用例未关联任务，无法执行'); return }
  router.push({ name: 'Execution', query: { taskId: row.task_id, caseIds: String(row.id) } })
}

const runBatch = () => {
  if (!selectedCases.value.length) { ElMessage.warning('请先勾选要执行的用例'); return }
  const taskId = selectedCases.value[0].task_id
  if (!selectedCases.value.every(c => c.task_id === taskId)) {
    ElMessage.warning('批量执行只支持同一任务下的用例，请筛选任务后再选择'); return
  }
  router.push({ name: 'Execution', query: { taskId, caseIds: selectedCases.value.map(c => c.id).join(',') } })
}

const editCase = (row) => {
  editingCase.value = row
  Object.assign(caseForm, {
    task_id: row.task_id, name: row.name, module: row.module,
    priority: row.priority, preconditions: row.preconditions,
    steps: row.steps, expected_results: row.expected_results, enabled: row.enabled
  })
  showCreateDialog.value = true
}

const saveCase = async () => {
  if (!caseForm.name || !caseForm.steps) { ElMessage.warning('请填写用例名称和测试步骤'); return }
  saving.value = true
  try {
    if (editingCase.value) {
      await taskStore.updateCase(editingCase.value.id, caseForm)
      ElMessage.success('更新成功')
    } else {
      await taskStore.createCase(caseForm)
      ElMessage.success('创建成功')
      taskStore.fetchTotalCaseCount()
    }
    showCreateDialog.value = false
    resetForm()
  } catch (error) {
    ElMessage.error('保存失败: ' + error.message)
  } finally {
    saving.value = false
  }
}

const deleteCase = async (row) => {
  try {
    await ElMessageBox.confirm('确定要删除这个用例吗?', '提示', { type: 'warning' })
    await taskStore.deleteCase(row.id)
    ElMessage.success('删除成功')
    taskStore.fetchTotalCaseCount()
  } catch (err) {
    if (err !== 'cancel') ElMessage.error('删除失败')
  }
}

const resetForm = () => {
  caseForm.task_id = filterTaskId.value || null
  caseForm.name = ''; caseForm.module = '通用'; caseForm.priority = 'P1'
  caseForm.preconditions = ''; caseForm.steps = ''; caseForm.expected_results = ''
  caseForm.enabled = true; editingCase.value = null
}

// ══════════════════════════════════════════════════════════════════
// 文档变更 · 增量更新
// ══════════════════════════════════════════════════════════════════
const docDiffDialogVisible = ref(false)
const docDiffStep          = ref(1)
const docDiffChecking      = ref(false)
const docDiffUpdating      = ref(false)
const docDiffResult        = ref(null)
const docDiffUploadRef     = ref(null)
const docDiffUploadedFile  = ref(null)
const docDiffUploadError   = ref('')
const docDiffNewContent    = ref('')   // 保留解析后的文本供后续步骤使用

const docDiffForm = reactive({
  sourceType:      'file',
  content:         '',
  reparseElements: false,
})

const handleDocDiffFileChange = (file) => {
  const maxMB = 20
  const ext = '.' + file.name.split('.').pop().toLowerCase()
  const allowed = new Set(['.pdf','.docx','.doc','.xlsx','.xls','.txt','.md','.html','.htm','.csv','.json','.pptx'])
  if (!allowed.has(ext)) {
    docDiffUploadError.value = `不支持的格式 ${ext}`
    docDiffUploadRef.value?.clearFiles()
    return
  }
  if (file.size > maxMB * 1024 * 1024) {
    docDiffUploadError.value = `文件超过 ${maxMB}MB`
    docDiffUploadRef.value?.clearFiles()
    return
  }
  docDiffUploadError.value = ''
  docDiffUploadedFile.value = file.raw
}

const openDocDiffDialog = () => {
  if (!filterTaskId.value) { ElMessage.warning('请先选择任务'); return }
  docDiffStep.value          = 1
  docDiffResult.value        = null
  docDiffNewContent.value    = ''
  docDiffUploadedFile.value  = null
  docDiffUploadError.value   = ''
  docDiffForm.sourceType     = 'file'
  docDiffForm.content        = ''
  docDiffForm.reparseElements = false
  docDiffDialogVisible.value = true
}

/** Step-1：上传文档并调 diff-check 接口 */
const doDocDiffCheck = async () => {
  let docPath = ''
  let inlineContent = ''

  if (docDiffForm.sourceType === 'file') {
    if (!docDiffUploadedFile.value) { ElMessage.warning('请先上传新版需求文档'); return }
    docDiffChecking.value = true
    try {
      const uploadResult = await documentApi.upload(docDiffUploadedFile.value)
      docPath = uploadResult.file_path || uploadResult.path || ''
    } catch (e) {
      ElMessage.error('文档上传失败: ' + (e.response?.data?.detail || e.message))
      docDiffChecking.value = false
      return
    }
  } else {
    inlineContent = docDiffForm.content
    if (!inlineContent.trim()) { ElMessage.warning('请输入新版需求文档内容'); return }
    docDiffChecking.value = true
  }

  try {
    const res = await caseApi.docDiffCheck(filterTaskId.value, {
      new_document_path: docPath || undefined,
      new_content:       inlineContent || undefined,
    })

    if (!res.has_change) {
      ElMessage.info(res.message || '文档内容未发生变化，无需更新用例')
      docDiffDialogVisible.value = false
      return
    }

    if (!res.diff) {
      ElMessage.warning(res.message || '旧版文档快照未保存，建议直接重新生成用例')
      docDiffDialogVisible.value = false
      return
    }

    // 保存新文档路径/内容备用
    docDiffNewContent.value        = inlineContent || ''
    docDiffForm._uploadedDocPath   = docPath
    docDiffResult.value            = res.diff
    docDiffStep.value              = 2
  } catch (e) {
    ElMessage.error('Diff 分析失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    docDiffChecking.value = false
  }
}

/** Step-2：确认执行增量更新 */
const doDocIncrementalUpdate = async () => {
  if (!docDiffResult.value) return
  docDiffUpdating.value = true
  progressTitle.value   = '文档变更 · 增量更新'
  progressPct.value     = 0
  progressStage.value   = '正在连接 AI...'
  connectWs('cases_gen')

  try {
    const payload = {
      diff:          docDiffResult.value,
      reparse_page:  docDiffForm.reparseElements,
      ...(docDiffForm._uploadedDocPath
        ? { new_document_path: docDiffForm._uploadedDocPath }
        : { new_content: docDiffNewContent.value || docDiffForm.content }),
    }
    const res = await caseApi.incrementalUpdate(filterTaskId.value, payload)
    progressPct.value   = 100
    progressStage.value = res.message || '增量更新完成'
    await new Promise(r => setTimeout(r, 600))
    ElMessage.success(res.message || '增量更新成功')
    docDiffDialogVisible.value = false
    // 刷新用例列表
    await taskStore.fetchCases(filterTaskId.value)
    taskStore.fetchTotalCaseCount()
  } catch (e) {
    ElMessage.error('增量更新失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    docDiffUpdating.value = false
    connectWs('cases_gen')
  }
}
</script>

<style scoped>
.cases-page { padding: 0; }
.card-header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.header-left { display: flex; align-items: center; }
.header-right { display: flex; gap: 8px; flex-wrap: wrap; }
.batch-actions { margin-top: 16px; display: flex; gap: 8px; flex-wrap: wrap; }

/* 操作按钮行 */
.row-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0;
  white-space: nowrap;
}
.row-actions .el-button {
  padding: 2px 6px;
  font-size: 12px;
}
.action-sep {
  display: inline-block;
  width: 1px;
  height: 12px;
  background: #dcdfe6;
  margin: 0 4px;
  flex-shrink: 0;
}

.progress-body { padding: 8px 0 4px; }
.progress-stage { margin: 12px 0 0; text-align: center; color: #606266; font-size: 13px; }

.coverage-panel { padding: 0 4px; }
.score-block { display: flex; align-items: center; gap: 20px; padding: 8px 0; }
.score-meta { display: flex; flex-direction: column; gap: 4px; }
.score-title { font-size: 16px; font-weight: 600; }
.score-total { color: #909399; font-size: 13px; }
.section-title { font-weight: 600; margin: 4px 0 10px; color: #303133; }
.priority-bars { display: flex; flex-direction: column; gap: 8px; }
.priority-row { display: flex; align-items: center; }
.count-label { width: 38px; text-align: right; color: #606266; font-size: 13px; }
.elem-coverage { padding: 4px 0; }
.elem-note { margin: 8px 0 0; color: #909399; font-size: 13px; }
.suggestions { padding-left: 18px; margin: 4px 0; }
.suggestions li { line-height: 1.8; color: #606266; font-size: 13px; }
.zero-warn { color: #f56c6c; font-weight: 600; }
.coverage-empty { display: flex; justify-content: center; align-items: center; height: 200px; }

/* 废弃用例 */
.case-deprecated { text-decoration: line-through; color: #c0c4cc; }

/* Diff 统计卡片 */
.diff-stat-box   { text-align:center; padding:10px 6px; border-radius:8px; border:1px solid transparent; }
.diff-stat-num   { font-size:24px; font-weight:700; }
.diff-stat-label { font-size:12px; margin-top:2px; }
.diff-changed    { background:#fdf6ec; border-color:#f5dab1; color:#e6a23c; }
.diff-added      { background:#f0f9eb; border-color:#b3e19d; color:#67c23a; }
.diff-removed    { background:#fef0f0; border-color:#fbc4c4; color:#f56c6c; }
.diff-unchanged  { background:#f5f7fa; border-color:#dcdfe6; color:#909399; }

/* Diff 模块列表行 */
.diff-module-row         { padding:5px 8px; font-size:13px; border-radius:4px; margin-bottom:4px; }
.diff-changed-row        { background:#fdf6ec; }
.diff-added-row          { background:#f0f9eb; }
.diff-removed-row        { background:#fef0f0; text-decoration:line-through; color:#c0c4cc; }
</style>
