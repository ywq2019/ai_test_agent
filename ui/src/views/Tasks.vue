<template>
  <div class="tasks-page">
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
            <el-tag type="info">{{ row.environment }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="180">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="viewTask(row)">查看</el-button>
            <el-button size="small" type="success" @click="startTest(row)">开始测试</el-button>
            <el-button size="small" type="danger" @click="deleteTask(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="showCreateDialog" title="创建测试任务" width="600px">
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
            accept=".pdf,.docx,.doc"
            :on-change="handleFileChange"
          >
            <el-button>选择文件</el-button>
            <template #tip>
              <div class="el-upload__tip">支持PDF、DOC、DOCX格式</div>
            </template>
          </el-upload>
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
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useTaskStore } from '../stores/task'
import { ElMessage, ElMessageBox } from 'element-plus'

const router = useRouter()
const taskStore = useTaskStore()

const showCreateDialog = ref(false)
const showParseDialog = ref(false)
const creating = ref(false)
const parsing = ref(false)
const uploadRef = ref(null)
const uploadedFile = ref(null)

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
    generating: 'warning',
    executing: 'primary',
    completed: 'success',
    failed: 'danger'
  }
  return types[status] || 'info'
}

const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('zh-CN')
}

const handleFileChange = (file) => {
  uploadedFile.value = file.raw
}

const createTask = async () => {
  if (!taskForm.name || !taskForm.url) {
    ElMessage.warning('请填写任务名称和URL')
    return
  }

  creating.value = true
  try {
    if (uploadedFile.value) {
      const uploadRes = await taskStore.uploadDocument(uploadedFile.value)
      taskForm.document_path = uploadRes.path
    }

    const task = await taskStore.createTask(taskForm)
    ElMessage.success('任务创建成功')
    showCreateDialog.value = false
    resetForm()

    ElMessage.info('正在解析页面元素...')
    await taskStore.parsePage(task.url, task.browser, task.id)
    ElMessage.success('页面解析完成，可前往测试用例管理生成测试用例')
  } catch (error) {
    ElMessage.error('创建失败: ' + error.message)
  } finally {
    creating.value = false
  }
}

const resetForm = () => {
  taskForm.name = ''
  taskForm.url = ''
  taskForm.document_path = ''
  taskForm.browser = 'chromium'
  taskForm.environment = 'test'
  uploadedFile.value = null
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
  await taskStore.fetchTasks()
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
</style>
