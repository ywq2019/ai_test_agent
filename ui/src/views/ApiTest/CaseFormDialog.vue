<template>
  <el-dialog
    v-model="visible"
    :title="editingCase ? '编辑用例' : '新建用例'"
    width="640px"
    @open="handleOpen"
  >
    <el-form :model="form" label-width="90px" size="small">
      <el-form-item label="用例名称" required>
        <el-input v-model="form.name" />
      </el-form-item>
      <el-form-item label="接口描述">
        <el-input v-model="form.description" placeholder="描述该接口的用途（同路径用例共享）" />
      </el-form-item>
      <el-row :gutter="12">
        <el-col :span="8">
          <el-form-item label="HTTP方法">
            <el-select v-model="form.method" style="width:100%">
              <el-option v-for="m in ['GET','POST','PUT','DELETE','PATCH']" :key="m" :label="m" :value="m" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="16">
          <el-form-item label="路径">
            <el-input v-model="form.path" placeholder="/users/{id}" />
          </el-form-item>
        </el-col>
      </el-row>
      <el-row :gutter="12">
        <el-col :span="12">
          <el-form-item label="模块">
            <el-autocomplete
              v-model="form.module"
              :fetch-suggestions="queryModules"
              placeholder="选择或输入模块名"
              style="width:100%"
              clearable
            />
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item label="优先级">
            <el-select v-model="form.priority" style="width:100%">
              <el-option label="P0" value="P0" />
              <el-option label="P1" value="P1" />
              <el-option label="P2" value="P2" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item label="超时(ms)">
            <el-input-number v-model="form.timeout_ms" :min="500" :max="300000" :step="1000"
              controls-position="right" style="width:100%"
              placeholder="留空=默认30s" :precision="0" />
          </el-form-item>
        </el-col>
      </el-row>

      <!-- Headers -->
      <el-form-item label="Headers">
        <div style="width:100%">
          <div
            v-for="(row, i) in form.headersRows" :key="i"
            style="display:flex;gap:6px;margin-bottom:6px;align-items:center"
          >
            <el-input v-model="row.key" placeholder="Header名" style="flex:1.2" size="small" />
            <el-input v-model="row.value" placeholder="值" style="flex:2" size="small" />
            <FnInsertBtn :fn-list="fnList" @insert="(fn) => insertFn(row, fn)" />
            <el-button size="small" text type="danger" @click="form.headersRows.splice(i, 1)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
          <el-button size="small" :icon="Plus" @click="form.headersRows.push({ key: '', value: '' })">添加 Header</el-button>
        </div>
      </el-form-item>

      <!-- Query Params -->
      <el-form-item label="Query Params">
        <div style="width:100%">
          <div
            v-for="(row, i) in form.paramsRows" :key="i"
            style="display:flex;gap:6px;margin-bottom:6px;align-items:center"
          >
            <el-input v-model="row.key" placeholder="参数名" style="flex:1" size="small" />
            <el-input v-model="row.value" placeholder="参数值" style="flex:2" size="small" />
            <FnInsertBtn :fn-list="fnList" @insert="(fn) => insertFn(row, fn)" />
            <el-button size="small" text type="danger" @click="form.paramsRows.splice(i, 1)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
          <el-button size="small" :icon="Plus" @click="form.paramsRows.push({ key: '', value: '' })">添加参数</el-button>
        </div>
      </el-form-item>

      <!-- 请求体 -->
      <el-form-item label="请求体">
        <div style="width:100%">
          <el-radio-group v-model="form.bodyType" size="small" style="margin-bottom:8px" @change="onBodyTypeChange">
            <el-radio-button value="none">无</el-radio-button>
            <el-radio-button value="json">JSON</el-radio-button>
            <el-radio-button value="form">Form 表单</el-radio-button>
            <el-radio-button value="raw">原始文本</el-radio-button>
          </el-radio-group>
          <div v-if="form.bodyType === 'json'">
            <div v-if="fnList.length" style="margin-bottom:4px;display:flex;align-items:center;gap:6px">
              <span style="font-size:12px;color:#909399">插入函数：</span>
              <el-dropdown trigger="click" @command="(fn) => form.bodyStr += fn">
                <el-button size="small" style="font-family:monospace;font-size:12px">ƒ(x)</el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item v-for="fn in fnList" :key="fn.value" :command="fn.value">
                      <span style="font-family:monospace;font-size:12px">{{ fn.value }}</span>
                      <span style="color:#aaa;font-size:11px;margin-left:8px">{{ fn.desc }}</span>
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
            <el-input v-model="form.bodyStr" type="textarea" :rows="5" placeholder='{"key": "value"}' style="font-family:monospace" />
          </div>
          <div v-else-if="form.bodyType === 'form'">
            <div
              v-for="(row, i) in form.formRows" :key="i"
              style="display:flex;gap:6px;margin-bottom:6px;align-items:center"
            >
              <el-input v-model="row.key" placeholder="参数名" style="flex:1" size="small" />
              <el-input v-model="row.value" placeholder="参数值" style="flex:2" size="small" />
              <FnInsertBtn :fn-list="fnList" @insert="(fn) => insertFn(row, fn)" />
              <el-button size="small" text type="danger" @click="form.formRows.splice(i, 1)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
            <el-button size="small" :icon="Plus" @click="form.formRows.push({ key: '', value: '' })">添加参数</el-button>
          </div>
          <el-input
            v-else-if="form.bodyType === 'raw'"
            v-model="form.bodyRaw" type="textarea" :rows="5"
            placeholder="请输入原始请求体内容..." style="font-family:monospace"
          />
        </div>
      </el-form-item>

      <!-- 断言规则 -->
      <el-form-item label="断言规则">
        <div style="width:100%">
          <div
            v-for="(row, i) in form.assertionRows" :key="i"
            style="margin-bottom:8px;background:#fafafa;padding:8px 10px;border-radius:6px;border:1px solid #eee"
          >
            <div style="display:flex;gap:6px;align-items:center;margin-bottom:6px">
              <el-select v-model="row.type" size="small" style="width:120px;flex-shrink:0" @change="onAssertionTypeChange(row)">
                <el-option label="状态码" value="status_code" />
                <el-option label="JSON Path" value="json_path" />
                <el-option label="响应时间" value="response_time" />
              </el-select>
              <template v-if="row.type === 'status_code'">
                <span style="font-size:12px;color:#909399;flex-shrink:0">期望状态码</span>
                <el-input-number v-model="row.expected" :min="100" :max="599" size="small" style="width:110px" controls-position="right" />
              </template>
              <template v-else-if="row.type === 'response_time'">
                <span style="font-size:12px;color:#909399;flex-shrink:0">最大响应时间</span>
                <el-input-number v-model="row.max_ms" :min="100" :max="60000" :step="500" size="small" style="width:140px" controls-position="right" />
                <span style="font-size:12px;color:#909399;flex-shrink:0">ms</span>
              </template>
              <el-button size="small" text type="danger" @click="form.assertionRows.splice(i, 1)" style="margin-left:auto;flex-shrink:0">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
            <template v-if="row.type === 'json_path'">
              <el-input v-model="row.path" placeholder="$.data.id" size="small"
                style="width:100%;margin-bottom:6px;font-family:monospace">
                <template #prepend><span style="font-family:monospace;color:#409eff">Path</span></template>
              </el-input>
              <div style="display:flex;gap:6px;align-items:center">
                <el-select v-model="row.match_type" size="small" style="width:110px;flex-shrink:0" @change="onMatchTypeChange(row)">
                  <el-option label="等于" value="equals" />
                  <el-option label="包含" value="contains" />
                  <el-option label="存在" value="exists" />
                  <el-option label="不存在" value="not_exists" />
                  <el-option label="非空" value="not_empty" />
                  <el-option label="类型是" value="type" />
                  <el-option label="正则匹配" value="regex" />
                </el-select>
                <el-select v-if="row.match_type === 'type'" v-model="row.expected" size="small" style="flex:1;min-width:0">
                  <el-option label="string" value="string" />
                  <el-option label="number" value="number" />
                  <el-option label="boolean" value="boolean" />
                  <el-option label="array" value="array" />
                  <el-option label="object" value="object" />
                  <el-option label="null" value="null" />
                </el-select>
                <el-input
                  v-else-if="!['exists','not_exists','not_empty'].includes(row.match_type)"
                  v-model="row.expected"
                  :placeholder="row.match_type === 'regex' ? '正则，如 ^\\d+$' : '期望值'"
                  size="small" style="flex:1;min-width:0"
                />
                <span v-else style="font-size:12px;color:#c0c4cc;flex:1">（无需期望值）</span>
              </div>
            </template>
          </div>
          <el-button size="small" :icon="Plus"
            @click="form.assertionRows.push({ type: 'status_code', expected: 200, path: '', match_type: 'equals', max_ms: 3000 })">
            添加断言
          </el-button>
        </div>
      </el-form-item>

      <!-- 变量提取 -->
      <el-form-item label="变量提取">
        <div style="width:100%">
          <div style="font-size:12px;color:#909399;margin-bottom:6px">
            执行后从响应中提取值存入变量。
            <code style="background:#f5f5f5;padding:1px 4px;border-radius:3px">local</code> —
            当前执行链可用 <code style="background:#f5f5f5;padding:1px 4px;border-radius:3px">&#123;&#123;var:名&#125;&#125;</code>；
            <code style="background:#f5f5f5;padding:1px 4px;border-radius:3px">global</code> —
            跨项目可用 <code style="background:#f5f5f5;padding:1px 4px;border-radius:3px">&#123;&#123;gvar:名&#125;&#125;</code>
          </div>
          <div
            v-for="(row, i) in form.varExtractsRows" :key="i"
            style="display:flex;gap:6px;margin-bottom:6px;align-items:center"
          >
            <el-input v-model="row.name" placeholder="变量名 (如 token)" style="flex:1" size="small">
              <template #prepend>变量</template>
            </el-input>
            <el-input v-model="row.path" placeholder="$.data.token" style="flex:2" size="small">
              <template #prepend>Path</template>
            </el-input>
            <el-select v-model="row.scope" size="small" style="width:90px">
              <el-option label="local" value="local" />
              <el-option label="global" value="global" />
            </el-select>
            <el-button size="small" text type="danger" @click="form.varExtractsRows.splice(i, 1)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
          <el-button size="small" :icon="Plus" @click="form.varExtractsRows.push({ name: '', path: '', scope: 'local' })">
            添加提取规则
          </el-button>
        </div>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" @click="handleSave">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Delete } from '@element-plus/icons-vue'
