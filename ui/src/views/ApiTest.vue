<template>
  <div class="api-test">
    <!-- 左侧：项目列表 -->
    <div class="project-panel">
      <div class="panel-header">
        <span>接口项目</span>
        <el-button size="small" type="primary" :icon="Plus" @click="showProjectDialog(null)">新建</el-button>
      </div>
      <div
        v-for="p in projects"
        :key="p.id"
        class="project-item"
        :class="{ active: currentProject?.id === p.id }"
        @click="selectProject(p)"
      >
        <div class="project-name">{{ p.name }}</div>
        <div class="project-url">{{ p.base_url }}</div>
        <div class="project-actions">
          <el-tooltip content="编辑" placement="top" :show-after="300">
            <el-button size="small" type="primary" link @click.stop="showProjectDialog(p)">
              <el-icon><Edit /></el-icon>
            </el-button>
          </el-tooltip>
          <el-tooltip content="删除" placement="top" :show-after="300">
            <el-button size="small" type="danger" link @click.stop="deleteProject(p)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </el-tooltip>
        </div>
      </div>
      <el-empty v-if="projects.length === 0" description="暂无项目" :image-size="60" />
    </div>

    <!-- 右侧：内容区 -->
    <div class="content-panel" v-if="currentProject">
      <el-tabs v-model="activeTab" class="content-tabs">

        <!-- ══════════════════════════════════════
             Tab 1: 接口用例（管理）
        ══════════════════════════════════════ -->
        <el-tab-pane label="接口用例" name="cases-mgmt">
          <div class="toolbar">
            <el-button type="primary" :icon="MagicStick" @click="showGenDialog" :loading="generating">AI生成用例</el-button>
            <el-button :icon="Plus" @click="showCaseDialog(null)">新建用例</el-button>
            <el-button type="danger" :icon="Delete" @click="() => deleteCases()"
              :disabled="selectedCases.length === 0">删除选中({{ selectedCases.length }})</el-button>
            <el-button :icon="Refresh" @click="loadCases" :loading="refreshing">刷新</el-button>
            <el-button style="margin-left:auto" @click="showScriptDialog">脚本函数</el-button>
            <el-button @click="showGvarDialog">全局变量</el-button>
          </div>

          <!-- 生成进度 -->
          <div v-if="generating || genProgress > 0" class="gen-progress-wrap">
            <div class="gen-progress-head">
              <div style="display:flex;align-items:center;gap:8px">
                <el-icon v-if="generating" class="is-loading" style="color:#409eff;font-size:17px"><Loading /></el-icon>
                <svg v-else viewBox="0 0 24 24" width="17" height="17" fill="none" style="flex-shrink:0">
                  <circle cx="12" cy="12" r="11" fill="#52c41a"/>
                  <path d="M7 12.5l3.5 3.5 6.5-7" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <span style="font-size:14px;font-weight:600;color:#1a1a1a">{{ generating ? 'AI 正在生成接口用例' : '生成完成' }}</span>
              </div>
              <span class="gen-pct-badge" :style="genProgress===100 ? 'color:#52c41a' : ''">{{ genProgress }}%</span>
            </div>

            <el-progress :percentage="genProgress" :striped="generating" :striped-flow="generating"
              :stroke-width="8" :show-text="false"
              :status="!generating && genProgress===100 ? 'success' : ''"
              style="margin:8px 0 6px" />

            <div class="gen-stage-text">
              <span class="gen-stage-dot" :class="{ pulsing: generating, done: !generating }"></span>
              {{ genStage }}
            </div>

            <!-- 步骤条 -->
            <div class="gen-steps-row">
              <template v-for="(step, i) in genStepDefs" :key="i">
                <div class="gen-step-item" :class="{
                  'gstep-done':    genProgress >= step.end,
                  'gstep-active':  generating && genProgress >= step.start && genProgress < step.end,
                  'gstep-pending': genProgress < step.start
                }">
                  <div class="gstep-dot">
                    <span v-if="genProgress >= step.end" style="font-size:12px">✓</span>
                    <el-icon v-else-if="generating && genProgress >= step.start" class="is-loading" style="font-size:10px"><Loading /></el-icon>
                    <span v-else style="font-size:11px">{{ i + 1 }}</span>
                  </div>
                  <span class="gstep-label">{{ step.label }}</span>
                </div>
                <div v-if="i < genStepDefs.length - 1" class="gstep-connector"
                  :class="{ 'connector-done': genProgress >= step.end }"></div>
              </template>
            </div>
          </div>

          <el-table :data="casesGrouped" row-key="id" :tree-props="{children:'children'}"
            default-expand-all
            ref="caseTableRef"
            :row-class-name="({ row }) => row._isGroup ? 'case-group-row' : 'case-leaf-row'"
            @select="(sel, row) => handleGroupSelect(sel, row, caseTableRef)"
            @selection-change="selectedCases = $event.filter(r => !r._isGroup)"
            @row-click="(row, col, e) => handleRowClick(row, col, e, caseTableRef)"
            stripe style="margin-top:12px">
            <el-table-column type="selection" width="45" />
            <el-table-column label="接口" min-width="360">
              <template #default="{ row }">
                <template v-if="row._isGroup">
                  <div class="group-cell">
                    <div class="group-cell-header">
                      <span class="group-cell-path">{{ row.path }}</span>
                      <el-tag type="primary" size="small" effect="plain" style="margin-left:10px;flex-shrink:0">{{ row._count }} 个用例</el-tag>
                    </div>
                    <el-input v-model="row.description" placeholder="点击添加接口描述..."
                      class="group-desc-field" @blur="saveGroupDescription(row)" />
                  </div>
                </template>
                <template v-else>
                  <div class="case-cell">
                    <el-tag :type="methodColor(row.method)" size="small" class="method-tag">{{ row.method }}</el-tag>
                    <span class="case-name">{{ row.name }}</span>
                  </div>
                </template>
              </template>
            </el-table-column>
            <el-table-column label="模块" width="90">
              <template #default="{ row }">
                <el-tag v-if="!row._isGroup && row.module" type="info" size="small" effect="plain">{{ row.module }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="优先级" width="76">
              <template #default="{ row }">
                <el-tag v-if="!row._isGroup" :type="row.priority === 'P0' ? 'danger' : row.priority === 'P1' ? 'warning' : 'info'" size="small">{{ row.priority }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="启用" width="64">
              <template #default="{ row }">
                <el-switch v-if="!row._isGroup" v-model="row.enabled" @change="toggleCase(row)" />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="80" fixed="right" align="center">
              <template #default="{ row }">
                <div v-if="!row._isGroup" class="table-action-btns">
                  <el-tooltip content="编辑" placement="top" :show-after="400">
                    <el-button size="small" type="primary" plain circle @click="showCaseDialog(row)">
                      <el-icon><Edit /></el-icon>
                    </el-button>
                  </el-tooltip>
                  <el-tooltip content="删除" placement="top" :show-after="400">
                    <el-button size="small" type="danger" plain circle @click="deleteCases([row.id])">
                      <el-icon><Delete /></el-icon>
                    </el-button>
                  </el-tooltip>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- ══════════════════════════════════════
             Tab 2: 单测执行
        ══════════════════════════════════════ -->
        <el-tab-pane label="单测执行" name="unit">
          <el-row :gutter="16">
            <!-- 左：接口选择 -->
            <el-col :span="10">
              <div class="exec-select-panel">
                <div class="exec-select-header">
                  <div class="exec-select-title">
                    <span>选择接口</span>
                    <el-tag type="primary" effect="plain" size="small" style="margin-left:8px">
                      {{ selectedUnitCases.length }} / {{ cases.length }}
                    </el-tag>
                  </div>
                  <div class="select-actions">
                    <span class="select-action-link" @click="selectAllUnit">全选</span>
                    <span class="select-action-sep">|</span>
                    <span class="select-action-link muted" @click="selectedUnitCases = []">清空</span>
                  </div>
                </div>
                <el-table :data="casesGrouped" @selection-change="selectedUnitCases = $event.filter(r => !r._isGroup)"
                  ref="unitTableRef" size="small" max-height="380" stripe
                  row-key="id" :tree-props="{children:'children'}" default-expand-all
                  :row-class-name="({ row }) => row._isGroup ? 'case-group-row' : ''"
                  @select="(sel, row) => handleGroupSelect(sel, row, unitTableRef)"
                  @row-click="(row, col, e) => handleRowClick(row, col, e, unitTableRef)">
                  <el-table-column type="selection" width="40" />
                  <el-table-column label="接口" show-overflow-tooltip>
                    <template #default="{ row }">
                      <template v-if="row._isGroup">
                        <div class="unit-group-path">
                          <span>{{ row.path }}</span>
                          <el-tag type="info" size="small" style="margin-left:6px;flex-shrink:0">{{ row._count }}</el-tag>
                        </div>
                        <div v-if="row.description" class="unit-group-desc">{{ row.description }}</div>
                      </template>
                      <template v-else>
                        <div class="case-cell">
                          <el-tag :type="methodColor(row.method)" size="small" class="method-tag">{{ row.method }}</el-tag>
                          <span class="case-name">{{ row.name }}</span>
                        </div>
                      </template>
                    </template>
                  </el-table-column>
                </el-table>
                <div class="exec-btn-wrap">
                  <el-button type="success" :icon="VideoPlay" style="width:100%;height:38px;font-size:14px"
                    @click="executeSelected" :disabled="selectedUnitCases.length === 0" :loading="executing">
                    {{ executing ? '执行中...' : `执行选中 (${selectedUnitCases.length})` }}
                  </el-button>
                </div>
              </div>
            </el-col>

            <!-- 右：进度 + 统计 + 结果 -->
            <el-col :span="14">
              <!-- 执行进度条 -->
              <div v-if="executing || execProgress > 0" class="unit-progress-panel">
                <div class="unit-progress-top">
                  <div style="display:flex;align-items:center;gap:8px">
                    <el-icon v-if="executing" class="is-loading" style="color:#409eff;font-size:15px"><Loading /></el-icon>
                    <svg v-else viewBox="0 0 24 24" width="15" height="15" fill="none">
                      <circle cx="12" cy="12" r="11" fill="#52c41a"/>
                      <path d="M7 12.5l3.5 3.5 6.5-7" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                    <span class="unit-progress-title">{{ executing ? '正在执行用例...' : '执行完成' }}</span>
                  </div>
                  <span class="unit-pct" :style="!executing && execProgress===100 ? 'color:#52c41a' : ''">{{ execProgress }}%</span>
                </div>
                <el-progress :percentage="execProgress" :striped="executing" :striped-flow="executing"
                  :stroke-width="6" :show-text="false"
                  :status="!executing && execSummary.failed > 0 ? 'exception' : (!executing && execProgress===100 ? 'success' : '')"
                  style="margin:8px 0 4px" />
                <div class="unit-stage-text">{{ execStage }}</div>
              </div>

              <!-- 统计数字行 -->
              <div v-if="execResults.length > 0" class="unit-stat-row">
                <div class="unit-stat-card stat-total">
                  <div class="stat-num">{{ execResults.length }}</div>
                  <div class="stat-label">总用例</div>
                </div>
                <div class="unit-stat-card stat-passed">
                  <div class="stat-num">{{ execSummary.passed }}</div>
                  <div class="stat-label">通过</div>
                </div>
                <div class="unit-stat-card stat-failed">
                  <div class="stat-num">{{ execSummary.failed }}</div>
                  <div class="stat-label">失败</div>
                </div>
                <div class="unit-stat-card stat-rate">
                  <el-progress type="circle" :percentage="Number(execSummary.pass_rate)"
                    :stroke-width="6" :width="58"
                    :status="execSummary.pass_rate >= 100 ? 'success' : execSummary.failed > 0 ? 'exception' : ''" />
                  <div class="stat-label" style="margin-top:5px">通过率</div>
                </div>
              </div>

              <!-- 结果表格 -->
              <div v-if="execResults.length > 0" class="unit-result-wrap">
                <el-table :data="execResults" size="small" max-height="320" stripe
                  :row-class-name="({ row }) => row.status === 'passed' ? 'result-pass-row' : 'result-fail-row'">
                  <el-table-column prop="method" label="方法" width="68">
                    <template #default="{ row }">
                      <el-tag :type="methodColor(row.method)" size="small">{{ row.method }}</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column prop="case_name" label="用例" min-width="140" show-overflow-tooltip />
                  <el-table-column prop="status_code" label="状态码" width="74" align="center" />
                  <el-table-column prop="duration_ms" label="耗时ms" width="80" align="right" />
                  <el-table-column prop="status" label="结果" width="68" align="center">
                    <template #default="{ row }">
                      <el-tag :type="row.status === 'passed' ? 'success' : 'danger'" size="small" effect="dark">
                        {{ row.status === 'passed' ? '通过' : '失败' }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column prop="error" label="错误信息" min-width="140" show-overflow-tooltip>
                    <template #default="{ row }">
                      <span :class="row.error ? 'result-error-text' : 'result-ok-text'">{{ row.error || '—' }}</span>
                    </template>
                  </el-table-column>
                </el-table>
              </div>

              <el-empty v-else-if="!executing && execProgress === 0"
                description="选择左侧接口后点击执行" :image-size="80" style="margin-top:60px" />
            </el-col>
          </el-row>
        </el-tab-pane>

        <!-- ══════════════════════════════════════
             Tab 3: 压力测试
        ══════════════════════════════════════ -->
        <el-tab-pane label="压力测试" name="load">
          <el-row :gutter="16">
            <!-- 左列：接口选择 + 压测配置 + 结果汇总 -->
            <el-col :span="10">
              <!-- 接口选择 -->
              <div class="exec-select-panel" style="margin-bottom:12px">
                <div class="exec-select-header">
                  <div class="exec-select-title">
                    <span>选择压测接口</span>
                    <el-tag type="warning" effect="plain" size="small" style="margin-left:8px">
                      {{ selectedLoadCases.length }} / {{ cases.length }}
                    </el-tag>
                  </div>
                  <div class="select-actions">
                    <span class="select-action-link" @click="selectAllLoad">全选</span>
                    <span class="select-action-sep">|</span>
                    <span class="select-action-link muted" @click="selectedLoadCases = []">清空</span>
                  </div>
                </div>
                <el-table :data="casesGrouped" @selection-change="selectedLoadCases = $event.filter(r => !r._isGroup)"
                  ref="loadTableRef" size="small" max-height="200" stripe
                  row-key="id" :tree-props="{children:'children'}" default-expand-all
                  :row-class-name="({ row }) => row._isGroup ? 'case-group-row' : ''"
                  @select="(sel, row) => handleGroupSelect(sel, row, loadTableRef)"
                  @row-click="(row, col, e) => handleRowClick(row, col, e, loadTableRef)">
                  <el-table-column type="selection" width="40" />
                  <el-table-column label="接口" show-overflow-tooltip>
                    <template #default="{ row }">
                      <template v-if="row._isGroup">
                        <div class="unit-group-path">
                          <span>{{ row.path }}</span>
                          <el-tag type="info" size="small" style="margin-left:6px;flex-shrink:0">{{ row._count }}</el-tag>
                        </div>
                        <div v-if="row.description" class="unit-group-desc">{{ row.description }}</div>
                      </template>
                      <template v-else>
                        <div class="case-cell">
                          <el-tag :type="methodColor(row.method)" size="small" class="method-tag">{{ row.method }}</el-tag>
                          <span class="case-name">{{ row.name }}</span>
                        </div>
                      </template>
                    </template>
                  </el-table-column>
                </el-table>
              </div>

              <!-- 压测参数 -->
              <div class="load-config-panel">
                <div class="load-config-header">压测参数</div>
                <div class="load-config-grid">
                  <div class="load-config-item">
                    <div class="load-config-label">并发用户数</div>
                    <el-input-number v-model="loadConfig.concurrent_users" :min="1" :max="500"
                      size="small" controls-position="right" style="width:100%" />
                  </div>
                  <div class="load-config-item">
                    <div class="load-config-label">持续时长(s)</div>
                    <el-input-number v-model="loadConfig.duration" :min="5" :max="3600"
                      size="small" controls-position="right" style="width:100%" />
                  </div>
                  <div class="load-config-item">
                    <div class="load-config-label">加速时长(s)</div>
                    <el-input-number v-model="loadConfig.ramp_up" :min="0" :max="300"
                      size="small" controls-position="right" style="width:100%" />
                  </div>
                </div>
                <div class="load-action-row">
                  <el-button type="primary" :icon="VideoPlay" @click="startLoad"
                    :loading="loadRunning" :disabled="selectedLoadCases.length === 0" style="flex:1;height:38px">
                    {{ loadRunning ? '压测中...' : `开始压测 (${selectedLoadCases.length})` }}
                  </el-button>
                  <el-button type="danger" plain @click="stopLoad" :disabled="!loadRunning" style="height:38px">停止</el-button>
                </div>
              </div>

              <!-- 压测结果汇总 -->
              <div v-if="loadReport" class="load-report-panel">
                <div class="load-report-header">本次结果</div>
                <div class="load-report-grid">
                  <div class="load-report-item">
                    <div class="load-report-val">{{ loadReport.total_requests }}</div>
                    <div class="load-report-key">总请求数</div>
                  </div>
                  <div class="load-report-item" :class="loadReport.success_rate >= 99 ? 'lri-good' : loadReport.success_rate < 90 ? 'lri-bad' : ''">
                    <div class="load-report-val">{{ loadReport.success_rate }}%</div>
                    <div class="load-report-key">成功率</div>
                  </div>
                  <div class="load-report-item">
                    <div class="load-report-val">{{ loadReport.avg_tps }}</div>
                    <div class="load-report-key">平均TPS</div>
                  </div>
                  <div class="load-report-item">
                    <div class="load-report-val">{{ loadReport.avg_ms }}<span class="lrv-unit"> ms</span></div>
                    <div class="load-report-key">平均耗时</div>
                  </div>
                  <div class="load-report-item">
                    <div class="load-report-val">{{ loadReport.p95_ms }}<span class="lrv-unit"> ms</span></div>
                    <div class="load-report-key">P95</div>
                  </div>
                  <div class="load-report-item">
                    <div class="load-report-val">{{ loadReport.max_ms }}<span class="lrv-unit"> ms</span></div>
                    <div class="load-report-key">最大耗时</div>
                  </div>
                </div>
              </div>
            </el-col>

            <!-- 右列：实时图表 -->
            <el-col :span="14">
              <div class="chart-panel">
                <div class="chart-panel-header">
                  <span class="chart-panel-title">实时指标</span>
                  <div v-if="loadRunning" class="live-metrics-row">
                    <span class="live-badge">LIVE</span>
                    <div class="live-chip">
                      <span class="live-chip-label">TPS</span>
                      <span class="live-chip-val">{{ currentTPS }}</span>
                    </div>
                    <div class="live-chip">
                      <span class="live-chip-label">延迟</span>
                      <span class="live-chip-val">{{ currentAvgMs }}<span style="font-size:10px"> ms</span></span>
                    </div>
                    <div class="live-chip live-chip-err">
                      <span class="live-chip-label">错误率</span>
                      <span class="live-chip-val">{{ currentErrRate }}%</span>
                    </div>
                  </div>
                </div>
                <div v-if="selectedLoadCases.length === 0 && !loadRunning && !loadReport" class="chart-empty">
                  <el-empty description="请先在左侧选择要压测的接口" :image-size="64" />
                </div>
                <div v-else ref="chartRef" style="height:400px" />
              </div>
            </el-col>
          </el-row>
        </el-tab-pane>

        <!-- ══════════════════════════════════════
             Tab 4: 测试报告
        ══════════════════════════════════════ -->
        <el-tab-pane label="测试报告" name="reports">
          <div class="toolbar">
            <el-button :icon="Refresh" @click="loadReports" :loading="reportsLoading">刷新</el-button>
            <el-button type="danger" :icon="Delete" :disabled="selectedReports.length === 0"
              @click="deleteReports()">删除选中 ({{ selectedReports.length }})</el-button>
          </div>
          <el-table :data="reports" stripe v-loading="reportsLoading" row-key="id"
            @selection-change="selectedReports = $event">
            <el-table-column type="selection" width="45" />
            <el-table-column prop="report_type" label="类型" width="80">
              <template #default="{ row }">
                <el-tag :type="row.report_type === 'unit' ? 'primary' : 'warning'" size="small">
                  {{ row.report_type === 'unit' ? '单测' : '压测' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="total" label="总数" width="70" />
            <el-table-column prop="passed" label="通过" width="70">
              <template #default="{ row }"><span style="color:#67c23a">{{ row.passed }}</span></template>
            </el-table-column>
            <el-table-column prop="failed" label="失败" width="70">
              <template #default="{ row }">
                <span :style="row.failed > 0 ? 'color:#f56c6c' : ''">{{ row.failed }}</span>
              </template>
            </el-table-column>
            <el-table-column label="通过率" width="90">
              <template #default="{ row }">
                <span :style="passRateColor(row)">{{ passRate(row) }}%</span>
              </template>
            </el-table-column>
            <el-table-column label="压测指标" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                <span v-if="row.report_type === 'load' && row.summary">
                  TPS {{ row.summary.avg_tps }} | 均值 {{ row.summary.avg_ms }}ms | P95 {{ row.summary.p95_ms }}ms
                </span>
                <span v-else style="color:#999;font-size:12px">—</span>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="时间" width="160" show-overflow-tooltip>
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="140" fixed="right" align="center">
              <template #default="{ row }">
                <div class="table-action-btns">
                  <el-button size="small" type="primary" plain @click="showReportDetail(row)">
                    <el-icon><View /></el-icon> 详情
                  </el-button>
                  <el-button size="small" type="danger" plain @click="deleteReports([row.id])">
                    <el-icon><Delete /></el-icon> 删除
                  </el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

      </el-tabs>
    </div>

    <div class="content-panel empty-hint" v-else>
      <el-empty description="请先选择或新建一个接口项目" />
    </div>

    <!-- 新建/编辑项目 Dialog -->
    <el-dialog v-model="projectDialogVisible" :title="editingProject ? '编辑项目' : '新建项目'" width="520px">
      <el-form :model="projectForm" label-width="100px" size="small">
        <el-form-item label="项目名称" required>
          <el-input v-model="projectForm.name" placeholder="如：用户服务接口" />
        </el-form-item>
        <el-form-item label="Base URL" required>
          <el-input v-model="projectForm.base_url" placeholder="https://api.example.com" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="projectForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="代理地址">
          <el-input v-model="projectForm.proxy_url"
            placeholder="留空直连，例：http://proxy:8080 或 socks5://user:pass@host:1080" />
        </el-form-item>
        <el-form-item label="Hosts 映射">
          <el-input v-model="projectForm.hosts_map" type="textarea" :rows="3"
            placeholder="格式同 /etc/hosts，每行一条：&#10;47.94.236.243 japi.hqwx.com&#10;1.2.3.4 other.domain.com" />
        </el-form-item>
        <el-form-item label="认证方式">
          <el-select v-model="projectForm.auth_type" style="width:100%">
            <el-option label="无认证" value="none" />
            <el-option label="Bearer Token" value="bearer" />
            <el-option label="API Key (Header)" value="api_key" />
            <el-option label="Basic Auth" value="basic" />
          </el-select>
        </el-form-item>
        <template v-if="projectForm.auth_type === 'bearer'">
          <el-form-item label="Token">
            <el-input v-model="projectForm.auth_config.token" placeholder="eyJhbGciOiJIUzI1NiIs..." />
          </el-form-item>
        </template>
        <template v-if="projectForm.auth_type === 'api_key'">
          <el-form-item label="Header名">
            <el-input v-model="projectForm.auth_config.key" placeholder="X-API-Key" />
          </el-form-item>
          <el-form-item label="Key值">
            <el-input v-model="projectForm.auth_config.value" />
          </el-form-item>
        </template>
        <template v-if="projectForm.auth_type === 'basic'">
          <el-form-item label="用户名">
            <el-input v-model="projectForm.auth_config.username" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="projectForm.auth_config.password" type="password" />
          </el-form-item>
        </template>

        <!-- 前置用例 -->
        <el-divider content-position="left" style="margin:12px 0 8px">
          <span style="font-size:12px;color:#909399">Token 自动刷新</span>
        </el-divider>
        <el-form-item label="前置用例">
          <div style="width:100%">
            <div style="font-size:12px;color:#909399;margin-bottom:6px">
              每次执行前先跑这些用例（如登录），自动刷新全局变量中的 token
            </div>
            <el-select v-model="projectForm.setup_cases" multiple placeholder="选择前置用例"
              style="width:100%" value-key="key" @visible-change="loadAllCasesForSetup">
              <el-option-group v-for="g in allCasesGrouped" :key="g.project_id" :label="g.project_name">
                <el-option v-for="c in g.cases" :key="`${g.project_id}_${c.case_id}`"
                  :label="`${g.project_name} / ${c.label}`"
                  :value="{ project_id: g.project_id, case_id: c.case_id, label: `${g.project_name} / ${c.label}`, key: `${g.project_id}_${c.case_id}` }" />
              </el-option-group>
            </el-select>
          </div>
        </el-form-item>

        <!-- 鉴权失败特征 -->
        <el-form-item label="失败特征">
          <div style="width:100%">
            <div style="font-size:12px;color:#909399;margin-bottom:6px">
              响应命中以下特征时，自动重跑前置用例刷新 token 并重试（仅一次）
            </div>
            <div v-for="(row, i) in projectForm.auth_error_patterns" :key="i"
              style="display:flex;gap:6px;margin-bottom:6px;align-items:center">
              <el-input v-model="row.field" placeholder="字段路径（如 $.status.code 或 http_status）"
                style="flex:2" size="small" />
              <el-input v-model="row.value" placeholder="期望值（如 40042 或 401）"
                style="flex:1" size="small" />
              <el-button size="small" text type="danger" @click="projectForm.auth_error_patterns.splice(i,1)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
            <el-button size="small" :icon="Plus"
              @click="projectForm.auth_error_patterns.push({ field: '', value: '' })">
              添加特征
            </el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="projectDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveProject" :loading="savingProject">保存</el-button>
      </template>
    </el-dialog>

    <!-- AI 生成用例 Dialog -->
    <el-dialog v-model="genDialogVisible" title="AI生成接口用例" width="600px">
      <el-tabs v-model="genTab">
        <el-tab-pane label="粘贴Swagger/OpenAPI" name="swagger">
          <el-input
            v-model="genSwagger"
            type="textarea"
            :rows="10"
            placeholder="粘贴 Swagger JSON / OpenAPI YAML 内容..."
          />
        </el-tab-pane>
        <el-tab-pane label="自然语言描述" name="desc">
          <el-input
            v-model="genDescription"
            type="textarea"
            :rows="10"
            placeholder="描述接口功能，例如：用户管理系统，包含注册、登录、查询用户列表、更新用户信息、删除用户等接口..."
          />
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-button @click="genDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="startGenerate" :loading="generating">开始生成</el-button>
      </template>
    </el-dialog>

    <!-- 脚本函数管理 Dialog -->
    <el-dialog v-model="scriptDialogVisible" title="脚本函数库" width="980px" top="3vh" destroy-on-close
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
                <el-input
                  v-model="aiGenPrompt"
                  type="textarea"
                  :rows="3"
                  placeholder="例如：生成一个登录签名函数，用 sha1(请求体json + | + app_secret) 计算 reqSign，app_secret 固定为 K8O7dT7P5n1NGUWM"
                  class="ai-gen-input"
                  resize="none"
                  @keydown.ctrl.enter="doAiGenerate"
                />
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
                <textarea
                  class="py-textarea"
                  v-model="editingScript.code"
                  spellcheck="false"
                  autocomplete="off"
                  @scroll="syncEditorScroll"
                  @input="onCodeInput"
                  @keydown.tab.prevent="insertTab"
                  :placeholder="scriptPlaceholder"
                ></textarea>
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
                class="sed-test-btn">
                <svg v-if="!scriptTesting" width="12" height="12" viewBox="0 0 16 16" fill="currentColor" style="margin-right:3px">
                  <path d="M11.596 8.697l-6.363 3.692c-.54.313-1.233-.066-1.233-.697V4.308c0-.63.692-1.01 1.233-.696l6.363 3.692a.802.802 0 0 1 0 1.393z"/>
                </svg>
                执行
              </el-button>
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
            <el-button size="small" type="danger" plain :icon="Delete" @click="deleteScript(editingScript.id)">
              删除
            </el-button>
            <el-button size="small" type="primary" @click="saveScript">
              保存脚本
            </el-button>
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

    <!-- 报告详情 Dialog -->
    <el-dialog v-model="reportDetailVisible" title="报告详情" width="900px" top="3vh">
      <template v-if="selectedReport">

        <!-- ── 压测接口详情（仅压测报告） ── -->
        <template v-if="selectedReport.report_type === 'load'">
          <div class="report-section-title">压测接口</div>
          <div v-if="selectedReport.details?.length" class="load-cases-wrap">
            <el-collapse accordion>
              <el-collapse-item v-for="c in selectedReport.details" :key="c.id ?? c.path" :name="c.id ?? c.path">
                <template #title>
                  <div style="display:flex;align-items:center;gap:8px;flex:1;min-width:0">
                    <el-tag :type="methodColor(c.method)" size="small" style="flex-shrink:0">{{ c.method }}</el-tag>
                    <code style="font-size:13px;color:#303133;flex-shrink:0">{{ c.path }}</code>
                    <span style="font-size:13px;color:#606266;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ c.name }}</span>
                    <el-tag v-if="c.module && c.module !== '通用'" size="small" type="info" style="margin-left:auto;flex-shrink:0">{{ c.module }}</el-tag>
                  </div>
                </template>
                <div class="load-case-detail">
                  <div v-if="c.description" class="lcd-desc">{{ c.description }}</div>
                  <div class="lcd-grid">
                    <!-- Query Params -->
                    <div v-if="c.params && Object.keys(c.params).length" class="lcd-block">
                      <div class="lcd-block-title">Query Params</div>
                      <div v-for="(v, k) in c.params" :key="k" class="lcd-kv">
                        <code class="lcd-k">{{ k }}</code><span class="lcd-eq">=</span><code class="lcd-v">{{ v }}</code>
                      </div>
                    </div>
                    <!-- Headers -->
                    <div v-if="c.headers && Object.keys(c.headers).length" class="lcd-block">
                      <div class="lcd-block-title">Headers</div>
                      <div v-for="(v, k) in c.headers" :key="k" class="lcd-kv">
                        <code class="lcd-k">{{ k }}</code><span class="lcd-eq">:</span><code class="lcd-v">{{ v }}</code>
                      </div>
                    </div>
                    <!-- Body -->
                    <div v-if="c.body_type !== 'none' && (c.body || c.body_raw)" class="lcd-block lcd-block-full">
                      <div class="lcd-block-title">请求体 ({{ c.body_type }})</div>
                      <pre class="lcd-code">{{ formatBodyPreview(c) }}</pre>
                    </div>
                    <!-- Assertions -->
                    <div v-if="c.assertions?.length" class="lcd-block lcd-block-full">
                      <div class="lcd-block-title">断言规则</div>
                      <div v-for="(a, i) in c.assertions" :key="i" class="lcd-assertion">
                        <el-tag size="small" type="info">{{ a.type === 'status_code' ? '状态码' : a.type === 'json_path' ? 'JSON Path' : '响应时间' }}</el-tag>
                        <template v-if="a.type === 'status_code'">
                          <span class="lcd-eq">= {{ a.expected }}</span>
                        </template>
                        <template v-else-if="a.type === 'json_path'">
                          <el-tooltip :content="a.path" placement="top" :show-after="300" :disabled="!a.path || a.path.length < 24">
                            <code class="lcd-k lcd-path">{{ a.path }}</code>
                          </el-tooltip>
                          <span class="lcd-eq">{{ a.match_type || 'equals' }}</span>
                          <code v-if="a.expected !== null && a.expected !== undefined" class="lcd-v">{{ a.expected }}</code>
                        </template>
                        <template v-else-if="a.type === 'response_time'">
                          <span class="lcd-eq">≤ {{ a.max_ms }} ms</span>
                        </template>
                      </div>
                    </div>
                  </div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </div>
          <div v-else class="lcd-empty">暂无接口数据（旧报告未保存接口信息）</div>

          <!-- 压测配置 -->
          <div v-if="selectedReport.summary?.config" class="report-section-title" style="margin-top:16px">压测配置</div>
          <div v-if="selectedReport.summary?.config" class="load-config-summary">
            <div class="lcs-item">
              <span class="lcs-label">并发用户</span>
              <span class="lcs-value">{{ selectedReport.summary.config.concurrent_users }}</span>
            </div>
            <div class="lcs-item">
              <span class="lcs-label">持续时长</span>
              <span class="lcs-value">{{ selectedReport.summary.config.duration }} s</span>
            </div>
            <div class="lcs-item">
              <span class="lcs-label">爬坡时间</span>
              <span class="lcs-value">{{ selectedReport.summary.config.ramp_up }} s</span>
            </div>
            <div class="lcs-item">
              <span class="lcs-label">实际耗时</span>
              <span class="lcs-value">{{ selectedReport.summary.duration_secs }} s</span>
            </div>
          </div>

          <div class="report-section-title" style="margin-top:16px">压测结果</div>
        </template>

        <!-- 基础统计 -->
        <el-descriptions :column="3" border size="small" style="margin-bottom:16px">
          <el-descriptions-item label="类型">
            <el-tag :type="selectedReport.report_type === 'unit' ? 'primary' : 'warning'" size="small">
              {{ selectedReport.report_type === 'unit' ? '接口单测' : '压力测试' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="时间">{{ formatTime(selectedReport.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="通过率">
            <span :style="passRateColor(selectedReport)">{{ passRate(selectedReport) }}%</span>
          </el-descriptions-item>
          <el-descriptions-item label="总数">{{ selectedReport.total }}</el-descriptions-item>
          <el-descriptions-item label="通过"><span style="color:#67c23a">{{ selectedReport.passed }}</span></el-descriptions-item>
          <el-descriptions-item label="失败">
            <span :style="selectedReport.failed > 0 ? 'color:#f56c6c' : ''">{{ selectedReport.failed }}</span>
          </el-descriptions-item>
          <template v-if="selectedReport.report_type === 'load' && selectedReport.summary">
            <el-descriptions-item label="总请求数">{{ selectedReport.summary.total_requests }}</el-descriptions-item>
            <el-descriptions-item label="成功率">{{ selectedReport.summary.success_rate }}%</el-descriptions-item>
            <el-descriptions-item label="平均TPS">{{ selectedReport.summary.avg_tps }}</el-descriptions-item>
            <el-descriptions-item label="平均耗时">{{ selectedReport.summary.avg_ms }} ms</el-descriptions-item>
            <el-descriptions-item label="P50">{{ selectedReport.summary.p50_ms }} ms</el-descriptions-item>
            <el-descriptions-item label="P95">{{ selectedReport.summary.p95_ms }} ms</el-descriptions-item>
            <el-descriptions-item label="P99">{{ selectedReport.summary.p99_ms }} ms</el-descriptions-item>
            <el-descriptions-item label="最大耗时">{{ selectedReport.summary.max_ms }} ms</el-descriptions-item>
          </template>
        </el-descriptions>

        <!-- 单测用例明细 (可展开错误详情) -->
        <template v-if="selectedReport.report_type === 'unit' && selectedReport.details?.length">
          <div style="font-weight:600;margin-bottom:8px;font-size:13px">用例执行明细</div>
          <el-table :data="selectedReport.details" size="small" max-height="320" stripe row-key="case_id">
            <el-table-column type="expand">
              <template #default="{ row }">
                <div style="padding:10px 24px;font-size:12px">
                  <div style="margin-bottom:6px"><strong>请求URL：</strong><code>{{ row.url }}</code></div>
                  <div v-if="row.assertions?.length" style="margin-bottom:8px">
                    <div style="font-weight:500;font-size:12px;color:#555;margin-bottom:5px">断言结果</div>
                    <div class="assertion-list">
                      <div v-for="(a, i) in row.assertions" :key="i"
                           class="assertion-row" :class="a.passed ? 'ar-pass' : 'ar-fail'">
                        <div class="ar-main">
                          <!-- 状态图标 -->
                          <span class="ar-icon">{{ a.passed ? '✓' : '✗' }}</span>
                          <!-- 断言类型描述 -->
                          <span class="ar-desc">
                            <template v-if="a.type === 'status_code'">状态码</template>
                            <template v-else-if="a.type === 'json_path'">
                              <span style="color:#888;font-size:11px">JSON Path</span>
                              <el-tooltip :content="a.path" placement="top" :show-after="300" :disabled="!a.path || a.path.length < 28">
                                <code class="ar-path">{{ a.path }}</code>
                              </el-tooltip>
                              <span class="ar-op">{{ matchTypeLabel(a.match_type || 'equals') }}</span>
                            </template>
                            <template v-else-if="a.type === 'response_time'">响应时间</template>
                            <template v-else>{{ a.type }}</template>
                          </span>
                          <!-- 期望值 -->
                          <span v-if="a.type === 'response_time'" class="ar-kv">
                            <span class="ar-kv-label">限制</span><code>≤ {{ a.max_ms }}ms</code>
                          </span>
                          <span v-else-if="!['exists','not_exists','not_empty'].includes(a.match_type) && a.expected !== undefined && a.expected !== null" class="ar-kv">
                            <span class="ar-kv-label">期望</span><code>{{ a.expected }}</code>
                          </span>
                          <!-- 箭头 + 实际值 -->
                          <template v-if="a.type === 'response_time'">
                            <span class="ar-arrow">→</span>
                            <span class="ar-kv" :class="a.passed ? 'ar-actual-pass' : 'ar-actual-fail'">
                              <code>{{ a.actual_ms }}ms</code>
                            </span>
                          </template>
                          <template v-else-if="a.actual !== undefined && a.actual !== null">
                            <span class="ar-arrow">→</span>
                            <span class="ar-kv" :class="a.passed ? 'ar-actual-pass' : 'ar-actual-fail'">
                              <span class="ar-kv-label">实际</span><code>{{ a.actual }}</code>
                            </span>
                          </template>
                        </div>
                        <!-- 错误详情（第二行） -->
                        <div v-if="a.error" class="ar-error">{{ a.error }}</div>
                      </div>
                    </div>
                  </div>
                  <div v-if="row.error && row.status === 'failed'" style="margin-bottom:6px;color:#f56c6c">
                    <strong>错误：</strong>{{ row.error }}
                  </div>
                  <div v-if="row.extracted_vars && Object.keys(row.extracted_vars).length"
                    style="margin-bottom:6px;background:#f0f9eb;border:1px solid #b7eb8f;border-radius:4px;padding:5px 8px">
                    <div style="font-size:11px;color:#52c41a;font-weight:600;margin-bottom:3px">变量已提取</div>
                    <div v-for="(val, name) in row.extracted_vars" :key="name"
                      style="font-family:monospace;font-size:11px;color:#389e0d">
                      {{ varRef(name) }} = {{ String(val) }}
                    </div>
                  </div>
                  <div v-if="row.response_preview" style="margin-top:8px">
                    <div style="display:flex;align-items:center;gap:6px;margin-bottom:5px">
                      <strong style="font-size:12px;color:#555">响应内容</strong>
                      <span v-if="isJsonResponse(row.response_preview)"
                        style="background:#e6f4ff;color:#1677ff;border-radius:3px;padding:0 5px;font-size:11px;line-height:18px">JSON</span>
                      <span v-else style="background:#f0f0f0;color:#888;border-radius:3px;padding:0 5px;font-size:11px;line-height:18px">Text</span>
                      <el-button size="small" text style="margin-left:auto;height:18px;font-size:11px;color:#999;padding:0"
                        @click="copyResponseText(row.response_preview)">复制</el-button>
                    </div>
                    <pre class="response-preview-code" v-html="formatResponsePreview(row.response_preview)"></pre>
                  </div>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="method" label="方法" width="72">
              <template #default="{ row }">
                <el-tag :type="methodColor(row.method)" size="small">{{ row.method }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="case_name" label="用例" min-width="180" show-overflow-tooltip />
            <el-table-column prop="status_code" label="状态码" width="80" />
            <el-table-column prop="duration_ms" label="耗时(ms)" width="90" />
            <el-table-column prop="status" label="结果" width="80">
              <template #default="{ row }">
                <el-tag :type="row.status === 'passed' ? 'success' : 'danger'" size="small">
                  {{ row.status === 'passed' ? '通过' : '失败' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="error" label="失败原因" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                <span :style="row.error ? 'color:#f56c6c' : 'color:#aaa'">{{ row.error || '—' }}</span>
              </template>
            </el-table-column>
          </el-table>
        </template>

        <!-- AI 分析区 -->
        <div style="margin-top:16px;border-top:1px solid #eee;padding-top:14px">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
            <span style="font-weight:600;font-size:13px">AI 智能分析</span>
            <el-button
              type="primary" size="small" :icon="MagicStick"
              @click="runAnalysis" :loading="analysisLoading"
            >{{ analysisResult ? '重新分析' : '开始分析' }}</el-button>
          </div>
          <div v-if="analysisLoading" style="color:#999;font-size:13px;padding:16px;text-align:center;background:#f8fafc;border-radius:8px;border:1px solid #e8edf2">
            <el-icon class="is-loading" style="margin-right:6px"><Loading /></el-icon> AI 分析中，请稍候...
          </div>
          <div v-else-if="analysisResult" class="analysis-result">
            <div class="analysis-markdown" v-html="analysisHtml"></div>
          </div>
        </div>
      </template>
      <template #footer>
        <el-button @click="reportDetailVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 新建/编辑用例 Dialog -->
    <el-dialog v-model="caseDialogVisible" :title="editingCase ? '编辑用例' : '新建用例'" width="640px">
      <el-form :model="caseForm" label-width="90px" size="small">
        <el-form-item label="用例名称" required>
          <el-input v-model="caseForm.name" />
        </el-form-item>
        <el-form-item label="接口描述">
          <el-input v-model="caseForm.description" placeholder="描述该接口的用途（同路径用例共享）" />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="HTTP方法">
              <el-select v-model="caseForm.method" style="width:100%">
                <el-option v-for="m in ['GET','POST','PUT','DELETE','PATCH']" :key="m" :label="m" :value="m" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="16">
            <el-form-item label="路径">
              <el-input v-model="caseForm.path" placeholder="/users/{id}" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="模块">
              <el-input v-model="caseForm.module" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="优先级">
              <el-select v-model="caseForm.priority" style="width:100%">
                <el-option label="P0" value="P0" /><el-option label="P1" value="P1" /><el-option label="P2" value="P2" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="Headers">
          <div style="width:100%">
            <div v-for="(row, i) in caseForm.headersRows" :key="i"
              style="display:flex;gap:6px;margin-bottom:6px;align-items:center">
              <el-input v-model="row.key" placeholder="Header名 (如 Content-Type)" style="flex:1.2" size="small" />
              <el-input v-model="row.value" placeholder="值" style="flex:2" size="small" />
              <el-dropdown v-if="builtinFnList.length" trigger="click" @command="(cmd) => insertFn(row, cmd)">
                <el-button size="small" text style="font-family:monospace;color:#909399;padding:0 4px;min-width:20px">ƒ</el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item v-for="fn in builtinFnList" :key="fn.value" :command="fn.value">
                      <span style="font-family:monospace;font-size:12px">{{ fn.value }}</span>
                      <span style="color:#aaa;font-size:11px;margin-left:8px">{{ fn.desc }}</span>
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
              <el-button size="small" text type="danger" @click="removeHeadersRow(i)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
            <el-button size="small" :icon="Plus" @click="addHeadersRow">添加 Header</el-button>
          </div>
        </el-form-item>
        <el-form-item label="Query Params">
          <div style="width:100%">
            <div v-for="(row, i) in caseForm.paramsRows" :key="i"
              style="display:flex;gap:6px;margin-bottom:6px;align-items:center">
              <el-input v-model="row.key" placeholder="参数名" style="flex:1" size="small" />
              <el-input v-model="row.value" placeholder="参数值" style="flex:2" size="small" />
              <el-dropdown v-if="builtinFnList.length" trigger="click" @command="(cmd) => insertFn(row, cmd)">
                <el-button size="small" text style="font-family:monospace;color:#909399;padding:0 4px;min-width:20px">ƒ</el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item v-for="fn in builtinFnList" :key="fn.value" :command="fn.value">
                      <span style="font-family:monospace;font-size:12px">{{ fn.value }}</span>
                      <span style="color:#aaa;font-size:11px;margin-left:8px">{{ fn.desc }}</span>
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
              <el-button size="small" text type="danger" @click="removeParamsRow(i)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
            <el-button size="small" :icon="Plus" @click="addParamsRow">添加参数</el-button>
          </div>
        </el-form-item>
        <el-form-item label="请求体">
          <div style="width:100%">
            <el-radio-group v-model="caseForm.bodyType" size="small" style="margin-bottom:8px"
              @change="onBodyTypeChange">
              <el-radio-button value="none">无</el-radio-button>
              <el-radio-button value="json">JSON</el-radio-button>
              <el-radio-button value="form">Form 表单</el-radio-button>
              <el-radio-button value="raw">原始文本</el-radio-button>
            </el-radio-group>

            <!-- JSON -->
            <div v-if="caseForm.bodyType === 'json'">
              <div v-if="builtinFnList.length" style="margin-bottom:4px;display:flex;align-items:center;gap:6px">
                <span style="font-size:12px;color:#909399">插入函数：</span>
                <el-dropdown trigger="click" @command="insertBodyFn">
                  <el-button size="small" style="font-family:monospace;font-size:12px">ƒ(x)</el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item v-for="fn in builtinFnList" :key="fn.value" :command="fn.value">
                        <span style="font-family:monospace;font-size:12px">{{ fn.value }}</span>
                        <span style="color:#aaa;font-size:11px;margin-left:8px">{{ fn.desc }}</span>
                      </el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
              <el-input v-model="caseForm.bodyStr" type="textarea" :rows="5"
                placeholder='{"key": "value"}' style="font-family:monospace" />
            </div>

            <!-- Form 表单 key-value 编辑器 -->
            <div v-else-if="caseForm.bodyType === 'form'">
              <div v-for="(row, i) in caseForm.formRows" :key="i"
                style="display:flex;gap:6px;margin-bottom:6px;align-items:center">
                <el-input v-model="row.key" placeholder="参数名" style="flex:1" size="small" />
                <el-input v-model="row.value" placeholder="参数值" style="flex:2" size="small" />
                <el-dropdown v-if="builtinFnList.length" trigger="click" @command="(cmd) => insertFn(row, cmd)">
                  <el-button size="small" text style="font-family:monospace;color:#909399;padding:0 4px;min-width:20px">ƒ</el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item v-for="fn in builtinFnList" :key="fn.value" :command="fn.value">
                        <span style="font-family:monospace;font-size:12px">{{ fn.value }}</span>
                        <span style="color:#aaa;font-size:11px;margin-left:8px">{{ fn.desc }}</span>
                      </el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
                <el-button size="small" text type="danger" @click="removeFormRow(i)">
                  <el-icon><Delete /></el-icon>
                </el-button>
              </div>
              <el-button size="small" :icon="Plus" @click="addFormRow">添加参数</el-button>
            </div>

            <!-- 原始文本 -->
            <el-input v-else-if="caseForm.bodyType === 'raw'"
              v-model="caseForm.bodyRaw" type="textarea" :rows="5"
              placeholder="请输入原始请求体内容..." style="font-family:monospace" />
          </div>
        </el-form-item>
        <el-form-item label="断言规则">
          <div style="width:100%">
            <div v-for="(row, i) in caseForm.assertionRows" :key="i"
              style="margin-bottom:8px;background:#fafafa;padding:8px 10px;border-radius:6px;border:1px solid #eee">
              <!-- 第一行：类型 + 操作 -->
              <div style="display:flex;gap:6px;align-items:center;margin-bottom:6px">
                <el-select v-model="row.type" size="small" style="width:120px;flex-shrink:0" @change="onAssertionTypeChange(row)">
                  <el-option label="状态码" value="status_code" />
                  <el-option label="JSON Path" value="json_path" />
                  <el-option label="响应时间" value="response_time" />
                </el-select>
                <!-- 状态码断言（单行足够） -->
                <template v-if="row.type === 'status_code'">
                  <span style="font-size:12px;color:#909399;flex-shrink:0">期望状态码</span>
                  <el-input-number v-model="row.expected" :min="100" :max="599" size="small" style="width:110px" controls-position="right" />
                </template>
                <!-- 响应时间断言（单行足够） -->
                <template v-else-if="row.type === 'response_time'">
                  <span style="font-size:12px;color:#909399;flex-shrink:0">最大响应时间</span>
                  <el-input-number v-model="row.max_ms" :min="100" :max="60000" :step="500" size="small" style="width:140px" controls-position="right" />
                  <span style="font-size:12px;color:#909399;flex-shrink:0">ms</span>
                </template>
                <el-button size="small" text type="danger" @click="removeAssertionRow(i)" style="margin-left:auto;flex-shrink:0">
                  <el-icon><Delete /></el-icon>
                </el-button>
              </div>
              <!-- JSON Path 断言：path 独占第二行，匹配方式+期望值第三行 -->
              <template v-if="row.type === 'json_path'">
                <el-input v-model="row.path" placeholder="$.data.id  或  $.status.code" size="small"
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
                    <el-option label="string（字符串）" value="string" />
                    <el-option label="number（数字）" value="number" />
                    <el-option label="boolean（布尔）" value="boolean" />
                    <el-option label="array（数组）" value="array" />
                    <el-option label="object（对象）" value="object" />
                    <el-option label="null（空）" value="null" />
                  </el-select>
                  <el-input v-else-if="!['exists','not_exists','not_empty'].includes(row.match_type)"
                    v-model="row.expected"
                    :placeholder="row.match_type === 'regex' ? '正则，如 ^\\d+$' : row.match_type === 'contains' ? '包含的内容' : '期望值'"
                    size="small" style="flex:1;min-width:0" />
                  <span v-else style="font-size:12px;color:#c0c4cc;flex:1">（无需期望值）</span>
                </div>
              </template>
            </div>
            <el-button size="small" :icon="Plus" @click="addAssertionRow">添加断言</el-button>
          </div>
        </el-form-item>
        <el-form-item label="变量提取">
          <div style="width:100%">
            <div style="font-size:12px;color:#909399;margin-bottom:6px">
              执行后从响应中提取值存入变量。
              <code style="background:#f5f5f5;padding:1px 4px;border-radius:3px">local</code> — 当前执行链可用 <code style="background:#f5f5f5;padding:1px 4px;border-radius:3px">&#123;&#123;var:名&#125;&#125;</code>；
              <code style="background:#f5f5f5;padding:1px 4px;border-radius:3px">global</code> — 跨项目可用 <code style="background:#f5f5f5;padding:1px 4px;border-radius:3px">&#123;&#123;gvar:名&#125;&#125;</code>
            </div>
            <div v-for="(row, i) in caseForm.varExtractsRows" :key="i"
              style="display:flex;gap:6px;margin-bottom:6px;align-items:center">
              <el-input v-model="row.name" placeholder="变量名 (如 token)" style="flex:1" size="small">
                <template #prepend>变量</template>
              </el-input>
              <el-input v-model="row.path" placeholder="$.data.token" style="flex:2" size="small">
                <template #prepend>Path</template>
              </el-input>
              <el-select v-model="row.scope" size="small" style="width:90px" placeholder="范围">
                <el-option label="local" value="local" />
                <el-option label="global" value="global" />
              </el-select>
              <el-button size="small" text type="danger" @click="removeVarExtractRow(i)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
            <el-button size="small" :icon="Plus" @click="addVarExtractRow">添加提取规则</el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="caseDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveCase">保存</el-button>
      </template>
    </el-dialog>

    <!-- 全局变量池管理 Dialog -->
    <el-dialog v-model="gvarDialogVisible" title="全局变量池" width="700px" destroy-on-close>
      <div style="margin-bottom:12px;display:flex;justify-content:space-between;align-items:center">
        <span style="font-size:13px;color:#909399">
          在任意项目的参数 / Header / Body 中用 <code style="background:#f5f5f5;padding:1px 6px;border-radius:3px">&#123;&#123;gvar:变量名&#125;&#125;</code> 引用
        </span>
        <el-button type="primary" size="small" :icon="Plus" @click="showAddGvar">新增变量</el-button>
      </div>

      <el-table :data="gvars" size="small" stripe empty-text="暂无全局变量">
        <el-table-column prop="name" label="变量名" width="140" />
        <el-table-column label="值" min-width="200">
          <template #default="{ row }">
            <el-input v-if="row._editing" v-model="row._editVal" size="small"
              @blur="saveGvarInline(row)" @keyup.enter="saveGvarInline(row)" />
            <span v-else @click="startEditGvar(row)" style="cursor:pointer;font-family:monospace;font-size:12px">
              {{ row.value.length > 60 ? row.value.slice(0, 60) + '…' : row.value || '—' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" width="140" show-overflow-tooltip />
        <el-table-column prop="source_project" label="来源" width="120" show-overflow-tooltip />
        <el-table-column prop="updated_at" label="更新时间" width="100">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="70" align="center">
          <template #default="{ row }">
            <el-button size="small" text type="danger" @click="deleteGvar(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 新增变量表单 -->
      <el-form v-if="gvarForm.visible" :model="gvarForm" label-width="72px"
        style="margin-top:16px;padding:12px;background:#f9f9f9;border-radius:6px">
        <el-form-item label="变量名">
          <el-input v-model="gvarForm.name" placeholder="如 token、user_id" />
        </el-form-item>
        <el-form-item label="初始值">
          <el-input v-model="gvarForm.value" placeholder="可留空，由用例执行时自动填入" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="gvarForm.description" placeholder="简要说明用途" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="createGvar">确认创建</el-button>
          <el-button @click="gvarForm.visible = false">取消</el-button>
        </el-form-item>
      </el-form>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Edit, Delete, MagicStick, VideoPlay, Refresh, Loading, View, Histogram } from '@element-plus/icons-vue'
import { apiTestApi, scriptApi, gvarApi } from '../api'
import { marked } from 'marked'

// ── 项目 ──
const projects = ref([])
const currentProject = ref(null)
const projectDialogVisible = ref(false)
const editingProject = ref(null)
const savingProject = ref(false)
const allCasesGrouped = ref([])   // 所有项目用例，供前置用例选择器使用
const projectForm = reactive({
  name: '', base_url: '', description: '',
  auth_type: 'none',
  auth_config: { token: '', key: 'X-API-Key', value: '', username: '', password: '' },
  setup_cases: [],           // [{project_id, case_id, label, key}]
  auth_error_patterns: [],   // [{field, value}]
  proxy_url: '',             // HTTP/HTTPS/SOCKS5 代理，留空直连
  hosts_map: '',             // hosts 映射，格式同 /etc/hosts
})

const loadAllCasesForSetup = async (visible) => {
  if (!visible || allCasesGrouped.value.length) return
  allCasesGrouped.value = await apiTestApi.listAllCasesGrouped()
}

// ── 用例 ──
const cases = ref([])

// 请求体预览：raw 类型识别占位符函数调用，展示为可读标签；JSON 格式化
const formatBodyPreview = (c) => {
  if (c.body_type === 'raw' && c.body_raw) {
    const raw = c.body_raw
    // 整体就是一个占位符 {{fn(args)}}，显示为"[函数: fn(args)]"
    const m = raw.match(/^\{\{(\w+)\(([^{}]*)\)\}\}$/)
    if (m) return `[自定义函数: ${m[1]}(${m[2]})]`
    // 含占位符但有其他内容，截断显示前 120 字
    if (raw.includes('{{')) return raw.length > 120 ? raw.slice(0, 120) + '…' : raw
    // 纯文本，直接显示
    return raw.length > 200 ? raw.slice(0, 200) + '…' : raw
  }
  if (c.body) {
    try { return JSON.stringify(c.body, null, 2) } catch { return String(c.body) }
  }
  return ''
}

const casesGrouped = computed(() => {
  const groups = new Map()
  for (const c of cases.value) {
    const key = c.path || '/'
    if (!groups.has(key)) {
      groups.set(key, { id: `__g__${key}`, path: key, _isGroup: true, _count: 0, description: c.description || '', children: [] })
    }
    const g = groups.get(key)
    g.children.push(c)
    g._count++
  }
  return [...groups.values()]
})
const selectedCases = ref([])
const caseDialogVisible = ref(false)
const editingCase = ref(null)
const refreshing = ref(false)
const caseForm = reactive({
  name: '', module: '通用', method: 'GET', path: '/', priority: 'P1', description: '',
  headersRows: [{ key: '', value: '' }],
  paramsRows: [{ key: '', value: '' }],
  bodyType: 'json', bodyStr: '', bodyRaw: '',
  formRows: [{ key: '', value: '' }],
  assertionRows: [{ type: 'status_code', expected: 200, path: '', match_type: 'equals', max_ms: 3000 }],
  varExtractsRows: [],
})

// ── AI 生成 ──
const genDialogVisible = ref(false)
const genTab = ref('swagger')
const genSwagger = ref('')
const genDescription = ref('')
const generating = ref(false)
const genProgress = ref(0)
const genStage = ref('')
const genStepDefs = [
  { label: '分析文档', start: 0,  end: 10  },
  { label: '识别接口', start: 10, end: 25  },
  { label: '探测接口', start: 25, end: 40  },
  { label: '生成用例', start: 40, end: 85  },
  { label: '校验断言', start: 85, end: 92  },
  { label: '补全描述', start: 92, end: 99  },
  { label: '完成',     start: 99, end: 100 },
]

// ── 单测执行 ──
const executing = ref(false)
const execProgress = ref(0)
const execStage = ref('')
const lastExecStatus = ref('')
const execResults = ref([])
const execSummary = reactive({ passed: 0, failed: 0, pass_rate: 0 })

// ── 压测 ──
const activeTab = ref('cases-mgmt')
const loadRunning = ref(false)
const loadReport = ref(null)
const loadConfig = reactive({ concurrent_users: 10, duration: 60, ramp_up: 10 })
const chartRef = ref(null)
const unitTableRef = ref(null)
const loadTableRef = ref(null)
const caseTableRef = ref(null)

const toggleGroupCases = (groupRow, tableRef, selectedRef) => {
  const allSelected = groupRow.children.every(c => selectedRef.value.some(s => s.id === c.id))
  groupRow.children.forEach(c => tableRef.value?.toggleRowSelection(c, !allSelected))
}

const handleGroupSelect = (selection, row, tableRef) => {
  if (!row._isGroup) return
  const isSelected = selection.some(r => r.id === row.id)
  row.children?.forEach(child => tableRef.value?.toggleRowSelection(child, isSelected))
}

const handleRowClick = (row, col, event, tableRef) => {
  if (!row._isGroup) return
  if (event.target.closest('.el-checkbox, input, button, .el-switch, .el-button, .el-table__expand-icon, .el-input')) return
  tableRef.value?.toggleRowExpansion(row)
}

const saveGroupDescription = async (groupRow) => {
  const desc = groupRow.description || ''
  try {
    await Promise.all(groupRow.children.map(c => apiTestApi.updateCase(c.id, { description: desc })))
    groupRow.children.forEach(c => { c.description = desc })
    ElMessage.success('描述已保存')
  } catch {
    ElMessage.error('保存描述失败')
  }
}
let chart = null
const chartData = reactive({ elapsed: [], tps: [], avg_ms: [], p95_ms: [], error_rate: [] })

const currentTPS = computed(() => chartData.tps.length ? Number(chartData.tps[chartData.tps.length - 1]).toFixed(1) : '—')
const currentAvgMs = computed(() => chartData.avg_ms.length ? chartData.avg_ms[chartData.avg_ms.length - 1] : '—')
const currentErrRate = computed(() => chartData.error_rate.length ? Number(chartData.error_rate[chartData.error_rate.length - 1]).toFixed(1) : '—')

// 单测 / 压测各自独立的接口选择
const selectedUnitCases = ref([])
const selectedLoadCases = ref([])

// ── 测试报告 ──
const reports = ref([])
const reportsLoading = ref(false)
const reportDetailVisible = ref(false)
const selectedReport = ref(null)
const selectedReports = ref([])
const analysisLoading = ref(false)
const analysisResult = ref('')
const analysisHtml = computed(() => analysisResult.value ? marked.parse(analysisResult.value) : '')

// ── WebSocket ──
let ws = null
const connectWs = (clientId) => {
  disconnectWs()
  ws = new WebSocket(`ws://${window.location.hostname}:8000/ws?client_id=${clientId}`)
  ws.onmessage = (e) => {
    try { handleWsMsg(JSON.parse(e.data)) } catch {}
  }
}
const disconnectWs = () => { ws?.close(); ws = null }

const handleWsMsg = (data) => {
  if (data.type === 'api_gen_progress') {
    genProgress.value = data.percent || 0
    genStage.value = data.stage || ''
  } else if (data.type === 'api_gen_done') {
    generating.value = false
    genProgress.value = 100
    genStage.value = `生成完成，共 ${data.count} 条用例`
    genDialogVisible.value = false
    loadCases()
    disconnectWs()
  } else if (data.type === 'api_gen_error') {
    generating.value = false
    ElMessage.error('生成失败：' + data.message)
    disconnectWs()
  } else if (data.type === 'api_exec_progress') {
    execProgress.value = data.progress || 0
    execStage.value = `${data.current}/${data.total} ${data.case_name}`
    lastExecStatus.value = data.status
  } else if (data.type === 'setup') {
    // 前置用例进度
    execStage.value = `[前置] ${data.label} ${data.status === 'running' ? '执行中...' : data.status === 'passed' ? '✓' : '✗'}`
  } else if (data.type === 'retry') {
    // 鉴权失败自动重试提示
    execStage.value = `[重试] ${data.case_name}：${data.reason}`
  } else if (data.type === 'api_exec_done') {
    executing.value = false
    execProgress.value = 100
    execResults.value = data.results || []
    execSummary.passed = data.passed || 0
    execSummary.failed = data.failed || 0
    execSummary.pass_rate = data.pass_rate || 0
    disconnectWs()
    loadReports()
  } else if (data.type === 'load_metrics') {
    appendChartPoint(data)
  } else if (data.type === 'load_done') {
    loadRunning.value = false
    loadReport.value = data
    disconnectWs()
    loadReports()
  }
}

// ── 项目操作 ──
const loadProjects = async () => {
  projects.value = await apiTestApi.listProjects()
}

const selectProject = async (p) => {
  currentProject.value = p
  await loadCases()
  loadReport.value = null
  execResults.value = []
  genProgress.value = 0
  execProgress.value = 0
  reports.value = []
  selectedUnitCases.value = []
  selectedLoadCases.value = []
  if (activeTab.value === 'reports') loadReports()
}

const showProjectDialog = (p) => {
  editingProject.value = p
  allCasesGrouped.value = []   // 每次打开时重新加载
  if (p) {
    // 回填 setup_cases，补上 key 字段供 el-select value-key 使用
    const setupCases = (p.setup_cases || []).map(sc => ({
      ...sc, key: `${sc.project_id}_${sc.case_id}`,
    }))
    Object.assign(projectForm, {
      name: p.name, base_url: p.base_url, description: p.description || '',
      auth_type: p.auth_type || 'none',
      auth_config: { token: '', key: 'X-API-Key', value: '', username: '', password: '', ...(p.auth_config || {}) },
      setup_cases: setupCases,
      auth_error_patterns: (p.auth_error_patterns || []).map(r => ({ ...r })),
      proxy_url: p.proxy_url || '',
      hosts_map: p.hosts_map || '',
    })
  } else {
    Object.assign(projectForm, {
      name: '', base_url: '', description: '', auth_type: 'none',
      auth_config: { token: '', key: 'X-API-Key', value: '', username: '', password: '' },
      setup_cases: [],
      auth_error_patterns: [],
      proxy_url: '',
      hosts_map: '',
    })
  }
  projectDialogVisible.value = true
}

const saveProject = async () => {
  if (!projectForm.name || !projectForm.base_url) return ElMessage.warning('名称和Base URL必填')
  savingProject.value = true
  try {
    const payload = {
      name: projectForm.name, base_url: projectForm.base_url,
      description: projectForm.description, auth_type: projectForm.auth_type,
      auth_config: { ...projectForm.auth_config },
      setup_cases: projectForm.setup_cases.map(sc => ({
        project_id: sc.project_id, case_id: sc.case_id, label: sc.label,
      })),
      auth_error_patterns: projectForm.auth_error_patterns.filter(r => r.field && r.value),
      proxy_url: projectForm.proxy_url || '',
      hosts_map: projectForm.hosts_map || '',
    }
    if (editingProject.value) {
      const updated = await apiTestApi.updateProject(editingProject.value.id, payload)
      const idx = projects.value.findIndex(p => p.id === updated.id)
      if (idx !== -1) projects.value[idx] = updated
      if (currentProject.value?.id === updated.id) currentProject.value = updated
      ElMessage.success('项目已更新')
    } else {
      const created = await apiTestApi.createProject(payload)
      projects.value.unshift(created)
      ElMessage.success('项目创建成功')
    }
    projectDialogVisible.value = false
  } catch (e) {
    const msg = e?.response?.data?.detail || e?.message || '保存失败'
    ElMessage.error('保存失败：' + msg)
  } finally {
    savingProject.value = false
  }
}

const deleteProject = async (p) => {
  await ElMessageBox.confirm(`确认删除项目「${p.name}」及其所有用例？`, '警告', { type: 'warning' })
  try {
    await apiTestApi.deleteProject(p.id)
    projects.value = projects.value.filter(x => x.id !== p.id)
    if (currentProject.value?.id === p.id) currentProject.value = null
    ElMessage.success('已删除')
  } catch (e) {
    ElMessage.error('删除失败：' + (e?.response?.data?.detail || e?.message || ''))
  }
}

// ── 用例操作 ──
const loadCases = async () => {
  if (!currentProject.value) return
  refreshing.value = true
  try {
    cases.value = await apiTestApi.listCases(currentProject.value.id)
  } finally {
    refreshing.value = false
  }
}

const toAssertionRows = (assertions) => {
  if (!assertions || !assertions.length) return [{ type: 'status_code', expected: 200, path: '', match_type: 'equals', max_ms: 3000 }]
  return assertions.map(a => ({
    type: a.type || 'status_code',
    expected: a.type === 'status_code' ? (Number(a.expected) || 200) : (a.expected !== undefined && a.expected !== null ? String(a.expected) : ''),
    path: a.path || '',
    match_type: a.match_type || 'equals',
    max_ms: a.max_ms || 3000,
  }))
}

const showCaseDialog = (c) => {
  editingCase.value = c
  if (c) {
    const bt = c.body_type || 'json'
    const formRows = (bt === 'form' && c.body && typeof c.body === 'object')
      ? Object.entries(c.body).map(([key, value]) => ({ key, value: String(value) }))
      : [{ key: '', value: '' }]
    const paramsRows = (c.params && typeof c.params === 'object' && Object.keys(c.params).length)
      ? Object.entries(c.params).map(([key, value]) => ({ key, value: String(value) }))
      : [{ key: '', value: '' }]
    const headersRows = (c.headers && typeof c.headers === 'object' && Object.keys(c.headers).length)
      ? Object.entries(c.headers).map(([key, value]) => ({ key, value: String(value) }))
      : [{ key: '', value: '' }]
    Object.assign(caseForm, {
      name: c.name, module: c.module, method: c.method, path: c.path, priority: c.priority,
      description: c.description || '',
      headersRows,
      paramsRows,
      bodyType: bt,
      bodyStr: (bt === 'json' && c.body) ? JSON.stringify(c.body, null, 2) : '',
      bodyRaw: c.body_raw || '',
      formRows,
      assertionRows: toAssertionRows(c.assertions),
      varExtractsRows: (c.var_extracts || []).map(ve => ({ name: ve.name || '', path: ve.path || '', scope: ve.scope || 'local' })),
      _prevBodyType: bt,
    })
    // 初始化草稿，保证任意类型切换后可恢复
    _bodyDraft.json = (bt === 'json' && c.body) ? JSON.stringify(c.body, null, 2) : ''
    _bodyDraft.raw  = c.body_raw || ''
    _bodyDraft.form = formRows.map(r => ({ ...r }))
  } else {
    Object.assign(caseForm, {
      name: '', module: '通用', method: 'GET', path: '/', priority: 'P1', description: '',
      headersRows: [{ key: '', value: '' }],
      paramsRows: [{ key: '', value: '' }],
      bodyType: 'json', bodyStr: '', bodyRaw: '',
      formRows: [{ key: '', value: '' }],
      assertionRows: [{ type: 'status_code', expected: 200, path: '', match_type: 'equals', max_ms: 3000 }],
      varExtractsRows: [],
      _prevBodyType: 'json',
    })
    _bodyDraft.json = ''; _bodyDraft.raw = ''; _bodyDraft.form = []
  }
  caseDialogVisible.value = true
  loadBuiltinFns()
}

// 每种 body 类型独立保存草稿，切换时不丢数据
const _bodyDraft = { json: '', raw: '', form: [] }

const onBodyTypeChange = (newType) => {
  // 切换前先把当前值存入草稿
  const prev = caseForm._prevBodyType || 'none'
  if (prev === 'json') _bodyDraft.json = caseForm.bodyStr
  else if (prev === 'raw') _bodyDraft.raw = caseForm.bodyRaw
  else if (prev === 'form') _bodyDraft.form = caseForm.formRows.map(r => ({ ...r }))

  // 切换后从草稿恢复
  if (newType === 'json') caseForm.bodyStr = _bodyDraft.json
  else if (newType === 'raw') caseForm.bodyRaw = _bodyDraft.raw
  else if (newType === 'form') caseForm.formRows = _bodyDraft.form.length ? _bodyDraft.form : [{ key: '', value: '' }]

  caseForm._prevBodyType = newType
}

const addFormRow = () => caseForm.formRows.push({ key: '', value: '' })
const removeFormRow = (i) => caseForm.formRows.splice(i, 1)
const addParamsRow = () => caseForm.paramsRows.push({ key: '', value: '' })
const removeParamsRow = (i) => caseForm.paramsRows.splice(i, 1)
const addHeadersRow = () => caseForm.headersRows.push({ key: '', value: '' })
const removeHeadersRow = (i) => caseForm.headersRows.splice(i, 1)
const addAssertionRow = () => caseForm.assertionRows.push({ type: 'status_code', expected: 200, path: '', match_type: 'equals', max_ms: 3000 })
const removeAssertionRow = (i) => caseForm.assertionRows.splice(i, 1)
const addVarExtractRow = () => caseForm.varExtractsRows.push({ name: '', path: '', scope: 'local' })
const removeVarExtractRow = (i) => caseForm.varExtractsRows.splice(i, 1)
const varRef = (name) => `{{var:${name}}}`

// ── 全局变量池 ──
const gvarDialogVisible = ref(false)
const gvars = ref([])
const gvarForm = reactive({ visible: false, name: '', value: '', description: '' })

const showGvarDialog = async () => {
  gvarDialogVisible.value = true
  gvarForm.visible = false
  gvars.value = await gvarApi.list()
}
const showAddGvar = () => {
  Object.assign(gvarForm, { visible: true, name: '', value: '', description: '' })
}
const createGvar = async () => {
  if (!gvarForm.name.trim()) return ElMessage.warning('变量名不能为空')
  try {
    const g = await gvarApi.create({ name: gvarForm.name.trim(), value: gvarForm.value, description: gvarForm.description })
    gvars.value.push(g)
    gvarForm.visible = false
    ElMessage.success(`全局变量 ${g.name} 创建成功`)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '创建失败')
  }
}
const startEditGvar = (row) => {
  row._editing = true
  row._editVal = row.value
}
const saveGvarInline = async (row) => {
  row._editing = false
  if (row._editVal === row.value) return
  try {
    const updated = await gvarApi.update(row.id, { value: row._editVal })
    row.value = updated.value
    row.updated_at = updated.updated_at
    ElMessage.success('已更新')
  } catch (e) {
    ElMessage.error('更新失败')
  }
}
const deleteGvar = async (row) => {
  try {
    await ElMessageBox.confirm(`确定删除全局变量 "${row.name}"？`, '确认', { type: 'warning' })
    await gvarApi.delete(row.id)
    gvars.value = gvars.value.filter(g => g.id !== row.id)
    ElMessage.success('已删除')
  } catch { /* 取消 */ }
}

// ── 脚本函数管理 ──
const scriptDialogVisible = ref(false)
const scripts = ref([])
const editingScript = ref(null)
const scriptTestArgs = ref('')
const scriptTestResult = ref(null)
const scriptTesting = ref(false)
const editorWrapRef = ref(null)
const lineNumsRef = ref(null)

// 默认脚本模板
const scriptPlaceholder = `def my_func(*args):
    import time
    return str(int(time.time()))`

// 行数计算
const scriptLineCount = computed(() => {
  const code = editingScript.value?.code || ''
  return Math.max(code.split('\n').length, 10)
})

// Python 语法高亮
const scriptHighlighted = computed(() => {
  const code = editingScript.value?.code || ''
  if (!code) return ''
  // 1. 转义 HTML 特殊字符
  let s = code
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  // 2. 占位符格式：\x01p{idx}\x01
  //    "p" 是字母，让数字 \b\d+\b 不会误匹配占位符中的 idx
  const tokens = []
  const ph = (t) => { tokens.push(t); return `\x01p${tokens.length - 1}\x01` }

  // 3. 优先级从高到低，先匹配的会被"锁住"不再被后续 regex 触碰

  // 三引号字符串（多行）
  s = s.replace(/("""[\s\S]*?"""|'''[\s\S]*?''')/g, m =>
    ph(`<span class="py-str">${m}</span>`))
  // 单行字符串
  s = s.replace(/("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')/g, m =>
    ph(`<span class="py-str">${m}</span>`))
  // 注释（# 到行尾）
  s = s.replace(/(#[^\n]*)/g, m =>
    ph(`<span class="py-comment">${m}</span>`))
  // 装饰器
  s = s.replace(/(@\w+)/g, m =>
    ph(`<span class="py-decorator">${m}</span>`))
  // def 函数名（整体处理，避免 def 和函数名被拆开匹配）
  s = s.replace(/\bdef\s+(\w+)/g, (_, name) =>
    ph(`<span class="py-kw">def</span> <span class="py-fn-def">${name}</span>`))
  // 数字（放在关键字/内置函数之前，防止 None/True 里的字符被误识别）
  s = s.replace(/\b(\d+\.?\d*)\b/g, m =>
    ph(`<span class="py-num">${m}</span>`))
  // 内置函数
  s = s.replace(/\b(print|len|range|str|int|float|bool|list|dict|tuple|set|type|isinstance|hasattr|getattr|setattr|open|abs|round|min|max|sum|sorted|enumerate|zip|map|filter|any|all|repr|bytes|bytearray|input|format|hex|oct|bin|chr|ord|iter|next|reversed|vars|dir|id|hash|callable|staticmethod|classmethod|property|super|object|Exception|ValueError|TypeError|KeyError|IndexError|AttributeError|ImportError|OSError|RuntimeError|StopIteration|NotImplementedError|NameError)\b/g, m =>
    ph(`<span class="py-builtin">${m}</span>`))
  // 关键字（import/from/as 等都在这里）
  s = s.replace(/\b(return|import|from|as|if|elif|else|for|while|in|not|and|or|is|None|True|False|pass|break|continue|class|try|except|finally|raise|with|yield|lambda|global|nonlocal|del|assert|async|await)\b/g, m =>
    ph(`<span class="py-kw">${m}</span>`))

  // 4. 还原占位符
  s = s.replace(/\x01p(\d+)\x01/g, (_, i) => tokens[+i])
  return s
})

// 同步滚动
const syncEditorScroll = (e) => {
  const ta = e.target
  const pre = ta.previousElementSibling
  const lns = lineNumsRef.value
  if (pre) { pre.scrollTop = ta.scrollTop; pre.scrollLeft = ta.scrollLeft }
  if (lns) lns.scrollTop = ta.scrollTop
}

const onCodeInput = () => {
  // 触发 computed 重新计算（v-model 已更新，computed 自动响应）
}

// Tab 键插入 4 空格
const insertTab = (e) => {
  const ta = e.target
  const start = ta.selectionStart
  const end = ta.selectionEnd
  const code = editingScript.value.code
  editingScript.value.code = code.slice(0, start) + '    ' + code.slice(end)
  nextTick(() => { ta.selectionStart = ta.selectionEnd = start + 4 })
}

// ── AI 生成脚本 ──
const aiGenPanelVisible = ref(false)
const aiGenPrompt = ref('')
const aiGenerating = ref(false)

const doAiGenerate = async () => {
  if (!aiGenPrompt.value.trim() || aiGenerating.value) return
  aiGenerating.value = true
  try {
    // 默认名 my_func 不传给后端，让 AI 自行命名
    const currentName = editingScript.value?.name || ''
    const res = await scriptApi.aiGenerate({
      prompt: aiGenPrompt.value.trim(),
      func_name: currentName === 'my_func' ? '' : currentName,
    })
    if (res.ok && res.code) {
      editingScript.value.code = res.code
      // 自动填充函数名：后端解析到就覆盖（空名或默认名都替换）
      if (res.func_name) {
        editingScript.value.name = res.func_name
      }
      // 自动填充描述：仅当当前描述为空时才填充
      if (res.description && !editingScript.value.description) {
        editingScript.value.description = res.description
      }
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

// 切换脚本时关闭 AI 面板
const selectScript = (s) => {
  editingScript.value = { ...s }
  scriptTestResult.value = null
  scriptTestArgs.value = ''
  aiGenPanelVisible.value = false
  aiGenPrompt.value = ''
}

const showScriptDialog = async () => {
  scriptDialogVisible.value = true
  editingScript.value = null
  scriptTestResult.value = null
  scripts.value = await scriptApi.list(currentProject.value?.id)
}
const newScript = () => {
  editingScript.value = { id: null, name: 'my_func', description: '', code: 'def my_func(*args):\n    return "hello"', project_id: currentProject.value?.id || null }
  scriptTestResult.value = null
  scriptTestArgs.value = ''
}
const saveScript = async () => {
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
    builtinFnList.value = []   // 让 ƒ 下拉刷新
  } catch (e) { ElMessage.error('保存失败：' + (e?.message || '')) }
}
const deleteScript = async (id) => {
  try {
    await ElMessageBox.confirm('确定删除该脚本？', '确认', { type: 'warning' })
    await scriptApi.delete(id)
    scripts.value = scripts.value.filter(s => s.id !== id)
    editingScript.value = null
    ElMessage.success('已删除')
    builtinFnList.value = []
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
  } finally { scriptTesting.value = false }
}
// ── 内置函数 ──
const builtinFnList = ref([])
const loadBuiltinFns = async () => {
  if (builtinFnList.value.length) return
  try {
    const builtin = await apiTestApi.listBuiltinFunctions()
    const custom = currentProject.value
      ? await scriptApi.list(currentProject.value.id)
      : []
    const customItems = custom.map(s => ({
      value: `{{${s.name}()}}`,
      desc: s.description || '自定义脚本',
      category: '自定义',
    }))
    builtinFnList.value = [...builtin, ...customItems]
  } catch { /* 静默失败 */ }
}
const insertFn = (row, fnValue) => { row.value = (row.value || '') + fnValue }
const insertBodyFn = (fnValue) => { caseForm.bodyStr += fnValue }
const onAssertionTypeChange = (row) => {
  if (row.type === 'status_code') { row.expected = 200; row.path = ''; row.match_type = 'equals' }
  else if (row.type === 'json_path') { row.expected = ''; row.path = ''; row.match_type = 'equals' }
  else if (row.type === 'response_time') { row.max_ms = 3000; row.path = ''; row.match_type = 'equals' }
}
const onMatchTypeChange = (row) => {
  if (['exists', 'not_exists', 'not_empty'].includes(row.match_type)) {
    row.expected = ''
  } else if (row.match_type === 'type') {
    row.expected = 'string'
  } else {
    row.expected = ''
  }
}
const matchTypeLabel = (mt) => {
  const map = { equals: '等于', contains: '包含', exists: '存在', not_exists: '不存在', not_empty: '非空', type: '类型是', regex: '正则' }
  return map[mt] || mt
}

const saveCase = async () => {
  if (!caseForm.name) return ElMessage.warning('用例名称必填')
  let body = null, body_raw = ''

  if (caseForm.bodyType === 'json') {
    try { if (caseForm.bodyStr.trim()) body = JSON.parse(caseForm.bodyStr) }
    catch { return ElMessage.error('请求体 JSON 格式有误') }
  } else if (caseForm.bodyType === 'form') {
    body = {}
    for (const row of caseForm.formRows) {
      if (row.key.trim()) body[row.key.trim()] = row.value
    }
    if (!Object.keys(body).length) body = null
  } else if (caseForm.bodyType === 'raw') {
    body_raw = caseForm.bodyRaw
  }

  const params = {}
  for (const row of caseForm.paramsRows) {
    if (row.key.trim()) params[row.key.trim()] = row.value
  }

  const headers = {}
  for (const row of caseForm.headersRows) {
    if (row.key.trim()) headers[row.key.trim()] = row.value
  }

  const assertions = caseForm.assertionRows.map(r => {
    if (r.type === 'status_code') return { type: 'status_code', expected: Number(r.expected) || 200 }
    if (r.type === 'json_path') return { type: 'json_path', path: r.path, match_type: r.match_type || 'equals', expected: ['exists', 'not_exists', 'not_empty'].includes(r.match_type) ? null : r.expected }
    if (r.type === 'response_time') return { type: 'response_time', max_ms: Number(r.max_ms) || 3000 }
    return null
  }).filter(Boolean)

  const payload = {
    project_id: currentProject.value.id,
    name: caseForm.name, module: caseForm.module,
    method: caseForm.method, path: caseForm.path, priority: caseForm.priority,
    description: caseForm.description || '',
    headers: Object.keys(headers).length ? headers : null,
    params: Object.keys(params).length ? params : null,
    body_type: caseForm.bodyType, body, body_raw, assertions,
    var_extracts: caseForm.varExtractsRows.filter(r => r.name.trim() && r.path.trim())
      .map(r => ({ name: r.name.trim(), path: r.path.trim(), scope: r.scope || 'local' })),
  }
  try {
    if (editingCase.value) {
      const updated = await apiTestApi.updateCase(editingCase.value.id, payload)
      const idx = cases.value.findIndex(c => c.id === updated.id)
      if (idx !== -1) cases.value[idx] = updated
      ElMessage.success('用例已更新')
    } else {
      const created = await apiTestApi.createCase(payload)
      cases.value.push(created)
      ElMessage.success('用例创建成功')
    }
    caseDialogVisible.value = false
  } catch (e) {
    ElMessage.error('保存失败：' + (e?.response?.data?.detail || e?.message || ''))
  }
}

const toggleCase = async (c) => {
  await apiTestApi.updateCase(c.id, { enabled: c.enabled })
}

const deleteCases = async (ids) => {
  const targetIds = ids || selectedCases.value.map(c => c.id)
  if (!targetIds.length) return
  await ElMessageBox.confirm(`确认删除 ${targetIds.length} 条用例？`, '警告', { type: 'warning' })
  try {
    await apiTestApi.deleteCases(targetIds)
    cases.value = cases.value.filter(c => !targetIds.includes(c.id))
    ElMessage.success('已删除')
  } catch (e) {
    ElMessage.error('删除失败：' + (e?.response?.data?.detail || e?.message || ''))
  }
}

// ── AI 生成 ──
const showGenDialog = () => {
  genSwagger.value = ''
  genDescription.value = ''
  genDialogVisible.value = true
}

const startGenerate = async () => {
  const swagger_text = genTab.value === 'swagger' ? genSwagger.value : ''
  const description = genTab.value === 'desc' ? genDescription.value : ''
  if (!swagger_text && !description) return ElMessage.warning('请填写内容')
  generating.value = true
  genProgress.value = 0
  genStage.value = '准备生成...'
  connectWs('api_gen')
  try {
    await apiTestApi.generateCases(currentProject.value.id, { swagger_text, description })
    genDialogVisible.value = false
  } catch (e) {
    generating.value = false
    disconnectWs()
    const msg = e?.response?.data?.detail || e?.message || '启动失败'
    ElMessage.error('启动生成失败：' + msg)
  }
}

// ── 单测执行 ──
const executeSelected = async () => {
  const ids = selectedUnitCases.value.map(c => c.id)
  executing.value = true
  execProgress.value = 0
  execResults.value = []
  connectWs('api_exec')
  try {
    await apiTestApi.executeCases(currentProject.value.id, { case_ids: ids })
  } catch (e) {
    executing.value = false
    disconnectWs()
    ElMessage.error('启动执行失败：' + (e?.response?.data?.detail || e?.message || ''))
  }
}

const selectAllUnit = () => {
  unitTableRef.value?.toggleAllSelection()
}

const selectAllLoad = () => {
  loadTableRef.value?.toggleAllSelection()
}

const runCaseQuick = async (row, mode) => {
  activeTab.value = mode === 'unit' ? 'unit' : 'load'
  await nextTick()
  await nextTick()   // 等 tab 内表格渲染完毕
  if (mode === 'unit') {
    unitTableRef.value?.clearSelection()
    unitTableRef.value?.toggleRowSelection(row, true)
    ElMessage.success(`已跳转到单测执行并选中「${row.name}」`)
  } else {
    loadTableRef.value?.clearSelection()
    loadTableRef.value?.toggleRowSelection(row, true)
    ElMessage.success(`已跳转到压力测试并选中「${row.name}」`)
  }
}

// ── 压测 ──
const startLoad = async () => {
  if (!selectedLoadCases.value.length) return ElMessage.warning('请先选择要压测的接口')
  const ids = selectedLoadCases.value.map(c => c.id)
  loadRunning.value = true
  loadReport.value = null
  chartData.elapsed = []; chartData.tps = []; chartData.avg_ms = []
  chartData.p95_ms = []; chartData.error_rate = []
  initChart()
  connectWs('api_load')
  try {
    await apiTestApi.startLoad(currentProject.value.id, { ...loadConfig, case_ids: ids })
  } catch (e) {
    loadRunning.value = false
    disconnectWs()
    ElMessage.error('启动压测失败：' + (e?.response?.data?.detail || e?.message || ''))
  }
}

const stopLoad = async () => {
  await apiTestApi.stopLoad()
  loadRunning.value = false
  disconnectWs()
}

// ── 测试报告 ──
const loadReports = async () => {
  if (!currentProject.value) return
  reportsLoading.value = true
  try {
    reports.value = await apiTestApi.listReports(currentProject.value.id)
  } finally {
    reportsLoading.value = false
  }
}

const deleteReports = async (ids) => {
  const targetIds = ids || selectedReports.value.map(r => r.id)
  if (!targetIds.length) return
  await ElMessageBox.confirm(`确认删除 ${targetIds.length} 条报告？`, '警告', { type: 'warning' })
  try {
    if (targetIds.length === 1) {
      await apiTestApi.deleteReport(targetIds[0])
    } else {
      await apiTestApi.deleteReportsBatch(targetIds)
    }
    reports.value = reports.value.filter(r => !targetIds.includes(r.id))
    selectedReports.value = []
    ElMessage.success('已删除')
  } catch (e) {
    ElMessage.error('删除失败：' + (e?.response?.data?.detail || e?.message || ''))
  }
}

const showReportDetail = (r) => {
  selectedReport.value = r
  analysisResult.value = r.analysis || ''
  reportDetailVisible.value = true
}

const runAnalysis = async () => {
  if (!selectedReport.value) return
  analysisLoading.value = true
  try {
    const res = await apiTestApi.analyzeReport(selectedReport.value.id)
    analysisResult.value = res.analysis || '暂无分析结果'
    // 同步回列表数据，下次打开详情直接显示
    const target = reports.value.find(r => r.id === selectedReport.value.id)
    if (target) target.analysis = analysisResult.value
    selectedReport.value.analysis = analysisResult.value
  } catch (e) {
    ElMessage.error('AI分析失败：' + (e?.response?.data?.detail || e?.message || ''))
  } finally {
    analysisLoading.value = false
  }
}

const passRate = (r) => {
  if (!r.total) return 0
  return ((r.passed / r.total) * 100).toFixed(1)
}

const passRateColor = (r) => {
  const rate = r.total ? r.passed / r.total : 1
  return rate >= 0.9 ? 'color:#67c23a' : rate >= 0.6 ? 'color:#e6a23c' : 'color:#f56c6c'
}

const formatTime = (iso) => {
  if (!iso) return ''
  // 后端存 UTC，加 Z 让浏览器当 UTC 解析后转本地时间
  const d = new Date(iso.includes('Z') ? iso : iso + 'Z')
  const pad = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

const isJsonResponse = (text) => {
  if (!text) return false
  const t = text.trim()
  return (t.startsWith('{') || t.startsWith('['))
}

const formatResponsePreview = (text) => {
  if (!text) return ''
  const escape = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  let source = text
  if (isJsonResponse(text)) {
    try { source = JSON.stringify(JSON.parse(text), null, 2) } catch { /* keep original */ }
  }
  return escape(source).replace(
    /("(?:\\u[\da-fA-F]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(?:true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g,
    (m) => {
      if (/^"/.test(m)) {
        return /:$/.test(m)
          ? `<span class="rp-key">${m}</span>`
          : `<span class="rp-str">${m}</span>`
      }
      if (/true|false/.test(m)) return `<span class="rp-bool">${m}</span>`
      if (/null/.test(m)) return `<span class="rp-null">${m}</span>`
      return `<span class="rp-num">${m}</span>`
    }
  )
}

const copyResponseText = (text) => {
  navigator.clipboard.writeText(text).then(() => ElMessage.success('已复制')).catch(() => ElMessage.error('复制失败'))
}

// ── ECharts ──
const initChart = async () => {
  await nextTick()
  if (!chartRef.value) return
  const echarts = (await import('echarts')).default || (await import('echarts'))
  chart = echarts.init(chartRef.value)
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['TPS', '平均延迟(ms)', 'P95(ms)', '错误率(%)'] },
    xAxis: { type: 'category', data: chartData.elapsed, name: '时间(s)' },
    yAxis: [
      { type: 'value', name: 'TPS/延迟(ms)' },
      { type: 'value', name: '错误率(%)', max: 100 },
    ],
    series: [
      { name: 'TPS', type: 'line', data: chartData.tps, smooth: true },
      { name: '平均延迟(ms)', type: 'line', data: chartData.avg_ms, smooth: true },
      { name: 'P95(ms)', type: 'line', data: chartData.p95_ms, smooth: true },
      { name: '错误率(%)', type: 'line', data: chartData.error_rate, yAxisIndex: 1, smooth: true },
    ],
  })
}

const appendChartPoint = (m) => {
  chartData.elapsed.push(m.elapsed)
  chartData.tps.push(m.tps)
  chartData.avg_ms.push(m.avg_ms)
  chartData.p95_ms.push(m.p95_ms)
  chartData.error_rate.push(m.error_rate)
  if (!chart) return
  chart.setOption({
    xAxis: { data: chartData.elapsed },
    series: [
      { data: chartData.tps },
      { data: chartData.avg_ms },
      { data: chartData.p95_ms },
      { data: chartData.error_rate },
    ],
  })
}

// ── 工具函数 ──
const methodColor = (m) => {
  const map = { GET: '', POST: 'success', PUT: 'warning', DELETE: 'danger', PATCH: 'info' }
  return map[m] || ''
}

onMounted(loadProjects)
onUnmounted(disconnectWs)

watch(activeTab, (tab) => {
  if (tab === 'reports') loadReports()
})
</script>

<style scoped>
.api-test {
  display: flex;
  height: 100%;
  gap: 12px;
  overflow: hidden;
}

.project-panel {
  width: 220px;
  flex-shrink: 0;
  background: #fff;
  border-radius: 8px;
  padding: 12px;
  overflow-y: auto;
  box-shadow: 0 1px 4px rgba(0,0,0,.06);
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
  margin-bottom: 12px;
  font-size: 14px;
}

.project-item {
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 4px;
  transition: background .15s;
  position: relative;
}

.project-item:hover { background: #f5f7fa; }
.project-item.active { background: #ecf5ff; }

.project-name { font-size: 13px; font-weight: 500; color: #333; }
.project-url { font-size: 11px; color: #999; margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.project-actions {
  display: none;
  position: absolute;
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  gap: 2px;
  align-items: center;
  background: rgba(255,255,255,.9);
  border-radius: 4px;
  padding: 1px 2px;
}
.project-item:hover .project-actions { display: flex; }

.content-panel {
  flex: 1;
  min-width: 0;
  background: #fff;
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 1px 4px rgba(0,0,0,.06);
  overflow-y: auto;
}

.content-panel.empty-hint {
  display: flex;
  align-items: center;
  justify-content: center;
}

.content-tabs { }

.toolbar { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }

.group-select-link {
  font-size: 11px;
  color: #409eff;
  cursor: pointer;
  padding: 1px 6px;
  border-radius: 3px;
  transition: background .15s;
  user-select: none;
  vertical-align: middle;
}
.group-select-link:hover { background: #ecf5ff; }

/* ── 接口组行背景 ── */
:deep(.case-group-row) { cursor: pointer; }
:deep(.case-group-row > td) {
  background: linear-gradient(90deg, #edf3ff 0%, #f3f7ff 100%) !important;
  border-bottom: 1px solid #c7d9ff !important;
}
:deep(.el-table__body tr.case-group-row:hover > td) {
  background: linear-gradient(90deg, #deeaff 0%, #e8f0ff 100%) !important;
}
:deep(.case-group-row > td:first-child) {
  border-left: 3px solid #409eff;
  padding-left: 12px;
}

/* ── 组行内容 ── */
.group-cell {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 2px 0;
}
.group-cell-header {
  display: flex;
  align-items: center;
  gap: 0;
}
.group-cell-path {
  font-size: 14px;
  font-weight: 700;
  color: #1a56db;
  font-family: 'SFMono-Regular', Consolas, 'Courier New', monospace;
  letter-spacing: 0.3px;
}

/* 描述字段 — 底线风格 */
.group-desc-field {
  max-width: 480px;
}
.group-desc-field :deep(.el-input__wrapper) {
  background: transparent;
  box-shadow: none;
  border-radius: 0;
  padding: 0 2px;
  border-bottom: 1px dashed #93b4ff;
  transition: border-color .2s;
}
.group-desc-field :deep(.el-input__wrapper:hover),
.group-desc-field :deep(.el-input__wrapper.is-focus) {
  box-shadow: none;
  border-bottom-color: #409eff;
}
.group-desc-field :deep(.el-input__inner) {
  font-size: 13px;
  color: #1e3a8a;
  font-weight: 500;
  height: 24px;
  line-height: 24px;
}
.group-desc-field :deep(input::placeholder) {
  color: #9db4e8;
  font-weight: 400;
  font-size: 12px;
  font-style: italic;
}

/* ── 子用例行 ── */
.case-cell {
  display: flex;
  align-items: center;
  gap: 7px;
}
.method-tag {
  flex-shrink: 0;
  min-width: 50px;
  text-align: center;
  font-weight: 600;
  font-size: 11px;
}
.case-name {
  color: #374151;
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.table-action-btns {
  display: flex;
  gap: 6px;
  justify-content: center;
  align-items: center;
}

/* 全选/清空 行内操作链接 */
.select-actions { display: flex; align-items: center; gap: 4px; }

.select-action-link {
  font-size: 12px;
  color: #409eff;
  cursor: pointer;
  padding: 1px 5px;
  border-radius: 3px;
  transition: background .15s, color .15s;
  user-select: none;
}
.select-action-link:hover { background: #ecf5ff; }
.select-action-link.muted { color: #909399; }
.select-action-link.muted:hover { background: #f5f5f5; color: #606266; }

.select-action-sep { color: #ddd; font-size: 12px; }

.progress-card { margin-bottom: 10px; }
.progress-label { font-size: 13px; color: #666; margin-bottom: 6px; }

/* ── AI 生成进度卡片 ── */
.gen-progress-wrap {
  background: #fff;
  border: 1px solid #e4e9f2;
  border-radius: 10px;
  padding: 16px 20px 14px;
  margin-top: 12px;
  box-shadow: 0 2px 10px rgba(64,158,255,.08);
}
.gen-progress-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.gen-pct-badge {
  font-size: 24px;
  font-weight: 700;
  color: #409eff;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}
.gen-stage-text {
  font-size: 12px;
  color: #666;
  margin: 6px 0 14px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.gen-stage-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
  background: #409eff;
  transition: background .3s;
}
.gen-stage-dot.done { background: #52c41a; }
.gen-stage-dot.pulsing { animation: genPulse 1.2s ease-in-out infinite; }
@keyframes genPulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%       { opacity: .45; transform: scale(.75); }
}

/* 步骤行 */
.gen-steps-row {
  display: flex;
  align-items: flex-start;
  gap: 0;
}
.gen-step-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  flex-shrink: 0;
}
.gstep-dot {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  transition: background .25s, color .25s;
}
.gstep-done .gstep-dot    { background: #52c41a; color: #fff; }
.gstep-active .gstep-dot  { background: #409eff; color: #fff; box-shadow: 0 0 0 3px #cce5ff; }
.gstep-pending .gstep-dot { background: #f0f2f5; color: #c0c4cc; }
.gstep-label {
  font-size: 11px;
  white-space: nowrap;
  color: #bbb;
  transition: color .25s;
}
.gstep-done .gstep-label   { color: #52c41a; }
.gstep-active .gstep-label { color: #409eff; font-weight: 600; }
.gstep-connector {
  flex: 1;
  height: 2px;
  background: #eee;
  margin: 11px 3px 0;
  border-radius: 1px;
  transition: background .4s;
  min-width: 16px;
}
.gstep-connector.connector-done { background: #52c41a; }

.result-card { margin-top: 16px; }

.load-config-card { margin-bottom: 12px; }
.load-summary-card { }
.case-select-card { }

/* ── 单测 / 压测通用：接口选择面板 ── */
.exec-select-panel {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 1px 4px rgba(0,0,0,.05);
}
.exec-select-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  border-bottom: 1px solid #f0f2f5;
  background: #fafbfc;
}
.exec-select-title {
  display: flex;
  align-items: center;
  font-size: 13px;
  font-weight: 600;
  color: #374151;
}
.exec-btn-wrap {
  padding: 12px;
  border-top: 1px solid #f0f2f5;
}

/* unit-group 行内样式 */
.unit-group-path {
  display: flex;
  align-items: center;
  font-weight: 600;
  color: #303133;
  font-size: 12px;
  font-family: 'SFMono-Regular', Consolas, monospace;
}
.unit-group-desc {
  color: #909399;
  font-size: 11px;
  margin-top: 2px;
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ── 单测执行进度条 ── */
.unit-progress-panel {
  background: #fff;
  border: 1px solid #e4e9f2;
  border-radius: 8px;
  padding: 12px 16px 10px;
  margin-bottom: 12px;
  box-shadow: 0 1px 6px rgba(64,158,255,.06);
}
.unit-progress-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.unit-progress-title {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
}
.unit-pct {
  font-size: 20px;
  font-weight: 700;
  color: #409eff;
  font-variant-numeric: tabular-nums;
  transition: color .3s;
}
.unit-stage-text {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

/* ── 单测统计数字行 ── */
.unit-stat-row {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}
.unit-stat-card {
  flex: 1;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 12px 8px 10px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  box-shadow: 0 1px 4px rgba(0,0,0,.04);
}
.stat-num {
  font-size: 24px;
  font-weight: 700;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}
.stat-label {
  font-size: 12px;
  color: #909399;
}
.stat-total .stat-num  { color: #303133; }
.stat-passed .stat-num { color: #52c41a; }
.stat-failed .stat-num { color: #f56c6c; }
.stat-rate {
  flex: 1.3;
}

/* ── 单测结果表 ── */
.unit-result-wrap {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  overflow: hidden;
}
:deep(.result-pass-row > td:first-child) { border-left: 3px solid #52c41a; }
:deep(.result-fail-row > td:first-child) { border-left: 3px solid #f56c6c; }
.result-error-text { color: #f56c6c; font-size: 12px; }
.result-ok-text    { color: #c0c4cc; font-size: 12px; }

/* ── 压测：配置面板 ── */
.load-config-panel {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 14px;
  box-shadow: 0 1px 4px rgba(0,0,0,.05);
}
.load-config-header {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #f0f2f5;
}
.load-config-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-bottom: 14px;
}
.load-config-item {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.load-config-label {
  font-size: 12px;
  color: #606266;
  font-weight: 500;
}
.load-action-row {
  display: flex;
  gap: 8px;
}

/* ── 压测汇总结果面板 ── */
.load-report-panel {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 14px;
  margin-top: 12px;
  box-shadow: 0 1px 4px rgba(0,0,0,.05);
}
.load-report-header {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #f0f2f5;
}
.load-report-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}
.load-report-item {
  background: #f8fafc;
  border-radius: 6px;
  padding: 10px 8px 8px;
  text-align: center;
  border: 1px solid #eef0f3;
  transition: background .2s;
}
.load-report-item.lri-good { background: #f0fff4; border-color: #b7ebce; }
.load-report-item.lri-bad  { background: #fff2f0; border-color: #ffb8b8; }
.load-report-val {
  font-size: 18px;
  font-weight: 700;
  color: #303133;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}
.load-report-key {
  font-size: 11px;
  color: #909399;
  margin-top: 3px;
}
.lrv-unit { font-size: 11px; font-weight: 400; }
.lri-good .load-report-val { color: #52c41a; }
.lri-bad  .load-report-val { color: #f56c6c; }

/* ── 压测：右侧图表面板 ── */
.chart-panel {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 14px 16px;
  box-shadow: 0 1px 4px rgba(0,0,0,.05);
  height: 100%;
}
.chart-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  flex-wrap: wrap;
  gap: 8px;
}
.chart-panel-title {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
}
.chart-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 360px;
}

/* LIVE metrics chips */
.live-metrics-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.live-badge {
  font-size: 10px;
  font-weight: 700;
  color: #fff;
  background: #f56c6c;
  border-radius: 3px;
  padding: 1px 5px;
  letter-spacing: .5px;
  animation: livePulse 1.5s ease-in-out infinite;
}
@keyframes livePulse {
  0%, 100% { opacity: 1; }
  50%       { opacity: .55; }
}
.live-chip {
  display: flex;
  align-items: center;
  gap: 4px;
  background: #f0f7ff;
  border: 1px solid #c6deff;
  border-radius: 5px;
  padding: 3px 8px;
}
.live-chip-err {
  background: #fff2f0;
  border-color: #ffccc7;
}
.live-chip-label {
  font-size: 11px;
  color: #909399;
}
.live-chip-val {
  font-size: 13px;
  font-weight: 700;
  color: #1a56db;
  font-variant-numeric: tabular-nums;
}
.live-chip-err .live-chip-val { color: #f56c6c; }

.analysis-result {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 20px 24px;
  max-height: 520px;
  overflow-y: auto;
  box-shadow: 0 1px 4px rgba(0,0,0,.04);
}

.analysis-result :deep(.analysis-markdown) {
  font-size: 13.5px;
  line-height: 1.9;
  color: #374151;
}

.analysis-result :deep(h1),
.analysis-result :deep(h2),
.analysis-result :deep(h3),
.analysis-result :deep(h4) {
  font-weight: 600;
  color: #111827;
  line-height: 1.4;
}

.analysis-result :deep(h2) {
  font-size: 15px;
  margin: 20px 0 10px;
  padding: 8px 12px;
  background: linear-gradient(90deg, #eff6ff, transparent);
  border-left: 3px solid #3b82f6;
  border-radius: 0 6px 6px 0;
}

.analysis-result :deep(h3) {
  font-size: 13.5px;
  margin: 14px 0 6px;
  color: #1d4ed8;
}

.analysis-result :deep(h4) { font-size: 13px; margin: 10px 0 4px; }

.analysis-result :deep(p) {
  margin: 6px 0;
  color: #4b5563;
}

.analysis-result :deep(ul),
.analysis-result :deep(ol) {
  padding-left: 20px;
  margin: 4px 0 10px;
}

.analysis-result :deep(li) {
  margin: 5px 0;
  color: #4b5563;
  line-height: 1.7;
}

.analysis-result :deep(li::marker) {
  color: #3b82f6;
}

.analysis-result :deep(strong),
.analysis-result :deep(b) {
  font-weight: 600;
  color: #111827;
}

.analysis-result :deep(em) {
  color: #6366f1;
  font-style: normal;
}

.analysis-result :deep(code) {
  background: #f1f5f9;
  color: #dc2626;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 12px;
}

.analysis-result :deep(pre) {
  background: #1e293b;
  color: #e2e8f0;
  padding: 14px 18px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 10px 0;
}

.analysis-result :deep(pre code) {
  background: none;
  color: inherit;
  padding: 0;
  font-size: 12px;
}

.analysis-result :deep(blockquote) {
  border-left: 3px solid #6366f1;
  padding: 8px 14px;
  margin: 10px 0;
  background: #f5f3ff;
  border-radius: 0 6px 6px 0;
  color: #4b5563;
}

.analysis-result :deep(hr) {
  border: none;
  border-top: 1px solid #f1f5f9;
  margin: 14px 0;
}

.analysis-result :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 10px 0;
  font-size: 12.5px;
}

.analysis-result :deep(th) {
  background: #f8fafc;
  font-weight: 600;
  padding: 7px 12px;
  border: 1px solid #e2e8f0;
  text-align: left;
  color: #374151;
}

.analysis-result :deep(td) {
  padding: 6px 12px;
  border: 1px solid #e2e8f0;
  color: #4b5563;
}

.analysis-result :deep(tr:nth-child(even) td) {
  background: #f8fafc;
}

/* 断言结果列表 */
.assertion-list { display: flex; flex-direction: column; gap: 3px; }

.assertion-row {
  border-left: 3px solid;
  border-radius: 0 5px 5px 0;
  padding: 5px 10px;
  font-size: 12px;
  line-height: 1.5;
}

.ar-pass { border-left-color: #52c41a; background: #f6ffed; }
.ar-fail { border-left-color: #ff4d4f; background: #fff1f0; }

.ar-main { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }

.ar-icon { font-size: 13px; font-weight: 700; flex-shrink: 0; width: 14px; text-align: center; }
.ar-pass .ar-icon { color: #52c41a; }
.ar-fail .ar-icon { color: #ff4d4f; }

.ar-desc { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; font-weight: 500; color: #333; }

.ar-path {
  background: rgba(0,0,0,.07);
  padding: 0 5px;
  border-radius: 3px;
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 11px;
  color: #444;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-block;
  vertical-align: middle;
  cursor: default;
  font-weight: 400;
}

.ar-op {
  background: #e6f4ff;
  color: #1677ff;
  border-radius: 3px;
  padding: 0 5px;
  font-size: 11px;
  font-weight: 400;
}

.ar-kv { display: flex; align-items: center; gap: 3px; }
.ar-kv-label { color: #aaa; font-size: 11px; }
.ar-kv code {
  background: rgba(0,0,0,.07);
  padding: 0 5px;
  border-radius: 3px;
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 11px;
  color: #555;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-block;
  vertical-align: middle;
}

.ar-arrow { color: #bbb; font-size: 12px; }

.ar-actual-pass code { color: #389e0d !important; background: #d9f7be !important; }
.ar-actual-fail code { color: #cf1322 !important; background: #ffccc7 !important; }

.ar-error {
  margin-top: 3px;
  padding-left: 20px;
  color: #cf1322;
  font-size: 11px;
  font-style: italic;
}

/* 响应内容代码块 */
.response-preview-code {
  background: #1e1e2e;
  color: #cdd6f4;
  padding: 10px 14px;
  border-radius: 6px;
  margin: 0;
  max-height: 200px;
  overflow-y: auto;
  white-space: pre;
  overflow-x: auto;
  font-family: 'SFMono-Regular', Consolas, 'Courier New', monospace;
  font-size: 11.5px;
  line-height: 1.65;
  word-break: normal;
}

.response-preview-code :deep(.rp-key)  { color: #89b4fa; }
.response-preview-code :deep(.rp-str)  { color: #a6e3a1; }
.response-preview-code :deep(.rp-num)  { color: #fab387; }
.response-preview-code :deep(.rp-bool) { color: #cba6f7; }
.response-preview-code :deep(.rp-null) { color: #6c7086; font-style: italic; }

.script-list-item {
  padding: 8px 10px;
  border-radius: 7px;
  cursor: pointer;
  border: 1px solid transparent;
  transition: background 0.15s, border-color 0.15s;
}
.script-list-item:hover { background: #f5f7fa; }
.script-list-item.active { background: #ecf5ff; border-color: #c6e2ff; }

/* ── 脚本 Dialog 整体布局 ── */
.script-dialog :deep(.el-dialog__body) { padding: 0 20px 16px; }
.script-dialog :deep(.el-dialog__header) {
  padding: 16px 20px 12px;
  border-bottom: 1px solid #f0f0f0;
  margin-right: 0;
}

.script-layout {
  display: flex;
  gap: 0;
  height: 580px;
}

/* 左侧列表 */
.script-sidebar {
  width: 210px;
  flex-shrink: 0;
  border-right: 1px solid #ebeef5;
  padding: 12px 12px 0 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow: hidden;
}
.script-new-btn { width: 100%; }
.script-list-scroll {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-right: 2px;
}
.sli-name {
  display: flex;
  align-items: center;
  gap: 3px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.4;
}
.sli-icon {
  color: #409eff;
  font-size: 15px;
  font-style: italic;
  font-weight: 700;
  margin-right: 1px;
}
.sli-fn { color: #1d4ed8; }
.sli-paren { color: #6b7280; font-weight: 400; }
.sli-desc {
  font-size: 11px;
  color: #9ca3af;
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 右侧编辑区 */
.script-editor-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0;
  overflow: hidden;
  padding-left: 16px;
  padding-top: 12px;
}

/* 元信息区 */
.sed-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 10px;
}
.sed-meta-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.sed-label {
  font-size: 12px;
  color: #606266;
  font-weight: 600;
  width: 46px;
  flex-shrink: 0;
}
.sed-name-input { width: 220px; font-family: monospace; }
.sed-usage-tag {
  font-size: 11.5px;
  color: #909399;
  background: #f5f7fa;
  border: 1px solid #e9ecef;
  border-radius: 4px;
  padding: 2px 8px;
  white-space: nowrap;
}
.sed-usage-tag code {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  color: #d14;
  font-size: 11px;
}

/* 代码区 */
.sed-code-section {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}
.sed-code-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  flex-shrink: 0;
}
.sed-code-title {
  font-size: 12px;
  font-weight: 600;
  color: #374151;
  display: flex;
  align-items: center;
}
.sed-code-tip {
  font-size: 11px;
  color: #9ca3af;
}
.sed-code-tip code {
  font-family: monospace;
  background: #f3f4f6;
  padding: 1px 4px;
  border-radius: 3px;
  color: #d14;
}

/* ── Python 代码编辑器 ── */
.py-editor-wrap {
  flex: 1;
  display: flex;
  overflow: hidden;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  background: #1e1e2e;
  font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.65;
  min-height: 0;
}

/* 行号 */
.py-line-nums {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  padding: 12px 10px 12px 12px;
  background: #181825;
  border-right: 1px solid #313244;
  color: #45475a;
  font-size: 12px;
  line-height: 1.65;
  user-select: none;
  overflow: hidden;
  flex-shrink: 0;
  min-width: 36px;
}
.py-line-nums span { display: block; }

/* 编辑器内层（textarea + pre 叠加） */
.py-editor-inner {
  flex: 1;
  position: relative;
  overflow: hidden;
}
.py-highlight,
.py-textarea {
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  padding: 12px 14px;
  margin: 0;
  border: none;
  outline: none;
  font: inherit;
  line-height: 1.65;
  white-space: pre;
  overflow: auto;
  tab-size: 4;
  word-wrap: normal;
  width: 100%;
  box-sizing: border-box;
}
.py-highlight {
  color: #cdd6f4;
  background: transparent;
  pointer-events: none;
  overflow: hidden;
  z-index: 1;
}
.py-highlight code { font: inherit; }
.py-textarea {
  background: transparent;
  color: transparent;
  caret-color: #cba6f7;
  resize: none;
  z-index: 2;
  -webkit-text-fill-color: transparent;
}
.py-textarea::placeholder { color: #45475a; -webkit-text-fill-color: #45475a; }
.py-textarea:focus { outline: none; }

/* Python 颜色 token（Catppuccin Mocha 配色） */
.py-kw      { color: #cba6f7; font-weight: 600; }   /* 关键字：紫 */
.py-str     { color: #a6e3a1; }                      /* 字符串：绿 */
.py-comment { color: #6c7086; font-style: italic; }  /* 注释：灰 */
.py-num     { color: #fab387; }                      /* 数字：橙 */
.py-builtin { color: #89dceb; }                      /* 内置函数：青 */
.py-fn-def  { color: #89b4fa; font-weight: 600; }   /* 函数名：蓝 */
.py-decorator { color: #f38ba8; }                   /* 装饰器：红 */

/* 测试区 */
.sed-test-section {
  flex-shrink: 0;
  padding-top: 10px;
  border-top: 1px solid #f0f0f0;
  margin-top: 10px;
}
.sed-test-header {
  font-size: 12px;
  font-weight: 600;
  color: #374151;
  display: flex;
  align-items: center;
  margin-bottom: 7px;
}
.sed-test-row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.sed-test-input { flex: 1; }
.sed-test-btn { flex-shrink: 0; }
.sed-test-result {
  margin-top: 8px;
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid transparent;
  display: flex;
  align-items: flex-start;
  gap: 0;
}
.result-ok { background: #f0f9eb; border-color: #b7eb8f; }
.result-err { background: #fff1f0; border-color: #ffa39e; }
.str-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 5px 10px;
  flex-shrink: 0;
  align-self: stretch;
  display: flex;
  align-items: center;
}
.badge-ok { background: #b7eb8f; color: #135200; }
.badge-err { background: #ffa39e; color: #7b0b0b; }
.str-value {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 12px;
  margin: 0;
  padding: 5px 10px;
  white-space: pre-wrap;
  word-break: break-all;
  flex: 1;
}
.result-ok .str-value { color: #237804; }
.result-err .str-value { color: #a8071a; }

/* 底部操作 */
.sed-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 10px;
  flex-shrink: 0;
}

/* 空态 */
.script-empty-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding-left: 16px;
}
.sep-icon {
  font-size: 36px;
  font-family: 'JetBrains Mono', monospace;
  font-style: italic;
  font-weight: 700;
  color: #d1d5db;
  letter-spacing: -1px;
}
.sep-text { font-size: 14px; color: #9ca3af; }
.sep-sub { font-size: 12px; color: #c0c4cc; }
.sep-sub code {
  font-family: monospace;
  background: #f3f4f6;
  padding: 1px 4px;
  border-radius: 3px;
  color: #d14;
}

/* ── AI 生成按钮 ── */
.ai-gen-btn {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border-radius: 20px;
  border: 1px solid #c6b0f5;
  background: linear-gradient(135deg, #f5f0ff 0%, #ede9fe 100%);
  color: #6d28d9;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.18s ease;
  white-space: nowrap;
  flex-shrink: 0;
}
.ai-gen-btn:hover {
  background: linear-gradient(135deg, #ede9fe 0%, #ddd6fe 100%);
  border-color: #a78bfa;
  box-shadow: 0 0 0 3px rgba(167, 139, 250, 0.15);
}
.ai-gen-btn.active {
  background: linear-gradient(135deg, #7c3aed 0%, #6d28d9 100%);
  border-color: #5b21b6;
  color: #fff;
  box-shadow: 0 0 0 3px rgba(124, 58, 237, 0.2);
}
.ai-gen-btn-icon { font-size: 11px; }

/* ── AI 生成面板 ── */
.ai-gen-panel {
  background: linear-gradient(135deg, #faf5ff 0%, #f5f0fe 100%);
  border: 1px solid #ddd6fe;
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 8px;
  flex-shrink: 0;
}
.ai-gen-panel-title {
  font-size: 12px;
  color: #5b21b6;
  font-weight: 500;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 5px;
}
.ai-gen-star { color: #7c3aed; font-size: 13px; }
.ai-gen-input :deep(.el-textarea__inner) {
  font-size: 13px;
  background: #fff;
  border-color: #c4b5fd;
  border-radius: 6px;
  resize: none !important;
}
.ai-gen-input :deep(.el-textarea__inner):focus { border-color: #7c3aed; box-shadow: 0 0 0 2px rgba(124,58,237,0.12); }
.ai-gen-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
  gap: 8px;
}
.ai-gen-hint { font-size: 11px; color: #a78bfa; }
.ai-gen-submit {
  background: linear-gradient(135deg, #7c3aed, #6d28d9) !important;
  border-color: transparent !important;
  font-weight: 600;
  letter-spacing: 0.3px;
}
.ai-gen-submit:hover {
  background: linear-gradient(135deg, #6d28d9, #5b21b6) !important;
}

/* 过渡动画 */
.fade-slide-enter-active { transition: opacity .2s ease, transform .2s ease; }
.fade-slide-leave-active { transition: opacity .15s ease, transform .1s ease; }
.fade-slide-enter-from { opacity: 0; transform: translateY(-4px); }
.fade-slide-leave-to  { opacity: 0; transform: translateY(-2px); }

/* ── 压测报告接口详情 ── */
.report-section-title {
  font-size: 13px; font-weight: 600; color: #303133;
  margin-bottom: 8px; padding-bottom: 6px;
  border-bottom: 1px solid #ebeef5;
}
.load-cases-wrap { margin-bottom: 4px; }
.load-cases-wrap :deep(.el-collapse-item__header) {
  height: 42px; padding: 0 12px; background: #fafafa;
}
.load-cases-wrap :deep(.el-collapse-item__wrap) {
  background: #fff; border-top: 1px solid #ebeef5;
}
.load-case-detail { padding: 12px 16px; }
.lcd-desc { font-size: 12px; color: #909399; margin-bottom: 10px; }
.lcd-grid { display: flex; flex-wrap: wrap; gap: 12px; }
.lcd-block { min-width: 200px; flex: 1; }
.lcd-block-full { flex: 0 0 100%; }
.lcd-block-title {
  font-size: 11px; font-weight: 600; color: #606266;
  margin-bottom: 5px; text-transform: uppercase; letter-spacing: .5px;
}
.lcd-kv { display: flex; align-items: baseline; gap: 4px; margin-bottom: 3px; font-size: 12px; }
.lcd-k { background: #f0f2f5; padding: 1px 5px; border-radius: 3px; color: #4b5563; }
.lcd-path { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: inline-block; vertical-align: middle; cursor: default; }
.lcd-eq { color: #909399; flex-shrink: 0; }
.lcd-v { background: #f0f9eb; padding: 1px 5px; border-radius: 3px; color: #389e0d; word-break: break-all; }
.lcd-code {
  background: #1e1e2e; color: #cdd6f4; padding: 8px 12px;
  border-radius: 6px; font-size: 12px; font-family: monospace;
  white-space: pre-wrap; word-break: break-all; margin: 0; max-height: 160px; overflow-y: auto;
}
.lcd-assertion { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; font-size: 12px; }
.lcd-empty { font-size: 12px; color: #bbb; padding: 8px 0; }

.load-config-summary {
  display: flex; gap: 16px; flex-wrap: wrap;
  background: #f7f9fc; border-radius: 8px; padding: 10px 16px; margin-bottom: 4px;
}
.lcs-item { display: flex; flex-direction: column; gap: 2px; }
.lcs-label { font-size: 11px; color: #909399; }
.lcs-value { font-size: 16px; font-weight: 600; color: #303133; }</style>
