<template>
  <div class="tasks-page">
    <WorkspaceRequired v-if="auth.role !== 'admin' && !wsStore.currentId" />
    <template v-else>

      <!-- 顶部操作栏 -->
      <div class="page-header">
        <div class="page-header-left">
          <span class="page-title">任务管理</span>
          <el-tag type="info" size="small" style="margin-left:10px">
            {{ taskStore.tasks.length }} 个任务
          </el-tag>
        </div>
        <el-button type="primary" @click="showCreateDialog = true">
          <el-icon><Plus /></el-icon>新建任务
        </el-button>
      </div>

      <!-- 空状态 -->
      <el-empty v-if="taskStore.tasks.length === 0" description="暂无测试任务，点击右上角新建">
        <el-button type="primary" @click="showCreateDialog = true">
          <el-icon><Plus /></el-icon>新建第一个任务
        </el-button>
      </el-empty>

      <!-- 任务卡片网格 -->
      <div v-else class="task-grid">
        <div v-for="task in taskStore.tasks" :key="task.id" class="task-card">
          <!-- 卡片头 -->
          <div class="task-card-header">
            <div class="task-name-row">
              <el-icon class="task-icon"><Monitor /></el-icon>
              <span class="task-name" :title="task.name">{{ task.name }}</span>
            </div>
            <el-tag :type="getStatusType(task.status)" size="small" effect="plain">
              {{ getStatusLabel(task.status) }}
            </el-tag>
          </div>

          <!-- URL -->
          <div class="task-url" :title="task.url">
            <el-icon size="12" style="flex-shrink:0;color:#aaa"><Link /></el-icon>
            <span class="url-text">{{ task.url || '未设置 URL' }}</span>
          </div>

          <!-- 元信息行 -->
          <div class="task-meta">
            <el-tag size="small" effect="plain" class="browser-tag">
              <el-icon style="margin-right:3px"><Monitor /></el-icon>
              {{ browserLabel(task.browser) }}
            </el-tag>
            <el-tag size="small" type="info" effect="plain">
              {{ envLabel(task.environment) }}
            </el-tag>
            <span class="task-time">{{ formatDate(task.created_at) }}</span>
          </div>

          <!-- 统计行 -->
          <div class="task-stats">
            <div class="stat-item">
              <span class="stat-num">{{ caseCountMap[task.id] ?? '—' }}</span>
              <span class="stat-label">用例</span>
            </div>
            <div class="stat-divider"></div>
            <div class="stat-item">
              <span class="stat-num">{{ reportCountMap[task.id] ?? '—' }}</span>
              <span class="stat-label">报告</span>
            </div>
          </div>

          <!-- 操作按钮 -->
          <div class="task-actions">
            <div class="action-row primary">
              <el-button size="small" plain @click="goCases(task)">
                <el-icon><Document /></el-icon>用例<span class="badge">{{ caseCountMap[task.id] ?? '-' }}</span>
              </el-button>
              <el-button size="small" plain type="warning" @click="goRecord(task)">
                <el-icon><VideoCamera /></el-icon>录制
              </el-button>
              <el-button size="small" plain type="success" @click="goExecution(task)">
                <el-icon><VideoPlay /></el-icon>执行
              </el-button>
              <el-button size="small" type="primary" plain @click="goReports(task)">
                <el-icon><DataAnalysis /></el-icon>报告<span class="badge">{{ reportCountMap[task.id] ?? '-' }}</span>
              </el-button>
            </div>
            <div class="action-row secondary">
              <span class="spacer"></span>
              <el-button size="small" plain class="btn-edit" @click="openEditDialog(task)">
                <el-icon><Edit /></el-icon>编辑
              </el-button>
              <el-popconfirm
                title="确定删除该任务？"
                confirm-button-text="删除"
                cancel-button-text="取消"
                confirm-button-type="danger"
                @confirm="deleteTask(task)"
              >
                <template #reference>
                  <el-button size="small" plain type="danger" class="btn-delete">
                    <el-icon><Delete /></el-icon>删除
                  </el-button>
                </template>
              </el-popconfirm>
              <span class="spacer"></span>
            </div>
          </div>
        </div>
      </div>

      <!-- 新建任务对话框 -->
      <el-dialog v-model="showCreateDialog" title="新建测试任务" width="560px" @close="onDialogClose">
        <el-form :model="taskForm" label-width="90px">
          <el-form-item label="任务名称" required>
            <el-input v-model="taskForm.name" placeholder="例如：登录功能回归测试" clearable />
          </el-form-item>
          <el-form-item label="目标 URL" required>
            <el-input v-model="taskForm.url" placeholder="https://example.com/login" clearable>
              <template #prepend><el-icon><Link /></el-icon></template>
            </el-input>
          </el-form-item>
          <el-form-item label="需求文档">
            <el-upload
              ref="uploadRef"
              :auto-upload="false"
              :limit="1"
              :accept="ACCEPTED_EXTS"
              :on-change="handleFileChange"
              :on-remove="() => { uploadedFile = null; fileError = '' }"
              drag
              style="width:100%"
            >
              <el-icon size="28" color="#c0c4cc"><UploadFilled /></el-icon>
              <div style="font-size:13px;color:#909399;margin-top:6px">
                拖拽文档到此，或 <em style="color:#409eff">点击上传</em>
              </div>
              <template #tip>
                <div style="font-size:11px;color:#c0c4cc;margin-top:4px">
                  PDF / Word / Excel / PPTX / Markdown / TXT / JSON，≤ 20MB
                </div>
              </template>
            </el-upload>
            <el-alert v-if="fileError" :title="fileError" type="error" show-icon :closable="false" style="margin-top:6px" />
          </el-form-item>
          <el-row :gutter="12">
            <el-col :span="12">
              <el-form-item label="默认浏览器">
                <el-select v-model="taskForm.browser" style="width:100%">
                  <el-option label="🌐 Chromium" value="chromium" />
                  <el-option label="🦊 Firefox" value="firefox" />
                  <el-option label="🧭 WebKit" value="webkit" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="测试环境">
                <el-select v-model="taskForm.environment" style="width:100%">
                  <el-option label="测试环境" value="test" />
                  <el-option label="预发环境" value="staging" />
                  <el-option label="生产环境" value="production" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
        </el-form>

        <el-alert
          title="创建后可在「用例管理」中 AI 生成用例，或在「测试执行」中录制操作步骤"
          type="info"
          show-icon
          :closable="false"
          style="margin-top:4px"
        />

        <template #footer>
          <el-button @click="showCreateDialog = false">取消</el-button>
          <el-button type="primary" @click="createTask" :loading="creating">创建任务</el-button>
        </template>
      </el-dialog>

      <!-- 编辑任务对话框 -->
      <el-dialog v-model="showEditDialog" title="编辑任务" width="560px" @close="onEditDialogClose">
        <el-form :model="editForm" label-width="90px">
          <el-form-item label="任务名称" required>
            <el-input v-model="editForm.name" placeholder="例如：登录功能回归测试" clearable />
          </el-form-item>
          <el-form-item label="目标 URL" required>
            <el-input v-model="editForm.url" placeholder="https://example.com/login" clearable>
              <template #prepend><el-icon><Link /></el-icon></template>
            </el-input>
          </el-form-item>
          <el-form-item label="需求文档">
            <div v-if="editForm.document_path" class="current-doc">
              <el-icon><Document /></el-icon>
              <span>{{ editForm.document_path.split('/').pop() || editForm.document_path.split('\\').pop() }}</span>
            </div>
            <el-upload
              ref="editUploadRef"
              :auto-upload="false"
              :limit="1"
              :accept="ACCEPTED_EXTS"
              :on-change="handleEditFileChange"
              :on-remove="() => { editUploadedFile = null; editFileError = '' }"
              drag
              style="width:100%"
            >
              <el-icon size="28" color="#c0c4cc"><UploadFilled /></el-icon>
              <div style="font-size:13px;color:#909399;margin-top:6px">
                拖拽新文档到此，或 <em style="color:#409eff">点击上传</em>
              </div>
              <template #tip>
                <div style="font-size:11px;color:#c0c4cc;margin-top:4px">
                  PDF / Word / Excel / PPTX / Markdown / TXT / JSON，≤ 20MB
                </div>
              </template>
            </el-upload>
            <el-alert v-if="editFileError" :title="editFileError" type="error" show-icon :closable="false" style="margin-top:6px" />
          </el-form-item>
          <el-row :gutter="12">
            <el-col :span="12">
              <el-form-item label="默认浏览器">
                <el-select v-model="editForm.browser" style="width:100%">
                  <el-option label="Chromium" value="chromium" />
                  <el-option label="Firefox" value="firefox" />
                  <el-option label="WebKit" value="webkit" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="测试环境">
                <el-select v-model="editForm.environment" style="width:100%">
                  <el-option label="测试环境" value="test" />
                  <el-option label="预发环境" value="staging" />
                  <el-option label="生产环境" value="production" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
        </el-form>
        <el-alert
          title="文档变更不影响已有用例和执行记录。如需用新文档重新生成用例，请前往「用例管理」手动触发。"
          type="info"
          show-icon
          :closable="false"
          style="margin-top:4px"
        />
        <template #footer>
          <el-button @click="showEditDialog = false">取消</el-button>
          <el-button type="primary" @click="updateTask" :loading="updating">保存修改</el-button>
        </template>
      </el-dialog>

    </template>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useTaskStore } from '../stores/task'
