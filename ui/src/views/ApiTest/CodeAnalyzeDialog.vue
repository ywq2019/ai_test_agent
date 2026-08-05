<template>
  <el-dialog
    v-model="visible"
    title="代码可行性分析"
    width="900px"
    :close-on-click-modal="false"
    destroy-on-close
    @close="handleClose"
  >
    <!-- Step 1：输入区 -->
    <div v-if="step === 1">
      <el-alert
        title="粘贴需求文档 + 接口实现代码，AI 将对比两者，识别缺失实现、行为不一致、代码额外限制和潜在风险。"
        type="info" show-icon :closable="false" style="margin-bottom:16px"
      />
      <el-row :gutter="16">
        <el-col :span="12">
          <div style="font-size:13px;font-weight:600;color:#303133;margin-bottom:8px">
            📄 需求文档 / 功能描述
          </div>
          <el-input
            v-model="requirement"
            type="textarea" :rows="14"
            placeholder="粘贴需求文档内容，或者用自然语言描述接口的预期行为..."
          />
        </el-col>
        <el-col :span="12">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
            <span style="font-size:13px;font-weight:600;color:#303133">💻 接口实现代码</span>
            <el-select v-model="codeLang" size="small" style="width:160px">
              <el-option label="Python" value="python" />
              <el-option label="Java" value="java" />
              <el-option label="Go" value="go" />
              <el-option label="Node.js" value="node" />
              <el-option label="PHP" value="php" />
              <el-option label="其他" value="other" />
            </el-select>
          </div>
          <el-input
            v-model="code"
            type="textarea" :rows="14"
            placeholder="粘贴 Controller / Handler / Service 代码..."
          />
        </el-col>
      </el-row>
    </div>

    <!-- Step 2：分析中 -->
    <div v-else-if="step === 2" style="padding:40px 0;text-align:center">
      <el-icon class="is-loading" style="font-size:40px;color:#409eff"><Loading /></el-icon>
      <div style="margin-top:16px;font-size:15px;color:#409eff;font-weight:600">{{ stage }}</div>
      <el-progress
        :percentage="progress"
        :stroke-width="8"
        :show-text="false"
        status="striped" striped striped-flow :duration="6"
        style="margin:16px 40px 0"
      />
      <div style="font-size:12px;color:#909399;margin-top:8px">AI 正在对比需求与代码实现，约需 30-60 秒...</div>
    </div>

    <!-- Step 3：分析结果 -->
    <div v-else-if="step === 3 && report">
      <!-- 整体评估横幅 -->
      <div class="analyze-summary-bar" :class="`risk-${report.risk_level}`">
        <el-icon style="font-size:18px">
          <WarningFilled v-if="report.risk_level === 'high'" />
          <Warning v-else-if="report.risk_level === 'medium'" />
          <SuccessFilled v-else />
        </el-icon>
        <span class="analyze-risk-label">
          风险等级：{{ { high:'高', medium:'中', low:'低' }[report.risk_level] || report.risk_level }}
        </span>
        <span class="analyze-summary-text">{{ report.summary }}</span>
        <el-tag size="small" type="info" effect="plain" style="margin-left:auto;flex-shrink:0">
          发现 {{ report.items?.length || 0 }} 个问题
        </el-tag>
      </div>

      <!-- 差异条目列表 -->
      <div v-if="report.items?.length" class="analyze-items">
        <template v-for="typeKey in ['missing','mismatch','extra','risk']" :key="typeKey">
          <div v-if="report.items.filter(i => i.type === typeKey).length">
            <div class="analyze-type-header" :class="`type-${typeKey}`">
              <span class="type-icon">{{ { missing:'🔴', mismatch:'🟡', extra:'🔵', risk:'⚠️' }[typeKey] }}</span>
              <span class="type-label">{{ { missing:'缺失实现', mismatch:'行为不一致', extra:'代码额外限制', risk:'潜在风险' }[typeKey] }}</span>
              <el-badge :value="report.items.filter(i => i.type === typeKey).length" type="info" />
            </div>
            <div
              v-for="(item, idx) in report.items.filter(i => i.type === typeKey)"
              :key="idx"
              class="analyze-item" :class="`severity-${item.severity}`"
            >
              <div class="analyze-item-title">
                <el-tag :type="{ high:'danger', medium:'warning', low:'info' }[item.severity]" size="small" effect="plain">
                  {{ { high:'严重', medium:'中等', low:'低' }[item.severity] }}
                </el-tag>
                <span style="font-weight:600;margin-left:8px">{{ item.title }}</span>
              </div>
              <div class="analyze-item-body">
                <div v-if="item.requirement && item.requirement !== 'N/A'" class="analyze-row">
                  <span class="analyze-row-label">需求描述</span>
                  <span class="analyze-row-val">{{ item.requirement }}</span>
                </div>
                <div class="analyze-row">
                  <span class="analyze-row-label">代码行为</span>
                  <span class="analyze-row-val">{{ item.code_behavior }}</span>
                </div>
                <div class="analyze-row">
                  <span class="analyze-row-label">测试重点</span>
                  <span class="analyze-row-val" style="color:#409eff">{{ item.test_focus }}</span>
                </div>
                <div class="analyze-row">
                  <span class="analyze-row-label">修复建议</span>
                  <span class="analyze-row-val" style="color:#67c23a">{{ item.suggestion }}</span>
                </div>
              </div>
            </div>
          </div>
        </template>
      </div>
      <el-empty v-else description="未发现明显差异，需求与实现基本一致 🎉" :image-size="80" style="margin:20px 0" />

      <!-- 自动生成的差异验证用例预览 -->
      <div v-if="report.auto_cases?.length" style="margin-top:16px">
        <div style="font-size:13px;font-weight:600;color:#303133;margin-bottom:8px;display:flex;align-items:center;gap:8px">
          <el-icon color="#409eff"><Document /></el-icon>
          已自动生成 {{ report.auto_cases.length }} 条差异验证用例
        </div>
        <el-table :data="report.auto_cases" size="small" border max-height="200" style="width:100%">
          <el-table-column prop="name" label="用例名称" min-width="200" show-overflow-tooltip />
          <el-table-column prop="method" label="方法" width="70" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="{ GET:'success', POST:'primary', PUT:'warning', DELETE:'danger' }[row.method] || 'info'">
                {{ row.method }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="path" label="路径" width="160" show-overflow-tooltip />
          <el-table-column prop="priority" label="优先级" width="70" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="{ P0:'danger', P1:'warning', P2:'info' }[row.priority] || 'info'">{{ row.priority }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="_diff_ref" label="对应差异" min-width="140" show-overflow-tooltip />
        </el-table>
      </div>
    </div>

    <template #footer>
      <template v-if="step === 1">
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" @click="startAnalyze" :disabled="!requirement.trim() || !code.trim()">
          开始分析
        </el-button>
      </template>
      <template v-else-if="step === 2">
        <el-button @click="visible = false">关闭</el-button>
      </template>
      <template v-else-if="step === 3">
        <el-button @click="step = 1">重新分析</el-button>
        <el-button @click="visible = false">关闭</el-button>
        <el-button
          v-if="report?.auto_cases?.length"
          type="primary"
          @click="$emit('save-cases', report.auto_cases)"
          :loading="savingCases"
        >
          <el-icon><DocumentAdd /></el-icon>
          保存 {{ report.auto_cases.length }} 条差异验证用例到用例库
        </el-button>
      </template>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Loading, WarningFilled, Warning, SuccessFilled, Document, DocumentAdd } from '@element-plus/icons-vue'
import { apiTestApi } from '../../api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  projectId: { type: Number, default: null },
  savingCases: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'save-cases'])

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

