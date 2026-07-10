<template>
  <el-dialog v-model="visible" title="脚本函数库" width="980px" top="3vh" destroy-on-close
    class="script-dialog">
    <div class="script-layout">
      <!-- 左：脚本列表 -->
      <div class="script-sidebar">
        <el-button type="primary" size="small" :icon="Plus" @click="newScript" class="script-new-btn">
          新建脚本函数
        </el-button>
        <div class="script-list-scroll">
          <div v-for="s in scripts" :key="s.id"
            class="script-list-item" :class="{ active: editingScript?.id === s.id }"
            @click="selectScript(s)">
            <div class="sli-name">
              <span class="sli-icon">ƒ</span>
              <span class="sli-fn">{{ s.name }}</span>
              <span class="sli-paren">()</span>
            </div>
            <div class="sli-desc">{{ s.description || '暂无描述' }}</div>
          </div>
          <el-empty v-if="scripts.length === 0" description="暂无脚本" :image-size="48"
            style="margin-top:24px" />
        </div>
      </div>

      <!-- 右：编辑器 -->
      <div v-if="editingScript" class="script-editor-panel">
        <!-- 元信息 -->
        <div class="sed-meta">
          <div class="sed-meta-row">
            <label class="sed-label">函数名</label>
            <el-input v-model="editingScript.name" placeholder="my_func（字母/数字/下划线）"
              size="small" class="sed-name-input" />
            <span class="sed-usage-tag">
              用法：<code>&#123;&#123;{{ editingScript.name || 'func_name' }}()&#125;&#125;</code>
            </span>
          </div>
          <div class="sed-meta-row">
            <label class="sed-label">描述</label>
            <el-input v-model="editingScript.description" placeholder="简短描述函数用途（可选）"
              size="small" style="flex:1" />
          </div>
        </div>

        <!-- 代码区 -->
        <div class="sed-code-section">
          <div class="sed-code-header">
            <span class="sed-code-title">
              <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor" style="margin-right:4px;vertical-align:-1px">
                <path d="M5.854 4.854a.5.5 0 1 0-.708-.708l-3.5 3.5a.5.5 0 0 0 0 .708l3.5 3.5a.5.5 0 0 0 .708-.708L2.707 8l3.147-3.146zm4.292 0a.5.5 0 0 1 .708-.708l3.5 3.5a.5.5 0 0 1 0 .708l-3.5 3.5a.5.5 0 0 1-.708-.708L13.293 8l-3.147-3.146z"/>
              </svg>
              脚本代码
            </span>
            <span class="sed-code-tip">
              定义与函数名同名的函数（推荐），或在顶层直接设置 <code>result =</code> 变量
            </span>
            <button class="ai-gen-btn" @click="aiGenPanelVisible = !aiGenPanelVisible"
              :class="{ active: aiGenPanelVisible }">
              <span class="ai-gen-btn-icon">✦</span> AI 生成
            </button>
          </div>

          <!-- AI 生成面板 -->
          <transition name="fade-slide">
            <div v-if="aiGenPanelVisible" class="ai-gen-panel">
              <div class="ai-gen-panel-title">
                <span class="ai-gen-star">✦</span>
                用自然语言描述你想要的函数功能，AI 将自动生成代码
              </div>
              <el-input v-model="aiGenPrompt" type="textarea" :rows="3"
                placeholder="例如：生成一个登录签名函数，用 sha1(请求体json + | + app_secret) 计算 reqSign，app_secret 固定为 K8O7dT7P5n1NGUWM"
                class="ai-gen-input" resize="none" @keydown.ctrl.enter="doAiGenerate" />
              <div class="ai-gen-actions">
                <span class="ai-gen-hint">Ctrl+Enter 生成 · 生成结果会直接填入编辑器（覆盖现有代码）</span>
                <el-button type="primary" size="small" :loading="aiGenerating"
                  :disabled="!aiGenPrompt.trim()" @click="doAiGenerate" class="ai-gen-submit">
                  <span v-if="!aiGenerating">✦ 生成代码</span>
                  <span v-else>生成中…</span>
                </el-button>
              </div>
            </div>
          </transition>

          <!-- 带语法高亮的代码编辑器 -->
          <div class="py-editor-wrap" ref="editorWrapRef">
            <div class="py-line-nums" ref="lineNumsRef">
              <span v-for="n in scriptLineCount" :key="n">{{ n }}</span>
            </div>
            <div class="py-editor-inner">
              <pre class="py-highlight" aria-hidden="true"><code v-html="scriptHighlighted"></code></pre>
              <textarea class="py-textarea" v-model="editingScript.code"
                spellcheck="false" autocomplete="off"
                @scroll="syncEditorScroll" @input="onCodeInput"
                @keydown.tab.prevent="insertTab"
                :placeholder="scriptPlaceholder"></textarea>
            </div>
          </div>
        </div>

        <!-- 测试区 -->
        <div class="sed-test-section">
          <div class="sed-test-header">
            <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor" style="margin-right:4px;vertical-align:-1px">
              <path d="M11.596 8.697l-6.363 3.692c-.54.313-1.233-.066-1.233-.697V4.308c0-.63.692-1.01 1.233-.696l6.363 3.692a.802.802 0 0 1 0 1.393z"/>
            </svg>
            运行测试
          </div>
          <div class="sed-test-row">
            <el-input v-model="scriptTestArgs" placeholder="入参（逗号分隔，可留空）如：arg1, arg2"
              size="small" class="sed-test-input" clearable />
            <el-button size="small" type="primary" @click="runScriptTest" :loading="scriptTesting"
              class="sed-test-btn">执行</el-button>
          </div>
          <transition name="fade-slide">
            <div v-if="scriptTestResult !== null" class="sed-test-result"
              :class="scriptTestResult.ok ? 'result-ok' : 'result-err'">
              <div class="str-badge" :class="scriptTestResult.ok ? 'badge-ok' : 'badge-err'">
                {{ scriptTestResult.ok ? '✓ 成功' : '✗ 错误' }}
              </div>
              <pre class="str-value">{{ scriptTestResult.ok ? scriptTestResult.result : scriptTestResult.error }}</pre>
            </div>
          </transition>
        </div>

        <!-- 底部操作 -->
        <div class="sed-footer">
          <el-button size="small" type="danger" plain :icon="Delete" @click="handleDeleteScript(editingScript.id)">
            删除
          </el-button>
          <el-button size="small" type="primary" @click="handleSaveScript">保存脚本</el-button>
        </div>
      </div>

      <!-- 右：空态 -->
      <div v-else class="script-empty-panel">
        <div class="sep-icon">ƒ(x)</div>
        <div class="sep-text">选择左侧脚本或新建一个</div>
        <div class="sep-sub">自定义函数可在用例参数中用 <code>&#123;&#123;func()&#125;&#125;</code> 语法调用</div>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { ref, computed, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete } from '@element-plus/icons-vue'
