<template>
  <div class="ai-cases-page">
    <WorkspaceRequired v-if="auth.role !== 'admin' && !wsStore.currentId" />
    <template v-else>

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
                  <el-tooltip content="文档变更·增量更新" placement="top">
                    <el-button
                      size="small"
                      type="warning"
                      link
                      @click.stop="openDiffDialog(r)"
                    >
                      <el-icon><Refresh /></el-icon>
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
                <el-tag size="small" type="info" v-if="r.parent_id">增量更新</el-tag>
                <el-tag size="small" effect="plain" type="danger" v-if="r.record_status === 'deprecated'">已废弃</el-tag>
                <el-tag size="small" type="primary" effect="plain" v-if="r.gen_status === 'generating'">
                  <el-icon class="is-loading"><Loading /></el-icon> 生成中...
                </el-tag>
                <el-tag size="small" type="danger" effect="plain" v-if="r.gen_status === 'failed'">生成失败</el-tag>
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
            <div class="detail-header">
              <!-- 第一行：标题 + 版本标签 -->
              <div class="detail-title">
                <el-icon color="#409eff" :size="18"><MagicStick /></el-icon>
                <span class="detail-task-name">{{ current.task_name }}</span>
                <el-tag size="small" type="primary" effect="plain">{{ current.case_count }} 条用例</el-tag>
                <el-tag v-if="current.parent_id" size="small" type="warning" effect="plain">增量更新版本</el-tag>
              </div>
              <!-- 第二行：操作按钮分组 -->
              <div class="detail-actions">
                <!-- 编辑组 -->
                <div class="btn-group">
                  <el-button type="primary" size="small" plain @click="openAddCase">
                    <el-icon><Plus /></el-icon>新建用例
                  </el-button>
                </div>
                <!-- AI 操作组 -->
                <div class="btn-group">
                  <el-button type="warning" size="small" plain @click="openDiffDialog(current)">
                    <el-icon><Refresh /></el-icon>文档变更更新
                  </el-button>
                  <el-button
                    type="success" size="small"
                    @click="openOptimizeDialog(current)"
                    :loading="optimizing && optimizeTarget?.id === current.id"
                  >
                    <el-icon><MagicStick /></el-icon>覆盖度优化
                  </el-button>
                  <el-button
                    type="info" size="small"
                    @click="showCoverage(current)"
                    :loading="loadingCoverage && coverageTarget?.id === current.id"
                  >
                    <el-icon><DataAnalysis /></el-icon>覆盖度分析
                  </el-button>
                  <el-button
                    type="primary" size="small" plain
                    @click="openTraceability(current)"
                    :loading="tracLoading && tracTarget?.id === current.id"
                  >
                    <el-icon><Connection /></el-icon>需求追踪
                  </el-button>
                </div>
                <!-- 下载组 -->
                <div class="btn-group" v-if="current.has_md || current.has_xmind">
                  <el-button v-if="current.has_md" size="small" @click="download(current.id, 'md')">
                    <el-icon><Download /></el-icon>MD
                  </el-button>
                  <el-button v-if="current.has_xmind" size="small" type="warning" plain @click="download(current.id, 'xmind')">
                    <el-icon><Download /></el-icon>XMind
                  </el-button>
                </div>
              </div>
            </div>
          </template>

          <!-- diff_summary 提示条 -->
          <el-alert
            v-if="current.diff_summary"
            :title="`本版本变更：${current.diff_summary}`"
            type="warning"
            show-icon
            :closable="false"
            style="margin-bottom:12px"
          />

          <div v-if="current.modules && current.modules.length" class="modules-preview">
            <!-- 废弃用例开关 -->
            <div class="modules-toolbar">
              <span class="modules-stat">
                共 {{ activeCaseCount }} 条有效用例
                <span v-if="deprecatedCaseCount > 0" style="color:#909399">
                  ，{{ deprecatedCaseCount }} 条已废弃
                </span>
              </span>
              <el-switch
                v-if="deprecatedCaseCount > 0"
                v-model="showDeprecated"
                active-text="显示废弃用例"
                inactive-text=""
                size="small"
                style="margin-left:12px"
              />
            </div>

            <el-collapse v-model="openModules">
              <template v-for="(mod, mi) in current.modules" :key="mi">
                <!-- 废弃模块：只在 showDeprecated=true 时显示，且样式不同 -->
                <el-collapse-item
                  v-if="!isDeprecatedModule(mod) || showDeprecated"
                  :name="mi"
                  :class="{ 'deprecated-module': isDeprecatedModule(mod) }"
                >
                  <template #title>
                    <div class="mod-title">
                      <el-icon :color="isDeprecatedModule(mod) ? '#c0c4cc' : '#67c23a'">
                        <FolderOpened />
                      </el-icon>
                      <span :class="{ 'text-deprecated': isDeprecatedModule(mod) }">{{ mod.name }}</span>
                      <el-tag
                        v-if="isDeprecatedModule(mod)"
                        size="small" type="danger" effect="plain"
                        style="margin-left:6px"
                      >已废弃</el-tag>
                      <el-badge
                        v-else
                        :value="activeModCaseCount(mod)"
                        :type="activeModCaseCount(mod) > 0 ? 'primary' : 'info'"
                        class="mod-badge"
                      />
                      <el-button
                        v-if="selectedCases[mi] && selectedCases[mi].length > 0"
                        size="small" type="danger" plain
                        style="margin-left:10px"
                        @click.stop="batchDeleteCases(mi, mod.name)"
                      >
                        <el-icon><Delete /></el-icon>
                        删除选中 ({{ selectedCases[mi].length }})
                      </el-button>
                    </div>
                  </template>
                  <el-table
                    :data="visibleCases(mod)"
                    stripe size="small" style="width:100%"
                    :row-class-name="({ row }) => row.status === 'deprecated' ? 'row-deprecated' : ''"
                    @selection-change="(rows) => onSelectionChange(mi, rows)"
                  >
                    <el-table-column type="selection" width="40" />
                    <el-table-column prop="id" label="编号" width="80" />
                    <el-table-column prop="name" label="用例名称" min-width="180" show-overflow-tooltip>
                      <template #default="{ row }">
                        <span :class="{ 'case-deprecated': row.status === 'deprecated' }">{{ row.name }}</span>
                        <el-tag v-if="row.is_new" size="small" type="success" effect="dark" style="margin-left:4px">NEW</el-tag>
                        <el-tag v-else-if="row.is_updated" size="small" type="warning" effect="dark" style="margin-left:4px">更新</el-tag>
                        <el-tag v-else-if="row.status === 'deprecated'" size="small" type="danger" effect="plain" style="margin-left:4px">废弃</el-tag>
                      </template>
                    </el-table-column>
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
              </template>
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

    <!-- 需求追踪矩阵抽屉 -->
    <el-drawer v-model="tracDrawerVisible" title="需求追踪矩阵" size="700px" direction="rtl" :destroy-on-close="false">
      <div class="trac-panel">

        <!-- 步骤区：未提取或未映射时显示操作引导 -->
        <div v-if="!tracData || !tracData.ready" class="trac-guide">
          <el-steps :active="tracStep" finish-status="success" style="margin-bottom:24px">
            <el-step title="提取需求" description="从需求文档识别结构化需求条目" />
            <el-step title="建立映射" description="AI 分析每条用例覆盖哪些需求" />
            <el-step title="查看矩阵" description="需求覆盖率报告" />
          </el-steps>

          <!-- 进度条（提取/映射进行中时显示） -->
          <div v-if="tracExtracting || tracMapping" class="trac-progress-box">
            <el-progress :percentage="tracPercent" :status="tracPercent >= 100 ? 'success' : ''" :stroke-width="10" />
            <p class="trac-stage-text">{{ tracStage }}</p>
          </div>

          <div v-else-if="tracStep === 0" style="text-align:center">
            <p style="color:#666;margin-bottom:16px">点击下方按钮，AI 将从需求文档中提取结构化需求条目</p>
            <el-button type="primary" :loading="tracExtracting" @click="doExtractRequirements">
              <el-icon><Document /></el-icon> 开始提取需求
            </el-button>
          </div>
          <div v-else-if="tracStep === 1" style="text-align:center">
            <p style="color:#666;margin-bottom:8px">已提取 <b>{{ tracRequirements.length }}</b> 条需求，点击下方建立用例映射</p>
            <p style="color:#999;font-size:12px;margin-bottom:16px">AI 将分析每条用例对应哪些需求（用例较多时需要几分钟）</p>
            <el-button type="primary" :loading="tracMapping" @click="doMapCases">
              <el-icon><Connection /></el-icon> 建立用例-需求映射
            </el-button>
          </div>
        </div>

        <!-- 矩阵展示区 -->
        <div v-else>
          <!-- 汇总数据 -->
          <div class="trac-summary">
            <el-progress
              :percentage="tracData.summary.coverage_rate"
              :color="tracCoverageColor(tracData.summary.coverage_rate)"
              :stroke-width="14"
              style="margin-bottom:12px"
            />
            <div class="trac-stats">
              <div class="trac-stat"><span class="num">{{ tracData.summary.total }}</span><span class="lbl">需求总数</span></div>
              <div class="trac-stat ok"><span class="num">{{ tracData.summary.covered }}</span><span class="lbl">充分覆盖</span></div>
              <div class="trac-stat warn"><span class="num">{{ tracData.summary.insufficient }}</span><span class="lbl">覆盖不足</span></div>
              <div class="trac-stat bad"><span class="num">{{ tracData.summary.uncovered }}</span><span class="lbl">未覆盖</span></div>
            </div>
            <div style="font-size:12px;color:#999;margin-top:8px">
              提取于 {{ formatDate(tracData.extracted_at) }}
              · 映射于 {{ formatDate(tracData.mapped_at) }}
              <el-button link size="small" @click="doExtractRequirements" :loading="tracExtracting" style="margin-left:8px">重新提取</el-button>
              <el-button link size="small" @click="doMapCases" :loading="tracMapping">重新映射</el-button>
            </div>

            <!-- 重新提取/映射时的进度条（在已有矩阵基础上操作） -->
            <div v-if="tracExtracting || tracMapping" class="trac-progress-box" style="margin-top:12px">
              <el-progress :percentage="tracPercent" :stroke-width="8" />
              <p class="trac-stage-text">{{ tracStage }}</p>
            </div>
          </div>

          <!-- 未覆盖警告 -->
          <el-alert
            v-if="tracData.summary.uncovered > 0"
            :title="`有 ${tracData.summary.uncovered} 条需求未被任何用例覆盖，存在漏测风险`"
            type="warning" show-icon :closable="false"
            style="margin-bottom:12px"
          />

          <!-- 视角切换 -->
          <el-tabs v-model="tracTab" style="margin-bottom:8px">
            <el-tab-pane label="需求视角" name="req" />
            <el-tab-pane :label="`用例视角（${tracData.orphan_cases?.length || 0} 条未关联）`" name="case" />
          </el-tabs>

          <!-- 需求视角 -->
          <el-table v-if="tracTab==='req'" :data="tracMatrixFiltered" size="small" border
            row-class-name="trac-row" :row-style="tracRowStyle" height="520"
            style="width:100%" :table-layout="'fixed'">
            <el-table-column label="需求ID" prop="req_id" width="100" />
            <el-table-column label="模块" prop="module" width="90" show-overflow-tooltip />
            <el-table-column label="需求描述" prop="title" show-overflow-tooltip>
              <template #default="{row}">
                <el-tooltip :content="row.description" placement="top" :disabled="!row.description">
                  <span>{{ row.title }}</span>
                </el-tooltip>
              </template>
            </el-table-column>
            <el-table-column label="级别" prop="priority" width="55" align="center">
              <template #default="{row}">
                <el-tag :type="row.priority==='P0'?'danger':row.priority==='P1'?'warning':'info'" size="small">{{ row.priority }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="用例" prop="case_count" width="50" align="center" />
            <el-table-column label="状态" width="85" align="center">
              <template #default="{row}">
                <el-tag v-if="row.status==='covered'"           type="success" size="small">✅ 充分</el-tag>
                <el-tag v-else-if="row.status==='insufficient'" type="warning" size="small">⚠️ 不足</el-tag>
                <el-tag v-else                                  type="danger"  size="small">❌ 未覆盖</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="60" align="center">
              <template #default="{row}">
                <el-button
                  v-if="row.status !== 'covered'"
                  link size="small" type="primary"
                  :loading="supplementingReqId === row.req_id"
                  @click="openGapAnalysis(row)"
                >补充</el-button>
              </template>
            </el-table-column>
            <template #header>
              <div style="display:flex;align-items:center;gap:8px">
                <el-select v-model="tracFilter" size="small" style="width:110px" placeholder="全部状态">
                  <el-option label="全部" value="" />
                  <el-option label="充分覆盖" value="covered" />
                  <el-option label="覆盖不足" value="insufficient" />
                  <el-option label="未覆盖" value="uncovered" />
                </el-select>
              </div>
            </template>
          </el-table>

          <!-- 用例视角 -->
          <el-table v-else :data="tracOrphanCases" size="small" border height="520" style="width:100%">
            <el-table-column label="用例ID" prop="case_id" width="100" />
            <el-table-column label="用例名称" prop="name" show-overflow-tooltip />
            <el-table-column label="所属模块" prop="module" width="120" show-overflow-tooltip />
            <el-table-column label="操作" width="70" align="center">
              <template #default="{row}">
                <el-button link size="small" type="danger" @click="deleteOrphanCase(row)">删除</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="所有用例均已关联需求 🎉" />
            </template>
          </el-table>
        </div>
      </div>
    </el-drawer>

    <!-- 缺口分析 & 补充用例对话框 -->
    <el-dialog v-model="gapDialogVisible" title="覆盖缺口分析" width="600px" :close-on-click-modal="false">
      <div v-if="gapLoading" style="text-align:center;padding:40px 0">
        <el-icon class="is-loading" :size="32"><Loading /></el-icon>
        <p style="color:#666;margin-top:12px">正在分析覆盖缺口...</p>
      </div>
      <div v-else-if="gapData">
        <div class="gap-req-info">
          <el-tag type="primary" size="small">{{ gapData.req_id }}</el-tag>
          <span style="margin-left:8px;font-weight:600">{{ gapData.req_title }}</span>
          <el-tag style="margin-left:8px" size="small">已有 {{ gapData.existing_case_count }} 条用例</el-tag>
        </div>

        <div v-if="gapData.missing_dimensions.length === 0" style="padding:20px 0;text-align:center">
          <el-result icon="success" title="覆盖已充分" :sub-title="gapData.supplement_suggestion" />
        </div>
        <div v-else>
          <p style="color:#666;margin:12px 0 8px">
            {{ gapData.supplement_suggestion }}，缺少以下 {{ gapData.missing_dimensions.length }} 个维度：
          </p>
          <div class="gap-dimensions">
            <div
              v-for="(dim, i) in gapData.missing_dimensions" :key="i"
              class="gap-dim-item"
              :class="{ selected: selectedDimensions.includes(i) }"
              @click="toggleDimension(i)"
            >
              <div class="gap-dim-header">
                <el-checkbox :model-value="selectedDimensions.includes(i)" @change="toggleDimension(i)" />
                <span class="gap-dim-name">{{ dim.dimension }}</span>
              </div>
              <p class="gap-dim-reason">{{ dim.reason }}</p>
              <div class="gap-dim-examples">
                <el-tag v-for="(ex, j) in dim.examples" :key="j" size="small" type="info" style="margin:2px">{{ ex }}</el-tag>
              </div>
            </div>
          </div>
          <p style="font-size:12px;color:#999;margin-top:8px">
            已选 {{ selectedDimensions.length }} 个维度，AI 将针对这些维度生成补充用例
          </p>
        </div>

        <!-- 补充进行中进度条 -->
        <div v-if="supplementing" class="gap-progress">
          <el-progress :percentage="supplementPercent" :stroke-width="8" />
          <p style="font-size:13px;color:#666;margin-top:6px">{{ supplementStage }}</p>
        </div>
      </div>
      <template #footer>
        <el-button @click="gapDialogVisible = false" :disabled="supplementing">取消</el-button>
        <el-button
          v-if="gapData && gapData.missing_dimensions.length > 0"
          type="primary"
          :loading="supplementing"
          :disabled="selectedDimensions.length === 0"
          @click="doSupplementCases"
        >
          生成补充用例（{{ selectedDimensions.length }} 个维度）
        </el-button>
      </template>
    </el-dialog>

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
        <el-button
          v-if="optimizing"
          type="danger"
          plain
          @click="cancelOptimize"
        >
          取消优化
        </el-button>
        <el-button v-else @click="optimizeDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="optimizing"
          @click="doOptimize"
          :disabled="optimizing"
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
          大文件解析 + AI 生成约需 1-3 分钟，点「取消生成」可中止
        </div>
      </div>

      <template #footer>
        <el-button
          v-if="generating"
          type="danger"
          plain
          @click="cancelGenerate"
        >
          取消生成
        </el-button>
        <el-button v-else @click="genDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="generating" @click="doGenerate" :disabled="generating">
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
          <li v-for="(step, i) in (detailCase?.steps || [])" :key="i">{{ String(step).replace(/^\s*\d+\.\s*/, '') }}</li>
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

    <!-- ============================================================
         文档变更：Step-1 上传新文档 + Diff 预览对话框
         ============================================================ -->
    <el-dialog
      v-model="diffDialogVisible"
      title="文档变更 · 增量更新"
      width="640px"
      :close-on-click-modal="false"
    >
      <!-- Step 1: 上传新文档 -->
      <div v-if="diffStep === 1">
        <el-alert
          title="上传新版需求文档后，AI 将自动对比变更范围，仅对发生变化的模块重新生成用例，未变更模块保留原有用例。"
          type="info"
          show-icon
          :closable="false"
          style="margin-bottom:16px"
        />
        <el-form label-width="80px">
          <el-form-item label="需求来源">
            <el-radio-group v-model="diffForm.sourceType">
              <el-radio value="file">上传文档</el-radio>
              <el-radio value="text">手动输入</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item v-if="diffForm.sourceType === 'file'" label="新文档">
            <el-upload
              ref="diffUploadRef"
              :auto-upload="false"
              :limit="1"
              :on-change="handleDiffFileChange"
              :on-remove="() => { diffForm.document_path = ''; diffUploadedFile = null }"
              accept=".pdf,.docx,.doc,.xlsx,.xls,.txt,.md,.html,.htm,.csv,.json,.pptx"
              drag
            >
              <el-icon size="40" color="#c0c4cc"><UploadFilled /></el-icon>
              <div style="font-size:14px;color:#606266;margin-top:8px">
                拖拽新版文档到此处，或 <em style="color:#409eff">点击上传</em>
              </div>
            </el-upload>
            <el-alert v-if="diffUploadError" :title="diffUploadError" type="error" show-icon :closable="false" style="margin-top:8px" />
          </el-form-item>
          <el-form-item v-else label="新文档内容">
            <el-input
              v-model="diffForm.content"
              type="textarea"
              :rows="8"
              placeholder="粘贴新版需求文档内容..."
            />
          </el-form-item>
        </el-form>

        <!-- Diff 分析进度 -->
        <div v-if="diffChecking" class="generating-tip">
          <div class="gen-progress-header">
            <el-icon class="spin"><Loading /></el-icon>
            <span class="gen-stage-text">AI 正在对比文档差异，请稍候...</span>
          </div>
          <el-progress :percentage="50" status="striped" striped striped-flow :duration="4" :show-text="false" style="margin-top:8px" />
        </div>
      </div>

      <!-- Step 2: Diff 结果预览 -->
      <div v-else-if="diffStep === 2 && diffResult">
        <el-alert
          :title="diffResult.diff_summary || '需求文档已变更'"
          :type="diffResult.impact_level === 'high' ? 'error' : diffResult.impact_level === 'medium' ? 'warning' : 'info'"
          show-icon
          :closable="false"
          style="margin-bottom:14px"
        />

        <el-row :gutter="12" style="margin-bottom:12px">
          <el-col :span="6">
            <div class="diff-stat-box diff-changed">
              <div class="diff-stat-num">{{ diffResult.changed?.length || 0 }}</div>
              <div class="diff-stat-label">变更模块</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="diff-stat-box diff-added">
              <div class="diff-stat-num">{{ diffResult.added?.length || 0 }}</div>
              <div class="diff-stat-label">新增模块</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="diff-stat-box diff-removed">
              <div class="diff-stat-num">{{ diffResult.removed?.length || 0 }}</div>
              <div class="diff-stat-label">删除模块</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="diff-stat-box diff-unchanged">
              <div class="diff-stat-num">{{ diffResult.unchanged?.length || 0 }}</div>
              <div class="diff-stat-label">未变更</div>
            </div>
          </el-col>
        </el-row>

        <el-collapse>
          <el-collapse-item v-if="diffResult.changed?.length" name="changed">
            <template #title>
              <el-icon color="#e6a23c"><Warning /></el-icon>
              <span style="margin-left:6px;font-weight:600">变更模块（将重新生成用例）</span>
            </template>
            <div v-for="m in diffResult.changed" :key="m.module" class="diff-module-row diff-changed-row">
              <strong>{{ m.module }}</strong>：{{ m.summary }}
            </div>
          </el-collapse-item>
          <el-collapse-item v-if="diffResult.added?.length" name="added">
            <template #title>
              <el-icon color="#67c23a"><CircleCheck /></el-icon>
              <span style="margin-left:6px;font-weight:600">新增模块（将生成全新用例）</span>
            </template>
            <div v-for="m in diffResult.added" :key="m.module" class="diff-module-row diff-added-row">
              <strong>{{ m.module }}</strong>：{{ m.summary }}
            </div>
          </el-collapse-item>
          <el-collapse-item v-if="diffResult.removed?.length" name="removed">
            <template #title>
              <el-icon color="#f56c6c"><CircleClose /></el-icon>
              <span style="margin-left:6px;font-weight:600">删除模块（旧用例将标记废弃）</span>
            </template>
            <div v-for="name in diffResult.removed" :key="name" class="diff-module-row diff-removed-row">
              {{ name }}
            </div>
          </el-collapse-item>
          <el-collapse-item v-if="diffResult.unchanged?.length" name="unchanged">
            <template #title>
              <el-icon color="#909399"><Document /></el-icon>
              <span style="margin-left:6px;font-weight:600">未变更模块（直接保留）</span>
            </template>
            <div v-for="name in diffResult.unchanged" :key="name" class="diff-module-row">
              {{ name }}
            </div>
          </el-collapse-item>
        </el-collapse>

        <!-- 增量更新进度 -->
        <div v-if="incrementalUpdating" class="generating-tip" style="margin-top:14px">
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
            仅重生成变更模块，速度比全量生成快
          </div>
        </div>
      </div>

      <template #footer>
        <!-- Step 1 -->
        <template v-if="diffStep === 1">
          <el-button @click="diffDialogVisible = false" :disabled="diffChecking">取消</el-button>
          <el-button type="primary" :loading="diffChecking" @click="doDiffCheck">
            {{ diffChecking ? '分析中...' : '分析变更范围' }}
          </el-button>
        </template>
        <!-- Step 2 -->
        <template v-else-if="diffStep === 2">
          <el-button @click="diffStep = 1" :disabled="incrementalUpdating">重新上传</el-button>
          <el-button @click="diffDialogVisible = false" :disabled="incrementalUpdating">取消</el-button>
          <el-button
            type="warning"
            :loading="incrementalUpdating"
            @click="doIncrementalUpdate"
          >
            {{ incrementalUpdating ? '更新中...' : '确认增量更新' }}
          </el-button>
        </template>
      </template>
    </el-dialog>

    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { aiCaseApi, documentApi } from '../api'
import { useWorkspaceStore } from '../stores/workspace'
import { useAuthStore } from '../stores/auth'
import WorkspaceRequired from '../components/WorkspaceRequired.vue'

// ============================================================
// Diff / 增量更新状态
// ============================================================
const wsStore = useWorkspaceStore()
const auth = useAuthStore()
const diffDialogVisible  = ref(false)
const diffStep           = ref(1)           // 1=上传 2=预览
const diffChecking       = ref(false)       // Diff 分析中
const incrementalUpdating = ref(false)      // 增量更新中
const diffResult         = ref(null)        // analyze_document_diff 返回
const diffUploadRef      = ref(null)
const diffUploadedFile   = ref(null)
const diffUploadError    = ref('')
const diffTarget         = ref(null)        // 正在操作哪条记录
const diffNewContent     = ref('')          // 解析后的新文档文本

const diffForm = ref({
  sourceType: 'file',
  document_path: '',
  content: '',
})

const handleDiffFileChange = (file) => {
  const maxMB = 20
  const ext = '.' + file.name.split('.').pop().toLowerCase()
  const allowed = new Set(['.pdf','.docx','.doc','.xlsx','.xls','.txt','.md','.html','.htm','.csv','.json','.pptx'])
  if (!allowed.has(ext)) {
    diffUploadError.value = `不支持的格式 ${ext}`
    diffUploadRef.value?.clearFiles()
    return
  }
  if (file.size > maxMB * 1024 * 1024) {
    diffUploadError.value = `文件超过 ${maxMB}MB`
    diffUploadRef.value?.clearFiles()
    return
  }
  diffUploadError.value = ''
  diffUploadedFile.value = file.raw
}

const openDiffDialog = (r) => {
  diffTarget.value = r
  diffStep.value = 1
  diffResult.value = null
  diffNewContent.value = ''
  diffUploadedFile.value = null
  diffUploadError.value = ''
  diffForm.value = { sourceType: 'file', document_path: '', content: '' }
  diffDialogVisible.value = true
}

/** Step-1：上传文档 + 调 diff-check 接口 */
const doDiffCheck = async () => {
  if (!diffTarget.value) return

  let docPath = ''
  let inlineContent = ''

  if (diffForm.value.sourceType === 'file') {
    if (!diffUploadedFile.value) {
      ElMessage.warning('请先上传新版需求文档')
      return
    }
    diffChecking.value = true
    try {
      const uploadResult = await documentApi.upload(diffUploadedFile.value)
      docPath = uploadResult.file_path || uploadResult.path || ''
    } catch (e) {
      ElMessage.error('文档上传失败: ' + (e.response?.data?.detail || e.message))
      diffChecking.value = false
      return
    }
  } else {
    inlineContent = diffForm.value.content
    if (!inlineContent.trim()) {
      ElMessage.warning('请输入新版需求文档内容')
      return
    }
    diffChecking.value = true
  }

  try {
    const res = await aiCaseApi.diffCheck(diffTarget.value.id, {
      new_document_path: docPath || undefined,
      new_content: inlineContent || undefined,
    })

    if (!res.has_change) {
      ElMessage.info(res.message || '文档内容未发生变化，无需更新用例')
      diffDialogVisible.value = false
      return
    }

    // 无旧文档内容时后端会返回 diff=null，提示直接重新生成
    if (!res.diff) {
      ElMessage.warning(res.message || '旧版文档内容未保存，建议直接重新生成')
      diffDialogVisible.value = false
      return
    }

    // 保存新文档内容，用于后续增量更新
    diffNewContent.value = inlineContent || ''
    diffForm.value.document_path = docPath
    diffResult.value = res.diff
    diffStep.value = 2
  } catch (e) {
    ElMessage.error('Diff 分析失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    diffChecking.value = false
  }
}

/** Step-2：确认增量更新 */
const doIncrementalUpdate = async () => {
  if (!diffTarget.value || !diffResult.value) return
  incrementalUpdating.value = true
  genPercent.value = 0
  genStage.value = '正在连接 AI...'
  connectGenWS()
  try {
    const payload = {
      diff: diffResult.value,
      ...(diffForm.value.document_path
        ? { new_document_path: diffForm.value.document_path }
        : { new_content: diffNewContent.value || diffForm.value.content }),
    }
    const result = await aiCaseApi.incrementalUpdate(diffTarget.value.id, payload)
    genPercent.value = 100
    genStage.value = `增量更新完成！共 ${result.case_count} 条有效用例`
    await new Promise(r => setTimeout(r, 600))
    ElMessage.success(`增量更新成功！共 ${result.case_count} 条有效用例`)
    diffDialogVisible.value = false
    await fetchRecords()
    const found = records.value.find(r => r.id === result.id)
    if (found) current.value = found
  } catch (e) {
    ElMessage.error('增量更新失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    incrementalUpdating.value = false
    disconnectGenWS()
  }
}

const records = ref([])
const current = ref(null)
const openModules = ref(0)

// 覆盖度分析
const coverageDrawerVisible = ref(false)
const coverageData = ref(null)
const coverageTarget = ref(null)
const loadingCoverage = ref(false)

const scoreColor = (s) => s >= 70 ? '#67c23a' : s >= 40 ? '#e6a23c' : '#f56c6c'

// ── 废弃用例显示控制 ──────────────────────────────────────────────────
const showDeprecated = ref(false)   // 默认隐藏废弃用例

/** 判断整个模块是否全部废弃（所有用例都有 status=deprecated） */
const isDeprecatedModule = (mod) => {
  const cases = mod.cases || []
  return cases.length > 0 && cases.every(c => c.status === 'deprecated')
}

/** 模块内有效（非废弃）用例数 */
const activeModCaseCount = (mod) => {
  return (mod.cases || []).filter(c => c.status !== 'deprecated').length
}

/** 根据 showDeprecated 过滤模块内用例 */
const visibleCases = (mod) => {
  if (showDeprecated.value) return mod.cases || []
  return (mod.cases || []).filter(c => c.status !== 'deprecated')
}

/** 当前记录有效用例总数 */
const activeCaseCount = computed(() => {
  if (!current.value?.modules) return 0
  return current.value.modules.reduce((sum, mod) => {
    return sum + (mod.cases || []).filter(c => c.status !== 'deprecated').length
  }, 0)
})

/** 当前记录废弃用例总数 */
const deprecatedCaseCount = computed(() => {
  if (!current.value?.modules) return 0
  return current.value.modules.reduce((sum, mod) => {
    return sum + (mod.cases || []).filter(c => c.status === 'deprecated').length
  }, 0)
})

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

// ── 需求追踪矩阵 ──────────────────────────────────────────────────────────
const tracDrawerVisible = ref(false)
const tracTarget        = ref(null)
const tracLoading       = ref(false)
const tracData          = ref(null)
const tracRequirements  = ref([])
const tracExtracting    = ref(false)
const tracMapping       = ref(false)
const tracTab           = ref('req')
const tracFilter        = ref('')
const tracPercent       = ref(0)
const tracStage         = ref('')
const tracOrphanCases   = ref([])   // 用例视角：未关联需求的用例（可操作）
let   tracWs            = null

const tracStep = computed(() => {
  if (!tracRequirements.value.length) return 0
  if (!tracData.value?.ready) return 1
  return 2
})

const tracMatrixFiltered = computed(() => {
  if (!tracData.value?.matrix) return []
  if (!tracFilter.value) return tracData.value.matrix
  return tracData.value.matrix.filter(r => r.status === tracFilter.value)
})

const tracCoverageColor = (rate) =>
  rate >= 80 ? '#67c23a' : rate >= 50 ? '#e6a23c' : '#f56c6c'

const tracRowStyle = ({ row }) => {
  if (row.status === 'uncovered')    return { background: '#fff0f0' }
  if (row.status === 'insufficient') return { background: '#fffbe6' }
  return {}
}

function connectTracWS() {
  if (tracWs && tracWs.readyState < 2) return
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  tracWs = new WebSocket(`${proto}://${location.host}/ws?client_id=trac_gen`)
  tracWs.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data)
      // 心跳 ping → 回 pong
      if (msg.type === 'ping') { tracWs?.readyState === 1 && tracWs.send(JSON.stringify({ type: 'pong' })); return }
      if (msg.type === 'trac_gen_progress') {
        tracPercent.value = msg.percent ?? tracPercent.value
        tracStage.value   = msg.stage ?? tracStage.value
        if (msg.error) {
          ElMessage.error(msg.stage || '操作失败')
          tracExtracting.value = false
          tracMapping.value    = false
          disconnectTracWS()
        }
      } else if (msg.type === 'trac_extract_done') {
        // 提取完成
        tracRequirements.value = msg.requirements || []
        tracPercent.value = 100
        tracStage.value   = `已提取 ${msg.count} 条需求，请点「重新映射」建立用例关联`
        tracExtracting.value = false
        // 若当前已有矩阵（重新提取场景），不清空矩阵，保留视图，只提示用户
        if (!tracData.value?.ready) {
          tracData.value = null   // 首次提取：进入映射步骤
        }
        ElMessage.success(`已提取 ${msg.count} 条需求`)
        disconnectTracWS()
      } else if (msg.type === 'trac_map_done') {
        // 映射完成，拉取矩阵
        tracPercent.value = 100
        tracStage.value   = '映射完成，正在加载矩阵...'
        tracMapping.value = false
        aiCaseApi.getTraceability(tracTarget.value.id).then(res => {
          _applyTracData(res)
          ElMessage.success('追踪矩阵已生成')
        }).catch(() => {})
        disconnectTracWS()
      }
    } catch (_) {}
  }
  tracWs.onerror = () => {}
  tracWs.onclose = () => {}
}

