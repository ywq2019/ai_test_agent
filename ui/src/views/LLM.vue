<template>
  <div class="llm-page">
    <!-- 当前配置状态栏 -->
    <el-card shadow="hover" class="status-card">
      <div class="status-row">
        <div class="status-item">
          <span class="status-label">当前模型</span>
          <el-tag type="primary" size="large">{{ currentStatus.model || '未配置' }}</el-tag>
        </div>
        <div class="status-item">
          <span class="status-label">API 地址</span>
          <span class="status-url">{{ currentStatus.apiUrl || '未配置' }}</span>
        </div>
        <div class="status-item">
          <span class="status-label">API Key</span>
          <el-tag :type="currentStatus.keyConfigured ? 'success' : 'danger'" size="small">
            {{ currentStatus.keyConfigured ? '已配置' : '未配置' }}
          </el-tag>
        </div>
        <div class="status-item">
          <span class="status-label">Temperature</span>
          <el-tag type="info" size="small">{{ currentStatus.temperature }}</el-tag>
        </div>
        <el-button type="primary" :loading="testing" @click="testConnection" style="margin-left:auto">
          <el-icon><Connection /></el-icon>测试连接
        </el-button>
      </div>
      <el-alert v-if="testResult" :type="testResult.success ? 'success' : 'error'"
        :title="testResult.success ? `连接成功 · ${testResult.model}` : `连接失败：${testResult.error}`"
        :closable="true" show-icon style="margin-top:12px" @close="testResult=null" />
    </el-card>

    <el-row :gutter="20" style="margin-top:20px">
      <!-- 左：配置表单 -->
      <el-col :span="14">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>模型配置</span>
              <div>
                <el-button size="small" @click="loadFromSaved" :disabled="!savedConfigs.length">
                  <el-icon><FolderOpened /></el-icon>读取保存
                </el-button>
                <el-button size="small" type="primary" @click="saveConfig" :loading="saving">
                  <el-icon><Check /></el-icon>保存生效
                </el-button>
              </div>
            </div>
          </template>

          <!-- 供应商快选 -->
          <div class="provider-pills">
            <span class="pills-label">快速选择供应商：</span>
            <el-check-tag
              v-for="p in providers"
              :key="p.name"
              :checked="selectedProvider === p.name"
              @change="selectProvider(p)"
              style="margin-right:8px;margin-bottom:6px"
            >{{ p.name }}</el-check-tag>
          </div>

          <el-divider style="margin:12px 0" />

          <el-form :model="form" label-width="110px">
            <!-- 模型 ID -->
            <el-form-item label="模型 ID">
              <el-select
                v-if="!customModelMode"
                v-model="form.modelId"
                filterable
                allow-create
                placeholder="选择或输入模型 ID"
                style="width:100%"
                @change="onModelIdChange"
              >
                <el-option-group v-for="(ms, pname) in groupedModels" :key="pname" :label="pname">
                  <el-option v-for="m in ms" :key="m.id" :label="m.name" :value="m.id">
                    <span>{{ m.name }}</span>
                    <span style="float:right;color:#aaa;font-size:12px">{{ m.id }}</span>
                  </el-option>
                </el-option-group>
              </el-select>
              <el-input v-else v-model="form.modelId" placeholder="输入任意模型 ID，如 my-model-v2" style="width:100%" />
              <el-button
                size="small"
                :type="customModelMode ? 'primary' : 'default'"
                style="margin-left:8px;flex-shrink:0"
                @click="customModelMode = !customModelMode"
              >{{ customModelMode ? '改用列表' : '自由输入' }}</el-button>
            </el-form-item>

            <!-- 显示名称 -->
            <el-form-item label="显示名称">
              <el-input v-model="form.modelName" placeholder="可选，用于界面展示" />
            </el-form-item>

            <!-- API URL -->
            <el-form-item label="API URL">
              <el-input v-model="form.apiUrl" placeholder="https://api.example.com/v1" clearable />
            </el-form-item>

            <!-- API Key -->
            <el-form-item label="API Key">
              <el-input
                v-model="form.apiKey"
                :type="showKey ? 'text' : 'password'"
                :placeholder="currentStatus.keyConfigured ? '已配置，留空则保留原有 Key' : '请输入 API Key'"
                clearable
              >
                <template #suffix>
                  <el-icon style="cursor:pointer" @click="showKey=!showKey">
                    <View v-if="!showKey" /><Hide v-else />
                  </el-icon>
                </template>
              </el-input>
            </el-form-item>

            <!-- Temperature -->
            <el-form-item label="Temperature">
              <div style="display:flex;align-items:center;gap:12px;width:100%">
                <el-slider v-model="form.temperature" :min="0" :max="2" :step="0.1" style="flex:1" show-stops />
                <el-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" :precision="1" style="width:90px" size="small" />
              </div>
              <div class="temp-hint">
                {{ tempHint }}
              </div>
            </el-form-item>
          </el-form>

          <!-- 保存到本地预设 -->
          <el-divider>保存为本地预设</el-divider>
          <div style="display:flex;gap:8px">
            <el-input v-model="presetName" placeholder="预设名称，如「DeepSeek生产」" clearable style="flex:1" />
            <el-button @click="saveAsPreset" :disabled="!presetName.trim()">
              <el-icon><Plus /></el-icon>保存预设
            </el-button>
          </div>
        </el-card>
      </el-col>

      <!-- 右：本地预设 -->
      <el-col :span="10">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>本地预设 <el-badge :value="savedConfigs.length" type="info" /></span>
              <el-button size="small" type="danger" text :disabled="!savedConfigs.length" @click="clearAllPresets">清空</el-button>
            </div>
          </template>

          <el-empty v-if="!savedConfigs.length" description="暂无预设，保存配置后在此显示" :image-size="60" />

          <div v-else class="preset-list">
            <div
              v-for="(cfg, idx) in savedConfigs"
              :key="idx"
              class="preset-item"
              :class="{ active: isActiveCfg(cfg) }"
            >
              <div class="preset-main">
                <div class="preset-name">{{ cfg.name }}</div>
                <el-tag size="small" type="info">{{ cfg.modelId }}</el-tag>
              </div>
              <div class="preset-meta">{{ cfg.apiUrl }}</div>
              <div class="preset-actions">
                <el-button size="small" type="primary" @click="applyPreset(cfg)">应用</el-button>
                <el-button size="small" type="danger" text @click="deletePreset(idx)">
                  <el-icon><Delete /></el-icon>
                </el-button>
              </div>
            </div>
          </div>
        </el-card>

        <!-- 常用供应商地址参考 -->
        <el-card shadow="hover" style="margin-top:16px">
          <template #header><span>常用 API 地址</span></template>
          <div class="url-ref-list">
            <div v-for="p in providers" :key="p.name" class="url-ref-item">
              <span class="url-provider">{{ p.name }}</span>
              <code class="url-code" @click="form.apiUrl = p.url" title="点击填入">{{ p.url }}</code>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../api'

