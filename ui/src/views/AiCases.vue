<template>
  <div class="ai-cases-page">

    <!-- 统计栏 -->
    <div class="stats-bar">
      <div class="stat-card" v-for="s in stats" :key="s.label" :style="{ background: s.bg }">
        <div class="stat-icon"><el-icon :size="28"><component :is="s.icon" /></el-icon></div>
        <div class="stat-body">
          <div class="stat-num">{{ s.value }}</div>
          <div class="stat-label">{{ s.label }}</div>
        </div>
      </div>
    </div>

    <el-row :gutter="20">
      <!-- 左侧：生成历史列表 -->
      <el-col :span="8">
        <el-card shadow="hover" class="list-card">
          <template #header>
            <div class="card-header">
              <span>生成历史</span>
              <el-button type="primary" size="small" @click="openGenDialog">
                <el-icon><MagicStick /></el-icon>
                新建生成
              </el-button>
            </div>
          </template>
          <div v-if="records.length === 0" class="empty-box">
            <el-empty description="暂无生成记录，点击「新建生成」开始" />
          </div>
          <div v-else class="record-list">
            <div
              v-for="r in records"
              :key="r.id"
              class="record-item"
              :class="{ active: current && current.id === r.id }"
              @click="selectRecord(r)"
            >
              <div class="record-header">
                <span class="record-name">{{ r.task_name }}</span>
                <div class="record-actions">
                  <el-tooltip content="用例覆盖度优化" placement="top">
                    <el-button
                      size="small"
                      type="primary"
                      link
                      @click.stop="openOptimizeDialog(r)"
                    >
                      <el-icon><MagicStick /></el-icon>
                    </el-button>
                  </el-tooltip>
                  <el-button size="small" type="danger" link @click.stop="deleteRecord(r)">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </div>
              </div>
              <div class="record-meta">
                <el-tag size="small" type="success" v-if="r.has_md">MD</el-tag>
                <el-tag size="small" type="warning" v-if="r.has_xmind">XMind</el-tag>
                <span class="record-count">{{ r.case_count }} 条用例</span>
                <span class="record-date">{{ formatDate(r.created_at) }}</span>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- 右侧：用例预览 -->
      <el-col :span="16">
        <el-card v-if="current" shadow="hover">
          <template #header>
            <div class="card-header">
              <div class="detail-title">
                <el-icon color="#409eff"><MagicStick /></el-icon>
                <span>{{ current.task_name }}</span>
                <el-tag size="small">{{ current.case_count }} 条用例</el-tag>
              </div>
              <div class="download-btns">
                <el-button
                  type="primary"
                  size="small"
                  plain
                  @click="openAddCase"
                >
                  <el-icon><Plus /></el-icon>
                  新建用例
                </el-button>
                <el-button
                  type="success"
                  size="small"
                  @click="openOptimizeDialog(current)"
                  :loading="optimizing && optimizeTarget?.id === current.id"
                >
                  <el-icon><MagicStick /></el-icon>
                  覆盖度优化
                </el-button>
                <el-button
                  type="info"
                  size="small"
                  @click="showCoverage(current)"
                  :loading="loadingCoverage && coverageTarget?.id === current.id"
                >
                  <el-icon><DataAnalysis /></el-icon>
                  覆盖度分析
                </el-button>
                <el-button
                  v-if="current.has_md"
                  type="primary"
                  size="small"
                  @click="download(current.id, 'md')"
                >
                  <el-icon><Download /></el-icon>
                  下载 Markdown
                </el-button>
                <el-button
                  v-if="current.has_xmind"
                  type="warning"
                  size="small"
                  @click="download(current.id, 'xmind')"
                >
                  <el-icon><Download /></el-icon>
                  下载 XMind
                </el-button>
              </div>
            </div>
          </template>

          <div v-if="current.modules && current.modules.length" class="modules-preview">
            <el-collapse v-model="openModules" accordion>
              <el-collapse-item
                v-for="(mod, mi) in current.modules"
                :key="mi"
                :name="mi"
              >
                <template #title>
                  <div class="mod-title">
                    <el-icon color="#67c23a"><FolderOpened /></el-icon>
                    <span>{{ mod.name }}</span>
                    <el-badge :value="mod.cases ? mod.cases.length : 0" type="primary" class="mod-badge" />
                  </div>
                </template>
                <el-table :data="mod.cases || []" stripe size="small" style="width:100%">
                  <el-table-column prop="id" label="编号" width="80" />
                  <el-table-column prop="name" label="用例名称" min-width="180" show-overflow-tooltip />
                  <el-table-column prop="priority" label="优先级" width="80">
                    <template #default="{ row }">
                      <el-tag
                        size="small"
                        :type="row.priority === 'P0' ? 'danger' : row.priority === 'P1' ? 'warning' : 'info'"
                      >{{ row.priority }}</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column prop="type" label="类型" width="90" />
                  <el-table-column prop="test_method" label="测试方法" width="110" show-overflow-tooltip>
                    <template #default="{ row }">
                      <el-tag v-if="row.test_method" size="small" type="success">{{ row.test_method }}</el-tag>
                      <span v-else>-</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="操作" width="140">
                    <template #default="{ row }">
                      <el-button size="small" link type="primary" @click="viewCase(row)">详情</el-button>
                      <el-button size="small" link type="warning" @click="openEditCase(row, mod.name)">编辑</el-button>
                      <el-button size="small" link type="danger" @click="deleteCaseItem(row, mod.name)">删除</el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </el-collapse-item>
            </el-collapse>
          </div>
          <el-empty v-else description="暂无用例数据" />
        </el-card>
        <el-empty v-else description="请从左侧选择记录查看用例" />
      </el-col>
    </el-row>

    <!-- 覆盖度分析抽屉 -->
    <el-drawer v-model="coverageDrawerVisible" title="用例覆盖度分析" size="500px" direction="rtl">
      <div v-if="coverageData" class="coverage-panel">
        <!-- 总评分 -->
        <div class="score-block">
          <el-progress type="dashboard" :percentage="coverageData.score" :color="scoreColor(coverageData.score)" :width="100" />
          <div class="score-meta">
            <div class="score-title">综合评分</div>
            <div class="score-total">共 {{ coverageData.total }} 条用例</div>
            <div class="score-name">{{ coverageTarget?.task_name }}</div>
          </div>
        </div>

        <el-divider />

        <!-- 测试方法覆盖（AI 用例专属） -->
        <div class="section-title">测试方法覆盖（{{ coverageData.method_rate }}%）</div>
        <div class="method-grid">
          <div v-for="m in coverageData.method_coverage" :key="m.name" class="method-item" :class="{ covered: m.covered, missing: !m.covered }">
            <el-icon v-if="m.covered" color="#67c23a"><CircleCheck /></el-icon>
            <el-icon v-else color="#c0c4cc"><CircleClose /></el-icon>
            <span>{{ m.name }}</span>
          </div>
        </div>

        <el-divider />

        <!-- 用例类型分布 -->
        <div class="section-title">用例类型分布</div>
        <div class="type-bars">
          <div v-for="(count, type) in coverageData.type_distribution" :key="type" class="priority-row">
            <span class="type-label">{{ type }}</span>
            <el-progress
              :percentage="coverageData.total ? Math.round(count / coverageData.total * 100) : 0"
              style="flex:1;margin:0 10px" :show-text="false"
              :color="type === '功能测试' ? '#409eff' : type === '性能测试' ? '#e6a23c' : '#67c23a'"
            />
            <span class="count-label">{{ count }} 条</span>
          </div>
        </div>

        <el-divider />

        <!-- 优先级分布 -->
        <div class="section-title">优先级分布</div>
        <div class="priority-bars">
          <div v-for="(count, level) in coverageData.priority_distribution" :key="level" class="priority-row">
            <el-tag :type="level === 'P0' ? 'danger' : level === 'P1' ? 'warning' : 'info'" size="small" style="width:36px;text-align:center">{{ level }}</el-tag>
            <el-progress
              :percentage="coverageData.total ? Math.round(count / coverageData.total * 100) : 0"
              :color="level === 'P0' ? '#f56c6c' : level === 'P1' ? '#e6a23c' : '#909399'"
              style="flex:1;margin:0 10px" :show-text="false"
            />
            <span class="count-label">{{ count }} 条</span>
          </div>
        </div>

        <el-divider />

        <!-- 模块分布 -->
        <div class="section-title">模块覆盖</div>
        <el-table :data="coverageData.module_distribution" size="small" border style="width:100%">
          <el-table-column prop="name" label="模块" show-overflow-tooltip />
          <el-table-column prop="total" label="总计" width="55" align="center" />
          <el-table-column prop="P0" label="P0" width="45" align="center">
            <template #default="{ row }">
              <span :class="{ 'zero-warn': row.P0 === 0 }">{{ row.P0 }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="P1" label="P1" width="45" align="center" />
          <el-table-column prop="P2" label="P2" width="45" align="center" />
        </el-table>

        <el-divider />

        <!-- 优化建议 -->
        <div class="section-title">优化建议</div>
        <ul class="suggestions">
          <li v-for="(s, i) in coverageData.suggestions" :key="i">{{ s }}</li>
        </ul>
      </div>
      <div v-else class="coverage-empty"><el-empty description="暂无数据" /></div>
    </el-drawer>

    <!-- 优化对话框 -->
    <el-dialog
      v-model="optimizeDialogVisible"
      title="用例覆盖度优化"
      width="520px"
      :close-on-click-modal="false"
    >
      <div v-if="optimizeTarget" class="optimize-info">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="任务名称">{{ optimizeTarget.task_name }}</el-descriptions-item>
          <el-descriptions-item label="现有用例数">
            <el-tag type="info">{{ optimizeTarget.case_count }} 条</el-tag>
          </el-descriptions-item>
        </el-descriptions>
        <el-alert
          title="AI 将分析现有用例的覆盖盲区，自动补充边界测试、异常流程、安全测试等场景，并优化现有步骤和预期结果。优化完成后将覆盖原记录。"
          type="info"
          show-icon
          :closable="false"
          style="margin-top:14px"
        />
        <div class="optimize-tags">
          <span class="tag-label">将补充：</span>
          <el-tag size="small" type="danger">边界值测试</el-tag>
          <el-tag size="small" type="warning">异常/错误流程</el-tag>
          <el-tag size="small" type="success">安全测试</el-tag>
          <el-tag size="small">兼容性测试</el-tag>
          <el-tag size="small" type="info">性能场景</el-tag>
        </div>
      </div>

      <div v-if="optimizing" class="generating-tip" style="margin-top:14px">
        <div class="gen-progress-header">
          <el-icon class="spin"><Loading /></el-icon>
          <span class="gen-stage-text">{{ genStage }}</span>
          <span class="gen-pct">{{ genPercent }}%</span>
        </div>
        <el-progress
          :percentage="genPercent"
          :stroke-width="10"
          :show-text="false"
          status="striped"
          striped
          striped-flow
          :duration="6"
          style="margin-top:8px"
        />
        <div style="font-size:11px;color:#909399;margin-top:6px;text-align:center">
          覆盖度分析 + AI 优化约需 1-3 分钟
        </div>
      </div>

      <template #footer>
        <el-button @click="optimizeDialogVisible = false" :disabled="optimizing">取消</el-button>
        <el-button
          type="primary"
          :loading="optimizing"
          @click="doOptimize"
        >
          {{ optimizing ? '优化中...' : '开始优化' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 生成对话框 -->
    <el-dialog v-model="genDialogVisible" title="AI 用例生成" width="600px" :close-on-click-modal="false">
      <el-form :model="genForm" label-width="90px" :rules="genRules" ref="genFormRef">
        <el-form-item label="任务名称" prop="task_name">
          <el-input v-model="genForm.task_name" placeholder="如：会员中心功能测试" />
        </el-form-item>
        <el-form-item label="需求来源">
          <el-radio-group v-model="genForm.sourceType">
            <el-radio value="file">上传文档</el-radio>
            <el-radio value="text">手动输入</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="genForm.sourceType === 'file'" label="需求文档">
          <el-upload
            ref="uploadRef"
            :auto-upload="false"
            :limit="1"
            :on-change="handleFileChange"
            :on-remove="() => { genForm.document_path = ''; uploadedFile = null }"
            accept=".pdf,.docx,.doc,.xlsx,.xls,.txt,.md,.html,.htm,.csv,.json,.pptx"
            drag
          >
            <el-icon size="40" color="#c0c4cc"><UploadFilled /></el-icon>
            <div style="font-size:14px;color:#606266;margin-top:8px">
              拖拽文件到此处，或 <em style="color:#409eff">点击上传</em>
            </div>
            <template #tip>
              <div style="color:#909399;font-size:12px;margin-top:4px">
                支持 PDF / Word / Excel / TXT / Markdown 等，≤ 20MB
              </div>
            </template>
          </el-upload>
          <el-alert v-if="uploadError" :title="uploadError" type="error" show-icon :closable="false" style="margin-top:8px" />
        </el-form-item>
        <el-form-item v-else label="需求内容" prop="content">
          <el-input
            v-model="genForm.content"
            type="textarea"
            :rows="8"
            placeholder="请输入需求文档内容或功能描述..."
          />
        </el-form-item>
        <el-form-item label="输出格式">
          <el-checkbox-group v-model="genForm.formats">
            <el-checkbox value="md">
              <el-tag type="primary" size="small">Markdown (.md)</el-tag>
            </el-checkbox>
            <el-checkbox value="xmind" style="margin-left:16px">
              <el-tag type="warning" size="small">XMind (.xmind)</el-tag>
            </el-checkbox>
          </el-checkbox-group>
          <div style="font-size:12px;color:#909399;margin-top:4px">
            Markdown 便于阅读，XMind 可直接用思维导图软件打开
          </div>
        </el-form-item>
      </el-form>

      <div v-if="generating" class="generating-tip">
        <div class="gen-progress-header">
          <el-icon class="spin"><Loading /></el-icon>
          <span class="gen-stage-text">{{ genStage }}</span>
          <span class="gen-pct">{{ genPercent }}%</span>
        </div>
        <el-progress
          :percentage="genPercent"
          :stroke-width="10"
          :show-text="false"
          status="striped"
          striped
          striped-flow
          :duration="6"
          style="margin-top:8px"
        />
        <div style="font-size:11px;color:#909399;margin-top:6px;text-align:center">
          大文件解析 + AI 生成约需 1-3 分钟，请勿关闭弹窗
        </div>
      </div>

      <template #footer>
        <el-button @click="genDialogVisible = false" :disabled="generating">取消</el-button>
        <el-button type="primary" :loading="generating" @click="doGenerate">
          {{ generating ? '生成中...' : '开始生成' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 用例详情对话框 -->
    <el-dialog v-model="caseDetailVisible" :title="detailCase?.name" width="640px">
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="编号">{{ detailCase?.id }}</el-descriptions-item>
        <el-descriptions-item label="优先级">
          <el-tag :type="detailCase?.priority === 'P0' ? 'danger' : detailCase?.priority === 'P1' ? 'warning' : 'info'">
            {{ detailCase?.priority }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="类型">{{ detailCase?.type }}</el-descriptions-item>
        <el-descriptions-item v-if="detailCase?.test_method" label="测试方法">
          <el-tag type="success" size="small">{{ detailCase?.test_method }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="前置条件" :span="detailCase?.test_method ? 2 : 1">{{ detailCase?.preconditions || '无' }}</el-descriptions-item>
      </el-descriptions>
      <div style="margin-top:16px">
        <div class="detail-section-title">测试步骤</div>
        <ol class="step-list">
          <li v-for="(step, i) in (detailCase?.steps || [])" :key="i">{{ step }}</li>
        </ol>
      </div>
      <div style="margin-top:12px">
        <div class="detail-section-title">预期结果</div>
        <div class="expected-box">{{ detailCase?.expected }}</div>
      </div>
    </el-dialog>

    <!-- 新建/编辑单条用例对话框 -->
    <el-dialog
      v-model="caseFormVisible"
      :title="caseFormMode === 'add' ? '新建用例' : '编辑用例'"
      width="660px"
      :close-on-click-modal="false"
    >
      <el-form :model="caseForm" :rules="caseFormRules" ref="caseFormRef" label-width="88px" size="default">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="用例名称" prop="name">
              <el-input v-model="caseForm.name" placeholder="如：用户登录-正常流程" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="所属模块" prop="module">
              <el-select v-model="caseForm.module" allow-create filterable placeholder="选择或输入模块名" style="width:100%">
                <el-option
                  v-for="mod in (current?.modules || [])"
                  :key="mod.name"
                  :label="mod.name"
                  :value="mod.name"
                />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="优先级" prop="priority">
              <el-select v-model="caseForm.priority" style="width:100%">
                <el-option label="P0 - 核心" value="P0" />
                <el-option label="P1 - 重要" value="P1" />
                <el-option label="P2 - 一般" value="P2" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="用例类型">
              <el-select v-model="caseForm.type" style="width:100%">
                <el-option label="功能测试" value="功能测试" />
                <el-option label="性能测试" value="性能测试" />
                <el-option label="兼容性测试" value="兼容性测试" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="测试方法">
              <el-select v-model="caseForm.test_method" clearable placeholder="可选" style="width:100%">
                <el-option label="等价类划分" value="等价类划分" />
                <el-option label="边界值分析" value="边界值分析" />
                <el-option label="判定表" value="判定表" />
                <el-option label="场景法" value="场景法" />
                <el-option label="错误推测" value="错误推测" />
                <el-option label="状态转换" value="状态转换" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="前置条件">
          <el-input v-model="caseForm.preconditions" placeholder="如：用户已注册，未登录状态" />
        </el-form-item>
        <el-form-item label="测试步骤" prop="stepsText">
          <el-input
            v-model="caseForm.stepsText"
            type="textarea"
            :rows="5"
            placeholder="每行一个步骤，如：
1. 打开登录页面
2. 输入正确的用户名和密码
3. 点击登录按钮"
          />
          <div style="font-size:11px;color:#909399;margin-top:4px">每行一个步骤，行首序号可选</div>
        </el-form-item>
        <el-form-item label="预期结果" prop="expected">
          <el-input
            v-model="caseForm.expected"
            type="textarea"
            :rows="3"
            placeholder="如：成功跳转到首页，显示用户头像和昵称"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="caseFormVisible = false">取消</el-button>
        <el-button type="primary" :loading="caseFormSaving" @click="saveCaseForm">
          {{ caseFormSaving ? '保存中...' : '保存' }}
        </el-button>
      </template>
    </el-dialog>

  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { aiCaseApi, documentApi } from '../api'

const records = ref([])
const current = ref(null)
const openModules = ref(0)

// 覆盖度分析
const coverageDrawerVisible = ref(false)
const coverageData = ref(null)
const coverageTarget = ref(null)
const loadingCoverage = ref(false)

const scoreColor = (s) => s >= 70 ? '#67c23a' : s >= 40 ? '#e6a23c' : '#f56c6c'

const showCoverage = async (r) => {
  coverageTarget.value = r
  loadingCoverage.value = true
  try {
    coverageData.value = await aiCaseApi.coverage(r.id)
    coverageDrawerVisible.value = true
  } catch (e) {
    ElMessage.error('获取覆盖度失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    loadingCoverage.value = false
  }
}

// 生成对话框
const genDialogVisible = ref(false)
const genFormRef = ref(null)
const uploadRef = ref(null)
const uploadedFile = ref(null)
const uploadError = ref('')
const generating = ref(false)
const genPercent = ref(0)
const genStage = ref('准备中...')
const genForm = ref({
  task_name: '',
  sourceType: 'file',
  document_path: '',
  content: '',
  formats: ['md', 'xmind'],
})
const genRules = {
  task_name: [{ required: true, message: '请输入任务名称', trigger: 'blur' }],
  content: [{ required: false }],
}

// 用例详情
const caseDetailVisible = ref(false)
const detailCase = ref(null)

// ---------- WebSocket（AI 生成进度） ----------
let ws = null

function connectGenWS() {
  if (ws && ws.readyState < 2) return
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const host = location.host
  ws = new WebSocket(`${proto}://${host}/ws?client_id=ai_gen`)
  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data)
      if (msg.type === 'ai_gen_progress') {
        genPercent.value = msg.percent ?? genPercent.value
        genStage.value = msg.stage ?? genStage.value
      }
    } catch (_) {}
  }
  ws.onerror = () => {}
  ws.onclose = () => {}
}

function disconnectGenWS() {
  if (ws) { ws.close(); ws = null }
}

// ---------- 统计 ----------
const stats = computed(() => {
  const total = records.value.length
  const cases = records.value.reduce((s, r) => s + (r.case_count || 0), 0)
  const mdCount = records.value.filter(r => r.has_md).length
  const xmindCount = records.value.filter(r => r.has_xmind).length
  return [
    { label: '生成次数', value: total, icon: 'MagicStick', bg: 'linear-gradient(135deg,#667eea,#764ba2)' },
    { label: '用例总数', value: cases, icon: 'Document', bg: 'linear-gradient(135deg,#11998e,#38ef7d)' },
    { label: 'MD 文件', value: mdCount, icon: 'Tickets', bg: 'linear-gradient(135deg,#2193b0,#6dd5ed)' },
    { label: 'XMind 文件', value: xmindCount, icon: 'Share', bg: 'linear-gradient(135deg,#f7971e,#ffd200)' },
  ]
})

// ---------- 数据加载 ----------
const fetchRecords = async () => {
  try {
    const data = await aiCaseApi.list()
    records.value = data || []
    if (records.value.length && !current.value) {
      current.value = records.value[0]
    }
  } catch (e) {
    ElMessage.error('加载失败: ' + (e.message || e))
  }
}

const selectRecord = (r) => {
  current.value = r
  openModules.value = 0
}

const deleteRecord = async (r) => {
  try {
    await ElMessageBox.confirm(`确认删除「${r.task_name}」及其文件？`, '删除确认', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger'
    })
    await aiCaseApi.delete(r.id)
    ElMessage.success('删除成功')
    if (current.value?.id === r.id) current.value = null
    await fetchRecords()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('删除失败')
  }
}

// ---------- 生成 ----------
const openGenDialog = () => {
  genForm.value = { task_name: '', sourceType: 'file', document_path: '', content: '', formats: ['md', 'xmind'] }
  uploadError.value = ''
  uploadedFile.value = null
  genDialogVisible.value = true
}

const handleFileChange = (file) => {
  const maxMB = 20
  const ext = '.' + file.name.split('.').pop().toLowerCase()
  const allowed = new Set(['.pdf','.docx','.doc','.xlsx','.xls','.txt','.md','.html','.htm','.csv','.json','.pptx'])
  if (!allowed.has(ext)) {
    uploadError.value = `不支持的格式 ${ext}`
    uploadRef.value?.clearFiles()
    return
  }
  if (file.size > maxMB * 1024 * 1024) {
    uploadError.value = `文件超过 ${maxMB}MB`
    uploadRef.value?.clearFiles()
    return
  }
  uploadError.value = ''
  uploadedFile.value = file.raw
}

const doGenerate = async () => {
  await genFormRef.value?.validate()
  if (genForm.value.formats.length === 0) {
    ElMessage.warning('请至少选择一种输出格式')
    return
  }

  generating.value = true
  genPercent.value = 0
  genStage.value = '准备中...'
  connectGenWS()

  try {
    let docPath = ''

    if (genForm.value.sourceType === 'file') {
      if (!uploadedFile.value) {
        ElMessage.warning('请先上传需求文档')
        generating.value = false
        return
      }
      genPercent.value = 5
      genStage.value = '正在上传文档...'
      const uploadResult = await documentApi.upload(uploadedFile.value)
      docPath = uploadResult.file_path || uploadResult.path || ''
    }

    const payload = {
      task_name: genForm.value.task_name,
      formats: genForm.value.formats,
      ...(genForm.value.sourceType === 'file'
        ? { document_path: docPath }
        : { content: genForm.value.content }),
    }

    const result = await aiCaseApi.generate(payload)
    genPercent.value = 100
    genStage.value = `完成！共 ${result.case_count} 条用例`
    await new Promise(r => setTimeout(r, 600))
    ElMessage.success(`生成成功！共 ${result.case_count} 条用例`)
    genDialogVisible.value = false
    await fetchRecords()
    const found = records.value.find(r => r.id === result.id)
    if (found) current.value = found
  } catch (e) {
    const msg = e.response?.data?.detail || e.message || '生成失败'
    ElMessage.error(msg)
  } finally {
    generating.value = false
    disconnectGenWS()
  }
}

// ---------- 优化 ----------
const optimizeDialogVisible = ref(false)
const optimizeTarget = ref(null)
const optimizing = ref(false)

const openOptimizeDialog = (r) => {
  optimizeTarget.value = r
  genPercent.value = 0
  genStage.value = '准备中...'
  optimizeDialogVisible.value = true
}

const doOptimize = async () => {
  if (!optimizeTarget.value) return
  optimizing.value = true
  genPercent.value = 0
  genStage.value = '正在连接 AI...'
  connectGenWS()
  try {
    const result = await aiCaseApi.optimize(optimizeTarget.value.id)
    genPercent.value = 100
    genStage.value = `优化完成！共 ${result.case_count} 条用例`
    await new Promise(r => setTimeout(r, 600))
    const diff = result.case_count - optimizeTarget.value.case_count
    ElMessage.success(`优化成功！用例从 ${optimizeTarget.value.case_count} 条增至 ${result.case_count} 条（+${diff}）`)
    optimizeDialogVisible.value = false
    await fetchRecords()
    const found = records.value.find(r => r.id === result.id)
    if (found) current.value = found
  } catch (e) {
    const msg = e.response?.data?.detail || e.message || '优化失败'
    ElMessage.error(msg)
  } finally {
    optimizing.value = false
    disconnectGenWS()
  }
}

// ---------- 下载 ----------
const download = (id, format) => {
  const url = aiCaseApi.downloadUrl(id, format)
  window.open(url, '_blank')
}

// ---------- 用例详情 ----------
const viewCase = (row) => {
  detailCase.value = row
  caseDetailVisible.value = true
}

// ---------- 新建 / 编辑单条用例 ----------
const caseFormVisible = ref(false)
const caseFormMode = ref('add')           // 'add' | 'edit'
const caseFormSaving = ref(false)
const caseFormRef = ref(null)
const editingCaseId = ref('')             // 编辑时记录原始 case id
const editingModuleName = ref('')         // 编辑时记录原始所属模块

const defaultCaseForm = () => ({
  name: '',
  module: '',
  priority: 'P1',
  type: '功能测试',
  test_method: '',
  preconditions: '',
  stepsText: '',
  expected: '',
})
const caseForm = ref(defaultCaseForm())
const caseFormRules = {
  name:     [{ required: true, message: '请输入用例名称', trigger: 'blur' }],
  module:   [{ required: true, message: '请选择或输入所属模块', trigger: 'blur' }],
  priority: [{ required: true, message: '请选择优先级', trigger: 'change' }],
  stepsText:[{ required: true, message: '请输入测试步骤', trigger: 'blur' }],
  expected: [{ required: true, message: '请输入预期结果', trigger: 'blur' }],
}

/** 步骤文本 → 步骤数组（去掉行首 "1." "1、" "- " 等前缀） */
const stepsTextToArray = (text) =>
  (text || '')
    .split('\n')
    .map(l => l.replace(/^[\s\d]+[.、。\-\s]+/, '').trim())
    .filter(Boolean)

const openAddCase = () => {
  if (!current.value) return
  caseForm.value = defaultCaseForm()
  // 默认填入第一个模块名
  caseForm.value.module = current.value.modules?.[0]?.name || ''
  caseFormMode.value = 'add'
  editingCaseId.value = ''
  caseFormVisible.value = true
}

const openEditCase = (row, moduleName) => {
  caseForm.value = {
    name: row.name || '',
    module: moduleName || '',
    priority: row.priority || 'P1',
    type: row.type || '功能测试',
    test_method: row.test_method || '',
    preconditions: row.preconditions || '',
    stepsText: Array.isArray(row.steps) ? row.steps.join('\n') : (row.steps || ''),
    expected: row.expected || '',
  }
  editingCaseId.value = row.id
  editingModuleName.value = moduleName
  caseFormMode.value = 'edit'
  caseFormVisible.value = true
}

const saveCaseForm = async () => {
  await caseFormRef.value?.validate()
  caseFormSaving.value = true
  const payload = {
    name:         caseForm.value.name,
    module:       caseForm.value.module,
    priority:     caseForm.value.priority,
    type:         caseForm.value.type,
    test_method:  caseForm.value.test_method,
    preconditions: caseForm.value.preconditions,
    steps:        stepsTextToArray(caseForm.value.stepsText),
    expected:     caseForm.value.expected,
  }
  try {
    let result
    if (caseFormMode.value === 'add') {
      result = await aiCaseApi.addCase(current.value.id, payload)
      ElMessage.success('用例新建成功')
    } else {
      result = await aiCaseApi.updateCase(current.value.id, editingCaseId.value, payload)
      ElMessage.success('用例更新成功')
    }
    caseFormVisible.value = false
    // 用返回的最新数据刷新 current
    current.value = result
    // 同步更新 records 列表中的对应项
    const idx = records.value.findIndex(r => r.id === result.id)
    if (idx !== -1) records.value[idx] = result
  } catch (e) {
    ElMessage.error((e.response?.data?.detail || e.message || '保存失败'))
  } finally {
    caseFormSaving.value = false
  }
}

const deleteCaseItem = async (row, moduleName) => {
  try {
    await ElMessageBox.confirm(
      `确认删除用例「${row.name}」？此操作不可恢复。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消', confirmButtonClass: 'el-button--danger' }
    )
    const result = await aiCaseApi.deleteCase(current.value.id, row.id)
    ElMessage.success('用例已删除')
    current.value = result
    const idx = records.value.findIndex(r => r.id === result.id)
    if (idx !== -1) records.value[idx] = result
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.response?.data?.detail || e.message || '删除失败')
  }
}

// ---------- 工具 ----------
const formatDate = (str) => {
  if (!str) return ''
  try {
    const utc = /[Z+]/.test(str) ? str : str + 'Z'
    return new Date(utc).toLocaleString('zh-CN', { hour12: false })
  } catch { return str }
}

onMounted(fetchRecords)
onUnmounted(disconnectGenWS)
</script>

<style scoped>
.ai-cases-page { padding: 0; }

/* 统计栏 */
.stats-bar {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}
.stat-card {
  display: flex;
  align-items: center;
  padding: 18px 20px;
  border-radius: 10px;
  color: #fff;
  gap: 14px;
}
.stat-num { font-size: 30px; font-weight: 700; }
.stat-label { font-size: 13px; opacity: .9; margin-top: 2px; }

/* 列表 */
.list-card { min-height: 500px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.empty-box { display: flex; justify-content: center; align-items: center; min-height: 300px; }
.record-list { max-height: 620px; overflow-y: auto; }
.record-item {
  padding: 12px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: all .2s;
}
.record-item:hover { border-color: #409eff; box-shadow: 0 2px 8px rgba(64,158,255,.12); }
.record-item.active { border-color: #409eff; background: #ecf5ff; }
.record-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.record-name { font-weight: 600; font-size: 14px; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.record-actions { display: flex; align-items: center; gap: 2px; flex-shrink: 0; }

/* 优化弹窗 */
.optimize-info { }
.optimize-tags {
  display: flex; align-items: center; gap: 6px;
  flex-wrap: wrap; margin-top: 12px;
}
.tag-label { font-size: 12px; color: #606266; flex-shrink: 0; }
.record-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.record-count { font-size: 12px; color: #409eff; }
.record-date { font-size: 12px; color: #909399; margin-left: auto; }

/* 右侧详情 */
.detail-title { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600; }
.download-btns { display: flex; gap: 8px; }
.modules-preview { max-height: 560px; overflow-y: auto; }
.mod-title { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.mod-badge { margin-left: 4px; }

/* 覆盖度分析抽屉 */
.coverage-panel { padding: 0 4px; }
.score-block { display: flex; align-items: center; gap: 20px; padding: 8px 0; }
.score-meta { display: flex; flex-direction: column; gap: 4px; }
.score-title { font-size: 16px; font-weight: 600; }
.score-total { color: #909399; font-size: 13px; }
.score-name { color: #606266; font-size: 12px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.section-title { font-weight: 600; margin: 4px 0 10px; color: #303133; }
.method-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.method-item { display: flex; align-items: center; gap: 6px; font-size: 13px; padding: 6px 8px; border-radius: 6px; }
.method-item.covered { background: #f0f9eb; color: #67c23a; }
.method-item.missing { background: #f5f5f5; color: #909399; }
.type-bars, .priority-bars { display: flex; flex-direction: column; gap: 8px; }
.priority-row { display: flex; align-items: center; }
.type-label { width: 72px; font-size: 12px; color: #606266; flex-shrink: 0; }
.count-label { width: 38px; text-align: right; color: #606266; font-size: 13px; }
.suggestions { padding-left: 18px; margin: 4px 0; }
.suggestions li { line-height: 1.8; color: #606266; font-size: 13px; }
.zero-warn { color: #f56c6c; font-weight: 600; }
.coverage-empty { display: flex; justify-content: center; align-items: center; height: 200px; }

/* 生成对话框 */
.generating-tip {
  padding: 14px 16px;
  background: #ecf5ff;
  border-radius: 8px;
  margin-top: 10px;
  border: 1px solid #d9ecff;
}
.gen-progress-header {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #409eff;
  font-size: 14px;
  margin-bottom: 2px;
}
.gen-stage-text { flex: 1; }
.gen-pct { font-weight: 700; font-size: 15px; }
.spin { animation: spin 1s linear infinite; flex-shrink: 0; }
@keyframes spin { from { transform: rotate(0deg) } to { transform: rotate(360deg) } }

/* 用例详情 */
.detail-section-title {
  font-size: 13px; font-weight: 600; color: #303133;
  border-left: 3px solid #409eff; padding-left: 8px; margin-bottom: 8px;
}
.step-list { padding-left: 20px; }
.step-list li { padding: 3px 0; font-size: 13px; color: #606266; }
.expected-box {
  background: #f0f9eb; border: 1px solid #e1f3d8;
  border-radius: 4px; padding: 10px 14px;
  font-size: 13px; color: #67c23a;
}
</style>