function disconnectTracWS() {
  if (tracWs) { tracWs.close(); tracWs = null }
}

// 统一设置矩阵数据，同步 tracOrphanCases
const _applyTracData = (res) => {
  tracData.value = res
  tracOrphanCases.value = res?.orphan_cases ? [...res.orphan_cases] : []
  if (res?.ready) {
    tracRequirements.value = res.matrix?.map(row => ({ id: row.req_id })) || []
  }
}

const openTraceability = async (r) => {
  tracTarget.value = r
  tracDrawerVisible.value = true
  tracData.value = null
  tracOrphanCases.value = []
  tracRequirements.value = []
  tracTab.value = 'req'
  tracFilter.value = ''
  tracPercent.value = 0
  tracStage.value = ''
  tracLoading.value = true
  try {
    const res = await aiCaseApi.getTraceability(r.id)
    _applyTracData(res)
    if (!res.ready && res.extracted_at) {
      tracRequirements.value = [{ id: 'placeholder' }]
    }
  } catch (e) {
    ElMessage.error('获取追踪数据失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    tracLoading.value = false
  }
}

const doExtractRequirements = async () => {
  if (!tracTarget.value) return
  tracExtracting.value = true
  tracPercent.value = 10
  tracStage.value = '正在启动需求提取...'
  connectTracWS()
  try {
    await aiCaseApi.extractRequirements(tracTarget.value.id)
    // 接口立即返回，结果通过 WebSocket 推送
    // 兜底：若 WebSocket 断线，120s 后轮询数据库检查结果
    _startTracPoll('extract')
  } catch (e) {
    ElMessage.error('需求提取失败: ' + (e.response?.data?.detail || e.message))
    tracExtracting.value = false
    disconnectTracWS()
  }
}

const doMapCases = async () => {
  if (!tracTarget.value) return
  tracMapping.value = true
  tracPercent.value = 10
  tracStage.value = '正在启动用例映射...'
  connectTracWS()
  try {
    await aiCaseApi.mapCasesToReqs(tracTarget.value.id)
    // 接口立即返回，结果通过 WebSocket 推送
    // 兜底：若 WebSocket 断线，120s 后轮询数据库检查结果
    _startTracPoll('map')
  } catch (e) {
    ElMessage.error('映射失败: ' + (e.response?.data?.detail || e.message))
    tracMapping.value = false
    disconnectTracWS()
  }
}

// ── 追踪任务轮询兜底 ─────────────────────────────────────────────────────────
// WebSocket 断线时，定时拉接口检查任务是否已完成
let _tracPollTimer = null

function _startTracPoll(mode) {
  if (_tracPollTimer) return
  const FIRST_DELAY = 30000   // 首次轮询延迟30秒（给任务时间）
  const INTERVAL    = 10000   // 之后每10秒查一次
  let attempts = 0
  const MAX_ATTEMPTS = 24     // 最多查4分钟

  const check = async () => {
    if (!tracTarget.value) { _stopTracPoll(); return }
    attempts++
    if (attempts > MAX_ATTEMPTS) {
      _stopTracPoll()
      tracExtracting.value = false
      tracMapping.value    = false
      ElMessage.warning('任务超时，请手动刷新')
      return
    }
    try {
      const res = await aiCaseApi.getTraceability(tracTarget.value.id)
      if (mode === 'extract') {
        // 有 requirements_data 说明提取完成
        if (res.extracted_at) {
          _stopTracPoll()
          tracExtracting.value = false
          tracRequirements.value = res.matrix?.map(r => ({ id: r.req_id })) || [{ id: 'placeholder' }]
          if (!tracData.value?.ready) tracData.value = null
          ElMessage.success('需求提取完成（轮询兜底），请建立映射')
        }
      } else if (mode === 'map') {
        // ready=true 说明映射完成
        if (res.ready) {
          _stopTracPoll()
          tracMapping.value = false
          _applyTracData(res)
          ElMessage.success('映射完成（轮询兜底），追踪矩阵已生成')
        }
      }
    } catch (_) {}
  }

  // 首次延迟后再开始
  setTimeout(() => {
    check()
    _tracPollTimer = setInterval(check, INTERVAL)
  }, FIRST_DELAY)
}

function _stopTracPoll() {
  if (_tracPollTimer) { clearInterval(_tracPollTimer); _tracPollTimer = null }
}

// ── 缺口分析 & 补充用例 ───────────────────────────────────────────────────────
const gapDialogVisible    = ref(false)
const gapLoading          = ref(false)
const gapData             = ref(null)
const gapRow              = ref(null)
const selectedDimensions  = ref([])
const supplementing       = ref(false)
const supplementPercent   = ref(0)
const supplementStage     = ref('')
const supplementingReqId  = ref('')

const toggleDimension = (i) => {
  const idx = selectedDimensions.value.indexOf(i)
  if (idx === -1) selectedDimensions.value.push(i)
  else selectedDimensions.value.splice(idx, 1)
}

const openGapAnalysis = async (row) => {
  gapRow.value = row
  gapData.value = null
  selectedDimensions.value = []
  gapDialogVisible.value = true
  gapLoading.value = true
  try {
    const res = await aiCaseApi.analyzeGap(tracTarget.value.id, { req_id: row.req_id })
    gapData.value = res
    // 默认全选缺失维度
    selectedDimensions.value = res.missing_dimensions.map((_, i) => i)
  } catch (e) {
    ElMessage.error('缺口分析失败: ' + (e.response?.data?.detail || e.message))
    gapDialogVisible.value = false
  } finally {
    gapLoading.value = false
  }
}

const doSupplementCases = async () => {
  if (!tracTarget.value || !gapData.value) return
  supplementing.value = true
  supplementPercent.value = 10
  supplementStage.value = '正在启动补充用例生成...'
  supplementingReqId.value = gapData.value.req_id
  connectTracWS()

  // 监听补充完成事件（复用 tracWs，追加 trac_supplement_done 处理）
  const originalOnMessage = tracWs.onmessage
  tracWs.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data)
      if (msg.type === 'trac_gen_progress') {
        supplementPercent.value = msg.percent ?? supplementPercent.value
        supplementStage.value   = msg.stage ?? supplementStage.value
        if (msg.error) {
          ElMessage.error(msg.stage || '补充用例生成失败')
          supplementing.value = false
          supplementingReqId.value = ''
          disconnectTracWS()
        }
      } else if (msg.type === 'trac_supplement_done') {
        supplementPercent.value = 100
        supplementStage.value = `已生成 ${msg.count} 条补充用例`
        supplementing.value = false
        supplementingReqId.value = ''
        gapDialogVisible.value = false
        ElMessage.success(`成功为需求 ${msg.req_id} 生成 ${msg.count} 条补充用例`)
        // 重新加载追踪矩阵（含新增用例），同时刷新主列表
        aiCaseApi.getTraceability(tracTarget.value.id).then(res => {
          _applyTracData(res)
        }).catch(() => {})
        // 同步刷新右侧用例预览（current）
        aiCaseApi.getById(tracTarget.value.id).then(r => {
          const idx = records.value.findIndex(x => x.id === r.id)
          if (idx !== -1) records.value[idx] = r
          if (current.value?.id === r.id) current.value = r
        }).catch(() => {})
        disconnectTracWS()
      }
    } catch (_) {}
  }

  try {
    const missing = selectedDimensions.value.map(i => gapData.value.missing_dimensions[i])
    await aiCaseApi.supplementCases(tracTarget.value.id, {
      req_id: gapData.value.req_id,
      missing_dimensions: missing,
    })
  } catch (e) {
    ElMessage.error('补充用例失败: ' + (e.response?.data?.detail || e.message))
    supplementing.value = false
    supplementingReqId.value = ''
    disconnectTracWS()
  }
}

