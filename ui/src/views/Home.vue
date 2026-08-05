<template>
  <div class="home">
    <WorkspaceRequired v-if="auth.role !== 'admin' && !wsStore.currentId" />

    <template v-else>
      <!-- ══════════════════════════════════════模块一：AI 用例生成 ═══════════════════════════════════════ -->
      <div class="module-section">
        <div class="module-header header-purple">
          <div class="module-header-left">
            <div class="module-badge badge-purple"><el-icon size="18"><MagicStick /></el-icon></div>
            <div>
              <div class="module-title">AI 用例生成</div>
              <div class="module-subtitle">需求文档 → 结构化用例 · 6 种测试方法 · 增量更新 · 需求追踪矩阵</div>
            </div>
          </div>
        </div>

        <div class="module-body">
          <el-row :gutter="16">
            <el-col :span="12">
              <div class="dash-card full-height" @click="$router.push('/ai-cases')">
                <div class="dash-card-icon-wrap dci-purple"><el-icon size="28"><MagicStick /></el-icon></div>
                <div class="dash-card-body">
                  <div class="dash-card-title">文档驱动生成</div>
                  <div class="dash-card-desc">
                    上传 Word / PDF / Markdown 需求文档，AI 按功能模块并行生成覆盖等价类、边界值、判定表、场景法、错误推测、状态转换的高质量测试用例。
                  </div>
                </div>
                <div class="dash-card-footer">
                  <div class="dash-stat">
                    <span class="dash-stat-num">{{ aiCaseCount }}</span>
                    <span class="dash-stat-lbl">AI 用例集</span>
                  </div>
                  <el-button type="primary" link size="small">进入模块</el-button>
                </div>
              </div>
            </el-col>
            <el-col :span="12">
              <div class="sub-card full-height">
                <div class="sub-card-title">核心能力</div>
                <div class="feature-list">
                  <div class="feature-item"><div class="feature-dot" style="background:#9254de"></div><span>需求文档 → 多模块并行生成，6 种测试方法全覆盖</span></div>
                  <div class="feature-item"><div class="feature-dot" style="background:#409eff"></div><span>需求变更增量更新 — AI Diff 分析，用例级精准合并</span></div>
                  <div class="feature-item"><div class="feature-dot" style="background:#67c23a"></div><span>RAG 知识库 — 文档分段向量检索，超长文档不遗漏</span></div>
                  <div class="feature-item"><div class="feature-dot" style="background:#e6a23c"></div><span>需求追踪矩阵 — 用例→需求双向映射，覆盖度可视化</span></div>
                  <div class="feature-item"><div class="feature-dot" style="background:#36cfc9"></div><span>支持 Claude / DeepSeek / GPT / Ollama 一键切换</span></div>
                  <div class="feature-item"><div class="feature-dot" style="background:#f56c6c"></div><span>导出 Markdown / XMind / Excel · 截断 JSON 自动修复</span></div>
                </div>
              </div>
            </el-col>
          </el-row>
        </div>
      </div>

      <!-- ══════════════════════════════════════模块二：WebUI 自动化 ═══════════════════════════════════════ -->
      <div class="module-section">
        <div class="module-header header-blue">
          <div class="module-header-left">
            <div class="module-badge badge-blue"><el-icon size="18"><Monitor /></el-icon></div>
            <div>
              <div class="module-title">WebUI 自动化</div>
              <div class="module-subtitle">AI 场景规划 · 有头浏览器录制 · 步骤健壮化 · 多浏览器并行执行 · 截图报告</div>
            </div>
          </div>
        </div>

        <!-- 模块概览统计 -->
        <div class="stat-row-inline">
          <div class="stat-mini" @click="$router.push('/tasks')">
            <span class="stat-mini-num">{{ taskStore.taskCount }}</span>
            <span class="stat-mini-lbl">测试任务</span>
          </div>
          <div class="stat-mini-divider"></div>
          <div class="stat-mini" @click="$router.push('/cases')">
            <span class="stat-mini-num">{{ taskStore.totalCaseCount }}</span>
            <span class="stat-mini-lbl">WebUI 用例</span>
          </div>
          <div class="stat-mini-divider"></div>
          <div class="stat-mini" @click="$router.push('/execution')">
            <span class="stat-mini-num">{{ recordedCount }}</span>
            <span class="stat-mini-lbl">录制用例</span>
          </div>
          <div class="stat-mini-divider"></div>
          <div class="stat-mini" @click="$router.push('/reports')">
            <span class="stat-mini-num">{{ reportCount }}</span>
            <span class="stat-mini-lbl">测试报告</span>
          </div>
        </div>

        <div class="module-body">
          <!-- 工作流 -->
          <div class="sub-card">
            <div class="sub-card-title">工作流程</div>
            <div class="flow-steps">
              <div class="flow-step">
                <div class="flow-num fn-1">1</div>
                <div class="flow-body">
                  <div class="flow-title">新建任务</div>
                  <div class="flow-desc">填写目标 URL，抓取页面元素</div>
                </div>
              </div>
              <div class="flow-arrow"><el-icon><ArrowRight /></el-icon></div>
              <div class="flow-step">
                <div class="flow-num fn-2">2</div>
                <div class="flow-body">
                  <div class="flow-title">AI 规划场景</div>
                  <div class="flow-desc">5 个维度自动规划 · 一键启动录制</div>
                </div>
              </div>
              <div class="flow-arrow"><el-icon><ArrowRight /></el-icon></div>
              <div class="flow-step">
                <div class="flow-num fn-3">3</div>
                <div class="flow-body">
                  <div class="flow-title">录制 & 健壮化</div>
                  <div class="flow-desc">真实操作录制 · AI 自动补全断言 · Selector 多候选</div>
                </div>
              </div>
              <div class="flow-arrow"><el-icon><ArrowRight /></el-icon></div>
              <div class="flow-step">
                <div class="flow-num fn-4">4</div>
                <div class="flow-body">
                  <div class="flow-title">执行 & 报告</div>
                  <div class="flow-desc">多浏览器并行 · 截图 · PDF · 失败修正</div>
                </div>
              </div>
            </div>
          </div>

          <!-- 子模块入口 + 最近任务 -->
          <el-row :gutter="16" style="margin-top:12px">
            <el-col :span="16">
              <div class="sub-card" style="margin-bottom:12px">
                <div class="sub-card-title">核心能力</div>
                <div class="feature-list">
                  <div class="feature-item"><div class="feature-dot" style="background:#409eff"></div><span>AI 场景规划 — 5 个落地维度（核心流程/表单验证/增删改/筛选/异常反馈）自动生成录制场景</span></div>
                  <div class="feature-item"><div class="feature-dot" style="background:#67c23a"></div><span>录制健壮化 — Selector 多候选 + A/B/C/D 稳定性评级，执行失败率显著降低</span></div>
                  <div class="feature-item"><div class="feature-dot" style="background:#9254de"></div><span>可视化步骤编辑器 — 行内编辑 action/selector/value，D 级 selector 标红提示替换</span></div>
                  <div class="feature-item"><div class="feature-dot" style="background:#e6a23c"></div><span>智能断言补全 — 关键操作后自动插入 wait + assert，避免执行空档漏检</span></div>
                  <div class="feature-item"><div class="feature-dot" style="background:#36cfc9"></div><span>多浏览器并行 — Chromium / Firefox / WebKit 同步执行，矩阵报告对比</span></div>
                  <div class="feature-item"><div class="feature-dot" style="background:#f56c6c"></div><span>场景覆盖视图 — 规划场景与录制用例对照，直观看哪个维度还没覆盖</span></div>
                </div>
              </div>
              <div class="action-grid-2">
                <div class="action-item" @click="$router.push('/tasks')">
                  <div class="action-icon ai-blue"><el-icon size="18"><FolderOpened /></el-icon></div>
                  <div class="action-info">
                    <div class="action-name">任务管理</div>
                    <div class="action-desc">新建任务 · 抓取页面元素</div>
                  </div>
                  <el-icon class="action-go"><ArrowRight /></el-icon>
                </div>
                <div class="action-item" @click="$router.push('/cases')">
                  <div class="action-icon ai-green"><el-icon size="18"><Document /></el-icon></div>
                  <div class="action-info">
                    <div class="action-name">用例管理</div>
                    <div class="action-desc">来源标签 · 步骤编辑器 · 场景覆盖</div>
                  </div>
                  <el-icon class="action-go"><ArrowRight /></el-icon>
                </div>
                <div class="action-item" @click="$router.push('/execution')">
                  <div class="action-icon ai-orange"><el-icon size="18"><VideoCamera /></el-icon></div>
                  <div class="action-info">
                    <div class="action-name">录制 & 执行</div>
                    <div class="action-desc">AI 规划场景 · 录制 · 并行执行</div>
                  </div>
                  <el-icon class="action-go"><ArrowRight /></el-icon>
                </div>
                <div class="action-item" @click="$router.push('/reports')">
                  <div class="action-icon ai-purple"><el-icon size="18"><DataAnalysis /></el-icon></div>
                  <div class="action-info">
                    <div class="action-name">测试报告</div>
                    <div class="action-desc">分浏览器报告 · 截图 · PDF</div>
                  </div>
                  <el-icon class="action-go"><ArrowRight /></el-icon>
                </div>
              </div>
            </el-col>
            <el-col :span="8">
              <div class="sub-card full-height">
                <div class="sub-card-title row-between">
                  <span>最近任务</span>
                  <el-button link size="small" @click="$router.push('/tasks')">全部</el-button>
                </div>
                <div v-if="recentTasks.length === 0" class="empty-wrap">
                  <el-empty description="暂无任务" :image-size="54" />
                </div>
                <div v-else class="recent-list">
                  <div v-for="task in recentTasks" :key="task.id" class="recent-item"
                    @click="$router.push({ name: 'Cases', query: { taskId: task.id } })">
                    <div class="recent-dot"></div>
                    <div class="recent-body">
                      <div class="recent-name">{{ task.name }}</div>
                      <div class="recent-meta">
                        <el-tag size="small" effect="plain" class="recent-tag">{{ browserLabel(task.browser) }}</el-tag>
                        <span class="recent-time">{{ formatDate(task.updated_at || task.created_at) }}</span>
                      </div>
                    </div>
                    <el-button link size="small" type="primary"
                      @click.stop="$router.push({ name: 'Execution', query: { taskId: task.id } })">执行</el-button>
                  </div>
                </div>
              </div>
            </el-col>
          </el-row>
        </div>
      </div>

      <!-- ══════════════════════════════════════模块三：接口自动化 ═══════════════════════════════════════ -->
      <div class="module-section">
        <div class="module-header header-teal">
          <div class="module-header-left">
            <div class="module-badge badge-teal"><el-icon size="18"><Tickets /></el-icon></div>
            <div>
              <div class="module-title">接口自动化</div>
              <div class="module-subtitle">AI 生成 · 多环境 · 数据驱动 · 压测 · CI/CD · Mock · 定时执行</div>
            </div>
          </div>
        </div>

        <div class="module-body">
          <div class="action-grid-3">
            <div class="dash-card" @click="$router.push('/api-test')">
              <div class="dash-card-icon-wrap dci-teal"><el-icon size="24"><Tickets /></el-icon></div>
              <div class="dash-card-body">
                <div class="dash-card-title">接口测试</div>
                <div class="dash-card-desc">
                  AI 生成用例（Swagger / 代码 / URL）· Postman/HAR 导入 · 多环境切换 · 断言 · 变量提取 · CSV 数据驱动 · 压测
                </div>
              </div>
              <div class="dash-card-footer">
                <div class="dash-stat">
                  <span class="dash-stat-num">{{ apiProjectCount }}</span>
                  <span class="dash-stat-lbl">项目</span>
                </div>
                <el-button type="primary" link size="small">进入</el-button>
              </div>
            </div>

            <div class="dash-card" @click="$router.push('/test-plan')">
              <div class="dash-card-icon-wrap dci-cyan"><el-icon size="24"><Memo /></el-icon></div>
              <div class="dash-card-body">
                <div class="dash-card-title">测试计划</div>
                <div class="dash-card-desc">
                  跨项目用例编排 · 共享变量上下文 · Cron 定时执行 · CI/CD Webhook 触发 · 执行完成推送通知
                </div>
              </div>
              <div class="dash-card-footer">
                <div class="dash-stat">
                  <span class="dash-stat-num">{{ planCount }}</span>
                  <span class="dash-stat-lbl">计划</span>
                </div>
                <el-button type="primary" link size="small">进入</el-button>
              </div>
            </div>

            <div class="dash-card" @click="$router.push('/pentest')">
              <div class="dash-card-icon-wrap dci-red"><el-icon size="24"><Warning /></el-icon></div>
              <div class="dash-card-body">
                <div class="dash-card-title">渗透测试</div>
                <div class="dash-card-desc">12 个扫描模块，覆盖 OWASP API Top 10，SQL 注入 / 越权 / 敏感信息泄露，AI 修复建议</div>
              </div>
              <div class="dash-card-footer">
                <el-tag size="small" type="danger" effect="plain">安全检测</el-tag>
                <el-button type="danger" link size="small">进入</el-button>
              </div>
            </div>

            <div class="dash-card" @click="$router.push('/mock')">
              <div class="dash-card-icon-wrap dci-purple"><el-icon size="24"><Connection /></el-icon></div>
              <div class="dash-card-body">
                <div class="dash-card-title">Mock 服务</div>
                <div class="dash-card-desc">
                  配置路径 + 方法 + 参数匹配规则，返回预设响应，支持延迟模拟与模板变量
                </div>
              </div>
              <div class="dash-card-footer">
                <el-tag size="small" type="info" effect="plain">联调利器</el-tag>
                <el-button type="primary" link size="small">进入</el-button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ══════════════════════════════════════模块四：系统设置 ═══════════════════════════════════════ -->
      <div class="module-section">
        <div class="module-header header-gray">
          <div class="module-header-left">
            <div class="module-badge badge-gray"><el-icon size="18"><Setting /></el-icon></div>
            <div>
              <div class="module-title">系统设置</div>
              <div class="module-subtitle">工作空间管理 · AI Agent 技能 · 大模型配置 · 全局变量池</div>
            </div>
          </div>
        </div>

        <div class="module-body">
          <div class="action-grid-3">
            <div class="sys-entry" @click="$router.push('/workspaces')">
              <div class="sys-entry-icon"><el-icon size="20"><Folder /></el-icon></div>
              <div class="sys-entry-info">
                <div class="sys-entry-name">工作空间</div>
                <div class="sys-entry-desc">管理团队隔离环境与成员权限</div>
              </div>
              <el-icon class="action-go"><ArrowRight /></el-icon>
            </div>
            <div class="sys-entry" @click="$router.push('/skills')">
              <div class="sys-entry-icon"><el-icon size="20"><Box /></el-icon></div>
              <div class="sys-entry-info">
                <div class="sys-entry-name">技能管理</div>
                <div class="sys-entry-desc">配置与管理 AI Agent 技能</div>
              </div>
              <el-icon class="action-go"><ArrowRight /></el-icon>
            </div>
            <div class="sys-entry" @click="$router.push('/llm')">
              <div class="sys-entry-icon"><el-icon size="20"><Cpu /></el-icon></div>
              <div class="sys-entry-info">
                <div class="sys-entry-name">大模型配置</div>
                <div class="sys-entry-desc">切换模型 · 配置 API Key · Prompt</div>
              </div>
              <el-icon class="action-go"><ArrowRight /></el-icon>
            </div>
          </div>
        </div>
      </div>

    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useTaskStore } from '../stores/task'