const STORAGE_KEY = 'uitest_llm_presets'

const models = ref([])
const testing = ref(false)
const saving = ref(false)
const testResult = ref(null)
const showKey = ref(false)
const customModelMode = ref(false)
const presetName = ref('')
const selectedProvider = ref('')
const savedConfigs = ref(JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'))

const currentStatus = reactive({
  model: '',
  modelName: '',
  apiUrl: '',
  keyConfigured: false,
  temperature: 0.5
})

const form = reactive({
  modelId: '',
  modelName: '',
  apiUrl: '',
  apiKey: '',
  temperature: 0.5
})

const providers = [
  { name: 'DeepSeek',   url: 'https://api.deepseek.com/v1' },
  { name: 'OpenAI',     url: 'https://api.openai.com/v1' },
  { name: 'Anthropic',  url: 'https://api.anthropic.com/v1' },
  { name: 'Moonshot',   url: 'https://api.moonshot.cn/v1' },
  { name: 'Alibaba',    url: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { name: 'Google',     url: 'https://generativelanguage.googleapis.com/v1' },
  { name: '01AI',       url: 'https://api.01.ai/v1' },
  { name: '自定义',      url: '' },
]

const groupedModels = computed(() => {
  const g = {}
  models.value.forEach(m => {
    if (!g[m.provider]) g[m.provider] = []
    g[m.provider].push(m)
  })
  return g
})

const tempHint = computed(() => {
  const t = form.temperature
  if (t <= 0.3) return '低（输出更确定、稳定，适合精准任务）'
  if (t <= 0.7) return '中（推荐，平衡创造性与准确性）'
  if (t <= 1.2) return '较高（输出更多样化，适合创意任务）'
  return '高（输出随机性强，可能不稳定）'
})

const loadModels = async () => {
  try {
    const res = await request.get('/llm/models')
    models.value = res.models || []
    currentStatus.model = res.current_model
    currentStatus.modelName = res.current_model_name
    currentStatus.apiUrl = res.current_api_url
    currentStatus.keyConfigured = res.api_key_configured
    currentStatus.temperature = res.temperature ?? 0.5
    form.modelId = res.current_model
    form.modelName = res.current_model_name || ''
    form.apiUrl = res.current_api_url || ''
    form.temperature = res.temperature ?? 0.5
  } catch (err) {
    ElMessage.error('加载模型列表失败: ' + err.message)
  }
}

const selectProvider = (p) => {
  selectedProvider.value = p.name
  if (p.url) form.apiUrl = p.url
  if (p.name === '自定义') customModelMode.value = true
}

const onModelIdChange = (id) => {
  const m = models.value.find(x => x.id === id)
  if (m) {
    form.modelName = m.name
    const p = providers.find(x => x.name === m.provider)
    if (p?.url && !form.apiUrl) form.apiUrl = p.url
  }
}

const saveConfig = async () => {
  if (!form.modelId) {
    ElMessage.warning('请选择或输入模型 ID')
    return
  }
  saving.value = true
  try {
    await request.put('/llm/model', {
      model: form.modelId,
      model_name: form.modelName || form.modelId,
      api_key: form.apiKey || undefined,
      api_url: form.apiUrl || undefined,
      temperature: form.temperature
    })
    ElMessage.success('配置已保存并生效')
    form.apiKey = ''
    await loadModels()
  } catch (err) {
    ElMessage.error('保存失败: ' + err.message)
  } finally {
    saving.value = false
  }
}

const testConnection = async () => {
  testing.value = true
  testResult.value = null
  try {
    const res = await request.post('/llm/test', {
      model: form.modelId || currentStatus.model,
      api_key: form.apiKey || undefined,
      api_url: form.apiUrl || currentStatus.apiUrl
    })
    testResult.value = res
    if (!res.success) ElMessage.error('连接失败: ' + res.error)
  } catch (err) {
    testResult.value = { success: false, error: err.message }
  } finally {
    testing.value = false
  }
}

const saveAsPreset = () => {
  if (!form.modelId) {
    ElMessage.warning('请先填写模型 ID')
    return
  }
  const cfg = {
    name: presetName.value.trim(),
    modelId: form.modelId,
    modelName: form.modelName,
    apiUrl: form.apiUrl,
    temperature: form.temperature
  }
  savedConfigs.value.unshift(cfg)
  localStorage.setItem(STORAGE_KEY, JSON.stringify(savedConfigs.value))
  presetName.value = ''
  ElMessage.success(`预设「${cfg.name}」已保存`)
}

const applyPreset = (cfg) => {
  form.modelId = cfg.modelId
  form.modelName = cfg.modelName || ''
  form.apiUrl = cfg.apiUrl || ''
  form.temperature = cfg.temperature ?? 0.5
  customModelMode.value = !models.value.find(m => m.id === cfg.modelId)
  ElMessage.info(`已填入预设「${cfg.name}」，点击「保存生效」提交`)
}

const deletePreset = async (idx) => {
  const name = savedConfigs.value[idx].name
  try {
    await ElMessageBox.confirm(`删除预设「${name}」？`, '确认', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    savedConfigs.value.splice(idx, 1)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(savedConfigs.value))
  } catch {}
}

const clearAllPresets = async () => {
  try {
    await ElMessageBox.confirm('清空所有本地预设？', '确认', { type: 'warning' })
    savedConfigs.value = []
    localStorage.removeItem(STORAGE_KEY)
  } catch {}
}

const loadFromSaved = () => {
  if (!savedConfigs.value.length) return
  applyPreset(savedConfigs.value[0])
}

const isActiveCfg = (cfg) => cfg.modelId === currentStatus.model && cfg.apiUrl === currentStatus.apiUrl

onMounted(loadModels)
</script>

<style scoped>
.llm-page { padding: 0; }

.status-card .status-row {
  display: flex;
  align-items: center;
  gap: 24px;
  flex-wrap: wrap;
}

.status-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-label {
  font-size: 13px;
  color: #909399;
}

.status-url {
  font-size: 12px;
  color: #606266;
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.provider-pills {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}

.pills-label {
  font-size: 13px;
  color: #606266;
  margin-right: 4px;
}

.temp-hint {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.preset-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 360px;
  overflow-y: auto;
}

.preset-item {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 10px 12px;
  transition: all 0.2s;
}

.preset-item:hover { border-color: #409eff; background: #f5f9ff; }
.preset-item.active { border-color: #67c23a; background: #f0f9eb; }

.preset-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.preset-name { font-weight: 600; font-size: 14px; }

.preset-meta {
  font-size: 12px;
  color: #909399;
  margin-bottom: 8px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preset-actions {
  display: flex;
  justify-content: flex-end;
  gap: 4px;
}

.url-ref-list { display: flex; flex-direction: column; gap: 8px; }

.url-ref-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.url-provider {
  font-size: 12px;
  color: #606266;
  min-width: 64px;
  font-weight: 500;
}

.url-code {
  font-size: 11px;
  background: #f5f7fa;
  padding: 2px 6px;
  border-radius: 4px;
  cursor: pointer;
  color: #409eff;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.url-code:hover { background: #ecf5ff; }
</style>
