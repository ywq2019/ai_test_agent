<template>
  <div class="mock-page">
    <div class="page-header">
      <el-button type="primary" :icon="Plus" @click="showDialog(null)">新建规则</el-button>
      <span style="font-size:13px;color:#909399;margin-left:12px">
        Mock 服务地址：<code style="background:#f0f0f0;padding:2px 6px;border-radius:4px">{{ mockBaseUrl }}/mock/your/path</code>
      </span>
    </div>

    <el-table :data="rules" stripe v-loading="loading" style="margin-top:12px">
      <el-table-column label="启用" width="65" align="center">
        <template #default="{ row }">
          <el-switch v-model="row.enabled" @change="toggleRule(row)" />
        </template>
      </el-table-column>
      <el-table-column label="名称" prop="name" min-width="140" show-overflow-tooltip />
      <el-table-column label="方法" width="80" align="center">
        <template #default="{ row }">
          <el-tag :type="methodColor(row.method)" size="small">{{ row.method }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="路径" prop="path" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">
          <code style="font-size:12px">/mock{{ row.path }}</code>
        </template>
      </el-table-column>
      <el-table-column label="状态码" width="80" align="center" prop="status_code" />
      <el-table-column label="延迟" width="80" align="center">
        <template #default="{ row }">{{ row.delay_ms ? `${row.delay_ms}ms` : '—' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="120" align="center">
        <template #default="{ row }">
          <el-button size="small" text type="primary" @click="showDialog(row)">编辑</el-button>
          <el-button size="small" text type="danger" @click="deleteRule(row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新建/编辑 Dialog -->
    <el-dialog v-model="dialogVisible" :title="editing ? '编辑规则' : '新建规则'" width="640px">
      <el-form :model="form" label-width="90px" size="small">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="HTTP 方法">
              <el-select v-model="form.method" style="width:100%">
                <el-option v-for="m in ['GET','POST','PUT','DELETE','PATCH','ANY']" :key="m" :label="m" :value="m" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="16">
            <el-form-item label="路径">
              <el-input v-model="form.path" placeholder="/api/users/{id}">
                <template #prepend>/mock</template>
              </el-input>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="状态码">
              <el-input-number v-model="form.status_code" :min="100" :max="599" controls-position="right" style="width:100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="延迟(ms)">
              <el-input-number v-model="form.delay_ms" :min="0" :max="30000" controls-position="right" style="width:100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="启用">
              <el-switch v-model="form.enabled" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="匹配参数">
          <div style="width:100%">
            <div style="font-size:12px;color:#909399;margin-bottom:6px">
              GET：填 Query 参数；POST/PUT：填 Body 字段名。留空则匹配所有请求，填了则仅当请求包含这些字段时命中。
            </div>
            <div v-for="(row, i) in form.matchParamRows" :key="i"
              style="display:flex;gap:6px;margin-bottom:6px;align-items:center">
              <el-input v-model="row.key" placeholder="参数名" style="flex:1" size="small" />
              <el-input v-model="row.value" placeholder="期望值（留空=仅要求字段存在）" style="flex:2" size="small" />
              <el-button size="small" text type="danger" @click="form.matchParamRows.splice(i,1)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
            <el-button size="small" @click="form.matchParamRows.push({key:'',value:''})">+ 添加匹配参数</el-button>
          </div>
        </el-form-item>
        <el-form-item label="响应头">
          <div style="width:100%">
            <div v-for="(row, i) in form.headerRows" :key="i"
              style="display:flex;gap:6px;margin-bottom:6px;align-items:center">
              <el-input v-model="row.key" placeholder="Header 名" style="flex:1" size="small" />
              <el-input v-model="row.value" placeholder="值" style="flex:2" size="small" />
              <el-button size="small" text type="danger" @click="form.headerRows.splice(i,1)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
            <el-button size="small" @click="form.headerRows.push({key:'',value:''})">+ 添加</el-button>
          </div>
        </el-form-item>
        <el-form-item label="响应体">
          <el-input v-model="form.response_body" type="textarea" :rows="8"
            placeholder='{"code": 0, "data": {"id": "{{param0}}"}, "message": "success"}'
            style="font-family:monospace;font-size:12px" />
          <div style="font-size:12px;color:#909399;margin-top:4px">
            路径参数可用 <code>&#123;&#123;param0&#125;&#125;</code>、<code>&#123;&#123;param1&#125;&#125;</code> 引用；查询参数用 <code>&#123;&#123;key_name&#125;&#125;</code>
          </div>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveRule" :loading="saving">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete } from '@element-plus/icons-vue'
import api from '../api'
import { useWorkspaceStore } from '../stores/workspace'

const wsStore = useWorkspaceStore()

const rules = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const editing = ref(null)
const saving = ref(false)

const mockBaseUrl = computed(() => window.location.origin)

const form = reactive({
  name: '', method: 'GET', path: '/', status_code: 200, delay_ms: 0,
  enabled: true, description: '', response_body: '{"code": 0, "data": {}}',
  headerRows: [{ key: 'Content-Type', value: 'application/json' }],
  matchParamRows: [],  // [{key, value}] 请求匹配参数
})

const methodColor = (m) => ({
  GET: 'success', POST: 'primary', PUT: 'warning', DELETE: 'danger', PATCH: 'warning', ANY: 'info'
}[m] || 'info')

const loadRules = async () => {
  loading.value = true
  try {
    const params = wsStore.currentId ? { workspace_id: wsStore.currentId } : {}
    const res = await api.get('/mock/rules', { params })
    rules.value = res
  } finally {
    loading.value = false
  }
}

const showDialog = (rule) => {
  editing.value = rule
  if (rule) {
    Object.assign(form, {
      name: rule.name, method: rule.method, path: rule.path,
      status_code: rule.status_code, delay_ms: rule.delay_ms || 0,
      enabled: rule.enabled, description: rule.description || '',
      response_body: rule.response_body || '',
      headerRows: Object.entries(rule.response_headers || {}).map(([k, v]) => ({ key: k, value: v })),
      matchParamRows: Object.entries(rule.match_params || {}).map(([k, v]) => ({ key: k, value: v })),
    })
  } else {
    Object.assign(form, {
      name: '', method: 'GET', path: '/', status_code: 200, delay_ms: 0,
      enabled: true, description: '', response_body: '{"code": 0, "data": {}}',
      headerRows: [{ key: 'Content-Type', value: 'application/json' }],
      matchParamRows: [],
    })
  }
  dialogVisible.value = true
}

const saveRule = async () => {
  if (!form.name || !form.path) return ElMessage.warning('名称和路径必填')
  saving.value = true
  try {
    const payload = {
      name: form.name, method: form.method, path: form.path,
      status_code: form.status_code, delay_ms: form.delay_ms,
      enabled: form.enabled, description: form.description,
      response_body: form.response_body,
      response_headers: Object.fromEntries(
        form.headerRows.filter(r => r.key.trim()).map(r => [r.key.trim(), r.value])
      ),
      match_params: Object.fromEntries(
        form.matchParamRows.filter(r => r.key.trim()).map(r => [r.key.trim(), r.value])
      ),
      workspace_id: wsStore.currentId || null,
    }
    if (editing.value) {
      const updated = await api.put(`/mock/rules/${editing.value.id}`, payload)
      const idx = rules.value.findIndex(r => r.id === updated.id)
      if (idx !== -1) rules.value[idx] = updated
      ElMessage.success('规则已更新')
    } else {
      const created = await api.post('/mock/rules', payload)
      rules.value.unshift(created)
      ElMessage.success('规则已创建')
    }
    dialogVisible.value = false
  } catch (e) {
    ElMessage.error('保存失败：' + (e?.response?.data?.detail || e?.message))
  } finally {
    saving.value = false
  }
}

const toggleRule = async (rule) => {
  try {
    await api.put(`/mock/rules/${rule.id}`, { enabled: rule.enabled })
  } catch (e) {
    rule.enabled = !rule.enabled
    ElMessage.error('更新失败')
  }
}

const deleteRule = async (id) => {
  await ElMessageBox.confirm('确定删除该规则？', '警告', { type: 'warning' })
  await api.delete(`/mock/rules/${id}`)
  rules.value = rules.value.filter(r => r.id !== id)
  ElMessage.success('已删除')
}

onMounted(loadRules)
</script>

<style scoped>
.mock-page { padding: 0; }
.page-header { display: flex; align-items: center; margin-bottom: 4px; }
</style>