// 内部状态
const step        = ref(1)
const requirement = ref('')
const code        = ref('')
const codeLang    = ref('python')
const progress    = ref(0)
const stage       = ref('AI 正在分析...')
const report      = ref(null)

const handleClose = () => {
  step.value     = 1
  report.value   = null
  progress.value = 0
}

const startAnalyze = async () => {
  if (!requirement.value.trim() || !code.value.trim()) return
  step.value     = 2
  progress.value = 10
  stage.value    = 'AI 正在解析需求文档...'

  const progressTimer = setInterval(() => {
    if (progress.value < 85) {
      progress.value += Math.floor(Math.random() * 8) + 3
      const stages = [
        'AI 正在解析接口代码结构...',
        'AI 正在对比需求与代码实现...',
        'AI 正在识别差异点...',
        'AI 正在生成差异验证用例...',
      ]
      stage.value = stages[Math.min(
        Math.floor((progress.value - 10) / 20),
        stages.length - 1
      )]
    }
  }, 2000)

  try {
    const result = await apiTestApi.codeAnalyze(props.projectId, {
      requirement: requirement.value,
      code:        code.value,
      lang:        codeLang.value,
    })
    report.value   = result
    progress.value = 100
    step.value     = 3
  } catch (e) {
    step.value = 1
    ElMessage.error('分析失败：' + (e?.response?.data?.detail || e?.message || '未知错误'))
  } finally {
    clearInterval(progressTimer)
  }
}
</script>

<style scoped>
/* 复用 ApiTest.vue 中 analyze-* 样式 */
.analyze-summary-bar {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 16px; border-radius: 8px; margin-bottom: 16px;
  font-size: 14px; border: 1px solid transparent;
}
.risk-high   { background: #fff0f0; border-color: #fcd3d3; color: #c0392b; }
.risk-medium { background: #fffbf0; border-color: #fde8a0; color: #d4960a; }
.risk-low    { background: #f0fff4; border-color: #b7ebc8; color: #27ae60; }
.analyze-risk-label { font-weight: 700; white-space: nowrap; }
.analyze-summary-text { flex: 1; color: #606266; font-size: 13px; }

.analyze-items { max-height: 420px; overflow-y: auto; }
.analyze-type-header {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px; margin: 12px 0 6px;
  border-radius: 6px; font-size: 13px; font-weight: 600;
}
.type-missing  { background: #fff0f0; }
.type-mismatch { background: #fffbf0; }
.type-extra    { background: #f0f8ff; }
.type-risk     { background: #fdf6ec; }
.analyze-item {
  border: 1px solid #eee; border-radius: 6px;
  margin-bottom: 8px; overflow: hidden;
}
.analyze-item-title {
  display: flex; align-items: center;
  padding: 8px 12px; background: #fafafa;
  border-bottom: 1px solid #eee;
}
.analyze-item-body { padding: 8px 12px; }
.analyze-row { display: flex; gap: 8px; margin-bottom: 4px; font-size: 12px; }
.analyze-row-label {
  flex-shrink: 0; width: 64px; color: #909399; font-weight: 600;
}
.analyze-row-val { flex: 1; color: #303133; line-height: 1.5; }
.severity-high   .analyze-item-title { background: #fff8f8; }
.severity-medium .analyze-item-title { background: #fffdf5; }
</style>