import { useWorkspaceStore } from '../stores/workspace'
import { useAuthStore } from '../stores/auth'
import WorkspaceRequired from '../components/WorkspaceRequired.vue'
import { ElMessage } from 'element-plus'
import { caseApi, reportApi } from '../api/index'

const ACCEPTED_EXTS = '.pdf,.docx,.doc,.xlsx,.xls,.pptx,.md,.txt,.csv,.html,.htm,.json'
const ACCEPTED_SET  = new Set(ACCEPTED_EXTS.split(','))
const MAX_SIZE_MB   = 20

const router    = useRouter()
const taskStore = useTaskStore()
const wsStore   = useWorkspaceStore()
const auth      = useAuthStore()

const showCreateDialog = ref(false)
const showEditDialog   = ref(false)
const editingTaskId    = ref(null)
const creating         = ref(false)
const updating         = ref(false)
const uploadRef        = ref(null)
const uploadedFile     = ref(null)
const fileError        = ref('')
const editUploadRef    = ref(null)
const editUploadedFile = ref(null)
const editFileError    = ref('')

// 每个任务的用例数 / 报告数
const caseCountMap   = ref({})
const reportCountMap = ref({})

const taskForm = reactive({
  name: '', url: '',
  document_path: '',
  browser: 'chromium',
  environment: 'test',
})