import { useWorkspaceStore } from '../stores/workspace'
import { useAuthStore } from '../stores/auth'
import WorkspaceRequired from '../components/WorkspaceRequired.vue'
import api, { reportApi, aiCaseApi } from '../api/index'

const taskStore = useTaskStore()
const wsStore   = useWorkspaceStore()
const auth      = useAuthStore()

const reportCount   = ref(0)
const recordedCount = ref(0)
const apiProjectCount = ref(0)
const planCount       = ref(0)
const aiCaseCount     = ref(0)

const recentTasks = computed(() => taskStore.tasks.slice(0, 6))

const browserLabel = (b) =>
  ({ chromium: 'Chromium', firefox: 'Firefox', webkit: 'WebKit' }[b] || b || 'Chromium')

const formatDate = (d) => {
  if (!d) return ''
  try {
    const str = String(d)
    const date = new Date(str.includes('Z') || str.includes('+') ? str : str + 'Z')
    if (isNaN(date.getTime())) return ''
    const now = new Date()
    const isToday = date.toDateString() === now.toDateString()
    const hhmm = `${String(date.getHours()).padStart(2,'0')}:${String(date.getMinutes()).padStart(2,'0')}`
    return isToday ? hhmm : `${date.getMonth() + 1}/${date.getDate()} ${hhmm}`
  } catch { return '' }
}