import { apiTestApi } from '../../api'

// ── 内联的小工具组件：函数插入按钮 ──────────────────────────────────────────
// 避免为 4 行的小组件单独建文件
const FnInsertBtn = {
  props: { fnList: Array },
  emits: ['insert'],
  template: `
    <el-dropdown v-if="fnList && fnList.length" trigger="click" @command="$emit('insert', $event)">
      <el-button size="small" text style="font-family:monospace;color:#909399;padding:0 4px;min-width:20px">ƒ</el-button>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item v-for="fn in fnList" :key="fn.value" :command="fn.value">
            <span style="font-family:monospace;font-size:12px">{{ fn.value }}</span>
            <span style="color:#aaa;font-size:11px;margin-left:8px">{{ fn.desc }}</span>
          </el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  `,
}

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  editingCase: { type: Object, default: null },
  projectId: { type: Number, default: null },
  fnList: { type: Array, default: () => [] },
  moduleList: { type: Array, default: () => [] },  // 当前项目已有的模块列表
})

const emit = defineEmits(['update:modelValue', 'saved'])

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

// 模块自动补全：按输入过滤已有模块，始终把「通用」放第一个
const queryModules = (query, cb) => {
  const all = props.moduleList.length
    ? [...new Set(['通用', ...props.moduleList])]
    : ['通用']
  const results = query
    ? all.filter(m => m.toLowerCase().includes(query.toLowerCase()))
    : all
  cb(results.map(m => ({ value: m })))
}