import { scriptApi } from '../../api'

const props = defineProps({
  modelValue: Boolean,
  projectId: { type: Number, default: null },
})
const emit = defineEmits(['update:modelValue', 'saved'])

const visible = computed({
  get: () => props.modelValue,
  set: v => emit('update:modelValue', v),
})

// ── 脚本列表状态 ──────────────────────────────────────────────────────────────
const scripts = ref([])
const editingScript = ref(null)
const scriptTestArgs = ref('')
const scriptTestResult = ref(null)
const scriptTesting = ref(false)
const editorWrapRef = ref(null)
const lineNumsRef = ref(null)

const scriptPlaceholder = `def my_func(*args):
    import time
    return str(int(time.time()))`

const scriptLineCount = computed(() => {
  const code = editingScript.value?.code || ''
  return Math.max(code.split('\n').length, 10)
})

const scriptHighlighted = computed(() => {
  const code = editingScript.value?.code || ''
  if (!code) return ''
  let s = code
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const tokens = []
  const ph = (t) => { tokens.push(t); return `\x01p${tokens.length - 1}\x01` }
  s = s.replace(/("""[\s\S]*?"""|'''[\s\S]*?''')/g, m => ph(`<span class="py-str">${m}</span>`))
  s = s.replace(/("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')/g, m => ph(`<span class="py-str">${m}</span>`))
  s = s.replace(/(#[^\n]*)/g, m => ph(`<span class="py-comment">${m}</span>`))
  s = s.replace(/(@\w+)/g, m => ph(`<span class="py-decorator">${m}</span>`))
  s = s.replace(/\bdef\s+(\w+)/g, (_, name) => ph(`<span class="py-kw">def</span> <span class="py-fn-def">${name}</span>`))
  s = s.replace(/\b(\d+\.?\d*)\b/g, m => ph(`<span class="py-num">${m}</span>`))
  s = s.replace(/\b(print|len|range|str|int|float|bool|list|dict|tuple|set|type|isinstance|hasattr|getattr|setattr|open|abs|round|min|max|sum|sorted|enumerate|zip|map|filter|any|all|repr|bytes|bytearray|input|format|hex|oct|bin|chr|ord|iter|next|reversed|vars|dir|id|hash|callable|staticmethod|classmethod|property|super|object|Exception|ValueError|TypeError|KeyError|IndexError|AttributeError|ImportError|OSError|RuntimeError|StopIteration|NotImplementedError|NameError)\b/g, m => ph(`<span class="py-builtin">${m}</span>`))
  s = s.replace(/\b(return|import|from|as|if|elif|else|for|while|in|not|and|or|is|None|True|False|pass|break|continue|class|try|except|finally|raise|with|yield|lambda|global|nonlocal|del|assert|async|await)\b/g, m => ph(`<span class="py-kw">${m}</span>`))
  s = s.replace(/\x01p(\d+)\x01/g, (_, i) => tokens[+i])
  return s
})

// ── 编辑器辅助 ────────────────────────────────────────────────────────────────
const syncEditorScroll = (e) => {
  const ta = e.target
  const pre = ta.previousElementSibling
  const lns = lineNumsRef.value
  if (pre) { pre.scrollTop = ta.scrollTop; pre.scrollLeft = ta.scrollLeft }
  if (lns) lns.scrollTop = ta.scrollTop
}
const onCodeInput = () => {}
const insertTab = (e) => {
  const ta = e.target
  const start = ta.selectionStart
  const end = ta.selectionEnd
  const code = editingScript.value.code
  editingScript.value.code = code.slice(0, start) + '    ' + code.slice(end)
  nextTick(() => { ta.selectionStart = ta.selectionEnd = start + 4 })
}

// ── AI 生成 ───────────────────────────────────────────────────────────────────
const aiGenPanelVisible = ref(false)
const aiGenPrompt = ref('')
const aiGenerating = ref(false)

const doAiGenerate = async () => {
  if (!aiGenPrompt.value.trim() || aiGenerating.value) return
  aiGenerating.value = true
  try {
    const currentName = editingScript.value?.name || ''
    const res = await scriptApi.aiGenerate({
      prompt: aiGenPrompt.value.trim(),
      func_name: currentName === 'my_func' ? '' : currentName,
    })
    if (res.ok && res.code) {
      editingScript.value.code = res.code
      if (res.func_name) editingScript.value.name = res.func_name
      if (res.description && !editingScript.value.description) editingScript.value.description = res.description
      aiGenPanelVisible.value = false
      aiGenPrompt.value = ''
      ElMessage.success('代码已生成，请检查后保存')
    } else {
      ElMessage.error('生成失败：' + (res.error || '未知错误'))
    }
  } catch (e) {
    ElMessage.error('生成失败：' + (e?.response?.data?.detail || e?.message || '网络错误'))
  } finally {
    aiGenerating.value = false
  }
}

// ── 脚本操作 ──────────────────────────────────────────────────────────────────
const selectScript = (s) => {
  editingScript.value = { ...s }
  scriptTestResult.value = null
  scriptTestArgs.value = ''
  aiGenPanelVisible.value = false
  aiGenPrompt.value = ''
}

const newScript = () => {
  editingScript.value = { id: null, name: 'my_func', description: '', code: 'def my_func(*args):\n    return "hello"', project_id: props.projectId }
  scriptTestResult.value = null
  scriptTestArgs.value = ''
}

const handleSaveScript = async () => {
  const s = editingScript.value
  if (!s.name.trim()) return ElMessage.warning('函数名不能为空')
  if (!/^\w+$/.test(s.name.trim())) return ElMessage.warning('函数名只能包含字母、数字、下划线')
  try {
    if (s.id) {
      const updated = await scriptApi.update(s.id, s)
      const idx = scripts.value.findIndex(x => x.id === s.id)
      if (idx !== -1) scripts.value[idx] = updated
      editingScript.value = { ...updated }
    } else {
      const created = await scriptApi.create(s)
      scripts.value.push(created)
      editingScript.value = { ...created }
    }
    ElMessage.success('脚本已保存')
    emit('saved')
  } catch (e) {
    ElMessage.error('保存失败：' + (e?.message || ''))
  }
}

const handleDeleteScript = async (id) => {
  try {
    await ElMessageBox.confirm('确定删除该脚本？', '确认', { type: 'warning' })
    await scriptApi.delete(id)
    scripts.value = scripts.value.filter(s => s.id !== id)
    editingScript.value = null
    ElMessage.success('已删除')
    emit('saved')
  } catch {}
}

const runScriptTest = async () => {
  const s = editingScript.value
  if (!s?.code) return
  scriptTesting.value = true
  scriptTestResult.value = null
  try {
    scriptTestResult.value = await scriptApi.test({ name: s.name, code: s.code, args: scriptTestArgs.value })
  } catch (e) {
    scriptTestResult.value = { ok: false, error: e?.message || '请求失败' }
  } finally {
    scriptTesting.value = false
  }
}

// ── 对外暴露：打开时加载脚本 ──────────────────────────────────────────────────
const open = async () => {
  editingScript.value = null
  scriptTestResult.value = null
  scripts.value = await scriptApi.list(props.projectId)
}

defineExpose({ open })
</script>

<style scoped>
/* 复用 ApiTest.vue 中的脚本 Dialog 样式 */
.script-dialog :deep(.el-dialog__body) { padding: 0 20px 16px; }
.script-dialog :deep(.el-dialog__header) { padding: 16px 20px 12px; border-bottom: 1px solid #f0f0f0; margin-right: 0; }
.script-layout { display: flex; gap: 0; height: 580px; }
.script-sidebar { width: 210px; flex-shrink: 0; border-right: 1px solid #ebeef5; padding: 12px 12px 0 0; display: flex; flex-direction: column; gap: 8px; overflow: hidden; }
.script-new-btn { width: 100%; }
.script-list-scroll { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 4px; padding-right: 2px; }
.script-list-item { padding: 8px 10px; border-radius: 7px; cursor: pointer; border: 1px solid transparent; transition: background .15s, border-color .15s; }
.script-list-item:hover { background: #f5f7fa; }
.script-list-item.active { background: #ecf5ff; border-color: #c6e2ff; }
.sli-name { display: flex; align-items: center; gap: 3px; font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 13px; font-weight: 600; line-height: 1.4; }
.sli-icon { color: #409eff; font-size: 15px; font-style: italic; font-weight: 700; margin-right: 1px; }
.sli-fn { color: #1d4ed8; }
.sli-paren { color: #6b7280; font-weight: 400; }
.sli-desc { font-size: 11px; color: #9ca3af; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.script-editor-panel { flex: 1; display: flex; flex-direction: column; gap: 0; overflow: hidden; padding-left: 16px; padding-top: 12px; }
.sed-meta { display: flex; flex-direction: column; gap: 6px; margin-bottom: 10px; }
.sed-meta-row { display: flex; align-items: center; gap: 8px; }
.sed-label { font-size: 12px; color: #606266; font-weight: 600; width: 46px; flex-shrink: 0; }
.sed-name-input { width: 220px; font-family: monospace; }
.sed-usage-tag { font-size: 11.5px; color: #909399; background: #f5f7fa; border: 1px solid #e9ecef; border-radius: 4px; padding: 2px 8px; white-space: nowrap; }
.sed-usage-tag code { font-family: 'JetBrains Mono', monospace; color: #d14; font-size: 11px; }
.sed-code-section { flex: 1; display: flex; flex-direction: column; overflow: hidden; min-height: 0; }
.sed-code-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; flex-shrink: 0; }
.sed-code-title { font-size: 12px; font-weight: 600; color: #374151; display: flex; align-items: center; }
.sed-code-tip { font-size: 11px; color: #9ca3af; }
.sed-code-tip code { font-family: monospace; background: #f3f4f6; padding: 1px 4px; border-radius: 3px; color: #d14; }
.py-editor-wrap { flex: 1; display: flex; overflow: hidden; border: 1px solid #d1d5db; border-radius: 8px; background: #1e1e2e; font-family: 'JetBrains Mono','Fira Code','Cascadia Code',Consolas,monospace; font-size: 13px; line-height: 1.65; min-height: 0; }
.py-line-nums { display: flex; flex-direction: column; align-items: flex-end; padding: 12px 10px 12px 12px; background: #181825; border-right: 1px solid #313244; color: #45475a; font-size: 12px; line-height: 1.65; user-select: none; overflow: hidden; flex-shrink: 0; min-width: 36px; }
.py-line-nums span { display: block; }
.py-editor-inner { flex: 1; position: relative; overflow: hidden; }
.py-highlight, .py-textarea { position: absolute; top: 0; left: 0; right: 0; bottom: 0; padding: 12px 14px; margin: 0; border: none; outline: none; font: inherit; line-height: 1.65; white-space: pre; overflow: auto; tab-size: 4; word-wrap: normal; width: 100%; box-sizing: border-box; }
.py-highlight { color: #cdd6f4; background: transparent; pointer-events: none; overflow: hidden; z-index: 1; }
.py-highlight code { font: inherit; }
.py-textarea { background: transparent; color: transparent; caret-color: #cba6f7; resize: none; z-index: 2; -webkit-text-fill-color: transparent; }
.py-textarea::placeholder { color: #45475a; -webkit-text-fill-color: #45475a; }
.py-kw { color: #cba6f7; font-weight: 600; }
.py-str { color: #a6e3a1; }
.py-comment { color: #6c7086; font-style: italic; }
.py-num { color: #fab387; }
.py-builtin { color: #89dceb; }
.py-fn-def { color: #89b4fa; font-weight: 600; }
.py-decorator { color: #f38ba8; }
.sed-test-section { flex-shrink: 0; padding-top: 10px; border-top: 1px solid #f0f0f0; margin-top: 10px; }
.sed-test-header { font-size: 12px; font-weight: 600; color: #374151; display: flex; align-items: center; margin-bottom: 7px; }
.sed-test-row { display: flex; gap: 8px; align-items: center; }
.sed-test-input { flex: 1; }
.sed-test-btn { flex-shrink: 0; }
.sed-test-result { margin-top: 8px; border-radius: 6px; overflow: hidden; border: 1px solid transparent; display: flex; align-items: flex-start; }
.result-ok { background: #f0f9eb; border-color: #b7eb8f; }
.result-err { background: #fff1f0; border-color: #ffa39e; }
.str-badge { font-size: 11px; font-weight: 700; padding: 5px 10px; flex-shrink: 0; align-self: stretch; display: flex; align-items: center; }
.badge-ok { background: #b7eb8f; color: #135200; }
.badge-err { background: #ffa39e; color: #7b0b0b; }
.str-value { font-family: 'JetBrains Mono', monospace; font-size: 12px; margin: 0; padding: 5px 10px; white-space: pre-wrap; word-break: break-all; flex: 1; }
.result-ok .str-value { color: #237804; }
.result-err .str-value { color: #a8071a; }
.sed-footer { display: flex; justify-content: flex-end; gap: 8px; padding-top: 10px; flex-shrink: 0; }
.script-empty-panel { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; padding-left: 16px; }
.sep-icon { font-size: 36px; font-family: 'JetBrains Mono', monospace; font-style: italic; font-weight: 700; color: #d1d5db; letter-spacing: -1px; }
.sep-text { font-size: 14px; color: #9ca3af; }
.sep-sub { font-size: 12px; color: #c0c4cc; }
.sep-sub code { font-family: monospace; background: #f3f4f6; padding: 1px 4px; border-radius: 3px; color: #d14; }
.ai-gen-btn { margin-left: auto; display: inline-flex; align-items: center; gap: 4px; padding: 3px 10px; border-radius: 20px; border: 1px solid #c6b0f5; background: linear-gradient(135deg, #f5f0ff, #ede9fe); color: #6d28d9; font-size: 12px; font-weight: 600; cursor: pointer; transition: all .18s; white-space: nowrap; flex-shrink: 0; }
.ai-gen-btn:hover { background: linear-gradient(135deg, #ede9fe, #ddd6fe); border-color: #a78bfa; }
.ai-gen-btn.active { background: linear-gradient(135deg, #7c3aed, #6d28d9); border-color: #5b21b6; color: #fff; }
.ai-gen-btn-icon { font-size: 11px; }
.ai-gen-panel { background: linear-gradient(135deg, #faf5ff, #f5f0fe); border: 1px solid #ddd6fe; border-radius: 8px; padding: 12px 14px; margin-bottom: 8px; flex-shrink: 0; }
.ai-gen-panel-title { font-size: 12px; color: #5b21b6; font-weight: 500; margin-bottom: 8px; display: flex; align-items: center; gap: 5px; }
.ai-gen-star { color: #7c3aed; font-size: 13px; }
.ai-gen-input :deep(.el-textarea__inner) { font-size: 13px; background: #fff; border-color: #c4b5fd; border-radius: 6px; resize: none !important; }
.ai-gen-actions { display: flex; align-items: center; justify-content: space-between; margin-top: 8px; gap: 8px; }
.ai-gen-hint { font-size: 11px; color: #a78bfa; }
.ai-gen-submit { background: linear-gradient(135deg, #7c3aed, #6d28d9) !important; border-color: transparent !important; font-weight: 600; }
.fade-slide-enter-active { transition: opacity .2s, transform .2s; }
.fade-slide-leave-active { transition: opacity .15s, transform .1s; }
.fade-slide-enter-from { opacity: 0; transform: translateY(-4px); }
.fade-slide-leave-to { opacity: 0; transform: translateY(-2px); }
</style>