async function loadData() {
  if (auth.role !== 'admin' && !wsStore.currentId) return
  await Promise.all([
    taskStore.fetchTasks(wsStore.currentId),
    taskStore.fetchTotalCaseCount(wsStore.currentId),
  ])
  // WebUI 报告数量
  try {
    const reports = await reportApi.list(wsStore.currentId)
    reportCount.value = Array.isArray(reports) ? reports.length : 0
  } catch { reportCount.value = 0 }
  // 录制用例数量
  try {
    const statsParams = wsStore.currentId ? { workspace_id: wsStore.currentId } : {}
    const statsRes = await api.get('/stats', { params: statsParams })
    recordedCount.value = statsRes?.recorded_count ?? 0
  } catch { recordedCount.value = 0 }
  // 接口项目数量
  try {
    const projects = await api.get('/api-test/projects', { params: wsStore.currentId ? { workspace_id: wsStore.currentId } : {} })
    apiProjectCount.value = Array.isArray(projects) ? projects.length : 0
  } catch { apiProjectCount.value = 0 }
  // 测试计划数量
  try {
    const plans = await api.get('/test-plans', { params: wsStore.currentId ? { workspace_id: wsStore.currentId } : {} })
    planCount.value = Array.isArray(plans) ? plans.length : 0
  } catch { planCount.value = 0 }
  // AI 用例集数量
  try {
    const aiCases = await aiCaseApi.list(wsStore.currentId)
    aiCaseCount.value = Array.isArray(aiCases) ? aiCases.length : 0
  } catch { aiCaseCount.value = 0 }
}

