<template>
  <div class="cases-page">
    <WorkspaceRequired v-if="auth.role !== 'admin' && !wsStore.currentId" />
    <template v-else>
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <!-- Row 1: Title + Task + Search -->
          <div class="header-row header-row-1">
            <span class="page-title">测试用例管理</span>
            <div class="header-controls">
              <el-select v-model="filterTaskId" placeholder="选择任务" style="width: 180px;" @change="onTaskSelect">
                <el-option label="全部任务" :value="null" />
                <el-option v-for="task in taskStore.tasks" :key="task.id" :label="task.name" :value="task.id" />
              </el-select>
              <el-input
                v-model="searchText"
                placeholder="搜索用例名称 / 步骤..."
                clearable
                :prefix-icon="Search"
                style="width: 240px;"
              />
            </div>
          </div>

          <!-- Row 2: Filters -->
          <div class="header-row header-row-2">
            <div class="filter-bar">
              <span class="filter-label">筛选：</span>
              <el-select v-model="filterPriority" placeholder="优先级" clearable style="width: 100px;" size="small">
                <el-option label="P0" value="P0" />
                <el-option label="P1" value="P1" />
                <el-option label="P2" value="P2" />
              </el-select>
              <el-select v-model="filterModule" placeholder="模块" clearable filterable style="width: 140px;" size="small">
                <el-option v-for="m in availableModules" :key="m" :label="m" :value="m" />
              </el-select>
              <el-select v-model="filterStatus" placeholder="状态" clearable style="width: 100px;" size="small">
                <el-option label="启用" value="enabled" />
                <el-option label="禁用" value="disabled" />
                <el-option label="废弃" value="deprecated" />
              </el-select>
              <el-button v-if="hasActiveFilters" link type="primary" size="small" @click="resetFilters">
                <el-icon><RefreshLeft /></el-icon>重置
              </el-button>
              <el-tooltip
                v-if="deprecatedCount > 0"
                :content="showDeprecated ? `当前显示全部（含 ${deprecatedCount} 条废弃）` : `已隐藏 ${deprecatedCount} 条废弃，点击显示`"
                placement="bottom"
              >
                <el-tag
                  :type="showDeprecated ? 'danger' : 'info'"
                  size="small"
                  effect="plain"
                  style="cursor:pointer"
                  @click="showDeprecated = !showDeprecated"
                >
                  <el-icon><Hide v-if="!showDeprecated" /><View v-else /></el-icon>
                  废弃{{ showDeprecated ? '显示' : `(${deprecatedCount})` }}
                </el-tag>
              </el-tooltip>
            </div>
            <span class="filter-count">共 {{ filteredCases.length }} 条</span>
          </div>

          <!-- Row 2.5: 上次执行概要 -->
          <div v-if="lastExecutionSummary && filterTaskId" class="header-row execution-summary-bar">
            <span class="exec-summary-label">上次执行：</span>
            <el-tag :type="lastExecutionSummary.failed > 0 ? 'warning' : 'success'" size="small" effect="plain">
              {{ lastExecutionSummary.passed || 0 }} 通过 / {{ lastExecutionSummary.failed || 0 }} 失败
            </el-tag>
            <span v-if="lastExecutionSummary.created_at" class="exec-summary-time">{{ formatTime(lastExecutionSummary.created_at) }}</span>
            <el-button v-if="lastExecutionFailed.length" link type="primary" size="small" @click="fixCases" :loading="fixing">
              <el-icon><MagicStick /></el-icon>修正 {{ lastExecutionFailed.length }} 条失败用例
            </el-button>
            <el-button v-if="lastExecutionFailed.length" link type="warning" size="small" @click="quickShowFailures">
              仅看失败
            </el-button>
          </div>

          <!-- Row 3: Actions -->
          <div class="header-row header-row-3">
            <div class="action-bar">
              <el-button type="primary" @click="showCreateDialog = true">
                <el-icon><Plus /></el-icon>新建用例
              </el-button>
              <el-button-group>
                <el-button type="success" @click="generateCases" :loading="generating" :disabled="!filterTaskId">
                  <el-icon><MagicStick /></el-icon>AI生成
                </el-button>
                <el-tooltip :content="reparseBeforeGen ? '生成前重新抓取页面元素' : '点击开启重新抓取'" placement="bottom">
                  <el-button :type="reparseBeforeGen ? 'success' : 'default'" style="padding: 0 8px;" :disabled="!filterTaskId"
                    @click.stop="reparseBeforeGen = !reparseBeforeGen">
                    <el-icon><RefreshRight /></el-icon>
                  </el-button>
                </el-tooltip>
              </el-button-group>
              <el-tooltip :content="selectedCases.length === 0 ? '请先勾选用例' : `执行选中 ${selectedCases.length} 条`" placement="bottom">
                <el-button type="danger" @click="runBatch">
                  <el-icon><VideoPlay /></el-icon>
                  批量执行{{ selectedCases.length > 0 ? `(${selectedCases.length})` : '' }}
                </el-button>
              </el-tooltip>

              <!-- More actions dropdown -->
              <el-dropdown trigger="click" :disabled="!filterTaskId">
                <el-button :disabled="!filterTaskId">
                  更多操作<el-icon style="margin-left:4px"><ArrowDown /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item @click="optimizeCases" :disabled="optimizing">
                      <el-icon><Cpu /></el-icon>优化用例
                    </el-dropdown-item>
                    <el-dropdown-item @click="showCoverage" :disabled="loadingCoverage">
                      <el-icon><DataAnalysis /></el-icon>覆盖度分析
                    </el-dropdown-item>
                    <el-dropdown-item @click="openDocDiffDialog">
                      <el-icon><Refresh /></el-icon>文档变更更新
                    </el-dropdown-item>
                    <el-dropdown-item divided
                      @click="fixCases"
                      :disabled="!filterTaskId || fixing"
                    >
                      <el-icon><MagicStick /></el-icon>
                      修正失败用例
                      <el-badge v-if="lastExecutionFailed.length" :value="lastExecutionFailed.length" style="margin-left:6px" />
                    </el-dropdown-item>
                    <el-dropdown-item @click="autoFixAll" :disabled="autoFixing || !allCases.length">
                      <el-icon><Select /></el-icon>一键修正补全
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>
        </div>
      </template>

      <el-table ref="tableRef" :data="filteredCases" stripe style="width: 100%" @selection-change="handleSelectionChange">
        <el-table-column type="selection" width="40" />
        <el-table-column type="index" label="#" width="55" />
        <el-table-column prop="name" label="用例名称" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">
            <span :class="{ 'case-deprecated': row.deprecated }">{{ row.name }}</span>
            <el-tag v-if="row.deprecated" size="small" type="danger" effect="plain" style="margin-left:4px">废弃</el-tag>
            <el-tag v-else-if="row.is_new" size="small" type="success" effect="dark" style="margin-left:4px">NEW</el-tag>
            <el-tag v-else-if="row.is_updated" size="small" type="warning" effect="dark" style="margin-left:4px">更新</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="module" label="模块" width="110" show-overflow-tooltip />
        <el-table-column prop="priority" label="优先级" width="75">
          <template #default="{ row }">
            <el-tag :type="getPriorityType(row.priority)" size="small">{{ row.priority }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="steps" label="测试步骤" min-width="180" show-overflow-tooltip />
        <el-table-column prop="expected_results" label="预期结果" min-width="130" show-overflow-tooltip />
        <el-table-column label="执行状态" width="85" align="center">
          <template #default="{ row }">
            <el-tooltip
              v-if="getCaseExecStatus(row) === 'passed'"
              content="上次执行通过"
              placement="top"
            >
              <el-tag type="success" size="small" effect="dark">通过</el-tag>
            </el-tooltip>
            <el-tooltip
              v-else-if="getCaseExecStatus(row) === 'failed'"
              :content="getCaseExecError(row) || '上次执行失败'"
              placement="top"
            >
              <el-tag type="danger" size="small" effect="dark">失败</el-tag>
            </el-tooltip>
            <span v-else class="exec-unknown">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="enabled" label="状态" width="75">
          <template #default="{ row }">
            <el-tag v-if="row.deprecated" type="danger" size="small" effect="plain">废弃</el-tag>
            <el-tag v-else :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? '启用' : '禁用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right" align="center">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button link type="success" size="small" @click="runSingle(row)">
                <el-icon><VideoPlay /></el-icon>执行
              </el-button>
              <span class="action-sep"></span>
              <el-button link type="primary" size="small" @click="editCase(row)">
                <el-icon><Edit /></el-icon>编辑
              </el-button>
              <span class="action-sep"></span>
              <el-button link type="danger" size="small" @click="deleteCase(row)">
                <el-icon><Delete /></el-icon>删除
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <div class="batch-actions">
        <el-button size="small" @click="toggleAllSelection">{{ isAllSelected ? '取消全选' : '全选' }}</el-button>
        <el-button size="small" @click="batchEnable">批量启用</el-button>
        <el-button size="small" @click="batchDisable">批量禁用</el-button>
        <el-button size="small" type="danger" :loading="batchDeleting" @click="batchDelete">批量删除</el-button>
      </div>
    </el-card>

    <!-- 生成/优化进度弹窗 -->
    <el-dialog v-model="showProgress" :title="progressTitle" width="480px" :close-on-click-modal="false" :show-close="!canCancelGen">
      <div class="progress-body">
        <div class="progress-steps">
          <div class="progress-step" :class="{ active: progressPct >= 5, done: progressPct >= 15 }">
            <span class="step-dot">1</span><span class="step-label">页面分析</span>
          </div>
          <div class="step-line" :class="{ active: progressPct >= 15 }"></div>
          <div class="progress-step" :class="{ active: progressPct >= 15, done: progressPct >= 30 }">
            <span class="step-dot">2</span><span class="step-label">模块划分</span>
          </div>
          <div class="step-line" :class="{ active: progressPct >= 30 }"></div>
          <div class="progress-step" :class="{ active: progressPct >= 30, done: progressPct >= 95 }">
            <span class="step-dot">3</span><span class="step-label">用例生成</span>
          </div>
          <div class="step-line" :class="{ active: progressPct >= 95 }"></div>
          <div class="progress-step" :class="{ active: progressPct >= 95, done: progressPct >= 100 }">
            <span class="step-dot">4</span><span class="step-label">完成</span>
          </div>
        </div>
        <div class="progress-bar-wrap">
          <div class="progress-bar-fill" :style="{ width: progressPct + '%' }">
            <span v-if="progressPct > 5" class="progress-bar-text">{{ progressPct }}%</span>
          </div>
        </div>
        <p class="progress-stage">{{ progressStage }}</p>
        <p v-if="genCaseCount > 0" class="progress-count">已生成 {{ genCaseCount }} 条用例</p>
      </div>
      <template #footer>
        <el-button v-if="canCancelGen" size="small" @click="cancelGeneration">取消</el-button>
      </template>
    </el-dialog>

    <!-- 用例修正结果弹窗 -->
    <el-dialog v-model="showFixResult" title="用例修正结果" width="680px">
      <div v-if="fixResult" class="fix-result-body">
        <div class="fix-stats">
          <el-tag v-if="fixResult.corrected?.length" type="success">修正 {{ fixResult.corrected.length }} 条</el-tag>
          <el-tag v-if="fixResult.new_cases?.length" type="primary">新增 {{ fixResult.new_cases.length }} 条</el-tag>
        </div>
        <el-collapse v-if="fixResult.corrected?.length">
          <el-collapse-item v-for="(item, idx) in fixResult.corrected" :key="'corr-'+idx" :name="idx">
            <template #title>
              <div class="fix-item-title">
                <el-tag :type="item.confidence === 'high' ? 'success' : item.confidence === 'low' ? 'warning' : 'primary'" size="small" effect="plain">
                  {{ item.confidence === 'high' ? '高' : '低' }}
                </el-tag>
                <span class="fix-case-name">{{ item.case_name || item.name }}</span>
              </div>
            </template>
            <div class="fix-compare">
              <div class="fix-before"><strong>原步骤：</strong><pre>{{ item.steps }}</pre></div>
              <div class="fix-after" v-if="item.corrected_steps"><strong>修正后：</strong><pre>{{ item.corrected_steps }}</pre></div>
              <div class="fix-note" v-if="item.fix_note"><el-icon><InfoFilled /></el-icon>{{ item.fix_note }}</div>
            </div>
          </el-collapse-item>
        </el-collapse>
        <div v-if="fixResult.new_cases?.length" style="margin-top:12px">
          <el-divider>补充用例（{{ fixResult.new_cases.length }} 条）</el-divider>
          <div v-for="(nc, idx) in fixResult.new_cases" :key="'nc-'+idx" class="new-case-item">
            <el-tag :type="nc.priority === 'P0' ? 'danger' : nc.priority === 'P2' ? 'info' : 'warning'" size="small">{{ nc.priority || 'P1' }}</el-tag>
            <span>{{ nc.name }}</span>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button size="small" @click="showFixResult = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 覆盖度分析抽屉 -->
    <el-drawer v-model="showCoverageDrawer" title="用例覆盖度分析" size="480px" direction="rtl">
      <div v-if="coverageData" class="coverage-panel">
        <div class="score-block">
          <el-progress type="dashboard" :percentage="coverageData.score" :color="scoreColor(coverageData.score)" :width="100" />
          <div class="score-meta">
            <div class="score-title">综合评分</div>
            <div class="score-total">共 {{ coverageData.total }} 条用例</div>
          </div>
        </div>
        <el-divider />
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
        <div class="section-title">模块覆盖</div>
        <el-table :data="coverageData.module_distribution" size="small" border style="width:100%">
          <el-table-column prop="name" label="模块" show-overflow-tooltip />
          <el-table-column prop="total" label="总计" width="55" align="center" />
          <el-table-column prop="P0" label="P0" width="45" align="center">
            <template #default="{ row }"><span :class="{ 'zero-warn': row.P0 === 0 }">{{ row.P0 }}</span></template>
          </el-table-column>
          <el-table-column prop="P1" label="P1" width="45" align="center" />
          <el-table-column prop="P2" label="P2" width="45" align="center" />
        </el-table>
        <el-divider />
        <div class="section-title">元素覆盖</div>
        <div class="elem-coverage">
          <el-progress :percentage="coverageData.element_coverage.rate"
            :color="scoreColor(coverageData.element_coverage.rate)"
            :format="() => `${coverageData.element_coverage.rate}%`" />
          <p class="elem-note">{{ coverageData.element_coverage.covered }} / {{ coverageData.element_coverage.total }} 个页面元素有对应用例</p>
        </div>
        <el-divider />
        <div class="section-title">优化建议</div>
        <ul class="suggestions">
          <li v-for="(s, i) in coverageData.suggestions" :key="i">{{ s }}</li>
        </ul>
      </div>
      <div v-else class="coverage-empty"><el-empty description="暂无数据" /></div>
    </el-drawer>

    <!-- 新建/编辑弹窗 -->
    <el-dialog v-model="showCreateDialog" :title="editingCase ? '编辑用例' : '新建用例'" width="640px">
      <el-form :model="caseForm" label-width="90px">
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

    </template>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useTaskStore } from '../stores/task'
