<template>
  <div class="test-plan-page">
    <WorkspaceRequired v-if="auth.role !== 'admin' && !wsStore.currentId" />
    <template v-else>
    <!-- 左侧：计划列表 -->
    <el-card class="plan-list-card">
      <template #header>
        <div class="card-header">
          <span>测试计划</span>
          <el-button type="primary" size="small" :icon="Plus" @click="openCreateDialog">新建计划</el-button>
        </div>
      </template>

      <el-input v-model="searchText" placeholder="搜索计划名称" clearable class="mb-12" />

      <el-scrollbar height="calc(100vh - 220px)">
        <div
          v-for="plan in filteredPlans"
          :key="plan.id"
          class="plan-item"
          :class="{ active: activePlanId === plan.id }"
          @click="selectPlan(plan.id)"
        >
          <div class="plan-item-header">
            <span class="plan-name">{{ plan.name }}</span>
            <el-tag :type="statusTagType(plan.status)" size="small">{{ statusLabel(plan.status) }}</el-tag>
          </div>
          <div class="plan-item-meta">
            <el-icon><List /></el-icon>
            <span>{{ plan.step_count ?? 0 }} 步骤</span>
            <span class="dot">·</span>
            <span>{{ formatDate(plan.created_at) }}</span>
          </div>
        </div>
        <el-empty v-if="!filteredPlans.length" description="暂无测试计划" :image-size="60" />
      </el-scrollbar>
    </el-card>

    <!-- 右侧：计划详情 + 执行 + 报告 -->
    <div class="plan-detail" v-if="activePlan">
      <el-tabs v-model="activeTab" class="detail-tabs">
        <!-- Tab1：步骤编辑 -->
        <el-tab-pane label="步骤编辑" name="steps">
          <div class="tab-toolbar">
            <el-button
              type="primary" :icon="VideoPlay"
              @click="runPlan(false)"
              :loading="running"
              :disabled="!activePlan.steps.length"
            >{{ running ? '执行中…' : '执行计划' }}</el-button>
            <el-button
              v-if="activePlan.status === 'running' && !running"
              type="warning" :icon="RefreshRight"
              @click="runPlan(true)"
            >强制重跑</el-button>
            <el-button :icon="Edit" @click="openEditDialog">编辑</el-button>
            <el-button type="danger" :icon="Delete" @click="deletePlan">删除</el-button>
            <span class="toolbar-sep"></span>
            <el-button :icon="Plus" @click="openAddStepDialog">添加步骤</el-button>
            <el-button :icon="Refresh" @click="loadPlanDetail(activePlanId)">刷新</el-button>
          </div>

          <!-- ── 执行监控面板（执行中 / 刚完成时显示） ── -->
          <div v-if="showExecPanel" class="exec-panel">
            <!-- 汇总进度条 -->
            <div class="exec-summary">
              <el-progress
                :percentage="execPercent"
                :stroke-width="12"
                :status="running ? '' : executionProgress.failed > 0 ? 'exception' : 'success'"
                striped
                :striped-flow="running"
                :duration="4"
              />
              <div class="exec-meta">
                <span class="exec-meta-steps">
                  {{ execDoneCount }}&nbsp;/&nbsp;{{ execTotalCount }}&nbsp;步
                </span>
                <el-tag type="success" size="small" effect="dark">✓ {{ executionProgress.passed }}</el-tag>
                <el-tag type="danger"  size="small" effect="dark">✗ {{ executionProgress.failed }}</el-tag>
                <span v-if="running" class="exec-current-name">
                  <el-icon class="spin" style="color:#409eff"><Loading /></el-icon>
                  {{ executionProgress.currentName }}
                </span>
                <el-button
                  v-if="running" link type="danger" size="small"
                  style="margin-left:auto" @click="forceResetRunning"
                >强制停止</el-button>
                <el-button
                  v-else link size="small"
                  style="margin-left:auto" @click="stepLogs = []"
                >收起</el-button>
              </div>
            </div>

            <!-- 步骤实时日志 -->
            <div class="step-log-list">
              <div
                v-for="log in stepLogs" :key="log.stepNum"
                class="step-log-item"
                :class="'sli-' + log.status"
              >
                <!-- 序号 -->
                <span class="sli-num">{{ log.stepNum }}</span>

                <!-- 状态图标 -->
                <span class="sli-icon">
                  <el-icon v-if="log.status === 'passed'"  color="#67c23a"><CircleCheck /></el-icon>
                  <el-icon v-else-if="log.status === 'failed'" color="#f56c6c"><CircleClose /></el-icon>
                  <el-icon v-else-if="log.status === 'running'" class="spin" color="#409eff"><Loading /></el-icon>
                  <el-icon v-else-if="log.status === 'skipped'" color="#e6a23c"><WarningFilled /></el-icon>
                  <el-icon v-else color="#c0c4cc"><Clock /></el-icon>
                </span>

                <!-- 用例名 -->
                <span class="sli-name" :title="log.case_name">{{ log.case_name }}</span>

                <!-- 方法 + 状态码 -->
                <span v-if="log.method" class="sli-method">
                  <el-tag :type="methodTagType(log.method)" size="small" effect="plain">{{ log.method }}</el-tag>
                </span>
                <span v-if="log.status_code" class="sli-code"
                  :style="{color: log.status_code < 400 ? '#67c23a' : '#f56c6c'}">
                  {{ log.status_code }}
                </span>

                <!-- 耗时 -->
                <span v-if="log.duration_ms" class="sli-duration">{{ log.duration_ms }}ms</span>

                <!-- 状态标签 -->
                <span class="sli-status-tag">
                  <el-tag
                    v-if="log.status !== 'pending'"
                    :type="{passed:'success',failed:'danger',running:'',skipped:'warning'}[log.status] || 'info'"
                    size="small"
                  >{{ {passed:'通过',failed:'失败',running:'执行中',skipped:'跳过',pending:'等待'}[log.status] }}</el-tag>
                </span>

                <!-- 错误信息 -->
                <span v-if="log.error && log.status === 'failed'" class="sli-error" :title="log.error">
                  {{ log.error }}
                </span>
              </div>
            </div>
          </div>

          <!-- ── 步骤列表表格（未执行时显示） ── -->
          <el-table
            v-else
            :data="activePlan.steps"
            row-key="id"
            border
            size="small"
            class="steps-table"
          >
            <el-table-column label="#" width="50" align="center">
              <template #default="{ $index }">{{ $index + 1 }}</template>
            </el-table-column>
            <el-table-column label="用例名称" prop="case_name" min-width="180" />
            <el-table-column label="模块" prop="module" width="120" show-overflow-tooltip />
            <el-table-column label="所属项目" prop="project_name" width="140" show-overflow-tooltip />
            <el-table-column label="启用" width="70" align="center">
              <template #default="{ row }">
                <el-switch v-model="row.enabled" size="small" @change="toggleStep(row)" />
              </template>
            </el-table-column>
            <el-table-column v-if="lastReport" label="上次结果" width="100" align="center">
              <template #default="{ $index }">
                <el-tag
                  v-if="lastReport.details[$index]"
                  :type="lastReport.details[$index].status === 'passed' ? 'success' : 'danger'"
                  size="small"
                >{{ lastReport.details[$index].status === 'passed' ? '通过' : '失败' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="80" align="center">
              <template #default="{ row }">
                <el-button link type="danger" size="small" @click="deleteStep(row)">移除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- Tab3：CI/CD 集成 -->
        <el-tab-pane label="CI/CD 集成" name="cicd">
          <div style="padding: 20px 0; max-width: 680px">

            <!-- 定时执行区块 -->
            <div style="margin-bottom: 28px">
              <div style="font-size: 14px; font-weight: 600; color: #303133; margin-bottom: 12px">
                ⏰ 定时执行
              </div>
              <el-form label-width="90px" size="small">
                <el-form-item label="启用定时">
                  <el-switch v-model="cronEnabled" @change="saveCronConfig" />
                  <span style="font-size:12px;color:#909399;margin-left:10px">
                    {{ cronEnabled ? '已启用，按 Cron 表达式自动执行' : '未启用' }}
                  </span>
                </el-form-item>
                <el-form-item v-if="cronEnabled" label="Cron 表达式">
                  <el-input v-model="cronExpr" placeholder="0 9 * * 1-5（工作日 09:00）"
                    style="width:260px" @blur="saveCronConfig">
                    <template #append>
                      <el-tooltip placement="top" :content="`下次执行: ${nextCronTime}`">
                        <el-icon style="cursor:pointer"><InfoFilled /></el-icon>
                      </el-tooltip>
                    </template>
                  </el-input>
                  <div style="font-size:12px;color:#909399;margin-top:4px">
                    标准 5 字段 Cron：分 时 日 月 周。例：<code>0 9 * * *</code>（每天09:00）、<code>*/30 * * * *</code>（每30分钟）
                  </div>
                </el-form-item>
              </el-form>
            </div>

            <el-divider />

            <!-- Webhook Token 区块 -->
            <div style="margin-bottom: 28px">
              <div style="font-size: 14px; font-weight: 600; color: #303133; margin-bottom: 12px">
                🔗 Webhook 触发
              </div>
              <div style="font-size: 13px; color: #606266; margin-bottom: 12px; line-height: 1.6">
                生成 Token 后，外部系统（Jenkins / GitHub Actions 等）可通过 HTTP POST 请求触发本计划执行，无需 JWT 登录。
              </div>

              <!-- 无 Token 状态 -->
              <div v-if="!hasWebhookToken">
                <el-button type="primary" :loading="webhookLoading" @click="generateWebhookToken">
                  生成 Webhook Token
                </el-button>
              </div>

              <!-- 有 Token 状态 -->
              <div v-else>
                <el-form label-width="90px" size="small">
                  <el-form-item label="Token">
                    <el-input :value="activePlan.webhook_token" readonly style="font-family:monospace">
                      <template #append>
                        <el-button @click="copyText(activePlan.webhook_token)">复制</el-button>
                      </template>
                    </el-input>
                  </el-form-item>
                  <el-form-item label="触发 URL">
                    <el-input :value="webhookTriggerUrl" readonly style="font-family:monospace;font-size:12px">
                      <template #append>
                        <el-button @click="copyText(webhookTriggerUrl)">复制</el-button>
                      </template>
                    </el-input>
                  </el-form-item>
                </el-form>

                <!-- curl 示例 -->
                <div style="margin-top:12px">
                  <div style="font-size:12px;color:#909399;margin-bottom:6px">curl 示例：</div>
                  <div style="background:#1e1e1e;border-radius:6px;padding:12px 14px;font-family:monospace;font-size:12px;color:#d4d4d4;line-height:1.8;overflow-x:auto;white-space:pre">{{ curlExample }}</div>
                </div>

                <div style="margin-top:14px;display:flex;gap:10px">
                  <el-button size="small" @click="generateWebhookToken" :loading="webhookLoading">重新生成</el-button>
                  <el-button size="small" type="danger" plain @click="revokeWebhookToken" :loading="webhookLoading">撤销 Token</el-button>
                </div>
              </div>
            </div>

            <!-- 使用说明 -->
            <el-divider />
            <div style="font-size: 14px; font-weight: 600; color: #303133; margin-bottom: 12px">
              📖 使用说明
            </div>
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="Jenkins">
                在构建后步骤中添加 HTTP Request 插件，POST 请求触发 URL
              </el-descriptions-item>
              <el-descriptions-item label="GitHub Actions">
                使用 <code style="background:#f0f0f0;padding:1px 5px;border-radius:3px">curl -X POST "$TRIGGER_URL"</code> 步骤触发
              </el-descriptions-item>
              <el-descriptions-item label="回调通知">
                触发时附加 <code style="background:#f0f0f0;padding:1px 5px;border-radius:3px">?callback_url=https://your-ci/hook</code> 参数，执行完成后回调
              </el-descriptions-item>
              <el-descriptions-item label="安全">
                Token 可随时撤销，撤销后旧请求立即返回 401
              </el-descriptions-item>
            </el-descriptions>
          </div>
        </el-tab-pane>

        <!-- Tab2：执行报告 -->
        <el-tab-pane name="reports">
          <template #label>
            <span>执行报告</span>
            <el-badge v-if="reports.length" :value="reports.length" type="info" style="margin-left:4px" />
          </template>

          <!-- 批量操作栏 -->
          <transition name="slide-down">
            <div v-if="selectedReports.length" class="reports-batch-bar">
              <el-icon color="#409eff"><InfoFilled /></el-icon>
              <span class="batch-hint">已选 <strong>{{ selectedReports.length }}</strong> 条报告</span>
              <el-button type="danger" size="small" :icon="Delete" @click="batchDeleteReports">批量删除</el-button>
            </div>
          </transition>

          <!-- 报告卡片列表 -->
          <div class="report-card-list" v-if="reports.length">
            <div
              v-for="(row, idx) in reports"
              :key="row.id"
              class="report-card"
              :class="rcClass(row)"
            >
              <!-- 复选框 -->
              <div class="rc-check" @click.stop>
                <el-checkbox
                  :model-value="isSelectedReport(row)"
                  @change="toggleSelectReport(row)"
                />
              </div>

              <!-- 序号徽章 -->
              <div class="rc-rank">
                <span class="rc-rank-badge">#{{ reports.length - idx }}</span>
              </div>

              <!-- 主信息 -->
              <div class="rc-body">
                <div class="rc-time">
                  <el-icon size="12" style="vertical-align:-1px;margin-right:3px"><Clock /></el-icon>
                  {{ formatDate(row.created_at) }}
                </div>
                <div class="rc-stats">
                  <span class="rc-stat rc-stat-total">
                    <el-icon size="11"><List /></el-icon> {{ row.total }} 步
                  </span>
                  <span class="rc-sep">·</span>
                  <span class="rc-stat rc-stat-pass">✓ {{ row.passed }} 通过</span>
                  <span v-if="row.failed" class="rc-sep">·</span>
                  <span v-if="row.failed" class="rc-stat rc-stat-fail">✗ {{ row.failed }} 失败</span>
                </div>
              </div>

              <!-- 通过率环形 -->
              <div class="rc-progress">
                <el-progress
                  type="circle"
                  :percentage="row.pass_rate"
                  :width="54"
                  :stroke-width="5"
                  :color="row.pass_rate >= 100 ? '#67c23a' : row.pass_rate >= 60 ? '#e6a23c' : '#f56c6c'"
                >
                  <template #default>
                    <span class="rc-pct">{{ row.pass_rate }}%</span>
                  </template>
                </el-progress>
              </div>

              <!-- 操作区 -->
              <div class="rc-actions">
                <el-button type="primary" size="small" @click="viewReport(row.id)">
                  <el-icon><Document /></el-icon> 详情
                </el-button>
                <el-button type="warning" plain size="small" @click="exportReportPdf(row.id, row.plan_name)">PDF</el-button>
                <el-button type="danger" plain size="small" @click="deleteReport(row.id)">删除</el-button>
              </div>
            </div>
          </div>
          <el-empty v-else description="暂无执行报告" :image-size="64" style="padding: 30px 0" />
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 右侧空态 -->
    <div class="plan-empty" v-else>
      <el-empty description="请在左侧选择或新建一个测试计划" />
    </div>

    <!-- ── 新建/编辑计划 Dialog ── -->
    <el-dialog v-model="planDialogVisible" :title="planDialogMode === 'create' ? '新建测试计划' : '编辑测试计划'" width="480px" :close-on-click-modal="false">
      <div style="padding: 0 10px">
        <div style="margin-bottom: 16px">
          <div style="margin-bottom: 6px; font-size: 13px; color: #606266">
            计划名称 <span style="color:#f56c6c">*</span>
          </div>
          <el-input v-model="planForm.name" placeholder="请输入计划名称" @keyup.enter="submitPlanForm" />
        </div>
        <div>
          <div style="margin-bottom: 6px; font-size: 13px; color: #606266">描述</div>
          <el-input v-model="planForm.description" type="textarea" :rows="3" placeholder="可选" />
        </div>
        <div style="margin-top: 16px">
          <div style="margin-bottom: 6px; font-size: 13px; color: #606266">
            代理地址
            <span style="color:#909399;font-size:12px;margin-left:6px">优先级高于项目代理，留空则用各步骤所属项目的代理</span>
          </div>
          <el-input v-model="planForm.proxy_url"
            placeholder="留空直连，例：http://proxy:8080 或 socks5://user:pass@host:1080" />
        </div>
        <div style="margin-top: 16px">
          <div style="margin-bottom: 6px; font-size: 13px; color: #606266">
            Hosts 映射
            <span style="color:#909399;font-size:12px;margin-left:6px">覆盖项目级同名条目，留空则用各步骤所属项目的配置</span>
          </div>
          <el-input v-model="planForm.hosts_map" type="textarea" :rows="3"
            placeholder="格式同 /etc/hosts，每行一条：&#10;47.94.236.243 japi.hqwx.com" />
        </div>
      </div>
      <template #footer>
        <el-button @click="planDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitPlanForm" :loading="saving">确定</el-button>
      </template>
    </el-dialog>

    <!-- ── 添加步骤 Dialog ── -->
    <el-dialog v-model="stepDialogVisible" title="添加步骤" width="720px" destroy-on-close>
      <div class="step-dialog-toolbar">
        <el-select v-model="stepFilterProject" placeholder="按项目筛选" clearable style="width:200px" @change="loadCandidateCases">
          <el-option v-for="p in allProjects" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
        <el-input v-model="stepSearchText" placeholder="搜索用例名称" clearable style="width:220px" />
      </div>
      <el-table
        :data="filteredCandidateCases"
        border
        size="small"
        max-height="380"
        @selection-change="selectedCases = $event"
      >
        <el-table-column type="selection" width="45" />
        <el-table-column label="用例名称" prop="name" min-width="180" show-overflow-tooltip />
        <el-table-column label="模块" prop="module" width="120" show-overflow-tooltip />
        <el-table-column label="方法" prop="method" width="70" align="center">
          <template #default="{ row }">
            <el-tag :type="methodTagType(row.method)" size="small">{{ row.method }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="所属项目" prop="project_name" width="130" show-overflow-tooltip />
      </el-table>
      <template #footer>
        <el-button @click="stepDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitAddSteps" :loading="saving">
          添加 {{ selectedCases.length }} 条
        </el-button>
      </template>
    </el-dialog>

    <!-- ── 报告详情 Drawer ── -->
    <el-drawer v-model="reportDrawerVisible" size="70%" direction="rtl" destroy-on-close>
      <template #header="{ titleId, titleClass }">
        <div style="display:flex;align-items:center;justify-content:space-between;width:100%;padding-right:8px">
          <span :id="titleId" :class="titleClass">执行报告详情</span>
          <div style="display:flex;gap:8px;align-items:center">
            <el-button
              v-if="reportDetail"
              type="warning"
              size="small"
              @click="exportReportPdf(reportDetail.id, reportDetail.plan_name)"
            >
              <el-icon><Document /></el-icon> 导出 PDF
            </el-button>
            <el-button
              v-if="reportDetail"
              type="primary"
              size="small"
              :loading="aiAnalyzing"
              @click="analyzeReport"
            >
              <template #icon><Cpu /></template>
              {{ aiAnalyzing ? '分析中…' : aiAnalysis ? '重新分析' : 'AI 分析' }}
            </el-button>
          </div>
        </div>
      </template>

      <div v-if="reportDetail" class="report-detail">

        <!-- ── 汇总卡片 ── -->
        <div class="report-summary-card mb-16">
          <div class="rsc-metric">
            <div class="rsc-val rsc-val-rate"
              :class="reportDetail.pass_rate>=100?'clr-success':reportDetail.pass_rate>=60?'clr-warning':'clr-danger'">
              {{ reportDetail.pass_rate }}%
            </div>
            <div class="rsc-label">通过率</div>
          </div>
          <div class="rsc-divider"></div>
          <div class="rsc-metric">
            <div class="rsc-val">{{ reportDetail.total }}</div>
            <div class="rsc-label">总步骤</div>
          </div>
          <div class="rsc-divider"></div>
          <div class="rsc-metric">
            <div class="rsc-val clr-success">{{ reportDetail.passed }}</div>
            <div class="rsc-label">通过</div>
          </div>
          <div class="rsc-divider"></div>
          <div class="rsc-metric">
            <div class="rsc-val" :class="reportDetail.failed ? 'clr-danger' : 'clr-muted'">{{ reportDetail.failed }}</div>
            <div class="rsc-label">失败</div>
          </div>
          <div class="rsc-divider"></div>
          <div class="rsc-meta">
            <div class="rsc-plan-name">{{ reportDetail.plan_name }}</div>
            <div class="rsc-time">{{ formatDate(reportDetail.created_at) }}</div>
          </div>
        </div>

        <!-- ── AI 分析面板 ── -->
        <transition name="aa-fade">
          <div v-if="aiAnalyzing && !aiAnalysis" class="ai-analysis-panel mb-16">
            <div class="ai-analysis-header">
              <div class="ai-hdr-left">
                <span class="ai-hdr-icon">✦</span>
                <span class="ai-hdr-title">AI 正在分析…</span>
              </div>
            </div>
            <div class="ai-analysis-body">
              <el-skeleton :rows="6" animated />
            </div>
          </div>
        </transition>

        <transition name="aa-fade">
          <div v-if="aiAnalysis" class="ai-analysis-panel mb-16">
            <div class="ai-analysis-header">
              <div class="ai-hdr-left">
                <span class="ai-hdr-icon">✦</span>
                <span class="ai-hdr-title">AI 分析报告</span>
              </div>
              <el-button size="small" text style="color:#fff;opacity:.85" @click="copyAnalysis">
                <el-icon><CopyDocument /></el-icon> 复制
              </el-button>
            </div>
            <div class="ai-analysis-body">
              <template v-for="(block, i) in analysisBlocks" :key="i">
                <div v-if="block.type==='atx'" class="aa-atx" :class="`aa-atx-${block.level}`" v-html="block.text"></div>
                <div v-else-if="block.type==='heading'" class="aa-heading">
                  <span class="aa-num">{{ block.num }}</span>
                  <span class="aa-title" v-html="block.text"></span>
                </div>
                <div v-else-if="block.type==='bullet'" class="aa-bullet">
                  <span class="aa-dot"></span>
                  <span class="aa-bullet-text" v-html="block.text"></span>
                </div>
                <div v-else-if="block.type==='spacer'" class="aa-spacer"></div>
                <div v-else class="aa-text" v-html="block.text"></div>
              </template>
            </div>
          </div>
        </transition>

        <!-- ── 共享变量快照 ── -->
        <el-collapse class="mb-16">
          <el-collapse-item :title="`共享变量快照（${Object.keys(reportDetail.var_snapshot || {}).length} 个）`" name="vars">
            <el-table :data="varSnapshotRows(reportDetail.var_snapshot)" size="small" border>
              <el-table-column label="变量名" prop="name" width="180" />
              <el-table-column label="值" prop="value" show-overflow-tooltip />
            </el-table>
          </el-collapse-item>
        </el-collapse>

        <!-- ── 步骤明细 ── -->
        <el-timeline>
          <el-timeline-item
            v-for="(step, idx) in reportDetail.details"
            :key="idx"
            :type="step.status === 'passed' ? 'success' : step.status === 'skipped' ? 'info' : 'danger'"
            :timestamp="`步骤 ${step.step}  ·  ${step.duration_ms}ms`"
            placement="top"
          >
            <el-card shadow="never" class="step-result-card">
              <div class="step-result-header">
                <el-tag :type="step.status === 'passed' ? 'success' : step.status === 'skipped' ? 'info' : 'danger'" size="small">
                  {{ step.status === 'passed' ? '通过' : step.status === 'skipped' ? '跳过' : '失败' }}
                </el-tag>
                <strong class="ml-8">{{ step.case_name }}</strong>
                <el-text type="info" class="ml-8" size="small">{{ step.project_name }}</el-text>
                <span class="step-method-url">
                  <el-tag :type="methodTagType(step.method)" size="small">{{ step.method }}</el-tag>
                  <el-text class="ml-4" size="small" style="word-break:break-all">{{ step.url }}</el-text>
                </span>
              </div>
              <div v-if="step.error" class="step-error">
                <el-text type="danger">{{ step.error }}</el-text>
              </div>
              <el-table v-if="step.assertions && step.assertions.length" :data="step.assertions" size="small" class="assertions-table">
                <el-table-column label="断言类型" prop="type" width="120" />
                <el-table-column label="期望" width="140">
                  <template #default="{ row }">{{ row.expected ?? row.max_ms }}</template>
                </el-table-column>
                <el-table-column label="实际" width="140">
                  <template #default="{ row }">{{ row.actual ?? row.actual_ms }}</template>
                </el-table-column>
                <el-table-column label="结果" width="70" align="center">
                  <template #default="{ row }">
                    <el-icon :color="row.passed ? '#67c23a' : '#f56c6c'">
                      <CircleCheck v-if="row.passed" /><CircleClose v-else />
                    </el-icon>
                  </template>
                </el-table-column>
              </el-table>
              <div v-if="Object.keys(step.extracted_vars || {}).length" class="step-vars">
                <el-tag v-for="(val, key) in step.extracted_vars" :key="key" type="info" size="small" class="mr-4">
                  {{ key }} = {{ val }}
                </el-tag>
              </div>
              <el-collapse v-if="step.response_preview">
                <el-collapse-item title="响应预览" name="preview">
                  <pre class="response-preview">{{ step.response_preview }}</pre>
                </el-collapse-item>
              </el-collapse>
            </el-card>
          </el-timeline-item>
        </el-timeline>
      </div>
      <el-skeleton v-else :rows="10" animated />
    </el-drawer>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import {
  Plus, Edit, Delete, VideoPlay, Refresh, List, Document, InfoFilled,
  CircleCheck, CircleClose, RefreshRight, Clock, WarningFilled, Loading, Cpu, CopyDocument,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api, { downloadPdf } from '../api'
import { useWorkspaceStore } from '../stores/workspace'
import { useAuthStore } from '../stores/auth'
import WorkspaceRequired from '../components/WorkspaceRequired.vue'
import { useWebSocket } from '../composables/useWebSocket'

const wsStore = useWorkspaceStore()
const auth = useAuthStore()


// ── 状态 ────────────────────────────────────────────────────────────────────
const plans = ref([])
const activePlanId = ref(null)
const activePlan = ref(null)
const activeTab = ref('steps')
const searchText = ref('')
const running = ref(false)
const saving = ref(false)
const reports = ref([])
const lastReport = ref(null)

// ── Webhook / CI/CD ──────────────────────────────────────────────────────────
const webhookLoading = ref(false)
const cronEnabled = ref(false)
const cronExpr = ref('')

// 简单估算下次执行时间（只用于提示，不做严格解析）
const nextCronTime = computed(() => {
  if (!cronExpr.value || !cronEnabled.value) return '—'
  return '请重启后端后在日志中确认'
})

// 切换计划时同步 Cron 配置
watch(activePlan, (plan) => {
  if (plan) {
    cronEnabled.value = plan.cron_enabled || false
    cronExpr.value = plan.cron_expr || ''
  }
}, { immediate: true })

const saveCronConfig = async () => {
  if (!activePlanId.value) return
  try {
    await api.put(`/test-plans/${activePlanId.value}`, {
      cron_enabled: cronEnabled.value,
      cron_expr: cronExpr.value || null,
    })
    activePlan.value.cron_enabled = cronEnabled.value
    activePlan.value.cron_expr = cronExpr.value
    ElMessage.success('定时配置已保存')
  } catch (e) {
    ElMessage.error('保存失败：' + (e?.response?.data?.detail || e?.message))
  }
}

const hasWebhookToken = computed(() => !!(activePlan.value && activePlan.value.webhook_token))

const webhookTriggerUrl = computed(() => {
  if (!activePlan.value?.webhook_token) return ''
  const base = window.location.origin
  return `${base}/api/v1/test-plans/${activePlanId.value}/trigger?token=${activePlan.value.webhook_token}`
})

const curlExample = computed(() => {
  if (!webhookTriggerUrl.value) return ''
  return `curl -X POST "${webhookTriggerUrl.value}"

# 带回调通知（可选）
curl -X POST "${webhookTriggerUrl.value}&callback_url=https://your-ci.example.com/hook"`
})

const copyText = (text) => {
  navigator.clipboard.writeText(text).then(() => {
    ElMessage.success('已复制到剪贴板')
  }).catch(() => {
    ElMessage.warning('复制失败，请手动复制')
  })
}

const generateWebhookToken = async () => {
  webhookLoading.value = true
  try {
    const res = await api.put(`/test-plans/${activePlanId.value}/webhook-token`, {})
    activePlan.value.webhook_token = res.webhook_token
    ElMessage.success('Webhook Token 已生成')
  } catch (e) {
    const detail = e?.response?.data?.detail
    const msg = Array.isArray(detail) ? detail.map(d => d.msg).join('; ') : (detail || e?.message)
    ElMessage.error('生成失败：' + msg)
  } finally {
    webhookLoading.value = false
  }
}

const revokeWebhookToken = async () => {
  await ElMessageBox.confirm('撤销后，CI/CD 触发将返回 401，确定撤销？', '确认撤销', { type: 'warning' })
  webhookLoading.value = true
  try {
    await api.delete(`/test-plans/${activePlanId.value}/webhook-token`)
    activePlan.value.webhook_token = ''
    ElMessage.success('Token 已撤销')
  } catch (e) {
    ElMessage.error('撤销失败：' + (e?.response?.data?.detail || e?.message))
  } finally {
    webhookLoading.value = false
  }
}

// 执行进度
const executionProgress = ref({ current: 0, total: 0, currentName: '', failed: 0, passed: 0 })
let runningTimer = null   // 超时兜底定时器

// 步骤日志（执行面板）
const stepLogs = ref([])   // [{stepNum, case_name, status, duration_ms, method, status_code, error}]

// 新建/编辑对话框
const planDialogVisible = ref(false)
const planDialogMode = ref('create')
const planForm = ref({ name: '', description: '', proxy_url: '', hosts_map: '' })

// 添加步骤对话框
const stepDialogVisible = ref(false)
const allProjects = ref([])
const allCases = ref([])         // 全部用例（含 project_name）
const stepFilterProject = ref(null)
const stepSearchText = ref('')
const selectedCases = ref([])

// 报告抽屉
const reportDrawerVisible = ref(false)
const reportDetail = ref(null)
const aiAnalysis = ref('')
const aiAnalyzing = ref(false)

// 批量选择报告
const selectedReports = ref([])

// WebSocket — 由下方 useWebSocket 管理，此处不再声明 ws 变量

// ── 计算 ─────────────────────────────────────────────────────────────────────
const filteredPlans = computed(() =>
  searchText.value
    ? plans.value.filter(p => p.name.includes(searchText.value))
    : plans.value
)

const execPercent = computed(() => {
  if (!execTotalCount.value) return 0
  return Math.round((execDoneCount.value / execTotalCount.value) * 100)
})

const showExecPanel = computed(() => running.value || stepLogs.value.length > 0)
const execDoneCount = computed(() => stepLogs.value.filter(l => ['passed', 'failed', 'skipped'].includes(l.status)).length)
const execTotalCount = computed(() => stepLogs.value.length)

const filteredCandidateCases = computed(() => {
  let list = allCases.value
  if (stepFilterProject.value) list = list.filter(c => c.project_id === stepFilterProject.value)
  if (stepSearchText.value) list = list.filter(c => c.name.includes(stepSearchText.value))
  return list
})

// AI 分析文本 → 结构化区块（支持 ## 标题、数字列表、- 无序列表、**bold**、`code`）
const analysisBlocks = computed(() => {
  if (!aiAnalysis.value) return []
  const blocks = []
  for (const line of aiAnalysis.value.split('\n')) {
    // ATX 标题 ## / ###
    const atxHeading = line.match(/^(#{1,3})\s+(.*)/)
    // 数字列表 1. / 1、
    const numHeading = line.match(/^(\d+)[.、．\)]\s+(.*)/)
    // 无序列表
    const bullet = line.match(/^(\s*)[-*•]\s+(.*)/)

    if (atxHeading) {
      blocks.push({ type: 'atx', level: atxHeading[1].length, text: fmtInline(atxHeading[2]) })
    } else if (numHeading) {
      blocks.push({ type: 'heading', num: numHeading[1], text: fmtInline(numHeading[2]) })
    } else if (bullet) {
      blocks.push({ type: 'bullet', text: fmtInline(bullet[2]) })
    } else if (!line.trim()) {
      if (blocks.length && blocks[blocks.length - 1].type !== 'spacer')
        blocks.push({ type: 'spacer' })
    } else {
      blocks.push({ type: 'text', text: fmtInline(line) })
    }
  }
  return blocks
})

// 行内格式化：**bold** 和 `code`（返回 HTML 字符串，配合 v-html 使用）
function fmtInline(s) {
  return s
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`(.+?)`/g, '<code style="background:#e8f4ff;padding:1px 5px;border-radius:3px;font-size:11px;color:#0958d9">$1</code>')
}

// ── 工具函数 ──────────────────────────────────────────────────────────────────
function statusTagType(s) {
  return { pending: 'info', running: 'warning', passed: 'success', failed: 'danger' }[s] || 'info'
}
function statusLabel(s) {
  return { pending: '待执行', running: '执行中', passed: '已通过', failed: '有失败' }[s] || s
}
function methodTagType(m) {
  return { GET: '', POST: 'success', PUT: 'warning', DELETE: 'danger', PATCH: 'warning' }[m] || 'info'
}
function formatDate(d) {
  if (!d) return '-'
  // DB stores UTC without timezone suffix; append 'Z' so JS parses it as UTC
  const utc = /[Z+]/.test(d) ? d : d + 'Z'
  return new Date(utc).toLocaleString('zh-CN', { hour12: false })
}
function varSnapshotRows(snap) {
  return Object.entries(snap || {}).map(([name, value]) => ({ name, value }))
}

// 报告卡片样式
function rcClass(row) {
  if (row.pass_rate >= 100) return 'rc-success'
  if (row.pass_rate >= 60)  return 'rc-warning'
  return 'rc-danger'
}

// 报告批量选择
function isSelectedReport(row) {
  return selectedReports.value.some(r => r.id === row.id)
}
function toggleSelectReport(row) {
  const idx = selectedReports.value.findIndex(r => r.id === row.id)
  if (idx >= 0) selectedReports.value.splice(idx, 1)
  else selectedReports.value.push(row)
}

// 复制 AI 分析结果
async function copyAnalysis() {
  try {
    await navigator.clipboard.writeText(aiAnalysis.value)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.warning('复制失败，请手动选择文字复制')
  }
}

// ── 数据加载 ──────────────────────────────────────────────────────────────────
async function loadPlans() {
  const res = await api.get(`/test-plans`, { params: wsStore.currentId ? { workspace_id: wsStore.currentId } : {} })
  plans.value = res
}

async function selectPlan(id) {
  activePlanId.value = id
  stepLogs.value = []     // 清空上一个计划的执行日志
  executionProgress.value = { current: 0, total: 0, currentName: '', failed: 0, passed: 0 }
  await loadPlanDetail(id)
  await loadPlanReports(id)
  activeTab.value = 'steps'
}

async function loadPlanDetail(id) {
  const res = await api.get(`/test-plans/${id}`)
  activePlan.value = res
}

async function loadPlanReports(id) {
  const res = await api.get(`/test-plans/${id}/reports`)
  reports.value = res
  lastReport.value = reports.value[0] ? await fetchReportDetail(reports.value[0].id) : null
}

async function fetchReportDetail(id) {
  const res = await api.get(`/test-plans/reports/${id}`)
  return res
}

async function loadAllProjects() {
  const res = await api.get(`/api-test/projects`)
  allProjects.value = res
}

async function loadCandidateCases() {
  // 使用 all-cases 接口，返回 [{project_id, project_name, cases:[...]}]
  const params = wsStore.currentId ? { workspace_id: wsStore.currentId } : {}
  const res = await api.get(`/api-test/all-cases`, { params })
  const result = []
  for (const proj of res) {
    for (const c of proj.cases || []) {
      result.push({ ...c, project_id: proj.project_id, project_name: proj.project_name })
    }
  }
  allCases.value = result
}

// ── 计划 CRUD ─────────────────────────────────────────────────────────────────
function openCreateDialog() {
  planDialogMode.value = 'create'
  planForm.value = { name: '', description: '', proxy_url: '', hosts_map: '' }
  planDialogVisible.value = true
}

function openEditDialog() {
  planDialogMode.value = 'edit'
  planForm.value = { name: activePlan.value.name, description: activePlan.value.description, proxy_url: activePlan.value.proxy_url || '', hosts_map: activePlan.value.hosts_map || '' }
  planDialogVisible.value = true
}

async function submitPlanForm() {
  const name = planForm.value.name.trim()
  if (!name) {
    ElMessage.warning('请输入计划名称')
    return
  }
  saving.value = true
  try {
    if (planDialogMode.value === 'create') {
      const res = await api.post(`/test-plans`, {
        name,
        description: planForm.value.description || '',
        proxy_url: planForm.value.proxy_url || '',
        hosts_map: planForm.value.hosts_map || '',
        workspace_id: wsStore.currentId || null,
      })
      planDialogVisible.value = false
      ElMessage.success('计划已创建')
      await loadPlans()
      await selectPlan(res.id)
    } else {
      await api.put(`/test-plans/${activePlanId.value}`, {
        name,
        description: planForm.value.description || '',
        proxy_url: planForm.value.proxy_url || '',
        hosts_map: planForm.value.hosts_map || '',
      })
      planDialogVisible.value = false
      ElMessage.success('已更新')
      await loadPlans()
      await loadPlanDetail(activePlanId.value)
    }
  } catch (e) {
    const msg = e?.response?.data?.detail || e?.message || '操作失败，请检查后端服务是否正常'
    ElMessage.error(msg)
    console.error('[submitPlanForm]', e)
  } finally {
    saving.value = false
  }
}

async function deletePlan() {
  await ElMessageBox.confirm(`确定删除计划「${activePlan.value.name}」？其步骤和报告也会一并删除。`, '删除确认', { type: 'warning' })
  try {
    await api.delete(`/test-plans/${activePlanId.value}`)
    ElMessage.success('已删除')
    activePlanId.value = null
    activePlan.value = null
    await loadPlans()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

// ── 步骤管理 ──────────────────────────────────────────────────────────────────
async function openAddStepDialog() {
  selectedCases.value = []
  stepSearchText.value = ''
  stepFilterProject.value = null
  await loadAllProjects()
  await loadCandidateCases()
  stepDialogVisible.value = true
}

async function submitAddSteps() {
  if (!selectedCases.value.length) {
    ElMessage.warning('请至少选择一条用例')
    return
  }
  saving.value = true
  try {
    const currentMax = activePlan.value.steps.length
    const newSteps = selectedCases.value.map((c, i) => ({
      case_id: c.id,
      case_project_id: c.project_id,
      sort_order: currentMax + i,
      enabled: true,
    }))
    await api.post(`/test-plans/${activePlanId.value}/steps`, { steps: newSteps, replace: false })
    ElMessage.success(`已添加 ${newSteps.length} 个步骤`)
    await loadPlanDetail(activePlanId.value)
    await loadPlans()
    stepDialogVisible.value = false
  } finally {
    saving.value = false
  }
}

async function deleteStep(row) {
  await ElMessageBox.confirm(`确定移除步骤「${row.case_name}」？`, '确认', { type: 'warning' })
  await api.delete(`/test-plans/${activePlanId.value}/steps/${row.id}`)
  ElMessage.success('已移除')
  await loadPlanDetail(activePlanId.value)
  await loadPlans()
}

async function toggleStep(row) {
  // 前端已修改 row.enabled，批量替换步骤保存
  const steps = activePlan.value.steps.map((s, i) => ({
    case_id: s.case_id,
    case_project_id: s.case_project_id,
    sort_order: i,
    enabled: s.enabled,
  }))
  await api.post(`/test-plans/${activePlanId.value}/steps`, { steps, replace: true })
}

// ── 执行 ──────────────────────────────────────────────────────────────────────
const MAX_RUN_MS = 10 * 60 * 1000  // 10 分钟超时兜底

function startRunningTimer() {
  clearRunningTimer()
  runningTimer = setTimeout(() => {
    if (running.value) {
      running.value = false
      ElMessage.warning('执行超时（10分钟），已自动停止等待。请检查后端日志。')
      loadPlans()
      if (activePlanId.value) loadPlanDetail(activePlanId.value)
    }
  }, MAX_RUN_MS)
}

function clearRunningTimer() {
  if (runningTimer) { clearTimeout(runningTimer); runningTimer = null }
}

function forceResetRunning() {
  running.value = false
  clearRunningTimer()
  executionProgress.value = { current: 0, total: 0, currentName: '', failed: 0, passed: 0 }
  stepLogs.value.forEach(l => { if (l.status === 'running' || l.status === 'pending') l.status = 'skipped' })
  ElMessage.info('已强制停止等待，执行可能仍在后台运行')
  loadPlans()
  if (activePlanId.value) loadPlanDetail(activePlanId.value)
}

async function runPlan(force = false) {
  if (running.value && !force) return
  running.value = true
  executionProgress.value = {
    current: 0,
    total: activePlan.value.steps.filter(s => s.enabled).length,
    currentName: '',
    failed: 0,
    passed: 0,
  }
  // 初始化步骤日志列表
  stepLogs.value = activePlan.value.steps
    .filter(s => s.enabled)
    .map((s, i) => ({
      stepNum: i + 1,
      case_name: s.case_name,
      module: s.module,
      project_name: s.project_name,
      status: 'pending',
      duration_ms: 0,
      method: '',
      status_code: null,
      error: '',
    }))
  startRunningTimer()
  try {
    const url = `/test-plans/${activePlanId.value}/run${force ? '?force=true' : ''}`
    await api.post(url)
    // 结果通过 WebSocket 推送
  } catch (e) {
    const detail = e?.response?.data?.detail || '启动执行失败'
    if (e?.response?.status === 409) {
      // 计划状态为 running，提示强制重跑
      ElMessage.warning(detail + '，可点击「强制重跑」按钮')
    } else {
      ElMessage.error(detail)
    }
    running.value = false
    stepLogs.value = []
    clearRunningTimer()
  }
}

// ── 报告 ──────────────────────────────────────────────────────────────────────
async function viewReport(id) {
  aiAnalysis.value = ''
  reportDetail.value = null
  reportDrawerVisible.value = true
  reportDetail.value = await fetchReportDetail(id)
  if (reportDetail.value.analysis) aiAnalysis.value = reportDetail.value.analysis
}

function exportReportPdf(reportId, planName) {
  ElMessage.info('正在生成 PDF，请稍候...')
  const name = (planName || `plan_report_${reportId}`).replace(/[/\\]/g, '_')
  downloadPdf(`/test-plans/reports/${reportId}/pdf`, `${name}.pdf`)
}

async function deleteReport(id) {
  await ElMessageBox.confirm('确定删除该执行报告？', '确认', { type: 'warning' })
  await api.delete(`/test-plans/reports/${id}`)
  ElMessage.success('已删除')
  await loadPlanReports(activePlanId.value)
}

async function batchDeleteReports() {
  const ids = selectedReports.value.map(r => r.id)
  if (!ids.length) return
  await ElMessageBox.confirm(`确定删除选中的 ${ids.length} 条报告？`, '批量删除', { type: 'warning' })
  try {
    await api.delete(`/test-plans/reports/batch`, { data: ids })
    ElMessage.success(`已删除 ${ids.length} 条报告`)
    selectedReports.value = []
    await loadPlanReports(activePlanId.value)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

async function analyzeReport() {
  if (!reportDetail.value) return
  aiAnalyzing.value = true
  try {
    const res = await api.post(`/test-plans/reports/${reportDetail.value.id}/analyze`)
    aiAnalysis.value = res.analysis
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || 'AI分析失败')
  } finally {
    aiAnalyzing.value = false
  }
}

// ── WebSocket ─────────────────────────────────────────────────────────────────
let wsRetryTimer = null

const { connect: _wsPlanConnect, isConnected: planWsConnected } = useWebSocket(handleWsMessage)

function initWs() {
  _wsPlanConnect(`plan_${Date.now()}`)
}

// WS 断线后 3 秒重连（组件未卸载时）
let _wsDestroyed = false
watch(planWsConnected, (val) => {
  if (!val && !_wsDestroyed) {
    wsRetryTimer = setTimeout(initWs, 3000)
  }
})

function handleWsMessage(msg) {
  if (msg.type === 'plan_step_start' && msg.plan_id === activePlanId.value) {
    executionProgress.value.current = msg.step
    executionProgress.value.total = msg.total
    executionProgress.value.currentName = msg.case_name
    // 更新步骤日志状态
    const log = stepLogs.value.find(l => l.stepNum === msg.step)
    if (log) {
      log.status = 'running'
      log.case_name = msg.case_name || log.case_name
    }
  }
  if (msg.type === 'plan_step_done' && msg.plan_id === activePlanId.value) {
    const log = stepLogs.value.find(l => l.stepNum === msg.step)
    if (log) {
      log.status = msg.status || 'failed'
      log.duration_ms = msg.duration_ms || 0
      log.method = msg.method || ''
      log.status_code = msg.status_code || null
      log.error = msg.error || ''
    }
    if (msg.status === 'failed') executionProgress.value.failed++
    else executionProgress.value.passed++
  }
  if (msg.type === 'plan_done' && msg.plan_id === activePlanId.value) {
    running.value = false
    clearRunningTimer()
    executionProgress.value.current = msg.total
    executionProgress.value.total = msg.total
    executionProgress.value.currentName = ''
    // 将所有仍在 pending/running 的步骤标记为 skipped
    stepLogs.value.forEach(l => {
      if (l.status === 'pending' || l.status === 'running') l.status = 'skipped'
    })
    const ok = msg.status === 'passed'
    ElMessage[ok ? 'success' : 'error'](
      `执行完成：${msg.passed}/${msg.total} 通过，通过率 ${msg.pass_rate}%`
    )
    loadPlans()
    loadPlanDetail(activePlanId.value)
    loadPlanReports(activePlanId.value)
  }
}

// ── 生命周期 ──────────────────────────────────────────────────────────────────
watch(() => wsStore.currentId, () => { loadPlans() })
onMounted(async () => {
  _wsDestroyed = false  // 重置，支持路由切回时重新连接
  await loadPlans()
  initWs()
})

onUnmounted(() => {
  _wsDestroyed = true
  clearTimeout(wsRetryTimer)
  wsRetryTimer = null
  clearRunningTimer()
})

</script>

<style scoped>
.test-plan-page {
  display: flex;
  gap: 16px;
  height: calc(100vh - 100px);
}

.plan-list-card {
  width: 260px;
  flex-shrink: 0;
}
.plan-list-card :deep(.el-card__body) {
  padding: 12px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.mb-12 { margin-bottom: 12px; }
.mb-16 { margin-bottom: 16px; }
.ml-4  { margin-left: 4px; }
.ml-8  { margin-left: 8px; }
.mr-4  { margin-right: 4px; }

.plan-item {
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 6px;
  border: 1px solid #e4e7ed;
  transition: all 0.2s;
}
.plan-item:hover { border-color: #409eff; background: #f0f7ff; }
.plan-item.active { border-color: #409eff; background: #ecf5ff; }

.plan-item-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}
.plan-name { font-weight: 500; font-size: 13px; }

.plan-item-meta {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #909399;
}
.dot { color: #c0c4cc; }

.plan-detail {
  flex: 1;
  min-width: 0;
  background: #fff;
  border-radius: 4px;
  padding: 16px;
  overflow: auto;
}

.plan-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.detail-tabs {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.detail-tabs :deep(.el-tabs__content) {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

.tab-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.toolbar-sep { flex: 1; }

.exec-panel {
  margin-bottom: 12px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  overflow: hidden;
}

.exec-summary {
  padding: 10px 14px;
  background: #f5f7fa;
  border-bottom: 1px solid #e4e7ed;
}

.exec-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  font-size: 12px;
  color: #606266;
}
.exec-meta-steps { font-weight: 500; }
.exec-current-name {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #409eff;
  font-size: 12px;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 步骤日志列表 */
.step-log-list {
  max-height: 340px;
  overflow-y: auto;
}

.step-log-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 14px;
  border-bottom: 1px solid #f0f0f0;
  font-size: 13px;
  transition: background 0.15s;
}
.step-log-item:last-child { border-bottom: none; }
.step-log-item:hover { background: #fafafa; }

/* 状态着色 */
.sli-passed  { background: #f0fff4; }
.sli-failed  { background: #fff5f5; }
.sli-running { background: #f0f8ff; }
.sli-skipped { background: #fdfcf5; }
.sli-pending { }

.sli-num {
  width: 22px;
  min-width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #e4e7ed;
  color: #606266;
  font-size: 11px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.sli-passed  .sli-num { background: #d4edda; color: #1a7a3e; }
.sli-failed  .sli-num { background: #fde8e8; color: #c0392b; }
.sli-running .sli-num { background: #d0e8ff; color: #1877f2; }

.sli-icon { flex-shrink: 0; display: flex; align-items: center; }

.sli-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
  color: #303133;
}

.sli-method { flex-shrink: 0; }
.sli-code   { flex-shrink: 0; font-size: 12px; font-weight: 600; min-width: 32px; text-align: right; }
.sli-duration {
  flex-shrink: 0;
  font-size: 12px;
  color: #909399;
  min-width: 52px;
  text-align: right;
}
.sli-status-tag { flex-shrink: 0; }
.sli-error {
  flex-shrink: 0;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  color: #f56c6c;
}

/* spin 动画 */
@keyframes spin { to { transform: rotate(360deg); } }
.spin { animation: spin 1s linear infinite; }

.steps-table { width: 100%; }

/* ── 批量操作栏 ─────────────────────────────────────────────────────────── */
.reports-batch-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 12px;
  background: #ecf5ff;
  border: 1px solid #b3d8ff;
  border-radius: 6px;
  margin-bottom: 10px;
  font-size: 13px;
}
.batch-hint { color: #409eff; }
.batch-hint strong { font-weight: 700; }

/* ── 过渡动画 ───────────────────────────────────────────────────────────── */
.slide-down-enter-active, .slide-down-leave-active {
  transition: all 0.2s ease;
}
.slide-down-enter-from, .slide-down-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

/* ── 报告卡片列表 ───────────────────────────────────────────────────────── */
.report-card-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.report-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 8px;
  border: 1px solid #e4e7ed;
  border-left-width: 4px;
  background: #fff;
  transition: box-shadow 0.2s, transform 0.15s;
}
.report-card:hover {
  box-shadow: 0 4px 18px rgba(0, 0, 0, 0.07);
  transform: translateY(-1px);
}
.rc-success { border-left-color: #67c23a; background: linear-gradient(90deg, #f0fff4 0%, #fff 60%); }
.rc-warning  { border-left-color: #e6a23c; background: linear-gradient(90deg, #fffbf0 0%, #fff 60%); }
.rc-danger   { border-left-color: #f56c6c; background: linear-gradient(90deg, #fff5f5 0%, #fff 60%); }

.rc-check { flex-shrink: 0; }

.rc-rank { flex-shrink: 0; }
.rc-rank-badge {
  display: inline-block;
  padding: 2px 7px;
  border-radius: 10px;
  background: #f0f2f5;
  font-size: 11px;
  font-weight: 700;
  color: #909399;
}

.rc-body {
  flex: 1;
  min-width: 0;
}
.rc-time {
  font-size: 13px;
  color: #303133;
  font-weight: 500;
  margin-bottom: 5px;
}
.rc-stats {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.rc-stat { font-size: 12px; }
.rc-stat-total { color: #606266; }
.rc-stat-pass  { color: #67c23a; font-weight: 600; }
.rc-stat-fail  { color: #f56c6c; font-weight: 600; }
.rc-sep { color: #dcdfe6; font-size: 12px; }

.rc-progress { flex-shrink: 0; }
.rc-pct {
  font-size: 11px;
  font-weight: 700;
  color: #303133;
}

.rc-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

/* ── 报告详情抽屉 — 汇总卡片 ─────────────────────────────────────────── */
.report-summary-card {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 16px 20px;
  border-radius: 10px;
  background: linear-gradient(135deg, #f8faff 0%, #ffffff 100%);
  border: 1px solid #e4e7ed;
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
}
.rsc-metric {
  text-align: center;
  padding: 0 20px;
}
.rsc-val {
  font-size: 24px;
  font-weight: 700;
  line-height: 1.2;
  color: #303133;
}
.rsc-val-rate { font-size: 28px; }
.rsc-label {
  font-size: 12px;
  color: #909399;
  margin-top: 3px;
}
.rsc-divider {
  width: 1px;
  height: 36px;
  background: #e4e7ed;
  flex-shrink: 0;
}
.rsc-meta {
  padding-left: 20px;
  flex: 1;
  min-width: 0;
}
.rsc-plan-name {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rsc-time {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
.clr-success { color: #67c23a !important; }
.clr-warning  { color: #e6a23c !important; }
.clr-danger   { color: #f56c6c !important; }
.clr-muted    { color: #c0c4cc !important; }

/* ── AI 分析面板 ────────────────────────────────────────────────────────── */
.aa-fade-enter-active { transition: all 0.35s ease; }
.aa-fade-enter-from   { opacity: 0; transform: translateY(10px); }

.ai-analysis-panel {
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 4px 20px rgba(64, 158, 255, 0.14);
  border: 1px solid rgba(64, 158, 255, 0.22);
}

.ai-analysis-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 11px 16px;
  background: linear-gradient(100deg, #3a7bd5 0%, #00d2ff 100%);
}
.ai-hdr-left {
  display: flex;
  align-items: center;
  gap: 7px;
  color: #fff;
}
.ai-hdr-icon {
  font-size: 16px;
  animation: pulse-star 2s ease-in-out infinite;
}
@keyframes pulse-star {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%       { opacity: 0.7; transform: scale(1.2); }
}
.ai-hdr-title {
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.3px;
}

.ai-analysis-body {
  padding: 16px 20px;
  background: #fff;
  max-height: 540px;
  overflow-y: auto;
}

/* 编号标题 */
.aa-heading {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 18px 0 8px;
  padding: 9px 14px;
  background: linear-gradient(90deg, #e8f4ff 0%, #f5faff 100%);
  border-radius: 7px;
  border-left: 3px solid #409eff;
}
.aa-heading:first-child { margin-top: 0; }
.aa-num {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #409eff;
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.aa-title {
  font-size: 14px;
  font-weight: 600;
  color: #1a6fd4;
}

/* 子弹点 */
.aa-bullet {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 4px 14px 4px 20px;
}
.aa-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #409eff;
  margin-top: 8px;
  flex-shrink: 0;
  opacity: 0.7;
}
.aa-bullet-text {
  font-size: 13px;
  color: #4a5568;
  line-height: 1.7;
}

/* 普通文本 */
.aa-text {
  padding: 2px 14px 2px 20px;
  font-size: 13px;
  color: #606266;
  line-height: 1.7;
}

/* ATX 标题（## / ###） */
.aa-atx {
  margin: 16px 0 6px;
  font-weight: 700;
  color: #1a2a4a;
}
.aa-atx-1 { font-size: 15px; border-left: 3px solid #3a7bd5; padding-left: 10px; }
.aa-atx-2 { font-size: 14px; color: #1a6fd4; }
.aa-atx-3 { font-size: 13px; color: #409eff; }
.aa-atx:first-child { margin-top: 0; }

.aa-spacer { height: 6px; }

.step-dialog-toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}

/* Report drawer */
.report-detail { padding: 4px 0; }

.step-result-card {
  margin-bottom: 4px;
  border: 1px solid #e4e7ed;
}
.step-result-card :deep(.el-card__body) { padding: 10px 12px; }

.step-result-header {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 6px;
}
.step-method-url {
  display: flex;
  align-items: center;
  margin-left: 8px;
  font-size: 12px;
  color: #606266;
}

.step-error {
  font-size: 12px;
  margin: 4px 0;
}

.assertions-table {
  margin: 6px 0;
}

.step-vars {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin: 6px 0;
}

.response-preview {
  font-size: 12px;
  background: #f5f7fa;
  padding: 8px;
  border-radius: 4px;
  overflow: auto;
  max-height: 200px;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