const editForm = reactive({
  name: '', url: '',
  document_path: '',
  browser: 'chromium',
  environment: 'test',
})

// ── 辅助 ──────────────────────────────────────────────────────────────────────
const browserLabel = (b) => ({ chromium: 'Chromium', firefox: 'Firefox', webkit: 'WebKit' }[b] || b || 'Chromium')
const envLabel     = (e) => ({ test: '测试', staging: '预发', production: '生产' }[e] || e)
const getStatusType  = (s) => ({ created: 'info', completed: 'success', failed: 'danger', executing: 'primary', generating: 'warning' }[s] || 'info')
const getStatusLabel = (s) => ({ created: '已创建', completed: '已完成', failed: '失败', executing: '执行中', generating: '生成中', generated: '已生成' }[s] || s || '已创建')

const formatDate = (d) => {
  if (!d) return ''
  try { return new Date(d.includes('Z') ? d : d + 'Z').toLocaleDateString('zh-CN') } catch { return '' }
}

// ── 用例/报告数量（并行加载，避免串行 N 次请求）───────────────────────────────
const loadCounts = async (tasks) => {
  if (!tasks || tasks.length === 0) return
  // 并行拉取所有任务的用例列表
  const results = await Promise.allSettled(
    tasks.map(t => caseApi.list(t.id).then(cases => ({ id: t.id, count: Array.isArray(cases) ? cases.length : 0 })))
  )
  results.forEach(r => {
    if (r.status === 'fulfilled') {
      caseCountMap.value[r.value.id] = r.value.count
    }
  })
  // 并行拉取报告数（从报告列表按 task_id 聚合）
  try {
    const { reportApi } = await import('../api/index')
    const wsId = wsStore.currentId
    const reports = await reportApi.list(wsId)
    if (Array.isArray(reports)) {
      const countByTask = {}
      reports.forEach(r => {
        if (r.task_id) countByTask[r.task_id] = (countByTask[r.task_id] || 0) + 1
      })
      tasks.forEach(t => {
        reportCountMap.value[t.id] = countByTask[t.id] || 0
      })
    }
  } catch { /* 报告数加载失败不影响主流程 */ }
}

