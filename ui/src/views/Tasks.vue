<template>
  <div class="tasks-page">
    <WorkspaceRequired v-if="auth.role !== 'admin' && !wsStore.currentId" />
    <template v-else>
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>测试任务列表</span>
          <el-button type="primary" @click="showCreateDialog = true">
            <el-icon><Plus /></el-icon>
            新建任务
          </el-button>
        </div>
      </template>

      <el-table :data="taskStore.tasks" stripe style="width: 100%">
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="name" label="任务名称" min-width="150" />
        <el-table-column prop="url" label="测试URL" min-width="200" show-overflow-tooltip />
        <el-table-column prop="browser" label="浏览器" width="100">
          <template #default="{ row }">
            <el-tag>{{ row.browser }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="environment" label="环境" width="100">
          <template #default="{ row }">
            <el-tag type="info">{{ getEnvLabel(row.environment) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)">{{ getStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="180">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <div class="action-btns">
              <el-tooltip content="查看用例" placement="top">
                <el-button type="primary" link size="small" @click="viewTask(row)">
                  <el-icon><View /></el-icon>查看
                </el-button>
              </el-tooltip>
              <el-divider direction="vertical" />
              <el-tooltip content="开始执行测试" placement="top">
                <el-button type="success" link size="small" @click="startTest(row)">
                  <el-icon><VideoPlay /></el-icon>测试
                </el-button>
              </el-tooltip>
              <el-divider direction="vertical" />
              <el-tooltip content="删除任务" placement="top">
                <el-button type="danger" link size="small" @click="deleteTask(row)">
                  <el-icon><Delete /></el-icon>删除
                </el-button>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="showCreateDialog" title="创建测试任务" width="600px" @close="onDialogClose">
      <el-form :model="taskForm" label-width="100px">
        <el-form-item label="任务名称">
          <el-input v-model="taskForm.name" placeholder="请输入任务名称" />
        </el-form-item>
        <el-form-item label="测试URL">
          <el-input v-model="taskForm.url" placeholder="请输入待测试页面URL" />
        </el-form-item>
        <el-form-item label="需求文档">
          <el-upload
            ref="uploadRef"
            :auto-upload="false"
            :limit="1"
            :accept="ACCEPTED_EXTS"
            :before-upload="() => false"
            :on-change="handleFileChange"
            :on-remove="handleFileRemove"
          >
            <el-button><el-icon><Upload /></el-icon> 选择文件</el-button>
            <template #tip>
              <div class="el-upload__tip">
                支持：PDF · Word（DOCX/DOC）· Excel（XLSX/XLS）· PowerPoint（PPTX）·
                Markdown · 纯文本（TXT）· CSV · HTML · JSON
                <span style="color:#f56c6c;margin-left:6px;">文件大小 ≤ 20MB</span>
              </div>
            </template>
          </el-upload>
          <el-alert
            v-if="fileError"
            :title="fileError"
            type="error"
            show-icon
            :closable="false"
            style="margin-top:8px;"
          />
        </el-form-item>
        <el-form-item label="浏览器">
          <el-select v-model="taskForm.browser" style="width: 100%">
            <el-option label="Chromium" value="chromium" />
            <el-option label="Firefox" value="firefox" />
            <el-option label="WebKit" value="webkit" />
          </el-select>
        </el-form-item>
        <el-form-item label="测试环境">
          <el-select v-model="taskForm.environment" style="width: 100%">
            <el-option label="测试环境" value="test" />
            <el-option label="预发环境" value="staging" />
            <el-option label="生产环境" value="production" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="createTask" :loading="creating">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showParseDialog" title="解析页面" width="800px">
      <el-form :model="parseForm" label-width="100px">
        <el-form-item label="页面URL">
          <el-input v-model="parseForm.url" placeholder="请输入要解析的页面URL" />
        </el-form-item>
        <el-form-item label="浏览器">
          <el-select v-model="parseForm.browser" style="width: 100%">
            <el-option label="Chromium" value="chromium" />
            <el-option label="Firefox" value="firefox" />
            <el-option label="WebKit" value="webkit" />
          </el-select>
        </el-form-item>
      </el-form>

      <div v-if="taskStore.pageElements.length > 0" style="margin-top: 20px;">
        <el-divider>解析结果</el-divider>
        <el-tag type="success" style="margin-bottom: 10px;">
          共解析 {{ taskStore.pageElements.length }} 个可交互元素
        </el-tag>
        <el-table :data="taskStore.pageElements.slice(0, 20)" size="small" max-height="300">
          <el-table-column prop="tag" label="标签" width="80" />
          <el-table-column prop="type" label="类型" width="80" />
          <el-table-column prop="name" label="名称" width="120" show-overflow-tooltip />
          <el-table-column prop="text" label="文本" min-width="150" show-overflow-tooltip />
          <el-table-column prop="selector" label="选择器" min-width="150" show-overflow-tooltip />
        </el-table>
      </div>

      <template #footer>
        <el-button @click="showParseDialog = false">关闭</el-button>
        <el-button type="primary" @click="parsePage" :loading="parsing">开始解析</el-button>
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
import { ElMessage, ElMessageBox } from 'element-plus'
import { View, VideoPlay, Delete, Plus, Upload } from '@element-plus/icons-vue'

const ACCEPTED_EXTS = '.pdf,.docx,.doc,.xlsx,.xls,.pptx,.md,.txt,.csv,.html,.htm,.json'
const ACCEPTED_SET = new Set(ACCEPTED_EXTS.split(','))
const MAX_SIZE_MB = 20

const router = useRouter()
const taskStore = useTaskStore()
const wsStore = useWorkspaceStore()
const auth = useAuthStore()

const showCreateDialog = ref(false)
const showParseDialog = ref(false)
const creating = ref(false)
const parsing = ref(false)
const uploadRef = ref(null)
const uploadedFile = ref(null)
const fileError = ref('')

const taskForm = reactive({
  name: '',
  url: '',
  document_path: '',
  browser: 'chromium',
  environment: 'test'
})

const parseForm = reactive({
  url: '',
  browser: 'chromium'
})

const getStatusType = (status) => {
  const types = {
    created: 'info',
    parsing: 'warning',
    parsed: 'info',
    generating: 'warning',
    generated: 'info',
    executing: 'primary',
    reporting: 'warning',
    completed: 'success',
    failed: 'danger'
  }
  return types[status] || 'info'
}

const getStatusLabel = (status) => {
  const labels = {
    created: '已创建',
    parsing: '解析中',
    parsed: '已解析',
    generating: '生成中',
    generated: '已生成',
    executing: '执行中',
    reporting: '生成报告',
    completed: '已完成',
    failed: '失败'
  }
  return labels[status] || status
}

const getEnvLabel = (env) => {
  const labels = {
    test: '测试环境',
    staging: '预发环境',
    production: '生产环境'
  }
  return labels[env] || env
}

const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('zh-CN')
}

const handleFileChange = (file) => {
  fileError.value = ''
  const raw = file.raw
  // 扩展名校验
  const name = raw.name || ''
  const ext = ('.' + name.split('.').pop()).toLowerCase()
  if (!ACCEPTED_SET.has(ext)) {
    fileError.value = `不支持的文件格式「${ext}」，请选择：PDF / Word / Excel / PPTX / Markdown / TXT / CSV / HTML / JSON`
    uploadRef.value?.clearFiles()
    uploadedFile.value = null
    return
  }
  // 大小校验
  if (raw.size > MAX_SIZE_MB * 1024 * 1024) {
    fileError.value = `文件大小 ${(raw.size / 1024 / 1024).toFixed(1)} MB 超过限制（${MAX_SIZE_MB} MB）`
    uploadRef.value?.clearFiles()
    uploadedFile.value = null
    return
  }
  uploadedFile.value = raw
}

const handleFileRemove = () => {
  uploadedFile.value = null
  fileError.value = ''
}

const onDialogClose = () => {
  fileError.value = ''
  uploadedFile.value = null
  uploadRef.value?.clearFiles()
}

const createTask = async () => {
  if (!taskForm.name || !taskForm.url) {
    ElMessage.warning('请填写任务名称和URL')
    return
  }

  creating.value = true

  // Step 1: 上传文档（可选）
  let docPath = ''
  if (uploadedFile.value) {
    try {
      const uploadRes = await taskStore.uploadDocument(uploadedFile.value)
      docPath = uploadRes.path || ''
    } catch (err) {
      ElMessage.warning('需求文档上传失败，将跳过文档解析：' + (err.message || err))
    }
  }

  // Step 2: 创建任务（核心步骤，失败则终止）
  let task
  try {
    task = await taskStore.createTask({ ...taskForm, document_path: docPath, workspace_id: wsStore.currentId || null })
    ElMessage.success('任务创建成功')
    showCreateDialog.value = false
    resetForm()
  } catch (error) {
    ElMessage.error('任务创建失败: ' + (error.response?.data?.detail || error.message))
    creating.value = false
    return
  }

  // Step 3: 解析页面（失败给提示但不中断流程）
  try {
    ElMessage.info('正在解析页面元素...')
    await taskStore.parsePage(task.url, task.browser, task.id)
    ElMessage.success('页面解析完成')
  } catch (err) {
    ElMessage.warning('页面解析失败（可稍后在用例管理中手动解析）：' + (err.message || err))
    creating.value = false
    return
  }

  // Step 4: 解析文档（可选，失败继续）
  if (docPath) {
    try {
      ElMessage.info('正在解析需求文档...')
      await taskStore.parseDocument(docPath)
      ElMessage.success('需求文档解析完成')
    } catch (err) {
      ElMessage.warning('需求文档解析失败，AI 将仅依据页面元素生成用例')
    }
  }

  // Step 5: AI 生成用例
  try {
    ElMessage.info('正在生成测试用例...')
    await taskStore.generateCases(task.id)
    ElMessage.success('测试用例生成完成')
  } catch (err) {
    ElMessage.warning('用例生成失败（可稍后在用例管理中重新生成）：' + (err.message || err))
  }

  creating.value = false
}

const resetForm = () => {
  taskForm.name = ''
  taskForm.url = ''
  taskForm.document_path = ''
  taskForm.browser = 'chromium'
  taskForm.environment = 'test'
  uploadedFile.value = null
  fileError.value = ''
  uploadRef.value?.clearFiles()
}

const viewTask = (task) => {
  router.push({ name: 'Cases', query: { taskId: task.id } })
}

const startTest = (task) => {
  router.push({ name: 'Execution', query: { taskId: task.id } })
}

const deleteTask = async (task) => {
  try {
    await ElMessageBox.confirm('确定要删除这个任务吗?', '提示', {
      type: 'warning'
    })
    await taskStore.deleteTask(task.id)
    ElMessage.success('删除成功')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

const parsePage = async () => {
  if (!parseForm.url) {
    ElMessage.warning('请输入要解析的页面URL')
    return
  }

  parsing.value = true
  try {
    await taskStore.parsePage(parseForm.url, parseForm.browser)
    ElMessage.success('页面解析完成')
  } catch (error) {
    ElMessage.error('解析失败: ' + error.message)
  } finally {
    parsing.value = false
  }
}

onMounted(async () => {
  // 如果 workspace 已初始化直接 fetch；否则等 watch 触发
  if (wsStore.initialized) {
    await taskStore.fetchTasks(wsStore.currentId)
  }
})

// workspace 初始化完成 或 切换工作空间 时刷新列表
watch(() => wsStore.currentId, (id) => {
  taskStore.fetchTasks(id)
})
watch(() => wsStore.initialized, (ready) => {
  if (ready) taskStore.fetchTasks(wsStore.currentId)
})
</script>

<style scoped>
.tasks-page {
  padding: 0;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.action-btns {
  display: flex;
  align-items: center;
  gap: 2px;
}

.action-btns .el-button.is-link {
  padding: 4px 6px;
  font-size: 13px;
  gap: 3px;
}

.action-btns .el-divider--vertical {
  margin: 0 2px;
  height: 14px;
}
</style>
