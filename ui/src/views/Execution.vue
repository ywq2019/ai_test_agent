<template>
  <div class="execution-page">
    <WorkspaceRequired v-if="auth.role !== 'admin' && !wsStore.currentId" />
    <template v-else>
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span class="page-title">测试执行</span>
          <div class="header-controls">
            <el-tooltip :content="wsConnected ? 'WebSocket 已连接' : 'WebSocket 未连接'">
              <span class="ws-dot" :class="wsConnected ? 'ws-on' : 'ws-off'"></span>
            </el-tooltip>
            <el-select v-model="selectedTaskId" placeholder="选择任务" style="width: 180px;" @change="onTaskChange" size="default">
              <el-option v-for="task in taskStore.tasks" :key="task.id" :label="task.name" :value="task.id" />
            </el-select>
            <el-select v-model="selectedBrowser" style="width: 110px;" size="default">
              <el-option label="Chromium" value="chromium" />
              <el-option label="Firefox" value="firefox" />
              <el-option label="WebKit" value="webkit" />
            </el-select>
            <el-dropdown trigger="click">
              <el-button size="default" :disabled="!selectedTaskId">
                <el-icon><MoreFilled /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item @click="; multiBrowserMode = true">
                    <el-icon><Connection /></el-icon>多浏览器并行执行
                  </el-dropdown-item>
                  <el-dropdown-item @click="envVarDialogVisible = true">
                    <el-icon><Setting /></el-icon>环境变量
                  </el-dropdown-item>
                  <el-dropdown-item @click="exportPytest" :disabled="exportLoading">
                    <el-icon><Download /></el-icon>导出 pytest 脚本
                  </el-dropdown-item>
                  <el-dropdown-item divided @click="toggleRecording">
                    <el-icon><VideoCamera /></el-icon>{{ isRecording ? '停止录制' : recordingStarting ? '启动中...' : '录制操作' }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-button type="success" size="default" @click="openScenePlanner" :disabled="!selectedTaskId">
              <el-icon><MagicStick /></el-icon>
              AI 规划场景
            </el-button>
            <el-button type="primary" size="default" @click="executeAll" :loading="taskStore.isExecuting" :disabled="!selectedTaskId">
              <el-icon><VideoPlay /></el-icon>
              执行全部
            </el-button>
          </div>
        </div>
      </template>

      <!-- 多浏览器选项 -->
      <el-alert v-if="multiBrowserMode" type="info" :closable="true" @close="multiBrowserMode = false" style="margin-bottom: 14px;">
        <template #title>多浏览器并行模式</template>
        <el-checkbox-group v-model="selectedBrowsers" size="small">
          <el-checkbox-button value="chromium">Chromium</el-checkbox-button>
          <el-checkbox-button value="firefox">Firefox</el-checkbox-button>
          <el-checkbox-button value="webkit">WebKit</el-checkbox-button>
        </el-checkbox-group>
      </el-alert>

      <!-- Tabs: 实时执行 / 执行历史 -->
      <el-tabs v-model="activeTab" type="border-card" @tab-change="onTabChange">
        <el-tab-pane label="实时执行" name="live">
          <!-- 进度面板 -->
          <div v-if="taskStore.isExecuting || liveResults.length > 0" class="progress-panel">
            <div class="progress-header">
              <div class="progress-status-row">
                <span class="status-dot" :class="taskStore.isExecuting ? 'running' : (failedCount > 0 ? 'failed' : 'done')"></span>
                <span class="status-label">
                  {{ taskStore.isExecuting ? '执行中' : (failedCount > 0 ? '执行完成（含失败）' : '执行完成') }}
                </span>
                <span class="case-progress-text">{{ liveResults.length }} / {{ liveTotal }} 用例</span>
              </div>
              <div class="progress-right">
                <span v-if="elapsedTime !== null" class="elapsed-time">
                  <el-icon><Timer /></el-icon>{{ elapsedTime }}s
                </span>
                <div class="progress-controls" v-if="taskStore.isExecuting">
                  <el-button size="small" @click="pauseExecution">暂停</el-button>
                  <el-button size="small" type="primary" @click="resumeExecution">继续</el-button>
                  <el-button size="small" type="danger" @click="stopExecution">停止</el-button>
                </div>
              </div>
            </div>

            <el-progress
              :percentage="progressPercentage"
              :status="progressStatus"
              :stroke-width="16"
              :striped="taskStore.isExecuting"
              :striped-flow="taskStore.isExecuting"
              style="margin: 10px 0 6px;"
            />

            <div v-if="taskStore.isExecuting && currentCaseName" class="current-case-bar">
              <el-icon class="spin-icon"><Loading /></el-icon>
              <span>正在执行：<strong>{{ currentCaseName }}</strong></span>
            </div>

            <div class="progress-mini-stats">
              <div class="mini-stat total-stat"><span class="mini-val">{{ liveTotal }}</span><span class="mini-lbl">总计</span></div>
              <div class="mini-stat passed-stat"><span class="mini-val">{{ passedCount }}</span><span class="mini-lbl">通过</span></div>
              <div class="mini-stat failed-stat"><span class="mini-val">{{ failedCount }}</span><span class="mini-lbl">失败</span></div>
              <div class="mini-stat rate-stat"><span class="mini-val">{{ passRate }}%</span><span class="mini-lbl">通过率</span></div>
            </div>
          </div>

          <!-- 空状态提示 -->
          <el-empty v-if="!taskStore.isExecuting && liveResults.length === 0" description="选择任务后点击「执行全部」开始测试">
            <template #extra>
              <div style="color: #909399; font-size: 13px;">
                执行结果将实时显示在此处，也可切换到「执行历史」查看过往报告
              </div>
            </template>
          </el-empty>

          <!-- 执行结果表格 -->
          <el-table v-if="liveResults.length > 0" :data="liveResults" stripe style="width: 100%; margin-top: 12px;" max-height="460">
            <el-table-column prop="case_name" label="用例名称" min-width="160" show-overflow-tooltip />
            <el-table-column prop="status" label="状态" width="85" align="center">
              <template #default="{ row }">
                <el-tag :type="getStatusType(row.status)" size="small">{{ getStatusText(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="duration" label="耗时" width="80" align="center">
              <template #default="{ row }">{{ row.duration ? row.duration.toFixed(1) + 's' : '-' }}</template>
            </el-table-column>
            <el-table-column prop="error_message" label="错误信息" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                <span :style="{ color: row.status === 'failed' ? '#f56c6c' : '' }">{{ row.error_message || '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="截图" width="75" align="center">
              <template #default="{ row }">
                <el-button v-if="row.screenshot_path" type="primary" link size="small" @click="viewScreenshot(row.screenshot_path)">查看</el-button>
                <span v-else style="color:#c0c4cc;">-</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="80" align="center">
              <template #default="{ row }">
                <el-button type="warning" link size="small" @click="retryCase(row)" :disabled="taskStore.isExecuting">重试</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div v-if="liveResults.length > 0 && !taskStore.isExecuting" style="margin-top: 12px; display: flex; gap: 8px;">
            <el-button size="small" type="primary" @click="executeAll" :disabled="!selectedTaskId">
              <el-icon><RefreshRight /></el-icon>重新执行
            </el-button>
            <el-button v-if="failedCount > 0" size="small" type="warning" @click="goToCaseManagement">
              <el-icon><MagicStick /></el-icon>去用例管理修正失败用例
            </el-button>
          </div>
        </el-tab-pane>

        <!-- 执行历史 Tab -->
        <el-tab-pane label="执行历史" name="history">
          <div class="history-toolbar">
            <el-button size="small" type="primary" @click="fetchHistory" :loading="historyLoading" :disabled="!selectedTaskId">
              <el-icon><Refresh /></el-icon>刷新
            </el-button>
            <el-button size="small" type="danger" :disabled="historySelected.length === 0" @click="deleteHistoryBatch">
              <el-icon><Delete /></el-icon>批量删除{{ historySelected.length ? '(' + historySelected.length + ')' : '' }}
            </el-button>
            <span class="history-count" v-if="historyList.length">共 {{ historyList.length }} 条记录</span>
          </div>

          <el-empty v-if="historyList.length === 0 && !historyLoading" description="暂无执行记录，请先执行测试" />

          <el-table v-if="historyList.length > 0" :data="historyList" stripe max-height="460"
            @selection-change="onHistorySelectionChange" row-key="report_id">
            <el-table-column type="selection" width="40" />
            <el-table-column type="index" label="序号" width="60" />
            <el-table-column prop="task_name" label="任务" min-width="140" show-overflow-tooltip />
            <el-table-column label="通过率" width="90" align="center">
              <template #default="{ row }">
                <el-progress :percentage="row.pass_rate" :color="row.pass_rate >= 80 ? '#67c23a' : row.pass_rate >= 60 ? '#e6a23c' : '#f56c6c'" :stroke-width="6" style="width:60px;display:inline-block" />
                <span style="font-size:12px;margin-left:4px;">{{ row.pass_rate }}%</span>
              </template>
            </el-table-column>
            <el-table-column label="通过/失败" width="110" align="center">
              <template #default="{ row }">
                <span class="history-passed">{{ row.passed }}</span> /
                <span class="history-failed">{{ row.failed }}</span>
              </template>
            </el-table-column>
            <el-table-column label="执行时间" width="160" align="center">
              <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="130" align="center" fixed="right">
              <template #default="{ row }">
                <el-button type="primary" link size="small" @click="viewHistoryReport(row)">查看</el-button>
                <el-button type="danger" link size="small" @click="deleteHistoryOne(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 截图查看 dialog -->
    <el-dialog v-model="showScreenshotDialog" title="截图" width="800px">
      <img v-if="screenshotUrl" :src="screenshotUrl" style="width: 100%;" />
    </el-dialog>

    <!-- 环境变量 dialog -->
    <el-dialog v-model="envVarDialogVisible" title="任务环境变量" width="560px" destroy-on-close>
      <el-table :data="envVars" size="small">
        <el-table-column prop="key" label="Key" min-width="120" />
        <el-table-column label="Value" min-width="140">
          <template #default="{ row }">{{ row.is_secret ? '******' : row.value }}</template>
        </el-table-column>
        <el-table-column label="Secret" width="70">
          <template #default="{ row }"><el-tag size="small" :type="row.is_secret ? 'danger' : 'info'">{{ row.is_secret ? '是' : '否' }}</el-tag></template>
        </el-table-column>
        <el-table-column label="操作" width="60">
          <template #default="{ row }"><el-button type="danger" size="small" text @click="deleteEnvVar(row.id)">删除</el-button></template>
        </el-table-column>
      </el-table>
      <el-divider>新增</el-divider>
      <el-form :model="newEnvVar" inline>
        <el-form-item label="Key"><el-input v-model="newEnvVar.key" placeholder="KEY" style="width:120px;" size="small" /></el-form-item>
        <el-form-item label="Value"><el-input v-model="newEnvVar.value" placeholder="value" style="width:140px;" size="small" /></el-form-item>
        <el-form-item label="Secret"><el-switch v-model="newEnvVar.is_secret" size="small" /></el-form-item>
        <el-form-item><el-button type="primary" size="small" @click="saveEnvVar" :loading="envVarLoading">保存</el-button></el-form-item>
      </el-form>
    </el-dialog>

    <!-- 录制 dialog -->
    <el-dialog v-model="recordingDialogVisible" title="录制操作" width="520px" :close-on-click-modal="false">
      <!-- 启动中状态 -->
      <el-alert v-if="recordingStarting" type="info" show-icon :closable="false" style="margin-bottom:12px;">
        <template #title>
          <el-icon class="is-loading" style="margin-right:6px"><Loading /></el-icon>
          浏览器启动中，请稍候（约 15-20 秒）...
        </template>
      </el-alert>
      <!-- 录制中状态 -->
      <el-alert v-else-if="isRecording" type="warning" show-icon :closable="false" style="margin-bottom:12px;">
        浏览器已弹出，请在页面中操作，步骤会实时预览。完成后点击「停止录制」。
      </el-alert>
      <template v-if="!isRecording && !recordingStarting && recordedSteps.length">
        <el-alert type="success" show-icon :closable="false" style="margin-bottom:12px;">
          录制完成，共 {{ recordedSteps.length }} 个步骤
        </el-alert>
        <el-input v-model="recordingCaseName" placeholder="用例名称" style="margin-bottom:10px;" />
      </template>
      <el-scrollbar max-height="260px" v-if="recordedSteps.length">
        <div class="rec-step-list">
          <div v-for="(s, i) in recordedSteps" :key="i" class="rec-step-item">
            <el-tag size="small" :type="actionTagType(s.action)" effect="plain">{{ s.action }}</el-tag>
            <span class="rec-step-desc">{{ s.description || s.selector || s.url || s.value || '' }}</span>
          </div>
        </div>
      </el-scrollbar>
      <el-empty v-else-if="!isRecording && !recordingStarting" description="暂无步骤" />
      <template #footer>
        <el-button v-if="isRecording" type="danger" @click="stopRecording" :loading="recordingLoading">停止录制</el-button>
        <el-button v-if="!isRecording && !recordingStarting && recordedSteps.length" type="primary" @click="saveRecording" :loading="recordingLoading">保存为用例</el-button>
        <el-button @click="recordingDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- ══ AI 场景规划侧抽屉 ══ -->
    <el-drawer
      v-model="scenePlannerVisible"
      direction="rtl"
      size="500px"
      :close-on-click-modal="false"
    >
      <template #header>
        <div style="display:flex;align-items:center;gap:10px;flex:1">
          <el-icon size="20" color="#409eff"><MagicStick /></el-icon>
          <span style="font-size:16px;font-weight:600">AI 场景规划</span>
          <!-- 进度 -->
          <template v-if="scenes.length">
            <el-tag size="small" type="info" effect="plain">
              {{ scenes.filter(s=>s.recorded).length }}/{{ scenes.length }} 已录制
            </el-tag>
            <el-progress
              v-if="scenes.length"
              :percentage="Math.round(scenes.filter(s=>s.recorded).length/scenes.length*100)"
              :stroke-width="6"
              style="width:80px;margin-left:4px"
              :status="scenes.every(s=>s.recorded) ? 'success' : ''"
            />
          </template>
        </div>
      </template>

      <!-- ── 输入区（未生成 / 需重新规划） ── -->
      <div v-if="!scenes.length" class="scene-input-area">
        <div class="scene-intro">
          <p>AI 会从 <strong>5 个落地维度</strong>分析页面，自动规划场景列表：</p>
          <div class="scene-dimensions">
            <el-tag v-for="d in sceneDimensions" :key="d.name" size="small"
              :type="d.type" effect="plain" class="dim-tag">
              {{ d.name }}
            </el-tag>
          </div>
        </div>

        <!-- 无页面元素提示 -->
        <el-alert v-if="!hasPageElements" type="warning" show-icon :closable="false"
          style="margin-bottom:14px">
          <template #title>尚未抓取页面元素</template>
          <template #default>
            <div style="margin-top:6px">
              <div style="color:#606266;font-size:13px;margin-bottom:8px">
                抓取后 AI 可根据页面实际结构规划场景，准确度更高。也可以跳过，在下方补充功能描述后直接生成。
              </div>
              <el-button size="small" type="warning" plain
                :loading="parsingPage" @click="parseCurrentPage">
                <el-icon><Connection /></el-icon>
                {{ parsingPage ? '抓取中...' : '抓取页面元素' }}
              </el-button>
            </div>
          </template>
        </el-alert>
        <!-- 已有元素时显示简要信息 -->
        <div v-else class="page-elements-hint">
          <el-icon size="13" color="#67c23a"><SuccessFilled /></el-icon>
          已抓取页面元素
          <el-button size="small" link @click="parseCurrentPage" :loading="parsingPage"
            style="margin-left:4px">重新抓取</el-button>
        </div>

        <el-form label-position="top" size="small">
          <el-form-item>
            <template #label>
              <span>页面功能描述
                <span style="color:#909399;font-weight:400">（补充后 AI 更精准）</span>
              </span>
            </template>
            <el-input
              v-model="sceneDescription"
              type="textarea" :rows="3"
              placeholder="例：登录页，支持账号密码登录和短信验证码登录，登录失败提示错误原因，支持记住密码"
            />
          </el-form-item>
        </el-form>

        <el-button type="primary" style="width:100%;height:40px;font-size:14px"
          :loading="scenePlanning" @click="planScenes(false)">
          <el-icon style="margin-right:6px"><MagicStick /></el-icon>
          {{ scenePlanning ? 'AI 分析中...' : '开始分析，生成场景' }}
        </el-button>
        <div v-if="scenePlanning" class="scene-planning-hint">
          <el-icon class="is-loading"><Loading /></el-icon>
          正在从 6 个测试维度分析页面，约需 15-30 秒...
        </div>
      </div>

      <!-- ── 场景列表 ── -->
      <div v-else class="scene-list-area">
        <!-- 操作栏 -->
        <div class="scene-toolbar">
          <span style="font-size:13px;color:#606266">
            点击场景卡片的「录制」按钮，录完自动保存为用例
          </span>
          <div style="display:flex;gap:6px">
            <el-button size="small" :loading="scenePlanning" @click="planScenes(true)">
              <el-icon><Plus /></el-icon>追加场景
            </el-button>
            <el-button size="small" text type="danger" @click="resetScenes">
              重新规划
            </el-button>
          </div>
        </div>

        <div class="scene-list">
          <div v-for="scene in scenes" :key="scene.id"
            class="scene-card" :class="{ 'scene-recorded': scene.recorded }">

            <!-- 卡片头部 -->
            <div class="scene-card-header">
              <div style="display:flex;align-items:center;gap:6px;flex:1;min-width:0">
                <el-tag size="small"
                  :type="scene.priority==='P0'?'danger':scene.priority==='P1'?'warning':'info'"
                  effect="plain">{{ scene.priority }}</el-tag>
                <el-tag v-if="scene.dimension" size="small" type="info" effect="plain"
                  style="font-size:11px">{{ scene.dimension }}</el-tag>
                <!-- 场景名行内编辑 -->
                <template v-if="editingSceneId === scene.id">
                  <el-input v-model="scene.name" size="small" style="flex:1"
                    @blur="editingSceneId = null"
                    @keyup.enter="editingSceneId = null"
                    @keyup.esc="editingSceneId = null"
                    autofocus />
                </template>
                <span v-else class="scene-name" @click="editingSceneId = scene.id"
                  title="点击编辑名称">{{ scene.name }}</span>
              </div>
              <el-tag v-if="scene.recorded" size="small" type="success" effect="dark">✓ 已录制</el-tag>
              <el-button v-else link size="small" type="danger" style="padding:0;margin-left:4px"
                @click="removeScene(scene.id)" title="删除此场景">
                <el-icon><Close /></el-icon>
              </el-button>
            </div>

            <!-- 描述（可行内编辑） -->
            <div v-if="editingSceneId === scene.id">
              <el-input v-model="scene.description" size="small" type="textarea" :rows="2"
                style="margin-top:6px" placeholder="场景描述" />
            </div>
            <div v-else class="scene-desc" @click="editingSceneId = scene.id"
              title="点击编辑描述">{{ scene.description }}</div>

            <!-- 步骤预览（折叠） -->
            <el-collapse-transition>
              <div v-if="expandedSceneId === scene.id" class="scene-steps">
                <div v-for="(step, i) in scene.steps_desc" :key="i" class="scene-step-item">
                  <span class="step-num">{{ i + 1 }}</span>
                  <span>{{ step }}</span>
                </div>
                <div v-if="scene.expected" class="scene-expected" style="margin-top:6px">
                  <el-icon size="12" color="#67c23a"><SuccessFilled /></el-icon>
                  {{ scene.expected }}
                </div>
              </div>
            </el-collapse-transition>

            <!-- 展开/收起步骤 -->
            <div v-if="scene.steps_desc && scene.steps_desc.length"
              class="scene-expand-btn" @click="toggleExpandScene(scene.id)">
              <el-icon size="12"><ArrowDown v-if="expandedSceneId !== scene.id" /><ArrowUp v-else /></el-icon>
              {{ expandedSceneId === scene.id ? '收起' : `查看 ${scene.steps_desc.length} 步` }}
            </div>

            <!-- 操作按钮 -->
            <div class="scene-actions">
              <el-button v-if="!scene.recorded" type="primary" size="small"
                @click="startSceneRecording(scene)"
                :loading="scene.id === recordingSceneId">
                <el-icon><VideoCamera /></el-icon>开始录制
              </el-button>
              <el-button v-else size="small" plain @click="startSceneRecording(scene)">
                <el-icon><Refresh /></el-icon>重新录制
              </el-button>
            </div>
          </div>
        </div>

        <!-- 全部完成提示 -->
        <div v-if="scenes.length && scenes.every(s => s.recorded)" class="scene-done-banner">
          <div style="font-size:15px;color:#27ae60;font-weight:600;margin-bottom:4px">
            🎉 所有场景已录制完成
          </div>
          <div style="font-size:13px;color:#606266">用例已保存，可在「用例管理」页查看并执行</div>
        </div>
      </div>
    </el-drawer>

    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useTaskStore } from '../stores/task'
import { useWorkspaceStore } from '../stores/workspace'
import { useAuthStore } from '../stores/auth'
import WorkspaceRequired from '../components/WorkspaceRequired.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  VideoCamera, VideoPause, Setting, Download, VideoPlay, Timer,
  RefreshRight, MagicStick, Refresh, Delete, Connection, MoreFilled, DocumentChecked,
  Loading, SuccessFilled, Plus, Close, ArrowDown, ArrowUp,
} from '@element-plus/icons-vue'
import { useWebSocket } from '../composables/useWebSocket'
import { recordingApi, envVarApi, multiBrowserApi, pytestExportApi, reportApi, caseApi } from '../api/index'

const route = useRoute()
const router = useRouter()
const taskStore = useTaskStore()
const wsStore = useWorkspaceStore()
const auth = useAuthStore()

// ── 基础状态 ──
const selectedTaskId = ref(null)
const selectedBrowser = ref('chromium')
const multiBrowserMode = ref(false)
const selectedBrowsers = ref(['chromium', 'firefox', 'webkit'])
const activeTab = ref('live')

// ── 实时执行 ──
const liveResults = ref([])
const liveTotal = ref(0)
const liveProgress = ref(0)
const currentCaseName = ref('')
const elapsedTime = ref(null)
const wsConnected = ref(false)
let elapsedTimer = null
let startTimestamp = null
let wsReconnectTimer = null
let currentReportId = ref(null)

const showScreenshotDialog = ref(false)
const screenshotUrl = ref('')

// ── 执行历史 ──
const historyList = ref([])
const historyLoading = ref(false)
const historySelected = ref([])

// ── 录制 ──
const isRecording = ref(false)
const recordingLoading = ref(false)
const recordingStarting = ref(false)   // Chrome 正在启动中
const recordingDialogVisible = ref(false)
const recordedSteps = ref([])
const recordingCaseName = ref('')
let _recordingSessionId = null
let _recWsDisconnect = null  // 录制专用 WS 连接的断开函数

// 录制专用 WebSocket（监听 rec_{task_id} 频道）
const { connect: _recWsConnect, disconnect: _recWsDisconnectFn } = useWebSocket((msg) => {
  if (msg.type === 'recording_ready') {
    // Chrome 启动完成，切换到录制状态
    _recordingSessionId = msg.session_id
    isRecording.value = true
    recordingStarting.value = false
    recordingLoading.value = false
    ElMessage.success('浏览器已就绪，请在浏览器中操作')
  } else if (msg.type === 'recording_failed') {
    // 启动失败
    recordingStarting.value = false
    recordingLoading.value = false
    isRecording.value = false
    ElMessage.error('录制启动失败：' + (msg.error || '未知错误'))
    _recWsDisconnectFn()
  } else if (msg.type === 'rec_step') {
    // 实时步骤推送（已有逻辑）
    if (msg.step) recordedSteps.value.push(msg.step)
  }
})

// ── 环境变量 ──
const envVarDialogVisible = ref(false)
const envVars = ref([])
const envVarLoading = ref(false)
const newEnvVar = ref({ key: '', value: '', is_secret: false })

// ── pytest ──
const exportLoading = ref(false)

// ── AI 场景规划 ──────────────────────────────────────────────────────────────
const scenePlannerVisible = ref(false)
const scenePlanning = ref(false)
const sceneDescription = ref('')
const scenes = ref([])
const recordingSceneId = ref(null)
const editingSceneId = ref(null)     // 行内编辑中的场景 id
const expandedSceneId = ref(null)    // 展开步骤预览的场景 id

// 5 个测试维度标签
const sceneDimensions = [
  { name: '核心业务流程', type: 'success' },
  { name: '表单验证',     type: 'warning' },
  { name: '数据增删改',   type: 'primary' },
  { name: '列表与筛选',   type: 'info'    },
  { name: '异常与错误反馈', type: 'danger' },
]

// 当前任务是否已抓取页面元素
const hasPageElements = computed(() => {
  const task = taskStore.tasks.find(t => t.id === selectedTaskId.value)
  return task?.page_elements?.length > 0
})

// 抓取当前任务页面元素
const parsingPage = ref(false)
const parseCurrentPage = async () => {
  if (!selectedTaskId.value) return
  const task = taskStore.tasks.find(t => t.id === selectedTaskId.value)
  if (!task?.url) { ElMessage.warning('任务没有配置 URL，无法抓取页面元素'); return }
  parsingPage.value = true
  try {
    await taskStore.parsePage(task.url, task.browser || 'chromium', selectedTaskId.value)
    // 刷新 tasks 列表让 hasPageElements computed 更新
    await taskStore.fetchTasks(wsStore.currentId)
    ElMessage.success('页面元素抓取完成，AI 规划将更加精准')
  } catch (e) {
    ElMessage.error('抓取失败：' + (e?.response?.data?.detail || e?.message || ''))
  } finally {
    parsingPage.value = false
  }
}

const openScenePlanner = () => {
  scenePlannerVisible.value = true
}

// 从后端加载持久化的场景规划（从 Cases 页跳转过来时调用）
const loadPersistedScenes = async () => {
  if (!selectedTaskId.value) return
  try {
    const res = await caseApi.getScenePlan(selectedTaskId.value)
    if (res.scenes && res.scenes.length) {
      scenes.value = res.scenes
    }
  } catch { /* 无场景规划时静默忽略 */ }
}

// append=false → 重新规划；append=true → 追加规划（保留已录制）
const planScenes = async (append = false) => {
  if (!selectedTaskId.value) return
  scenePlanning.value = true
  try {
    const res = await caseApi.planScenes(selectedTaskId.value, {
      description: sceneDescription.value,
      append,
    })
    scenes.value = res.scenes || []
    if (!scenes.value.length) {
      ElMessage.warning('未能生成场景，请补充页面功能描述后重试')
    } else {
      ElMessage.success(append ? `已追加 ${res.scenes.length} 个场景` : `已生成 ${res.scenes.length} 个场景`)
    }
  } catch (e) {
    ElMessage.error('场景规划失败：' + (e?.response?.data?.detail || e?.message || ''))
  } finally {
    scenePlanning.value = false
  }
}

// 重新规划：清空本地列表，让用户重新输入描述后生成
const resetScenes = async () => {
  try {
    await ElMessageBox.confirm(
      '重新规划会清空所有未录制的场景（已录制的会保留），确认继续？',
      '重新规划', { type: 'warning', confirmButtonText: '确认', cancelButtonText: '取消' }
    )
    scenes.value = scenes.value.filter(s => s.recorded)
    if (!scenes.value.length) scenes.value = []
    sceneDescription.value = ''
  } catch { /* 取消 */ }
}

// 删除单个未录制场景
const removeScene = (sceneId) => {
  scenes.value = scenes.value.filter(s => s.id !== sceneId)
  // 同步持久化（静默）
  if (selectedTaskId.value) {
    caseApi.markSceneRecorded(selectedTaskId.value, sceneId, false).catch(() => {})
  }
}

// 展开/收起步骤预览
const toggleExpandScene = (sceneId) => {
  expandedSceneId.value = expandedSceneId.value === sceneId ? null : sceneId
}

const startSceneRecording = async (scene) => {
  // 先关闭抽屉，跳转到录制流程
  recordingSceneId.value = scene.id
  scenePlannerVisible.value = false

  // 设置录制完成后自动保存的场景名
  _pendingSceneName.value = scene.name

  // 触发录制（复用现有 startRecording 逻辑）
  await startRecording()
}

// 待保存的场景名（录制完成后自动填入用例名）
const _pendingSceneName = ref('')

// ── WebSocket ──
const { connect: _wsConnect, disconnect: _wsDisconnect, isConnected: wsIsConnected } = useWebSocket((msg) => {
  if (msg.type === 'case_complete') {
    if (currentReportId.value && msg.report_id && msg.report_id !== currentReportId.value) return
    liveResults.value.push({
      case_id: msg.case_id,
      case_name: msg.case_name,
      status: msg.status,
      duration: msg.duration,
      error_message: msg.error_message || '',
      screenshot_path: msg.screenshot_path || ''
    })
    liveTotal.value = msg.total || liveTotal.value
    liveProgress.value = msg.progress || 0
    currentCaseName.value = msg.case_name || ''
  } else if (msg.type === 'execution_started') {
    if (currentReportId.value && msg.report_id && msg.report_id !== currentReportId.value) return
    liveResults.value = []
    liveTotal.value = msg.total_cases || 0
    liveProgress.value = 0
    currentCaseName.value = ''
    taskStore.isExecuting = true
    startElapsedTimer()
  } else if (msg.type === 'execution_completed') {
    if (currentReportId.value && msg.report_id && msg.report_id !== currentReportId.value) return
    stopElapsedTimer()
    taskStore.isExecuting = false
    currentCaseName.value = ''
    liveProgress.value = 100
    ElMessage.success('执行完成')
  } else if (msg.type === 'execution_saved') {
    if (currentReportId.value && msg.report_id && msg.report_id !== currentReportId.value) return
    currentReportId.value = msg.report_id
    const s = msg.summary || {}
    ElMessage({ type: s.failed > 0 ? 'warning' : 'success', message: `${s.passed ?? '?'} 通过 / ${s.failed ?? '?'} 失败` })
  } else if (msg.type === 'execution_error') {
    if (currentReportId.value && msg.report_id && msg.report_id !== currentReportId.value) return
    stopElapsedTimer()
    taskStore.isExecuting = false
    ElMessage.error(`执行出错：${msg.error || '未知错误'}`)
  }
})

watch(wsIsConnected, (val) => {
  wsConnected.value = val
  if (!val && taskStore.isExecuting) {
    wsReconnectTimer = setTimeout(connectWS, 3000)
  }
})

function getClientId() { return `execution_${Date.now()}` }
function connectWS() {
  if (wsReconnectTimer) { clearTimeout(wsReconnectTimer); wsReconnectTimer = null }
  _wsConnect(getClientId())
}

const passedCount = computed(() => liveResults.value.filter(r => r.status === 'passed').length)
const failedCount = computed(() => liveResults.value.filter(r => r.status === 'failed').length)
const passRate = computed(() => {
  if (!liveResults.value.length) return 0
  return Math.round(passedCount.value / liveResults.value.length * 100)
})

const progressPercentage = computed(() => Math.round(liveProgress.value))
const progressStatus = computed(() => {
  if (liveProgress.value >= 100) return failedCount.value > 0 ? 'exception' : 'success'
  return ''
})

function startElapsedTimer() {
  startTimestamp = Date.now()
  elapsedTime.value = 0
  if (elapsedTimer) clearInterval(elapsedTimer)
  elapsedTimer = setInterval(() => { elapsedTime.value = Math.floor((Date.now() - startTimestamp) / 1000) }, 1000)
}
function stopElapsedTimer() {
  if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null }
}

const getStatusType = (s) => ({ passed: 'success', failed: 'danger', skipped: 'warning' }[s] || 'info')
const getStatusText = (s) => ({ passed: '通过', failed: '失败', skipped: '跳过' }[s] || s)
const formatDate = (d) => {
  if (!d) return '-'
  try { return new Date(d).toLocaleString('zh-CN', { hour12: false }) } catch { return d }
}

// ── 录制标签 ──
const actionTagType = (a) => {
  if (!a) return 'info'
  if (a.startsWith('assert')) return 'success'
  if (a === 'navigate') return 'primary'
  if (a === 'fill') return 'warning'
  return 'info'
}

// ── 任务切换 ──
const onTaskChange = async (taskId) => {
  if (taskId) await taskStore.fetchCases(taskId)
  // 切换到执行历史时自动拉取
  if (activeTab.value === 'history') fetchHistory()
}
const onTabChange = (tab) => { if (tab === 'history') fetchHistory() }

// ── 执行全部 ──
const executeAll = async () => {
  if (!selectedTaskId.value) { ElMessage.warning('请选择任务'); return }
  liveResults.value = []
  liveProgress.value = 0
  currentCaseName.value = ''
  currentReportId.value = null
  liveTotal.value = taskStore.cases.length
  activeTab.value = 'live'
  try {
    if (multiBrowserMode.value) {
      if (!selectedBrowsers.value.length) { ElMessage.warning('请至少选择一个浏览器'); return }
      const data = await multiBrowserApi.execute({ task_id: selectedTaskId.value, browsers: selectedBrowsers.value })
      if (data?.total) liveTotal.value = data.total
      if (data?.report_ids) {
        const ids = Object.values(data.report_ids)
        if (ids.length > 0) currentReportId.value = ids[0]
      }
      ElMessage.info(`已开始多浏览器并行执行（${selectedBrowsers.value.join('/')}）`)
    } else {
      const data = await taskStore.executeCases(selectedTaskId.value, null, selectedBrowser.value)
      if (data?.report_id) currentReportId.value = data.report_id
      if (data?.total) liveTotal.value = data.total
      ElMessage.info(`已开始执行 ${data?.total ?? liveTotal.value} 个用例`)
    }
  } catch (error) {
    taskStore.isExecuting = false
    stopElapsedTimer()
    ElMessage.error('执行失败: ' + error.message)
  }
}

const pauseExecution = async () => { await taskStore.pauseExecution(); ElMessage.info('已暂停') }
const resumeExecution = async () => { await taskStore.resumeExecution(); ElMessage.info('已继续') }
const stopExecution = async () => { await taskStore.stopExecution(); ElMessage.info('停止指令已发送') }

const retryCase = async (row) => {
  if (!selectedTaskId.value) return
  liveResults.value = []
  liveProgress.value = 0
  currentCaseName.value = ''
  currentReportId.value = null
  liveTotal.value = 1
  activeTab.value = 'live'
  try {
    const data = await taskStore.executeCases(selectedTaskId.value, [row.case_id], selectedBrowser.value)
    if (data?.report_id) currentReportId.value = data.report_id
    ElMessage.info('重试已开始')
  } catch (error) {
    taskStore.isExecuting = false
    stopElapsedTimer()
    ElMessage.error('重试失败: ' + error.message)
  }
}

const goToCaseManagement = () => {
  router.push({ path: '/cases', query: { taskId: selectedTaskId.value } })
}

const viewScreenshot = (path) => {
  screenshotUrl.value = path.startsWith('/') ? path : '/' + path
  showScreenshotDialog.value = true
}

// ── 执行历史 ──
const fetchHistory = async () => {
  if (!selectedTaskId.value) {
    historyList.value = []
    return
  }
  historyLoading.value = true
  try {
    const data = await reportApi.list(wsStore.currentId)
    // 过滤当前任务相关的报告
    historyList.value = (data || []).filter(r => r.task_id === selectedTaskId.value)
  } catch (e) {
    ElMessage.error('获取历史记录失败')
    historyList.value = []
  } finally {
    historyLoading.value = false
  }
}

const onHistorySelectionChange = (rows) => { historySelected.value = rows.map(r => r.report_id) }

const deleteHistoryOne = async (row) => {
  try {
    await ElMessageBox.confirm(`删除 ID 为 ${row.report_id} 的执行记录？`, '确认', { type: 'warning' })
    await reportApi.delete(row.report_id)
    ElMessage.success('已删除')
    fetchHistory()
  } catch (e) { /* cancelled */ }
}

const deleteHistoryBatch = async () => {
  if (!historySelected.value.length) return
  try {
    await ElMessageBox.confirm(`删除 ${historySelected.value.length} 条执行记录？`, '批量删除', { type: 'warning' })
    await reportApi.deleteBatch(historySelected.value)
    ElMessage.success(`已删除 ${historySelected.value.length} 条`)
    historySelected.value = []
    fetchHistory()
  } catch (e) { /* cancelled */ }
}

const viewHistoryReport = (row) => {
  router.push({ path: '/reports', query: { reportId: row.report_id } })
}

// ── 录制 ──
const toggleRecording = () => {
  if (recordingStarting.value) return  // 启动中禁止重复点击
  isRecording.value ? stopRecording() : startRecording()
}

const startRecording = async () => {
  if (!selectedTaskId.value) return
  recordingLoading.value = true
  recordingStarting.value = true
  try {
    const task = taskStore.tasks.find(t => t.id === selectedTaskId.value)
    // 先连上录制专用 WS 频道，再发起启动请求
    _recWsConnect(`rec_${selectedTaskId.value}`)
    const res = await recordingApi.start(selectedTaskId.value, task?.url || '', selectedBrowser.value)
    // 立即返回 status=starting，等 recording_ready WS 消息
    _recordingSessionId = res.session_id  // 预生成的 session_id
    recordedSteps.value = []
    recordingDialogVisible.value = true
    ElMessage.info('浏览器启动中，请稍候...')
    // loading 状态由 WS recording_ready 消息关闭
  } catch (e) {
    const status = e.response?.status
    const detail = e.response?.data?.detail || e.message
    if (status === 409) {
      ElMessage.warning('该任务已有录制会话在运行，请直接在已打开的浏览器中操作，或停止后重新录制')
      isRecording.value = true
    } else {
      ElMessage.error('启动录制失败：' + detail)
    }
    recordingStarting.value = false
    recordingLoading.value = false
    _recWsDisconnectFn()
  }
}

const stopRecording = async () => {
  if (!_recordingSessionId && !selectedTaskId.value) return
  recordingLoading.value = true
  try {
    const res = await recordingApi.stop(_recordingSessionId, selectedTaskId.value)
    recordedSteps.value = res.steps || []
    isRecording.value = false
    recordingStarting.value = false
    _recordingSessionId = null
    _recWsDisconnectFn()  // 断开录制专用 WS
    // 如果是场景录制，自动填入场景名
    if (_pendingSceneName.value) {
      recordingCaseName.value = _pendingSceneName.value
    }
    ElMessage.success(`录制完成，共 ${recordedSteps.value.length} 个步骤`)
  } catch (e) { ElMessage.error('停止录制失败：' + e.message) }
  finally { recordingLoading.value = false }
}

const saveRecording = async () => {
  if (!recordedSteps.value.length || !selectedTaskId.value) return
  recordingLoading.value = true
  try {
    const name = recordingCaseName.value.trim() || ''
    const pageTitle = recordedSteps.value.length > 0 ? (recordedSteps.value[0].url || document.title) : document.title
    await recordingApi.save(selectedTaskId.value, recordedSteps.value, name, pageTitle)
    ElMessage.success(`已保存为用例「${name || '自动命名'}」`)
    recordingDialogVisible.value = false
    recordedSteps.value = []
    recordingCaseName.value = ''
    _recordingSessionId = null

    // 如果是场景录制，同步标记后端 + 本地，重新打开场景抽屉
    if (recordingSceneId.value) {
      const sceneId = recordingSceneId.value
      const scene = scenes.value.find(s => s.id === sceneId)
      if (scene) scene.recorded = true
      // 持久化标记到后端
      try { await caseApi.markSceneRecorded(selectedTaskId.value, sceneId, true) } catch {}
      recordingSceneId.value = null
      _pendingSceneName.value = ''
      setTimeout(() => { scenePlannerVisible.value = true }, 300)
    }

    // T7：从 Cases 页跳过来的，保存完成后提示返回
    if (route.query.from === 'cases') {
      ElMessage({
        type: 'success',
        message: '用例已保存，点击返回用例管理',
        duration: 5000,
        showClose: true,
        onClick: () => router.push({ name: 'Cases', query: { taskId: selectedTaskId.value, refresh: '1' } }),
      })
    }
  } catch (e) { ElMessage.error('保存失败：' + e.message) }
  finally { recordingLoading.value = false }
}

// ── 环境变量 ──
const loadEnvVars = async () => {
  if (!selectedTaskId.value) return
  try { envVars.value = await envVarApi.list(selectedTaskId.value) } catch {}
}
const saveEnvVar = async () => {
  if (!newEnvVar.value.key.trim()) { ElMessage.warning('Key 不能为空'); return }
  envVarLoading.value = true
  try {
    await envVarApi.create(selectedTaskId.value, newEnvVar.value)
    newEnvVar.value = { key: '', value: '', is_secret: false }
    await loadEnvVars()
    ElMessage.success('已保存')
  } catch (e) { ElMessage.error('保存失败：' + e.message) }
  finally { envVarLoading.value = false }
}
const deleteEnvVar = async (id) => {
  try { await envVarApi.delete(id); await loadEnvVars(); ElMessage.success('已删除') }
  catch (e) { ElMessage.error('删除失败：' + e.message) }
}
watch(envVarDialogVisible, (v) => { if (v) loadEnvVars() })

// ── pytest 导出 ──
const exportPytest = async () => {
  if (!selectedTaskId.value) return
  exportLoading.value = true
  try {
    const blob = await pytestExportApi.export(selectedTaskId.value)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = `pytest_task_${selectedTaskId.value}.zip`; a.click()
    URL.revokeObjectURL(url)
  } catch (e) { ElMessage.error('导出失败：' + e.message) }
  finally { exportLoading.value = false }
}

// ── 生命周期 ──
onMounted(async () => {
  connectWS()
  if (wsStore.initialized) await taskStore.fetchTasks(wsStore.currentId)
  if (route.query.taskId) {
    selectedTaskId.value = parseInt(route.query.taskId)
    await taskStore.fetchCases(selectedTaskId.value)
    // 来自 Cases 页的重录：预填用例名
    if (route.query.replaceCaseName) {
      _pendingSceneName.value = route.query.replaceCaseName
    }
    if (route.query.startRecord === '1') { await startRecording(); return }
    if (route.query.openScenePlanner === '1') {
      // 先加载持久化的场景规划
      await loadPersistedScenes()
      scenePlannerVisible.value = true
      return
    }
    if (route.query.caseIds) {
      const ids = route.query.caseIds.split(',').map(Number)
      liveResults.value = []; liveProgress.value = 0; currentCaseName.value = ''; currentReportId.value = null; liveTotal.value = ids.length
      activeTab.value = 'live'
      try {
        const data = await taskStore.executeCases(selectedTaskId.value, ids, selectedBrowser.value)
        if (data?.report_id) currentReportId.value = data.report_id
      } catch { ElMessage.error('自动执行失败') }
    }
  }
})

watch(() => wsStore.currentId, async (id) => {
  selectedTaskId.value = null
  liveResults.value = []; liveProgress.value = 0; liveTotal.value = 0; currentCaseName.value = ''; currentReportId.value = null
  historyList.value = []; historySelected.value = []
  stopElapsedTimer()
  if (taskStore.isExecuting) taskStore.isExecuting = false
  await taskStore.fetchTasks(id)
})
watch(() => wsStore.initialized, async (ready) => { if (ready) await taskStore.fetchTasks(wsStore.currentId) })

onUnmounted(() => {
  if (wsReconnectTimer) clearTimeout(wsReconnectTimer)
  stopElapsedTimer()
})
</script>

<style scoped>
.execution-page { padding: 0; }
.page-title { font-weight: 600; font-size: 16px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.header-controls { display: flex; align-items: center; gap: 8px; }

.ws-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; display: inline-block; }
.ws-on { background: #67c23a; }
.ws-off { background: #f56c6c; animation: pulse 1.2s ease-in-out infinite; }

/* 进度面板 */
.progress-panel {
  background: #f8faff; border: 1px solid #d0e4ff; border-radius: 10px;
  padding: 14px 18px; margin-bottom: 14px;
}
.progress-header { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; }
.progress-status-row { display: flex; align-items: center; gap: 8px; }
.status-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.status-dot.running { background: #409eff; animation: pulse 1.2s ease-in-out infinite; }
.status-dot.done { background: #67c23a; }
.status-dot.failed { background: #f56c6c; }
@keyframes pulse { 0%, 100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.5); opacity: 0.6; } }
.status-label { font-weight: 600; font-size: 14px; }
.case-progress-text { font-size: 13px; color: #606266; background: #e8f4ff; padding: 2px 10px; border-radius: 12px; }
.progress-right { display: flex; align-items: center; gap: 10px; }
.elapsed-time { display: flex; align-items: center; gap: 4px; font-size: 13px; color: #909399; }
.progress-controls { display: flex; gap: 6px; }
.current-case-bar { display: flex; align-items: center; gap: 6px; font-size: 13px; color: #409eff; background: #ecf5ff; border-radius: 6px; padding: 6px 12px; margin-bottom: 8px; }
.spin-icon { animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

.progress-mini-stats { display: flex; gap: 10px; margin-top: 10px; flex-wrap: wrap; }
.mini-stat { display: flex; flex-direction: column; align-items: center; padding: 8px 18px; border-radius: 8px; min-width: 68px; }
.mini-stat .mini-val { font-size: 20px; font-weight: bold; line-height: 1.2; }
.mini-stat .mini-lbl { font-size: 12px; margin-top: 2px; opacity: 0.85; }
.total-stat { background: linear-gradient(135deg, #667eea, #764ba2); color: #fff; }
.passed-stat { background: linear-gradient(135deg, #52c41a, #73d13d); color: #fff; }
.failed-stat { background: linear-gradient(135deg, #ff4d4f, #ff7875); color: #fff; }
.rate-stat { background: linear-gradient(135deg, #11998e, #38ef7d); color: #fff; }

/* 执行历史 */
.history-toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.history-count { color: #909399; font-size: 13px; margin-left: auto; }
.history-passed { color: #67c23a; font-weight: 600; }
.history-failed { color: #f56c6c; font-weight: 600; }

/* 录制 */
.rec-step-list { display: flex; flex-direction: column; gap: 4px; }
.rec-step-item { display: flex; align-items: center; gap: 8px; padding: 6px 10px; border-radius: 6px; background: #f8fafc; font-size: 12px; }
.rec-step-desc { flex: 1; color: #606266; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* ── AI 场景规划抽屉 ── */
/* 输入区 */
.scene-input-area { padding: 0 2px; }
.scene-intro { margin-bottom: 16px; font-size: 13px; color: #606266; line-height: 1.7; }
.scene-intro p { margin: 0 0 10px; }
.scene-dimensions { display: flex; flex-wrap: wrap; gap: 6px; }
.dim-tag { cursor: default; }
.scene-planning-hint {
  display: flex; align-items: center; gap: 6px; justify-content: center;
  margin-top: 14px; color: #909399; font-size: 13px;
}

/* 场景列表区 */
.scene-list-area { padding: 0 2px; }
.scene-toolbar {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 14px; gap: 8px; flex-wrap: wrap;
}
.scene-list { display: flex; flex-direction: column; gap: 10px; }

/* 场景卡片 */
.scene-card {
  border: 1px solid #e4e7ed; border-radius: 10px;
  padding: 12px 14px; background: #fff;
  transition: box-shadow .2s, border-color .2s;
}
.scene-card:hover { box-shadow: 0 2px 12px rgba(0,0,0,.07); border-color: #c6d8f5; }
.scene-recorded { border-color: #b7ebc8; background: #f6fff9; }

.scene-card-header {
  display: flex; align-items: center; gap: 6px;
  margin-bottom: 6px; flex-wrap: wrap;
}
.scene-name {
  flex: 1; font-size: 14px; font-weight: 600; color: #303133;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  cursor: text; border-bottom: 1px dashed transparent;
  transition: border-color .2s;
}
.scene-name:hover { border-bottom-color: #c0c4cc; }

.scene-desc {
  font-size: 13px; color: #606266; line-height: 1.5; margin-bottom: 8px;
  cursor: text; border-bottom: 1px dashed transparent; transition: border-color .2s;
}
.scene-desc:hover { border-bottom-color: #c0c4cc; }

/* 展开步骤 */
.scene-expand-btn {
  display: flex; align-items: center; gap: 4px;
  font-size: 12px; color: #909399; cursor: pointer;
  margin-bottom: 8px; transition: color .2s;
}
.scene-expand-btn:hover { color: #409eff; }

.scene-steps {
  display: flex; flex-direction: column; gap: 4px;
  background: #f8fafc; border-radius: 6px;
  padding: 8px 10px; margin-bottom: 8px;
}
.scene-step-item {
  display: flex; align-items: flex-start; gap: 8px;
  font-size: 12px; color: #606266; line-height: 1.5;
}
.step-num {
  flex-shrink: 0; width: 18px; height: 18px; border-radius: 50%;
  background: #409eff; color: #fff;
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 600; margin-top: 1px;
}
.scene-expected {
  display: flex; align-items: flex-start; gap: 5px;
  font-size: 12px; color: #67c23a; background: #f0fff4;
  border-radius: 5px; padding: 5px 8px; line-height: 1.5;
}

.scene-actions { display: flex; justify-content: flex-end; }

.scene-done-banner {
  margin-top: 16px; background: #f0fff4;
  border: 1px solid #b7ebc8; border-radius: 8px;
  padding: 14px; text-align: center;
}

.page-elements-hint {
  display: flex; align-items: center; gap: 4px;
  font-size: 12px; color: #67c23a;
  margin-bottom: 12px;
}
</style>