// ── 文件上传 ───────────────────────────────────────────────────────────────────
const handleFileChange = (file) => {
  fileError.value = ''
  const ext = ('.' + file.name.split('.').pop()).toLowerCase()
  if (!ACCEPTED_SET.has(ext)) {
    fileError.value = `不支持的文件格式 "${ext}"，请上传 PDF / Word / Excel / PPTX / Markdown / TXT / CSV / HTML / JSON`
    uploadRef.value?.clearFiles()
    return
  }
  if (file.raw.size > MAX_SIZE_MB * 1024 * 1024) {
    fileError.value = `文件过大（${(file.raw.size / 1024 / 1024).toFixed(1)} MB），请上传 20 MB 以内的文件`
    uploadRef.value?.clearFiles()
    return
  }
  uploadedFile.value = file.raw
}

const handleEditFileChange = (file) => {
  editFileError.value = ''
  const ext = ('.' + file.name.split('.').pop()).toLowerCase()
  if (!ACCEPTED_SET.has(ext)) {
    editFileError.value = `不支持的文件格式 "${ext}"`
    editUploadRef.value?.clearFiles()
    return
  }
  if (file.raw.size > MAX_SIZE_MB * 1024 * 1024) {
    editFileError.value = `文件过大（${(file.raw.size / 1024 / 1024).toFixed(1)} MB），请上传 20 MB 以内的文件`
    editUploadRef.value?.clearFiles()
    return
  }
  editUploadedFile.value = file.raw
}

const onDialogClose = () => {
  fileError.value   = ''
  uploadedFile.value = null
  uploadRef.value?.clearFiles()
  Object.assign(taskForm, { name: '', url: '', document_path: '', browser: 'chromium', environment: 'test' })
}

// ── 创建任务（仅创建，不自动生成，引导用户去用例页） ─────────────────────────
const createTask = async () => {
  if (!taskForm.name.trim()) { ElMessage.warning('请填写任务名称'); return }
  if (!taskForm.url.trim())  { ElMessage.warning('请填写目标 URL'); return }

  creating.value = true
  let docPath = ''

  if (uploadedFile.value) {
    try {
      const res = await taskStore.uploadDocument(uploadedFile.value)
      docPath = res.path || ''
    } catch { ElMessage.warning('需求文档上传失败，已跳过') }
  }

  try {
    await taskStore.createTask({
      ...taskForm,
      document_path: docPath,
      workspace_id: wsStore.currentId || null,
    })
    ElMessage.success('任务创建成功，可前往「用例管理」AI 生成用例或「测试执行」录制步骤')
    showCreateDialog.value = false
    onDialogClose()
    await loadCounts(taskStore.tasks)
  } catch (e) {
    ElMessage.error('创建失败：' + (e.response?.data?.detail || e.message))
  } finally {
    creating.value = false
  }
}

// ── 删除 ──────────────────────────────────────────────────────────────────────
const deleteTask = async (task) => {
  try {
    await taskStore.deleteTask(task.id)
    ElMessage.success('已删除')
    delete caseCountMap.value[task.id]
    delete reportCountMap.value[task.id]
  } catch { ElMessage.error('删除失败') }
}

// ── 编辑 ──────────────────────────────────────────────────────────────────────
const openEditDialog = (task) => {
  editingTaskId.value = task.id
  editForm.name          = task.name || ''
  editForm.url           = task.url || ''
  editForm.document_path = task.document_path || ''
  editForm.browser       = task.browser || 'chromium'
  editForm.environment   = task.environment || 'test'
  editUploadedFile.value = null
  editFileError.value    = ''
  editUploadRef.value?.clearFiles()
  showEditDialog.value = true
}

const updateTask = async () => {
  if (!editForm.name.trim()) { ElMessage.warning('请填写任务名称'); return }
  if (!editForm.url.trim())  { ElMessage.warning('请填写目标 URL'); return }
  updating.value = true

  let docPath = editForm.document_path  // 未上传新文档时保留原路径
  if (editUploadedFile.value) {
    try {
      const res = await taskStore.uploadDocument(editUploadedFile.value)
      docPath = res.path || ''
    } catch { ElMessage.warning('文档上传失败，已跳过') }
  }

  try {
    await taskStore.updateTask(editingTaskId.value, {
      name: editForm.name.trim(),
      url: editForm.url.trim(),
      document_path: docPath,
      browser: editForm.browser,
      environment: editForm.environment,
    })
    ElMessage.success('任务已更新')
    showEditDialog.value = false
  } catch (e) {
    ElMessage.error('更新失败：' + (e.response?.data?.detail || e.message))
  } finally {
    updating.value = false
  }
}