watch(() => wsStore.currentId, loadData)
watch(() => wsStore.initialized, (ready) => { if (ready) loadData() })
onMounted(() => { if (wsStore.initialized) loadData() })
</script>

<style scoped>
.home { padding: 0; }

/* ── 模块分区 ── */
.module-section {
  background: #fff;
  border-radius: 12px;
  border: 1px solid #eef0f4;
  margin-bottom: 18px;
  overflow: hidden;
}

.module-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-bottom: 1px solid rgba(0,0,0,0.05);
}

.header-blue   { background: linear-gradient(90deg, #e8f4ff 0%, #f0f9ff 100%); }
.header-teal   { background: linear-gradient(90deg, #e6fff8 0%, #f0fffd 100%); }
.header-purple { background: linear-gradient(90deg, #f5f0ff 0%, #faf0ff 100%); }
.header-gray   { background: linear-gradient(90deg, #f5f7fa 0%, #f8fafc 100%); }

.module-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.module-badge {
  width: 34px; height: 34px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}

.badge-blue   { background: linear-gradient(135deg, #409eff, #36cfc9); }
.badge-teal   { background: linear-gradient(135deg, #0ec3a8, #36cfc9); }
.badge-purple { background: linear-gradient(135deg, #9254de, #b37feb); }
.badge-gray   { background: linear-gradient(135deg, #8c96a3, #b0bcc8); }

.module-title    { font-size: 15px; font-weight: 700; color: #1a2332; }
.module-subtitle { font-size: 12px; color: #909399; margin-top: 2px; }

.module-body { padding: 16px 20px; }

/* ── 模块内统计行 ── */
.stat-row-inline {
  display: flex;
  align-items: center;
  padding: 10px 20px;
  background: #fafbfc;
  border-bottom: 1px solid #eef0f4;
  gap: 0;
}

.stat-mini {
  flex: 1;
  text-align: center;
  cursor: pointer;
  padding: 4px 0;
  border-radius: 6px;
  transition: background 0.15s;
}
.stat-mini:hover { background: #eef4ff; }

.stat-mini-num { display: block; font-size: 20px; font-weight: 700; color: #1a2332; }
.stat-mini-lbl { display: block; font-size: 11px; color: #909399; margin-top: 2px; }

.stat-mini-divider {
  width: 1px; height: 28px;
  background: #e4e7ed;
  flex-shrink: 0;
}

/* ── 子卡片 ── */
.sub-card {
  background: #f8fafc;
  border-radius: 8px;
  padding: 14px 16px;
  border: 1px solid #eef0f4;
}
.sub-card.full-height { height: 100%; box-sizing: border-box; }
.sub-card-title { font-size: 13px; font-weight: 600; color: #303133; margin-bottom: 12px; }
.row-between { display: flex; justify-content: space-between; align-items: center; }
.empty-wrap { text-align: center; padding: 24px 0; }

/* ── 工作流步骤 ── */
.flow-steps { display: flex; align-items: center; gap: 6px; }
.flow-step  { display: flex; align-items: flex-start; gap: 8px; flex: 1; min-width: 0; }
.flow-num   {
  width: 22px; height: 22px; border-radius: 50%;
  color: #fff; font-size: 11px; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; margin-top: 1px;
}
.fn-1 { background: #409eff; } .fn-2 { background: #67c23a; }
.fn-3 { background: #e6a23c; } .fn-4 { background: #9254de; }
.flow-title { font-size: 12px; font-weight: 600; color: #303133; }
.flow-desc  { font-size: 11px; color: #909399; margin-top: 2px; line-height: 1.4; }
.flow-arrow { color: #c0c4cc; font-size: 16px; flex-shrink: 0; }

/* ── 操作项 ── */
.action-item {
  display: flex; align-items: center; gap: 10px;
  padding: 11px 13px; border-radius: 8px;
  border: 1px solid #eef0f4; background: #f8fafc;
  cursor: pointer; transition: background 0.15s, border-color 0.15s;
}
.action-item:hover { background: #f0f6ff; border-color: #c6d8f0; }
.action-icon {
  width: 34px; height: 34px; border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; color: #fff;
}
.ai-blue   { background: linear-gradient(135deg, #409eff, #36cfc9); }
.ai-green  { background: linear-gradient(135deg, #67c23a, #95d475); }
.ai-orange { background: linear-gradient(135deg, #e6a23c, #f5af2d); }
.ai-purple { background: linear-gradient(135deg, #9254de, #b37feb); }
.action-info  { flex: 1; min-width: 0; }
.action-name  { font-size: 13px; font-weight: 600; color: #303133; }
.action-desc  { font-size: 11px; color: #909399; margin-top: 2px; }
.action-go    { color: #c0c4cc; font-size: 13px; flex-shrink: 0; }

.action-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.action-grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }

/* ── 大卡片（接口/AI） ── */
.dash-card {
  background: #f8fafc; border-radius: 10px;
  border: 1px solid #eef0f4; padding: 20px;
  cursor: pointer; transition: box-shadow 0.18s, border-color 0.18s;
  display: flex; flex-direction: column; gap: 10px;
}
.dash-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.08); border-color: #d0dff5; }
.dash-card.full-height { height: 100%; box-sizing: border-box; }
.dash-card-icon-wrap {
  width: 44px; height: 44px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center; color: #fff;
}
.dci-teal   { background: linear-gradient(135deg, #0ec3a8, #36cfc9); }
.dci-cyan   { background: linear-gradient(135deg, #13c2c2, #36cfc9); }
.dci-red    { background: linear-gradient(135deg, #f5222d, #ff7875); }
.dci-purple { background: linear-gradient(135deg, #9254de, #b37feb); }
.dash-card-body  { flex: 1; }
.dash-card-title { font-size: 15px; font-weight: 700; color: #1a2332; }
.dash-card-desc  { font-size: 12px; color: #606266; line-height: 1.7; margin-top: 4px; }
.dash-card-footer { display: flex; align-items: center; justify-content: space-between; }
.dash-stat { display: flex; align-items: baseline; gap: 4px; }
.dash-stat-num { font-size: 18px; font-weight: 700; color: #1a2332; }
.dash-stat-lbl { font-size: 11px; color: #909399; }

/* ── 最近任务 ── */
.recent-list { display: flex; flex-direction: column; gap: 4px; }
.recent-item {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 8px; border-radius: 6px;
  cursor: pointer; transition: background 0.15s;
}
.recent-item:hover { background: #eef4ff; }
.recent-dot  { width: 6px; height: 6px; border-radius: 50%; background: #409eff; flex-shrink: 0; }
.recent-body { flex: 1; min-width: 0; }
.recent-name { font-size: 13px; color: #303133; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.recent-meta { display: flex; align-items: center; gap: 6px; margin-top: 2px; }
.recent-tag  { font-size: 10px; }
.recent-time { font-size: 11px; color: #c0c4cc; }

/* ── AI 特性列表 ── */
.feature-list { display: flex; flex-direction: column; gap: 10px; }
.feature-item { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #606266; }
.feature-dot  { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }

/* ── 系统设置入口 ── */
.sys-entry {
  display: flex; align-items: center; gap: 12px;
  padding: 14px 16px; border-radius: 10px;
  border: 1px solid #eef0f4; background: #f8fafc;
  cursor: pointer; transition: background 0.15s, border-color 0.15s;
}
.sys-entry:hover { background: #f0f4fa; border-color: #c0ccda; }
.sys-entry-icon {
  width: 40px; height: 40px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #8c96a3, #b0bcc8); color: #fff; flex-shrink: 0;
}
.sys-entry-info { flex: 1; min-width: 0; }
.sys-entry-name { font-size: 14px; font-weight: 600; color: #303133; }
.sys-entry-desc { font-size: 11px; color: #909399; margin-top: 2px; }
</style>