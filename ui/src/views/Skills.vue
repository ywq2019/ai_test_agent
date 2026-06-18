<template>
  <div class="skills-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>技能管理</span>
          <el-button type="primary" @click="loadSkills">
            <el-icon><Refresh /></el-icon>
            刷新技能
          </el-button>
        </div>
      </template>

      <el-row :gutter="20" style="margin-bottom: 20px;">
        <el-col :span="6">
          <el-statistic title="技能总数" :value="skills.length" />
        </el-col>
        <el-col :span="6">
          <el-statistic title="内置技能" :value="builtInCount" />
        </el-col>
        <el-col :span="6">
          <el-statistic title="外部技能" :value="externalCount" />
        </el-col>
        <el-col :span="6">
          <el-statistic title="已启用" :value="enabledCount" />
        </el-col>
      </el-row>

      <el-table :data="skills" stripe style="width: 100%">
        <el-table-column prop="name" label="技能名称" min-width="150">
          <template #default="{ row }">
            <div class="skill-name">
              <el-icon><Box /></el-icon>
              <span>{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="250" show-overflow-tooltip />
        <el-table-column prop="category" label="类别" width="120">
          <template #default="{ row }">
            <el-tag :type="getCategoryType(row.category)">{{ row.category }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="version" label="版本" width="80">
          <template #default="{ row }">
            <el-tag type="info" size="small">v{{ row.version }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="触发词" width="200">
          <template #default="{ row }">
            <el-tag
              v-for="(trigger, idx) in (row.triggers || []).slice(0, 3)"
              :key="idx"
              size="small"
              style="margin-right: 5px;"
            >
              {{ trigger }}
            </el-tag>
            <span v-if="(row.triggers || []).length > 3">+{{ row.triggers.length - 3 }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="viewSkillDetail(row)">详情</el-button>
            <el-button size="small" type="success" @click="viewSkillFiles(row)">文件</el-button>
            <el-button size="small" type="warning" @click="reloadSkill(row)">重载</el-button>
            <el-button size="small" type="danger" @click="executeSkill(row)">执行</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="showDetailDialog" title="技能详情" width="700px">
      <div v-if="currentSkill" class="skill-detail">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="技能名称">{{ currentSkill.name }}</el-descriptions-item>
          <el-descriptions-item label="版本">{{ currentSkill.version }}</el-descriptions-item>
          <el-descriptions-item label="类别">
            <el-tag :type="getCategoryType(currentSkill.category)">{{ currentSkill.category }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="文件路径">{{ currentSkill.file_path }}</el-descriptions-item>
          <el-descriptions-item label="描述" :span="2">{{ currentSkill.description }}</el-descriptions-item>
        </el-descriptions>

        <el-divider>触发词</el-divider>
        <div class="triggers">
          <el-tag
            v-for="(trigger, idx) in currentSkill.triggers"
            :key="idx"
            style="margin-right: 8px; margin-bottom: 8px;"
          >
            {{ trigger }}
          </el-tag>
        </div>

        <el-divider>使用示例</el-divider>
        <div v-if="currentSkill.examples && currentSkill.examples.length > 0">
          <el-card
            v-for="(example, idx) in currentSkill.examples"
            :key="idx"
            shadow="never"
            style="margin-bottom: 10px; background: #f5f7fa;"
          >
            <code>{{ example }}</code>
          </el-card>
        </div>
        <el-empty v-else description="暂无示例" :image-size="60" />
      </div>
      <template #footer>
        <el-button @click="showDetailDialog = false">关闭</el-button>
        <el-button type="primary" @click="executeSkill(currentSkill)">执行技能</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showFilesDialog" title="技能文件" width="800px">
      <div v-if="skillFiles" class="skill-files">
        <el-alert :title="`技能路径: ${skillFiles.path}`" type="info" :closable="false" style="margin-bottom: 15px;" />
        <el-table :data="skillFiles.files" stripe max-height="400">
          <el-table-column prop="name" label="文件名" min-width="200" />
          <el-table-column prop="path" label="路径" min-width="250" show-overflow-tooltip />
          <el-table-column prop="type" label="类型" width="80">
            <template #default="{ row }">
              <el-tag size="small" type="info">{{ row.type || 'file' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="size" label="大小" width="100">
            <template #default="{ row }">
              {{ formatSize(row.size) }}
            </template>
          </el-table-column>
        </el-table>
      </div>
      <template #footer>
        <el-button @click="showFilesDialog = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showExecuteDialog" title="执行技能" width="600px">
      <el-form :model="executeForm" label-width="100px">
        <el-form-item label="技能名称">
          <el-input v-model="executeForm.skillName" disabled />
        </el-form-item>
        <el-form-item label="测试套件" v-if="executeForm.hasSuite">
          <el-select v-model="executeForm.suite" style="width: 100%">
            <el-option label="冒烟测试 (smoke)" value="smoke" />
            <el-option label="回归测试 (regression)" value="regression" />
            <el-option label="完整测试 (full)" value="full" />
          </el-select>
        </el-form-item>
        <el-form-item label="无头模式">
          <el-switch v-model="executeForm.headless" />
        </el-form-item>
      </el-form>
      <div v-if="executeResult" class="execute-result">
        <el-divider>执行结果</el-divider>
        <el-alert :type="executeResult.status === 'success' ? 'success' : 'error'" :title="executeResult.status">
          <pre style="max-height: 300px; overflow: auto; font-size: 12px;">{{ executeResult.stdout || executeResult.message }}</pre>
        </el-alert>
      </div>
      <template #footer>
        <el-button @click="showExecuteDialog = false">关闭</el-button>
        <el-button type="primary" @click="confirmExecute" :loading="executing">执行</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import request from '../api'

const skills = ref([])
const showDetailDialog = ref(false)
const showFilesDialog = ref(false)
const showExecuteDialog = ref(false)
const currentSkill = ref(null)
const skillFiles = ref(null)
const executing = ref(false)
const executeResult = ref(null)

const executeForm = reactive({
  skillName: '',
  suite: 'smoke',
  headless: true,
  hasSuite: true
})

const builtInCount = computed(() => skills.value.filter(s => s.category === 'internal').length)
const externalCount = computed(() => skills.value.filter(s => s.category === 'external' || s.file_path?.includes('support_web_skill')).length)
const enabledCount = computed(() => skills.value.length)

const loadSkills = async () => {
  try {
    const res = await request.get('/skills')
    skills.value = res.skills || []
    ElMessage.success(`已加载 ${skills.value.length} 个技能`)
  } catch (err) {
    ElMessage.error('加载技能失败: ' + err.message)
  }
}

const viewSkillDetail = (skill) => {
  currentSkill.value = skill
  showDetailDialog.value = true
}

const viewSkillFiles = async (skill) => {
  try {
    const res = await request.get(`/skills/${skill.name}/files`)
    skillFiles.value = res
    showFilesDialog.value = true
  } catch (err) {
    ElMessage.error('获取技能文件失败: ' + err.message)
  }
}

const reloadSkill = async (skill) => {
  try {
    await request.post(`/skills/${skill.name}/reload`)
    ElMessage.success(`技能 "${skill.name}" 已重载`)
    await loadSkills()
  } catch (err) {
    ElMessage.error('重载技能失败: ' + err.message)
  }
}

const executeSkill = (skill) => {
  currentSkill.value = skill
  executeForm.skillName = skill.name
  executeForm.hasSuite = skill.name.includes('web') || skill.name.includes('test')
  executeResult.value = null
  showExecuteDialog.value = true
}

const confirmExecute = async () => {
  executing.value = true
  executeResult.value = null
  try {
    const res = await request.post('/command', {
      message: `执行${executeForm.skillName}`
    })
    executeResult.value = res.result || res
    ElMessage.success('技能执行完成')
  } catch (err) {
    ElMessage.error('执行技能失败: ' + err.message)
  } finally {
    executing.value = false
  }
}

const getCategoryType = (category) => {
  const types = {
    'web-testing': 'success',
    'api-testing': 'warning',
    'test-generation': 'primary',
    'reporting': 'info',
    'execution': 'danger',
    'monitoring': ''
  }
  return types[category] || ''
}

const formatSize = (bytes) => {
  if (!bytes) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

onMounted(() => {
  loadSkills()
})
</script>

<style scoped>
.skills-page {
  padding: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.skill-name {
  display: flex;
  align-items: center;
  gap: 8px;
}

.skill-detail {
  padding: 10px;
}

.triggers {
  display: flex;
  flex-wrap: wrap;
}

.execute-result {
  margin-top: 15px;
}

.execute-result pre {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 10px;
  border-radius: 4px;
}
</style>