const onEditDialogClose = () => {
  editingTaskId.value = null
  editUploadedFile.value = null
  editFileError.value = ''
  editUploadRef.value?.clearFiles()
  Object.assign(editForm, { name: '', url: '', document_path: '', browser: 'chromium', environment: 'test' })
}

// ── 跳转 ──────────────────────────────────────────────────────────────────────
const goCases     = (t) => router.push({ name: 'Cases',     query: { taskId: t.id } })
const goExecution = (t) => router.push({ name: 'Execution', query: { taskId: t.id } })
const goRecord    = (t) => router.push({ name: 'Cases', query: { taskId: t.id, startRecord: '1' } })
const goReports   = (t) => router.push({ name: 'Reports' })

// ── 生命周期 ───────────────────────────────────────────────────────────────────
onMounted(async () => {
  if (wsStore.initialized) {
    await taskStore.fetchTasks(wsStore.currentId)
    await loadCounts(taskStore.tasks)
  }
})

watch(() => wsStore.currentId, async (id) => {
  await taskStore.fetchTasks(id)
  await loadCounts(taskStore.tasks)
})

watch(() => wsStore.initialized, async (ready) => {
  if (ready) {
    await taskStore.fetchTasks(wsStore.currentId)
    await loadCounts(taskStore.tasks)
  }
})
</script>

<style scoped>
.tasks-page { padding: 0; }

/* 顶部操作栏 */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.page-title {
  font-size: 16px;
  font-weight: 600;
  color: #1a2332;
}

/* 卡片网格 */
.task-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}

.task-card {
  background: #fff;
  border: 1px solid #e8ecf0;
  border-radius: 10px;
  padding: 18px;
  transition: box-shadow 0.2s, border-color 0.2s;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.task-card:hover {
  box-shadow: 0 4px 16px rgba(0,0,0,0.08);
  border-color: #c6d8f0;
}

/* 卡片头 */
.task-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
}

.task-name-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
}

.task-icon {
  font-size: 16px;
  color: #409eff;
  flex-shrink: 0;
}

.task-name {
  font-size: 15px;
  font-weight: 600;
  color: #1a2332;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* URL */
.task-url {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: #909399;
  min-height: 18px;
}

.url-text {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}

/* 元信息 */
.task-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.browser-tag { font-size: 11px !important; }

.task-time {
  font-size: 11px;
  color: #c0c4cc;
  margin-left: auto;
}

/* 统计 */
.task-stats {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  background: #f8fafc;
  border-radius: 6px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.stat-num {
  font-size: 18px;
  font-weight: 700;
  color: #303133;
  line-height: 1;
}

.stat-label {
  font-size: 11px;
  color: #909399;
}

.stat-divider {
  width: 1px;
  height: 28px;
  background: #e4e7ed;
}

/* 操作按钮 */
.task-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.action-row {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.action-row.secondary {
  padding-top: 8px;
  border-top: 1px dashed #ebeef5;
}

.action-row.secondary .el-button {
  font-size: 12px;
  height: 28px;
}

.spacer {
  flex: 1;
  min-width: 0;
}

/* 编辑/删除按钮美化 */
.btn-edit {
  --el-button-hover-text-color: var(--el-color-primary);
  --el-button-hover-border-color: var(--el-color-primary-light-5);
  --el-button-hover-bg-color: var(--el-color-primary-light-9);
}

.btn-delete {
  opacity: .75;
  transition: opacity .2s;
}
.btn-delete:hover {
  opacity: 1;
}

.badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  max-width: 40px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  font-size: 11px;
  font-weight: 600;
  color: #909399;
  background: #f4f4f5;
  margin-left: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.current-doc {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  background: #f0f9eb;
  border: 1px solid #e1f3d8;
  border-radius: 6px;
  font-size: 13px;
  color: #67c23a;
  margin-bottom: 8px;
}

.current-doc .el-icon {
  flex-shrink: 0;
}

.current-doc span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