// 请求体草稿（切换 bodyType 时暂存内容）
const _bodyDraft = { json: '', raw: '', form: [] }

const _defaultForm = () => ({
  name: '', module: '通用', method: 'GET', path: '/', priority: 'P1', description: '',
  headersRows: [{ key: '', value: '' }],
  paramsRows: [{ key: '', value: '' }],
  bodyType: 'json', bodyStr: '', bodyRaw: '',
  formRows: [{ key: '', value: '' }],
  assertionRows: [{ type: 'status_code', expected: 200, path: '', match_type: 'equals', max_ms: 3000 }],
  varExtractsRows: [],
  timeout_ms: null,
  _prevBodyType: 'json',
})

const form = reactive(_defaultForm())

const toAssertionRows = (assertions) => {
  if (!assertions?.length) return [{ type: 'status_code', expected: 200, path: '', match_type: 'equals', max_ms: 3000 }]
  return assertions.map(a => ({
    type: a.type || 'status_code',
    expected: a.expected ?? 200,
    path: a.path || '',
    match_type: a.match_type || 'equals',
    max_ms: a.max_ms || 3000,
  }))
}

const handleOpen = () => {
  const c = props.editingCase
  if (c) {
    const bt = c.body_type || 'json'
    Object.assign(form, {
      name: c.name || '',
      module: c.module || '通用',
      method: c.method || 'GET',
      path: c.path || '/',
      priority: c.priority || 'P1',
      description: c.description || '',
      headersRows: Object.entries(c.headers || {}).map(([k, v]) => ({ key: k, value: v })),
      paramsRows: Object.entries(c.params || {}).map(([k, v]) => ({ key: k, value: v })),
      bodyType: bt,
      bodyStr: bt === 'json' ? (c.body ? JSON.stringify(c.body, null, 2) : '') : '',
      bodyRaw: c.body_raw || '',
      formRows: (bt === 'form' && c.body) ? Object.entries(c.body).map(([k, v]) => ({ key: k, value: v })) : [{ key: '', value: '' }],
      assertionRows: toAssertionRows(c.assertions),
      varExtractsRows: (c.var_extracts || []).map(r => ({ name: r.name || '', path: r.path || '', scope: r.scope || 'local' })),
      timeout_ms: c.timeout_ms || null,
      _prevBodyType: bt,
    })
    if (!form.headersRows.length) form.headersRows.push({ key: '', value: '' })
    if (!form.paramsRows.length) form.paramsRows.push({ key: '', value: '' })
  } else {
    Object.assign(form, _defaultForm())
  }
}