// ── 用例视角：删除未关联需求的用例 ──────────────────────────────────────────
const deleteOrphanCase = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确认删除用例「${row.case_id} ${row.name}」？删除后不可恢复。`,
      '删除用例', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch { return }

  try {
    await aiCaseApi.deleteCase(tracTarget.value.id, row.case_id)
    // 从用例视角列表里移除
    tracOrphanCases.value = tracOrphanCases.value.filter(c => c.case_id !== row.case_id)
    // 同步刷新主列表（用例数减少）
    const r = await aiCaseApi.getById(tracTarget.value.id)
    const idx = records.value.findIndex(x => x.id === r.id)
    if (idx !== -1) records.value[idx] = r
    if (current.value?.id === r.id) current.value = r
    ElMessage.success('用例已删除')
  } catch (e) {
    ElMessage.error('删除失败: ' + (e.response?.data?.detail || e.message))
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

// 用于取消正在进行的 AI 请求
let _genAbortController = null

const cancelGenerate = () => {
  if (_genAbortController) {
    _genAbortController.abort()
    _genAbortController = null
  }
  generating.value = false
  genPercent.value = 0
  genStage.value = '准备中...'
  disconnectGenWS()
  ElMessage.info('已取消生成')
  genDialogVisible.value = false
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
      // 心跳 ping → 回 pong
      if (msg.type === 'ping') { ws?.readyState === 1 && ws.send(JSON.stringify({ type: 'pong' })); return }
      if (msg.type === 'ai_gen_progress') {
        genPercent.value = msg.percent ?? genPercent.value
        genStage.value = msg.stage ?? genStage.value
        // 生成失败时结束等待
        if (msg.error) {
          generating.value = false
          ElMessage.error(msg.stage || '生成失败')
          disconnectGenWS()
        }
      } else if (msg.type === 'ai_gen_done') {
        // 后台生成完成，刷新列表并关闭对话框
        genPercent.value = 100
        genStage.value = `完成！共 ${msg.case_count} 条用例`
        ElMessage.success(`生成成功！共 ${msg.case_count} 条用例`)
        generating.value = false
        genDialogVisible.value = false
        fetchRecords().then(() => {
          const found = records.value.find(r => r.id === msg.record_id)
          if (found) current.value = found
        })
        disconnectGenWS()
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
// ── 生成状态轮询兜底 ──────────────────────────────────────────────────────
// 当 WebSocket 断线时，通过轮询保证 generating 状态的记录最终能更新
let _genPollTimer = null

function _startGenPolling() {
  if (_genPollTimer) return  // 已在轮询
  _genPollTimer = setInterval(async () => {
    const hasGenerating = records.value.some(r => r.gen_status === 'generating')
    if (!hasGenerating) {
      clearInterval(_genPollTimer)
      _genPollTimer = null
      return
    }
    try {
      const fresh = await aiCaseApi.list(wsStore.currentId)
      if (!fresh) return
      // 只更新状态发生变化的记录，避免整表刷新
      fresh.forEach(r => {
        const idx = records.value.findIndex(x => x.id === r.id)
        if (idx !== -1 && records.value[idx].gen_status !== r.gen_status) {
          records.value[idx] = r
          if (current.value?.id === r.id) current.value = r
          if (r.gen_status === 'done') {
            ElMessage.success(`「${r.task_name}」生成完成，共 ${r.case_count} 条用例`)
          } else if (r.gen_status === 'failed') {
            ElMessage.error(`「${r.task_name}」生成失败`)
          }
        }
      })
      // 没有 generating 记录了，停止轮询
      if (!records.value.some(r => r.gen_status === 'generating')) {
        clearInterval(_genPollTimer)
        _genPollTimer = null
      }
    } catch (_) {}
  }, 5000)  // 每5秒轮询一次
}

const fetchRecords = async () => {
  try {
    const data = await aiCaseApi.list(wsStore.currentId)
    records.value = data || []
    if (records.value.length && !current.value) {
      current.value = records.value[0]
    }
    // 有正在生成的记录，启动轮询兜底
    if (records.value.some(r => r.gen_status === 'generating')) {
      _startGenPolling()
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
  _genAbortController = new AbortController()
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
      workspace_id: wsStore.currentId || null,
      ...(genForm.value.sourceType === 'file'
        ? { document_path: docPath }
        : { content: genForm.value.content }),
    }

    // 后台任务模式：接口立即返回占位记录（gen_status=generating），
    // 后续通过 WebSocket 的 ai_gen_done 事件得知真正完成
    const placeholder = await aiCaseApi.generate(payload, _genAbortController.signal)
    genPercent.value = 10
    genStage.value = '后台生成中，请稍候...'
    // 先把占位记录加入列表（显示"生成中"状态），等 ai_gen_done 时再刷新
    if (placeholder && placeholder.id) {
      await fetchRecords()
    }
    // 不关对话框，等 ws 的 ai_gen_done 再关
  } catch (e) {
    // AbortError 是用户主动取消，不显示错误
    if (e.name === 'CanceledError' || e.name === 'AbortError' || e.code === 'ERR_CANCELED') {
      generating.value = false
      disconnectGenWS()
      return
    }
    const msg = e.response?.data?.detail || e.message || '生成失败'
    ElMessage.error(msg)
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

let _optAbortController = null

const cancelOptimize = () => {
  if (_optAbortController) {
    _optAbortController.abort()
    _optAbortController = null
  }
  optimizing.value = false
  genPercent.value = 0
  genStage.value = '准备中...'
  disconnectGenWS()
  ElMessage.info('已取消优化')
  optimizeDialogVisible.value = false
}

const doOptimize = async () => {
  if (!optimizeTarget.value) return
  optimizing.value = true
  genPercent.value = 0
  genStage.value = '正在连接 AI...'
  _optAbortController = new AbortController()
  connectGenWS()
  try {
    const result = await aiCaseApi.optimize(optimizeTarget.value.id, _optAbortController.signal)
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
    if (e.name === 'CanceledError' || e.name === 'AbortError' || e.code === 'ERR_CANCELED') return
    const msg = e.response?.data?.detail || e.message || '优化失败'
    ElMessage.error(msg)
  } finally {
    optimizing.value = false
    _optAbortController = null
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

// ---------- 模块用例多选 ----------
const selectedCases = ref({})  // { [moduleIndex]: row[] }

const onSelectionChange = (moduleIndex, rows) => {
  selectedCases.value = { ...selectedCases.value, [moduleIndex]: rows }
}

const batchDeleteCases = async (moduleIndex, moduleName) => {
  const rows = selectedCases.value[moduleIndex] || []
  if (!rows.length) return
  try {
    await ElMessageBox.confirm(
      `确认删除「${moduleName}」中选中的 ${rows.length} 条用例？此操作不可恢复。`,
      '批量删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消', confirmButtonClass: 'el-button--danger' }
    )
    let result
    for (const row of rows) {
      result = await aiCaseApi.deleteCase(current.value.id, row.id)
    }
    ElMessage.success(`已删除 ${rows.length} 条用例`)
    selectedCases.value = { ...selectedCases.value, [moduleIndex]: [] }
    if (result) {
      current.value = result
      const idx = records.value.findIndex(r => r.id === result.id)
      if (idx !== -1) records.value[idx] = result
    }
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.response?.data?.detail || e.message || '删除失败')
  }
}


const formatDate = (str) => {
  if (!str) return ''
  try {
    const utc = /[Z+]/.test(str) ? str : str + 'Z'
    return new Date(utc).toLocaleString('zh-CN', { hour12: false })
  } catch { return str }
}

watch(() => wsStore.currentId, () => { fetchRecords() })
onMounted(fetchRecords)
onUnmounted(() => {
  disconnectGenWS()
  disconnectTracWS()
  if (_genPollTimer)  { clearInterval(_genPollTimer);  _genPollTimer  = null }
  if (_tracPollTimer) { clearInterval(_tracPollTimer); _tracPollTimer = null }
})
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

/* 模块统计工具栏 */
.modules-toolbar {
  display: flex;
  align-items: center;
  padding: 6px 4px 10px;
  font-size: 13px;
  color: #606266;
}
.modules-stat { flex: 1; }

/* 废弃模块折叠项整体置灰 */
.deprecated-module { opacity: 0.65; }
.text-deprecated { text-decoration: line-through; color: #c0c4cc; }

/* 废弃行背景 */
:deep(.row-deprecated td) {
  background: #fafafa !important;
  color: #c0c4cc;
}

/* 右侧详情头：两行布局 */
.detail-header {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.detail-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}
.detail-task-name {
  font-size: 15px;
  color: #303133;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 400px;
}
.detail-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.btn-group {
  display: flex;
  align-items: center;
  gap: 6px;
}
.btn-group + .btn-group {
  padding-left: 12px;
  border-left: 1px solid #e4e7ed;
}
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

/* 需求追踪矩阵 */
.trac-panel { padding: 0 4px; }
.trac-guide { padding: 16px 0; }
.trac-progress-box { padding: 20px 0; text-align: center; }
.trac-stage-text { color: #666; font-size: 13px; margin-top: 10px; }
.trac-summary { background: #f8f9fa; border-radius: 8px; padding: 16px; margin-bottom: 16px; }
.trac-stats { display: flex; gap: 16px; margin-top: 8px; }
.trac-stat { text-align: center; flex: 1; }
.trac-stat .num { display: block; font-size: 24px; font-weight: 700; color: #303133; }
.trac-stat .lbl { font-size: 12px; color: #909399; }
.trac-stat.ok .num  { color: #67c23a; }
.trac-stat.warn .num { color: #e6a23c; }
.trac-stat.bad .num  { color: #f56c6c; }

/* 缺口分析对话框 */
.gap-req-info { padding: 8px 0 12px; border-bottom: 1px solid #f0f0f0; margin-bottom: 12px; }
.gap-dimensions { display: flex; flex-direction: column; gap: 8px; max-height: 320px; overflow-y: auto; }
.gap-dim-item { border: 1px solid #e4e7ed; border-radius: 6px; padding: 10px 12px; cursor: pointer; transition: all .2s; }
.gap-dim-item:hover { border-color: #409eff; }
.gap-dim-item.selected { border-color: #409eff; background: #ecf5ff; }
.gap-dim-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.gap-dim-name { font-weight: 600; font-size: 13px; }
.gap-dim-reason { font-size: 12px; color: #666; margin: 4px 0; }
.gap-dim-examples { margin-top: 4px; }
.gap-progress { margin-top: 16px; padding: 12px; background: #f8f9fa; border-radius: 6px; }

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
/* 用例变更标记 */
.case-deprecated { text-decoration: line-through; color: #c0c4cc; }

/* Diff 统计卡片 */
.diff-stat-box {
  text-align: center;
  padding: 10px 6px;
  border-radius: 8px;
  border: 1px solid transparent;
}
.diff-stat-num  { font-size: 24px; font-weight: 700; }
.diff-stat-label { font-size: 12px; margin-top: 2px; }
.diff-changed   { background: #fdf6ec; border-color: #f5dab1; color: #e6a23c; }
.diff-added     { background: #f0f9eb; border-color: #b3e19d; color: #67c23a; }
.diff-removed   { background: #fef0f0; border-color: #fbc4c4; color: #f56c6c; }
.diff-unchanged { background: #f5f7fa; border-color: #dcdfe6; color: #909399; }

/* Diff 模块列表行 */
.diff-module-row {
  padding: 5px 8px;
  font-size: 13px;
  border-radius: 4px;
  margin-bottom: 4px;
}
.diff-changed-row  { background: #fdf6ec; }
.diff-added-row    { background: #f0f9eb; }
.diff-removed-row  { background: #fef0f0; text-decoration: line-through; color: #c0c4cc; }
</style>
