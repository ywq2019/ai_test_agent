<template>
  <div class="llm-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>大模型配置</span>
          <el-button type="primary" @click="loadModels">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </template>

      <el-form :model="llmConfig" label-width="120px" style="max-width: 600px;">
        <el-form-item label="当前模型">
          <el-select v-model="llmConfig.currentModel" style="width: 100%;" @change="onModelChange">
            <el-option-group
              v-for="(models, provider) in groupedModels"
              :key="provider"
              :label="provider"
            >
              <el-option
                v-for="model in models"
                :key="model.id"
                :label="model.name"
                :value="model.id"
              >
                <span style="float: left">{{ model.name }}</span>
                <span style="float: right; color: #8492a6; font-size: 13px;">{{ model.id }}</span>
              </el-option>
            </el-option-group>
          </el-select>
        </el-form-item>
        <el-form-item label="API URL">
          <el-input
            v-model="llmConfig.apiUrl"
            placeholder="https://api.openai.com/v1"
            @blur="saveConfig"
          />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="llmConfig.apiKey"
            type="password"
            placeholder="请输入API Key"
            show-password
            @blur="saveConfig"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="success" @click="testConnection" :loading="testing">
            测试连接
          </el-button>
          <el-button type="primary" @click="saveConfig" :loading="saving">
            保存配置
          </el-button>
        </el-form-item>
      </el-form>

      <el-divider>连接测试结果</el-divider>
      <div v-if="testResult" class="test-result">
        <el-alert
          :type="testResult.success ? 'success' : 'error'"
          :title="testResult.success ? '连接成功' : '连接失败'"
          :description="testResult.error || testResult.message"
          show-icon
          :closable="false"
        />
      </div>
    </el-card>

    <el-card shadow="hover" style="margin-top: 20px;">
      <template #header>
        <span>可用模型列表</span>
      </template>

      <el-table :data="models" stripe style="width: 100%">
        <el-table-column prop="id" label="模型ID" min-width="150" />
        <el-table-column prop="name" label="名称" min-width="120" />
        <el-table-column prop="provider" label="供应商" width="120">
          <template #default="{ row }">
            <el-tag :type="getProviderType(row.provider)">{{ row.provider }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button
              size="small"
              :type="row.id === llmConfig.currentModel ? 'success' : 'default'"
              :disabled="row.id === llmConfig.currentModel"
              @click="selectModel(row)"
            >
              {{ row.id === llmConfig.currentModel ? '已选择' : '选择' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="hover" style="margin-top: 20px;">
      <template #header>
        <span>提示信息</span>
      </template>
      <el-alert type="info" :closable="false">
        <template #title>
          <ul style="margin: 0; padding-left: 20px;">
            <li>不同供应商的模型需要配置对应的API URL</li>
            <li>OpenAI系列: <code>https://api.openai.com/v1</code></li>
            <li>Moonshot系列: <code>https://api.moonshot.cn/v1</code></li>
            <li>DeepSeek系列: <code>https://api.deepseek.com/v1</code></li>
            <li>阿里Qwen系列: <code>https://dashscope.aliyuncs.com/compatible-mode/v1</code></li>
            <li>切换模型后，系统会自动保存配置</li>
          </ul>
        </template>
      </el-alert>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import request from '../api'

const models = ref([])
const testing = ref(false)
const saving = ref(false)
const testResult = ref(null)

const llmConfig = reactive({
  apiUrl: '',
  apiKey: '',
  currentModel: ''
})

const groupedModels = computed(() => {
  const groups = {}
  models.value.forEach(model => {
    if (!groups[model.provider]) {
      groups[model.provider] = []
    }
    groups[model.provider].push(model)
  })
  return groups
})

const loadModels = async () => {
  try {
    const res = await request.get('/llm/models')
    models.value = res.models || []
    llmConfig.currentModel = res.current_model
    llmConfig.apiUrl = res.current_api_url
    llmConfig.apiKey = ''
    testResult.value = null
  } catch (err) {
    ElMessage.error('加载模型列表失败: ' + err.message)
  }
}

const testConnection = async () => {
  if (!llmConfig.apiKey) {
    ElMessage.warning('请先输入API Key')
    return
  }

  testing.value = true
  testResult.value = null

  try {
    const res = await request.post('/llm/test', {
      model: llmConfig.currentModel,
      api_key: llmConfig.apiKey,
      api_url: llmConfig.apiUrl
    })
    testResult.value = res
    if (res.success) {
      ElMessage.success('连接测试成功')
    } else {
      ElMessage.error('连接测试失败: ' + res.error)
    }
  } catch (err) {
    ElMessage.error('测试连接失败: ' + err.message)
  } finally {
    testing.value = false
  }
}

const saveConfig = async () => {
  if (!llmConfig.currentModel) {
    return
  }

  saving.value = true
  try {
    await request.put('/llm/model', {
      model: llmConfig.currentModel,
      api_key: llmConfig.apiKey || undefined,
      api_url: llmConfig.apiUrl || undefined
    })
    ElMessage.success('配置已保存')
  } catch (err) {
    ElMessage.error('保存配置失败: ' + err.message)
  } finally {
    saving.value = false
  }
}

const onModelChange = async () => {
  const model = models.value.find(m => m.id === llmConfig.currentModel)
  if (!model) return

  const providerUrls = {
    'OpenAI': 'https://api.openai.com/v1',
    'Anthropic': 'https://api.anthropic.com/v1',
    'Google': 'https://generativelanguage.googleapis.com/v1',
    'Moonshot': 'https://api.moonshot.cn/v1',
    'DeepSeek': 'https://api.deepseek.com/v1',
    'Alibaba': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    '01AI': 'https://api.01.ai/v1'
  }

  if (providerUrls[model.provider]) {
    llmConfig.apiUrl = providerUrls[model.provider]
    ElMessage.info(`已自动切换到 ${model.provider} 的API URL`)
  }
}

const selectModel = async (model) => {
  llmConfig.currentModel = model.id

  const providerUrls = {
    'OpenAI': 'https://api.openai.com/v1',
    'Anthropic': 'https://api.anthropic.com/v1',
    'Google': 'https://generativelanguage.googleapis.com/v1',
    'Moonshot': 'https://api.moonshot.cn/v1',
    'DeepSeek': 'https://api.deepseek.com/v1',
    'Alibaba': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    '01AI': 'https://api.01.ai/v1'
  }

  if (providerUrls[model.provider]) {
    llmConfig.apiUrl = providerUrls[model.provider]
  }

  await saveConfig()
  await loadModels()
}

const getProviderType = (provider) => {
  const types = {
    'OpenAI': 'success',
    'Anthropic': 'warning',
    'Google': 'info',
    'Moonshot': 'primary',
    'DeepSeek': 'danger',
    'Alibaba': '',
    '01AI': 'info'
  }
  return types[provider] || ''
}

onMounted(() => {
  loadModels()
})
</script>

<style scoped>
.llm-page {
  padding: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.test-result {
  margin-top: 15px;
}

code {
  background: #f5f7fa;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: monospace;
}
</style>
