<template>
  <div class="cases-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <div>
            <span>测试用例管理</span>
            <el-select v-model="filterTaskId" placeholder="选择任务" style="margin-left: 20px; width: 200px;" @change="fetchCasesByTask">
              <el-option label="全部任务" :value="null" />
              <el-option v-for="task in taskStore.tasks" :key="task.id" :label="task.name" :value="task.id" />
            </el-select>
          </div>
          <div>
            <el-button type="primary" @click="showCreateDialog = true">
              <el-icon><Plus /></el-icon>
              新建用例
            </el-button>
            <el-button type="success" @click="generateCases" :loading="generating">
              <el-icon><MagicStick /></el-icon>
              AI生成用例
            </el-button>
          </div>
        </div>
      </template>

      <el-table :data="filteredCases" stripe style="width: 100%" @selection-change="handleSelectionChange">
        <el-table-column type="selection" width="50" />
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="name" label="用例名称" min-width="150" show-overflow-tooltip />
        <el-table-column prop="module" label="模块" width="120" />
        <el-table-column prop="priority" label="优先级" width="80">
          <template #default="{ row }">
            <el-tag :type="getPriorityType(row.priority)">{{ row.priority }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="steps" label="测试步骤" min-width="200" show-overflow-tooltip />
        <el-table-column prop="expected_results" label="预期结果" min-width="150" show-overflow-tooltip />
        <el-table-column prop="enabled" label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'">
              {{ row.enabled ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="editCase(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="deleteCase(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div style="margin-top: 20px;">
        <el-button @click="toggleAllSelection">全选</el-button>
        <el-button @click="batchEnable">批量启用</el-button>
        <el-button @click="batchDisable">批量禁用</el-button>
        <el-button type="danger" @click="batchDelete">批量删除</el-button>
      </div>
    </el-card>

    <el-dialog v-model="showCreateDialog" :title="editingCase ? '编辑用例' : '新建用例'" width="700px">
      <el-form :model="caseForm" label-width="100px">
        <el-form-item label="所属任务">
          <el-select v-model="caseForm.task_id" style="width: 100%">
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
          <el-select v-model="caseForm.priority" style="width: 100%">
            <el-option label="P0 - 核心必测" value="P0" />
            <el-option label="P1 - 常规测试" value="P1" />
            <el-option label="P2 - 次要场景" value="P2" />
          </el-select>
        </el-form-item>
        <el-form-item label="前置条件">
          <el-input v-model="caseForm.preconditions" type="textarea" :rows="2" placeholder="请输入前置条件" />
        </el-form-item>
        <el-form-item label="测试步骤">
          <el-input v-model="caseForm.steps" type="textarea" :rows="3" placeholder="请输入测试步骤" />
        </el-form-item>
        <el-form-item label="预期结果">
          <el-input v-model="caseForm.expected_results" type="textarea" :rows="2" placeholder="请输入预期结果" />
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
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useTaskStore } from '../stores/task'
import { ElMessage, ElMessageBox } from 'element-plus'

const route = useRoute()
const taskStore = useTaskStore()

const filterTaskId = ref(null)
const showCreateDialog = ref(false)
const editingCase = ref(null)
const saving = ref(false)
const generating = ref(false)
const selectedCases = ref([])

const caseForm = reactive({
  task_id: null,
  name: '',
  module: '通用',
  priority: 'P1',
  preconditions: '',
  steps: '',
  expected_results: '',
  enabled: true
})

const filteredCases = computed(() => {
  if (!filterTaskId.value) return taskStore.cases
  return taskStore.cases.filter(c => c.task_id === filterTaskId.value)
})

const getPriorityType = (priority) => {
  const types = { P0: 'danger', P1: 'warning', P2: 'info' }
  return types[priority] || 'info'
}

const fetchCasesByTask = async () => {
  if (filterTaskId.value) {
    await taskStore.fetchCases(filterTaskId.value)
    await taskStore.getTask(filterTaskId.value)
  }
}

const generateCases = async () => {
  if (!filterTaskId.value) {
    ElMessage.warning('请先选择任务')
    return
  }

  generating.value = true
  try {
    await taskStore.generateCases(filterTaskId.value)
    ElMessage.success('用例生成成功')
  } catch (error) {
    ElMessage.error('生成失败: ' + error.message)
  } finally {
    generating.value = false
  }
}

const handleSelectionChange = (selection) => {
  selectedCases.value = selection
}

const toggleAllSelection = () => {
}

const batchEnable = async () => {
  if (selectedCases.value.length === 0) {
    ElMessage.warning('请先选择用例')
    return
  }
  for (const c of selectedCases.value) {
    await taskStore.updateCase(c.id, { enabled: true })
  }
  ElMessage.success('批量启用成功')
}

const batchDisable = async () => {
  if (selectedCases.value.length === 0) {
    ElMessage.warning('请先选择用例')
    return
  }
  for (const c of selectedCases.value) {
    await taskStore.updateCase(c.id, { enabled: false })
  }
  ElMessage.success('批量禁用成功')
}

const batchDelete = async () => {
  if (selectedCases.value.length === 0) {
    ElMessage.warning('请先选择用例')
    return
  }
  try {
    await ElMessageBox.confirm(`确定要删除选中的 ${selectedCases.value.length} 个用例吗?`, '提示', { type: 'warning' })
    for (const c of selectedCases.value) {
      await taskStore.deleteCase(c.id)
    }
    ElMessage.success('批量删除成功')
  } catch (error) {
    if (error !== 'cancel') ElMessage.error('删除失败')
  }
}

const editCase = (row) => {
  editingCase.value = row
  Object.assign(caseForm, {
    task_id: row.task_id,
    name: row.name,
    module: row.module,
    priority: row.priority,
    preconditions: row.preconditions,
    steps: row.steps,
    expected_results: row.expected_results,
    enabled: row.enabled
  })
  showCreateDialog.value = true
}

const saveCase = async () => {
  if (!caseForm.name || !caseForm.steps) {
    ElMessage.warning('请填写用例名称和测试步骤')
    return
  }

  saving.value = true
  try {
    if (editingCase.value) {
      await taskStore.updateCase(editingCase.value.id, caseForm)
      ElMessage.success('更新成功')
    } else {
      await taskStore.createCase(caseForm)
      ElMessage.success('创建成功')
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
  } catch (error) {
    if (error !== 'cancel') ElMessage.error('删除失败')
  }
}

const resetForm = () => {
  caseForm.task_id = filterTaskId.value || null
  caseForm.name = ''
  caseForm.module = '通用'
  caseForm.priority = 'P1'
  caseForm.preconditions = ''
  caseForm.steps = ''
  caseForm.expected_results = ''
  caseForm.enabled = true
  editingCase.value = null
}

onMounted(async () => {
  await taskStore.fetchTasks()
  if (route.query.taskId) {
    filterTaskId.value = parseInt(route.query.taskId)
    caseForm.task_id = filterTaskId.value
  }
  if (filterTaskId.value) {
    await taskStore.fetchCases(filterTaskId.value)
  }
})
</script>

<style scoped>
.cases-page {
  padding: 0;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