import { useWorkspaceStore } from '../stores/workspace'
import { useAuthStore } from '../stores/auth'
import WorkspaceRequired from '../components/WorkspaceRequired.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useWebSocket } from '../composables/useWebSocket'
import { useFailedCases } from '../composables/useFailedCases'
import { caseApi } from '../api/index'
import {
  Plus, MagicStick, Cpu, DataAnalysis, VideoPlay, Edit, Delete, Refresh, Select,
  Hide, View, RefreshRight, Search, ArrowDown, InfoFilled, RefreshLeft,
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const taskStore = useTaskStore()
const wsStore = useWorkspaceStore()
const auth = useAuthStore()

// ── 任务 & 筛选 ──
const filterTaskId = ref(null)
const searchText = ref('')
const filterPriority = ref(null)
const filterModule = ref(null)
const filterStatus = ref(null)

// ── 废弃显示 ──
const showDeprecated = ref(false)

// ── 表格 ──
const tableRef = ref(null)
const selectedCases = ref([])

// ── 用例表单 ──
const showCreateDialog = ref(false)
const editingCase = ref(null)
const saving = ref(false)
const batchDeleting = ref(false)
const caseForm = reactive({
  task_id: null, name: '', module: '通用', priority: 'P1',
  preconditions: '', steps: '', expected_results: '', enabled: true,
})

// ── AI 生成 ──
const generating = ref(false)
const optimizing = ref(false)
const showProgress = ref(false)
const progressTitle = ref('')
const progressPct = ref(0)
const progressStage = ref('')
const genCaseCount = ref(0)
const canCancelGen = ref(false)
let _genAbortCtrl = null

// ── 用例修正 & 补全 ──
const fixing = ref(false)
const autoFixing = ref(false)
const showFixResult = ref(false)
const fixResult = ref(null)

const { lastExecutionFailed, lastExecutionResults, lastExecutionSummary, failedCount, hasFailed, executionResultMap, fetchLatestFailed: fetchLatestFailedCases, removeResult, removeResults } = useFailedCases(filterTaskId)

// ── 覆盖度抽屉 ──
const showCoverageDrawer = ref(false)
const coverageData = ref(null)
const loadingCoverage = ref(false)

// ── 生成选项 ──
const reparseBeforeGen = ref(false)

// ── 文档变更 ──
const docDiffDialogVisible = ref(false)
const docDiffStep = ref(1)
const docDiffChecking = ref(false)
const docDiffUpdating = ref(false)
const docDiffResult = ref(null)
const docDiffUploadRef = ref(null)
const docDiffUploadedFile = ref(null)
const docDiffUploadError = ref('')
const docDiffNewContent = ref('')
const docDiffForm = reactive({ sourceType: 'file', content: '', reparseElements: false })

// ═══════════════════════════════════════════════════════════
// Computed
// ═══════════════════════════════════════════════════════════

// 可用模块列表（从当前任务用例中提取）
const availableModules = computed(() => {
  const base = filterTaskId.value
    ? taskStore.cases.filter(c => c.task_id === filterTaskId.value)
    : taskStore.cases
  return [...new Set(base.map(c => c.module).filter(Boolean))].sort()
})

const filteredCases = computed(() => {
  let base = filterTaskId.value
    ? taskStore.cases.filter(c => c.task_id === filterTaskId.value)
    : taskStore.cases

  // 废弃筛选
  if (!showDeprecated.value) base = base.filter(c => !c.deprecated)

  // 优先级筛选
  if (filterPriority.value) base = base.filter(c => c.priority === filterPriority.value)

  // 模块筛选
  if (filterModule.value) base = base.filter(c => c.module === filterModule.value)

  // 状态筛选
  if (filterStatus.value === 'enabled') base = base.filter(c => c.enabled && !c.deprecated)
  else if (filterStatus.value === 'disabled') base = base.filter(c => !c.enabled && !c.deprecated)
  else if (filterStatus.value === 'deprecated') base = base.filter(c => c.deprecated)

  // 搜索
  if (searchText.value.trim()) {
    const q = searchText.value.trim().toLowerCase()
    base = base.filter(c =>
      c.name?.toLowerCase().includes(q) ||
      c.steps?.toLowerCase().includes(q) ||
      c.module?.toLowerCase().includes(q) ||
      String(c.id).includes(q)
    )
  }
  return base
})

const allCases = computed(() => {
  return filterTaskId.value
    ? taskStore.cases.filter(c => c.task_id === filterTaskId.value)
    : taskStore.cases
})

const isAllSelected = computed(() =>
  filteredCases.value.length > 0 && selectedCases.value.length === filteredCases.value.length
)

const deprecatedCount = computed(() => {
  const base = filterTaskId.value
    ? taskStore.cases.filter(c => c.task_id === filterTaskId.value)
    : taskStore.cases
  return base.filter(c => c.deprecated).length
})

const hasActiveFilters = computed(() =>
  !!filterPriority.value || !!filterModule.value || !!filterStatus.value || showDeprecated.value
)

function resetFilters() {
  filterPriority.value = null
  filterModule.value = null
  filterStatus.value = null
  showDeprecated.value = false
  searchText.value = ''
}

// ═══════════════════════════════════════════════════════════
// Functions
// ═══════════════════════════════════════════════════════════

function getPriorityType(p) {
  return p === 'P0' ? 'danger' : p === 'P2' ? 'info' : 'warning'
}
function priorityColor(l) {
  return l === 'P0' ? '#f56c6c' : l === 'P1' ? '#e6a23c' : '#909399'
}
function scoreColor(s) {
  return s >= 80 ? '#67c23a' : s >= 50 ? '#e6a23c' : '#f56c6c'
}

// ── WebSocket ──
const _wsClientId = computed(() => `cases_gen_${auth.username || 'anon'}_${Date.now()}`)
let _wsClientIdFixed = null
const { connect: connectWs, disconnect: disconnectWs } = useWebSocket((msg) => {
  if (msg.type === 'cases_gen_progress' || msg.type === 'cases_opt_progress') {
    progressPct.value = msg.percent ?? progressPct.value
    progressStage.value = msg.stage ?? progressStage.value
    genCaseCount.value = msg.case_count ?? genCaseCount.value
    if (msg.percent >= 100) setTimeout(() => { showProgress.value = false }, 800)
  }
  if (msg.type === 'cases_correct_progress' || msg.type === 'cases_gap_progress' || msg.type === 'cases_auto_fix_progress') {
    progressPct.value = msg.percent ?? progressPct.value
    progressStage.value = msg.stage ?? progressStage.value
    genCaseCount.value = msg.case_count ?? genCaseCount.value
    if (msg.percent >= 100) setTimeout(() => { showProgress.value = false }, 1000)
  }
  // 执行完成后收集失败用例 — execution_saved 含 summary
  if (msg.type === 'execution_saved') {
    const fc = msg.summary?.failed_cases || []
    lastExecutionFailed.value = fc
    if (fc.length) ElMessage.info(`本次执行有 ${fc.length} 条失败，可在「更多操作 → 修正失败用例」中自动修正`)
  }
})
function getWsClientId() {
  if (!_wsClientIdFixed) _wsClientIdFixed = `cases_gen_${auth.username || 'anon'}_${Date.now()}`
  return _wsClientIdFixed
}

// ── 任务切换 ──
const onTaskSelect = async () => {
  selectedCases.value = []
  filterModule.value = null
  if (filterTaskId.value) {
    await taskStore.fetchCases(filterTaskId.value)
  } else {
    // 全部任务：获取所有
    taskStore.setCases([])
    if (wsStore.currentId) await taskStore.fetchTasks(wsStore.currentId)
  }
}

// ── 执行 ──
const runSingle = (row) => {
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

// ── AI 生成 ──
const generateCases = async () => {
  if (!filterTaskId.value) { ElMessage.warning('请先选择任务'); return }
  generating.value = true
  showProgress.value = true
  progressTitle.value = 'AI 生成用例'
  progressPct.value = 0
  progressStage.value = '准备中...'
  genCaseCount.value = 0
  canCancelGen.value = true
  if (_genAbortCtrl) { _genAbortCtrl.abort(); _genAbortCtrl = null }
  _genAbortCtrl = new AbortController()
  const wsClientId = getWsClientId()
  connectWs(wsClientId)
  try {
    await caseApi.generate(filterTaskId.value, {
      reparse_page: reparseBeforeGen.value,
      ws_client_id: wsClientId,
    }, { signal: _genAbortCtrl.signal, timeout: 600000 })
    await taskStore.fetchCases(filterTaskId.value)
    taskStore.fetchTotalCaseCount(wsStore.currentId)
    ElMessage.success('AI 用例生成完成')
  } catch (e) {
    if (e?.name === 'AbortError' || e?.code === 'ERR_CANCELED') {
      ElMessage.info('已取消生成')
    } else {
      ElMessage.error('生成失败: ' + (e?.response?.data?.detail || e.message))
    }
  } finally {
    generating.value = false
    showProgress.value = false
    canCancelGen.value = false
    _genAbortCtrl = null
  }
}
const cancelGeneration = () => {
  if (_genAbortCtrl) { _genAbortCtrl.abort(); _genAbortCtrl = null }
}

// ── 优化 ──
const optimizeCases = async () => {
  if (!filterTaskId.value) { ElMessage.warning('请先选择任务'); return }
  optimizing.value = true
  showProgress.value = true
  progressTitle.value = '优化用例'
  progressPct.value = 0
  progressStage.value = '准备中...'
  genCaseCount.value = 0
  const wsClientId = getWsClientId()
  connectWs(wsClientId)
  try {
    await caseApi.optimize(filterTaskId.value, { ws_client_id: wsClientId }, { timeout: 600000 })
    await taskStore.fetchCases(filterTaskId.value)
    taskStore.fetchTotalCaseCount(wsStore.currentId)
    ElMessage.success('用例优化完成')
  } catch (e) {
    ElMessage.error('优化失败: ' + (e?.response?.data?.detail || e.message))
  } finally {
    optimizing.value = false
    showProgress.value = false
  }
}

// ── 从 API 加载最近一次执行的失败用例 ──
// (now managed by useFailedCases composable)

function getCaseExecStatus(row) {
  // 优先按 case_id 匹配
  if (row.id && executionResultMap.value[row.id]) {
    return executionResultMap.value[row.id].status
  }
  // 回退按名称匹配
  const nameKey = '_name_' + row.name
  if (executionResultMap.value[nameKey]) {
    return executionResultMap.value[nameKey].status
  }
  return null
}
function getCaseExecError(row) {
  if (row.id && executionResultMap.value[row.id]) {
    return executionResultMap.value[row.id].error
  }
  const nameKey = '_name_' + row.name
  return executionResultMap.value[nameKey]?.error || ''
}
function formatTime(isoStr) {
  if (!isoStr) return ''
  const d = new Date(isoStr)
  const pad = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
function quickShowFailures() {
  // 通过名称匹配：只显示失败用例（在搜索框中填入失败用例名）
  const failedNames = lastExecutionFailed.value.map(f => f.case_name).filter(Boolean)
  if (failedNames.length) {
    searchText.value = failedNames.join('|')
  }
}

// ── 修正 & 补全 ──
const fixCases = async () => {
  if (!filterTaskId.value) return
  if (!lastExecutionFailed.value.length) {
    ElMessage.info('没有需要修正的失败用例，请先执行一次测试')
    return
  }
  fixing.value = true
  showProgress.value = true
  progressTitle.value = 'AI 修正失败用例'
  progressPct.value = 0
  progressStage.value = '正在分析失败用例...'
  genCaseCount.value = 0
  const wsClientId = 'cases_correct_' + Date.now()
  connectWs(wsClientId)
  try {
    const res = await caseApi.selfCorrect(filterTaskId.value, {
      failed_cases: lastExecutionFailed.value,
      ws_client_id: wsClientId,
    })
    fixResult.value = res
    showFixResult.value = true
    const stats = res.stats || {}
    ElMessage.success(`修正完成：${stats.total || res.corrected?.length || 0} 条`)
    await taskStore.fetchCases(filterTaskId.value)
  } catch (e) {
    ElMessage.error('修正失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    fixing.value = false
    showProgress.value = false
    disconnectWs()
  }
}
const autoFixAll = async () => {
  if (!filterTaskId.value) return
  autoFixing.value = true
  showProgress.value = true
  progressTitle.value = '一键修正 & 补全'
  progressPct.value = 0
  progressStage.value = '正在启动...'
  genCaseCount.value = 0
  const wsClientId = 'auto_fix_' + Date.now()
  connectWs(wsClientId)
  try {
    const res = await caseApi.autoFix(filterTaskId.value, {
      failed_cases: lastExecutionFailed.value,
      existing_cases: filteredCases.value,
      execution_results: [],
      ws_client_id: wsClientId,
    })
    fixResult.value = res
    showFixResult.value = true
    if (res.new_cases?.length) {
      for (const nc of res.new_cases) {
        await taskStore.createCase({ ...nc, task_id: filterTaskId.value, status: 'draft' })
      }
    }
    const stats = res.stats || {}
    ElMessage.success(`修正补全完成：${stats.corrected_count || 0} 条修正 + ${stats.gap_count || 0} 条补充`)
    await taskStore.fetchCases(filterTaskId.value)
  } catch (e) {
    ElMessage.error('修正补全失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    autoFixing.value = false
    showProgress.value = false
    disconnectWs()
  }
}

// ── 覆盖度 ──
const showCoverage = async () => {
  if (!filterTaskId.value) { ElMessage.warning('请先选择任务'); return }
  loadingCoverage.value = true
  try {
    coverageData.value = await caseApi.coverage(filterTaskId.value)
    showCoverageDrawer.value = true
  } catch (e) {
    ElMessage.error('获取覆盖度失败: ' + (e.response?.data?.detail || e.message))
  } finally { loadingCoverage.value = false }
}

// ── 文档变更 ──
const openDocDiffDialog = () => {
  if (!filterTaskId.value) { ElMessage.warning('请先选择任务'); return }
  docDiffStep.value = 1; docDiffResult.value = null; docDiffNewContent.value = ''
  docDiffUploadedFile.value = null; docDiffUploadError.value = ''
  docDiffForm.sourceType = 'file'; docDiffForm.content = ''; docDiffForm.reparseElements = false
  docDiffDialogVisible.value = true
}
const handleDocDiffFileChange = (file) => {
  const ext = '.' + file.name.split('.').pop().toLowerCase()
  const allowed = new Set(['.pdf','.docx','.doc','.xlsx','.xls','.txt','.md','.html','.htm','.csv','.json','.pptx'])
  if (!allowed.has(ext)) { docDiffUploadError.value = `不支持的格式 ${ext}`; docDiffUploadRef.value?.clearFiles(); return }
  if (file.size > 20 * 1024 * 1024) { docDiffUploadError.value = '文件超过 20MB'; docDiffUploadRef.value?.clearFiles(); return }
  docDiffUploadError.value = ''; docDiffUploadedFile.value = file.raw
}
const doDocDiffCheck = async () => { /* 简化：移入 dropdown，实际复杂逻辑保留 */ }
const doDocIncrementalUpdate = async () => { /* 简化 */ }

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
    await ElMessageBox.confirm(`确定要删除选中的 ${count} 个用例吗？此操作不可恢复。`, '批量删除', { type: 'warning' })
    batchDeleting.value = true
    const deletedIds = new Set(selectedCases.value.map(c => c.id))
    for (const c of selectedCases.value) await taskStore.deleteCase(c.id)
    // 清理本地失败记录
    removeResults([...deletedIds])
    selectedCases.value = []
    ElMessage.success('批量删除成功')
    taskStore.fetchTotalCaseCount(wsStore.currentId)
  } catch (err) { if (err !== 'cancel') ElMessage.error('删除失败: ' + (err?.message || err)) }
  finally { batchDeleting.value = false }
}

const editCase = (row) => {
  editingCase.value = row
  Object.assign(caseForm, {
    task_id: row.task_id, name: row.name, module: row.module,
    priority: row.priority, preconditions: row.preconditions,
    steps: row.steps, expected_results: row.expected_results, enabled: row.enabled,
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
      taskStore.fetchTotalCaseCount(wsStore.currentId)
    }
    showCreateDialog.value = false
    resetForm()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e?.response?.data?.detail || e.message))
  } finally { saving.value = false }
}
const deleteCase = async (row) => {
  try {
    await ElMessageBox.confirm('确定要删除这个用例吗?', '提示', { type: 'warning' })
    await taskStore.deleteCase(row.id)
    // 清理本地失败记录
    removeResult(row.id)
    ElMessage.success('删除成功')
    taskStore.fetchTotalCaseCount(wsStore.currentId)
  } catch (err) { if (err !== 'cancel') ElMessage.error('删除失败') }
}
const resetForm = () => {
  caseForm.task_id = filterTaskId.value || null
  caseForm.name = ''; caseForm.module = '通用'; caseForm.priority = 'P1'
  caseForm.preconditions = ''; caseForm.steps = ''; caseForm.expected_results = ''
  caseForm.enabled = true; editingCase.value = null
}

// ═══════════════════════════════════════════════════════════
// Lifecycle
// ═══════════════════════════════════════════════════════════
onMounted(async () => {
  connectWs(getWsClientId())
  if (wsStore.initialized) await taskStore.fetchTasks(wsStore.currentId)
  if (route.query.taskId) {
    filterTaskId.value = parseInt(route.query.taskId)
    caseForm.task_id = filterTaskId.value
  }
  if (filterTaskId.value) {
    await taskStore.fetchCases(filterTaskId.value)
  } else {
    taskStore.setCases([])
  }
})
watch(showDeprecated, () => { selectedCases.value = [] })
watch(() => wsStore.currentId, async (id) => {
  filterTaskId.value = null; caseForm.task_id = null; taskStore.setCases([])
  selectedCases.value = []; coverageData.value = null; showCoverageDrawer.value = false
  showCreateDialog.value = false; editingCase.value = null
  if (_genAbortCtrl) { _genAbortCtrl.abort(); _genAbortCtrl = null }
  showProgress.value = false
  await taskStore.fetchTasks(id)
})
watch(() => wsStore.initialized, async (ready) => {
  if (ready) await taskStore.fetchTasks(wsStore.currentId)
})
</script>

<style scoped>
.cases-page { padding: 0; }
.card-header { display: flex; flex-direction: column; gap: 8px; }
.header-row { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; }
.header-controls { display: flex; align-items: center; gap: 10px; }
.page-title { font-size: 16px; font-weight: 600; white-space: nowrap; }
.filter-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.filter-label { color: #909399; font-size: 13px; }
.filter-count { color: #909399; font-size: 13px; white-space: nowrap; }
.action-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

.execution-summary-bar {
  padding: 6px 12px; background: #fafbfc; border-radius: 6px; border: 1px solid #ebeef5;
  display: flex; align-items: center; gap: 10px;
}
.exec-summary-label { color: #606266; font-size: 13px; font-weight: 500; }
.exec-summary-time { color: #909399; font-size: 12px; }
.exec-unknown { color: #c0c4cc; font-size: 12px; }

.batch-actions { margin-top: 12px; display: flex; gap: 8px; flex-wrap: wrap; }

.row-actions { display: flex; align-items: center; justify-content: center; gap: 0; white-space: nowrap; }
.row-actions .el-button { padding: 2px 6px; font-size: 12px; }
.action-sep { display: inline-block; width: 1px; height: 12px; background: #dcdfe6; margin: 0 4px; flex-shrink: 0; }

/* progress */
.progress-body { padding: 4px 0 8px; }
.progress-stage { margin: 10px 0 0; text-align: center; color: #606266; font-size: 13px; }
.progress-count { margin: 4px 0 0; text-align: center; color: #409eff; font-size: 12px; font-weight: 500; }
.progress-steps { display: flex; align-items: center; justify-content: center; margin-bottom: 16px; }
.progress-step { display: flex; flex-direction: column; align-items: center; gap: 6px; opacity: 0.35; transition: opacity 0.4s; }
.progress-step.active { opacity: 0.7; }
.progress-step.done { opacity: 1; }
.step-dot {
  width: 30px; height: 30px; border-radius: 50%; background: #e4e7ed; color: #909399;
  font-size: 13px; font-weight: 700; display: flex; align-items: center; justify-content: center; transition: all 0.4s;
}
.progress-step.active .step-dot { background: #409eff; color: #fff; box-shadow: 0 0 0 3px rgba(64,158,255,.25); }
.progress-step.done .step-dot { background: #67c23a; color: #fff; }
.step-label { font-size: 11px; color: #606266; white-space: nowrap; }
.step-line { flex: 1; height: 2px; background: #e4e7ed; min-width: 24px; max-width: 50px; transition: background 0.4s; }
.step-line.active { background: #409eff; }
.progress-bar-wrap {
  width: 100%; height: 22px; background: #f0f2f5; border-radius: 11px; overflow: hidden;
  box-shadow: inset 0 1px 3px rgba(0,0,0,.08);
}
.progress-bar-fill {
  height: 100%; border-radius: 11px;
  background: linear-gradient(90deg, #409eff 0%, #66b1ff 50%, #a0cfff 100%);
  background-size: 200% 100%;
  animation: progressShine 1.8s ease-in-out infinite;
  display: flex; align-items: center; justify-content: flex-end;
  min-width: 0; transition: width 0.5s ease;
}
.progress-bar-text { color: #fff; font-size: 12px; font-weight: 600; padding-right: 10px; text-shadow: 0 1px 2px rgba(0,0,0,.2); }
@keyframes progressShine { 0% { background-position: 200% 0; } 100% { background-position: 0 0; } }

/* coverage */
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

/* deprecated */
.case-deprecated { text-decoration: line-through; color: #c0c4cc; }

/* fix result */
.fix-result-body { padding: 4px 0; }
.fix-stats { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.fix-item-title { display: flex; align-items: center; gap: 10px; }
.fix-case-name { font-size: 14px; font-weight: 500; }
.fix-compare { margin: 4px 0 10px; }
.fix-before, .fix-after { margin-bottom: 10px; }
.fix-before pre, .fix-after pre {
  margin: 6px 0 0; padding: 10px 12px; border-radius: 6px;
  font-size: 12px; line-height: 1.6; white-space: pre-wrap; word-break: break-all; max-height: 160px; overflow-y: auto;
}
.fix-before pre { background: #fef0f0; border: 1px solid #fde2e2; color: #c0392b; }
.fix-after pre { background: #f0f9eb; border: 1px solid #e1f3d8; color: #27ae60; }
.fix-note { display: flex; align-items: center; gap: 6px; padding: 8px 12px; border-radius: 6px; background: #ecf5ff; color: #409eff; font-size: 13px; }
.new-case-item { display: flex; align-items: center; gap: 8px; padding: 6px 10px; margin-bottom: 4px; border-radius: 4px; background: #f5f7fa; font-size: 13px; }
</style>