const onBodyTypeChange = (newType) => {
  const prev = form._prevBodyType || 'none'
  if (prev === 'json') _bodyDraft.json = form.bodyStr
  else if (prev === 'raw') _bodyDraft.raw = form.bodyRaw
  else if (prev === 'form') _bodyDraft.form = [...form.formRows]
  if (newType === 'json') form.bodyStr = _bodyDraft.json
  else if (newType === 'raw') form.bodyRaw = _bodyDraft.raw
  else if (newType === 'form') form.formRows = _bodyDraft.form.length ? _bodyDraft.form : [{ key: '', value: '' }]
  form._prevBodyType = newType
}

const insertFn = (row, fn) => { row.value = (row.value || '') + fn }

const onAssertionTypeChange = (row) => {
  if (row.type === 'status_code') { row.expected = 200; row.path = ''; row.match_type = 'equals' }
  else if (row.type === 'json_path') { row.match_type = row.match_type || 'equals'; row.expected = row.expected ?? '' }
  else if (row.type === 'response_time') { row.max_ms = row.max_ms || 3000 }
}

const onMatchTypeChange = (row) => {
  if (['exists', 'not_exists', 'not_empty'].includes(row.match_type)) row.expected = null
}

const handleSave = async () => {
  if (!form.name) return ElMessage.warning('用例名称必填')
  let body = null, body_raw = ''
  if (form.bodyType === 'json') {
    try { if (form.bodyStr.trim()) body = JSON.parse(form.bodyStr) }
    catch { return ElMessage.error('请求体 JSON 格式有误') }
  } else if (form.bodyType === 'form') {
    body = {}
    for (const row of form.formRows) if (row.key.trim()) body[row.key.trim()] = row.value
    if (!Object.keys(body).length) body = null
  } else if (form.bodyType === 'raw') {
    body_raw = form.bodyRaw
  }
  const params = {}
  for (const row of form.paramsRows) if (row.key.trim()) params[row.key.trim()] = row.value
  const headers = {}
  for (const row of form.headersRows) if (row.key.trim()) headers[row.key.trim()] = row.value
  const assertions = form.assertionRows.map(r => {
    if (r.type === 'status_code') return { type: 'status_code', expected: Number(r.expected) || 200 }
    if (r.type === 'json_path') return { type: 'json_path', path: r.path, match_type: r.match_type || 'equals', expected: ['exists','not_exists','not_empty'].includes(r.match_type) ? null : r.expected }
    if (r.type === 'response_time') return { type: 'response_time', max_ms: Number(r.max_ms) || 3000 }
    return null
  }).filter(Boolean)
  const payload = {
    project_id: props.projectId,
    name: form.name, module: form.module, method: form.method,
    path: form.path, priority: form.priority, description: form.description || '',
    headers: Object.keys(headers).length ? headers : null,
    params: Object.keys(params).length ? params : null,
    body_type: form.bodyType, body, body_raw, assertions,
    timeout_ms: form.timeout_ms || null,
    var_extracts: form.varExtractsRows
      .filter(r => r.name.trim() && r.path.trim())
      .map(r => ({ name: r.name.trim(), path: r.path.trim(), scope: r.scope || 'local' })),
  }
  try {
    let result
    if (props.editingCase) {
      result = await apiTestApi.updateCase(props.editingCase.id, payload)
      ElMessage.success('用例已更新')
    } else {
      result = await apiTestApi.createCase(payload)
      ElMessage.success('用例创建成功')
    }
    visible.value = false
    emit('saved', result, !!props.editingCase)
  } catch (e) {
    ElMessage.error('保存失败：' + (e?.response?.data?.detail || e?.message || ''))
  }
}
</script>
