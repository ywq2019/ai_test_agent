<template>
  <div class="cases-page">
    <WorkspaceRequired v-if="auth.role !== 'admin' && !wsStore.currentId" />
    <template v-else>
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <!-- Row 1: Title + Task + Search -->
          <div class="header-row header-row-1">
            <span class="page-title">测试用例管理</span>
            <div class="header-controls">
              <el-select v-model="filterTaskId" placeholder="选择任务" style="width: 180px;" @change="onTaskSelect">
                <el-option v-for="task in taskStore.tasks" :key="task.id" :label="task.name" :value="task.id" />
              </el-select>
              <el-input
                v-model="searchText"
                placeholder="搜索用例名称 / 步骤..."
                clearable
                :prefix-icon="Search"
                style="width: 240px;"
              />
            </div>
          </div>

          <!-- Row 2: Filters -->
          <div class="header-row header-row-2">
            <div class="filter-bar">
              <span class="filter-label">筛选：</span>
              <el-select v-model="filterPriority" placeholder="优先级" clearable style="width: 100px;" size="small">
                <el-option label="P0" value="P0" />
                <el-option label="P1" value="P1" />
                <el-option label="P2" value="P2" />
              </el-select>
              <el-select v-model="filterModule" placeholder="模块" clearable filterable style="width: 140px;" size="small">
                <el-option v-for="m in availableModules" :key="m" :label="m" :value="m" />
              </el-select>
              <el-select v-model="filterStatus" placeholder="状态" clearable style="width: 100px;" size="small">
                <el-option label="启用" value="enabled" />
                <el-option label="禁用" value="disabled" />
                <el-option label="废弃" value="deprecated" />
              </el-select>
              <el-button v-if="hasActiveFilters" link type="primary" size="small" @click="resetFilters">
                <el-icon><RefreshLeft /></el-icon>重置
              </el-button>
              <el-tooltip
                v-if="deprecatedCount > 0"
                :content="showDeprecated ? `当前显示全部（含 ${deprecatedCount} 条废弃）` : `已隐藏 ${deprecatedCount} 条废弃，点击显示`"
                placement="bottom"
              >
                <el-tag
                  :type="showDeprecated ? 'danger' : 'info'"
                  size="small"
                  effect="plain"
                  style="cursor:pointer"
                  @click="showDeprecated = !showDeprecated"
                >
                  <el-icon><Hide v-if="!showDeprecated" /><View v-else /></el-icon>
                  废弃{{ showDeprecated ? '显示' : `(${deprecatedCount})` }}
                </el-tag>
              </el-tooltip>
            </div>
            <span class="filter-count">共 {{ filteredCases.length }} 条</span>
          </div>

          <!-- Row 2.5: 上次执行概要 -->
          <div v-if="lastExecutionSummary && filterTaskId" class="header-row execution-summary-bar">
            <span class="exec-summary-label">上次执行：</span>
            <el-tag :type="lastExecutionSummary.failed > 0 ? 'warning' : 'success'" size="small" effect="plain">
              {{ lastExecutionSummary.passed || 0 }} 通过 / {{ lastExecutionSummary.failed || 0 }} 失败
            </el-tag>
            <span v-if="lastExecutionSummary.created_at" class="exec-summary-time">{{ formatTime(lastExecutionSummary.created_at) }}</span>
            <el-button v-if="lastExecutionFailed.length" link type="primary" size="small" @click="fixCases" :loading="fixing">
              <el-icon><MagicStick /></el-icon>修正 {{ lastExecutionFailed.length }} 条失败用例
            </el-button>
            <el-button v-if="lastExecutionFailed.length" link type="warning" size="small" @click="quickShowFailures">
              仅看失败
            </el-button>
          </div>

          <!-- Row 3: Actions -->
          <div class="header-row header-row-3">
            <div class="action-bar">
              <el-button type="primary" @click="openCreateDialog">
                <el-icon><Plus /></el-icon>新建用例
              </el-button>
              <!-- AI 生成用例 -->
              <el-button type="warning" @click="openGenDialog" :disabled="!filterTaskId" :loading="generating">
                <el-icon><MagicStick /></el-icon>AI 生成用例
              </el-button>
              <!-- AI 规划场景（内嵌抽屉） -->
              <el-button type="success" @click="openScenePlanner" :disabled="!filterTaskId">
                <el-icon><MagicStick /></el-icon>AI 规划场景
              </el-button>
              <!-- 录制用例（内嵌） -->
              <el-button type="primary" plain @click="startRecording" :disabled="!filterTaskId">
                <el-icon><VideoCamera /></el-icon>录制用例
              </el-button>
              <el-tooltip :content="selectedCases.length === 0 ? '请先勾选用例' : `执行选中 ${selectedCases.length} 条`" placement="bottom">
                <el-button type="primary" plain @click="runBatch">
                  <el-icon><VideoPlay /></el-icon>
                  批量执行{{ selectedCases.length > 0 ? `(${selectedCases.length})` : '' }}
                </el-button>
              </el-tooltip>

              <!-- 批量操作（勾选后显示） -->
              <template v-if="selectedCases.length > 0">
                <el-divider direction="vertical" style="height:20px;margin:0 4px" />
                <span style="font-size:13px;color:#606266;white-space:nowrap">已选 {{ selectedCases.length }} 条</span>
                <el-button size="default" :loading="batchEnabling" @click="batchEnable">批量启用</el-button>
                <el-button size="default" :loading="batchDisabling" @click="batchDisable">批量禁用</el-button>
                <el-button size="default" type="danger" plain :loading="batchDeleting" @click="batchDelete">批量删除</el-button>
              </template>
              <el-button size="default" @click="toggleAllSelection" style="margin-left:auto">
                {{ isAllSelected ? '取消全选' : '全选' }}
              </el-button>

              <!-- More actions dropdown（瘦身后） -->
              <el-dropdown trigger="click" :disabled="!filterTaskId">
                <el-button :disabled="!filterTaskId">
                  更多操作<el-icon style="margin-left:4px"><ArrowDown /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item @click="openAliasManager" :disabled="!filterTaskId">
                      <el-icon><CollectionTag /></el-icon>元素别名库
                    </el-dropdown-item>
                    <el-dropdown-item @click="envVarDialogVisible = true" :disabled="!filterTaskId">
                      <el-icon><Setting /></el-icon>环境变量
                    </el-dropdown-item>
                    <el-dropdown-item @click="openSetupCaseDialog" :disabled="!filterTaskId">
                      <el-icon><Connection /></el-icon>登录用例设置
                      <el-tag v-if="currentTaskSetupCaseId" size="small" type="success" style="margin-left:6px">已配置</el-tag>
                    </el-dropdown-item>
                    <el-dropdown-item @click="exportPytest" :disabled="!filterTaskId || exportLoading">
                      <el-icon><Download /></el-icon>导出 pytest 脚本
                    </el-dropdown-item>
                    <el-dropdown-item divided @click="fixCases" :disabled="!filterTaskId || fixing">
                      <el-icon><MagicStick /></el-icon>
                      修正失败用例
                      <el-badge v-if="lastExecutionFailed.length" :value="lastExecutionFailed.length" style="margin-left:6px" />
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>
        </div>
      </template>

      <!-- ══ 主内容 Tabs ══ -->
      <el-tabs v-model="mainTab" type="border-card" style="margin-top:2px">

        <!-- Tab 1：用例列表 -->
        <el-tab-pane label="用例列表" name="list">
      <el-table ref="tableRef" :data="pagedCases" stripe style="width: 100%" @selection-change="handleSelectionChange">
        <el-table-column type="selection" width="40" />
        <el-table-column type="index" label="#" width="55" />
        <el-table-column prop="name" label="用例名称" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <div style="display:flex;align-items:center;gap:4px;flex-wrap:wrap">
              <span :class="{ 'case-deprecated': row.deprecated }">{{ row.name }}</span>
              <el-tag v-if="row.deprecated" size="small" type="danger" effect="plain">废弃</el-tag>
              <el-tag v-else-if="row.is_new" size="small" type="success" effect="dark">NEW</el-tag>
              <el-tag v-else-if="row.is_updated" size="small" type="warning" effect="dark">更新</el-tag>
              <!-- 来源标签 -->
              <el-tooltip :content="sourceLabel(row.source).tip" placement="top">
                <el-tag :type="sourceLabel(row.source).type" size="small" effect="plain" class="source-tag">
                  {{ sourceLabel(row.source).text }}
                </el-tag>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="module" label="模块" width="110" show-overflow-tooltip />
        <el-table-column prop="priority" label="优先级" width="75">
          <template #default="{ row }">
            <el-tag :type="getPriorityType(row.priority)" size="small">{{ row.priority }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="steps" label="测试步骤" min-width="180" show-overflow-tooltip />
        <el-table-column prop="expected_results" label="预期结果" min-width="130" show-overflow-tooltip />
        <el-table-column label="执行状态" width="100" align="center">
          <template #default="{ row }">
            <el-tooltip
              v-if="getCaseExecStatus(row) === 'passed'"
              content="上次执行通过"
              placement="top"
            >
              <el-tag type="success" size="small" effect="dark">通过</el-tag>
            </el-tooltip>
            <!-- AI生成且失败 → 显示重录按钮 -->
            <template v-else-if="getCaseExecStatus(row) === 'failed'">
              <el-tooltip :content="getCaseExecError(row) || '上次执行失败'" placement="top">
                <el-tag type="danger" size="small" effect="dark">失败</el-tag>
              </el-tooltip>
              <el-tooltip v-if="row.source === 'ai_generated'" content="AI生成用例执行失败，建议用录制替换" placement="top">
                <el-button link type="warning" size="small" style="margin-left:2px;padding:0" @click="reRecordCase(row)">
                  重录
                </el-button>
              </el-tooltip>
            </template>
            <span v-else class="exec-unknown">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="enabled" label="状态" width="75">
          <template #default="{ row }">
            <el-tag v-if="row.deprecated" type="danger" size="small" effect="plain">废弃</el-tag>
            <el-tag v-else :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? '启用' : '禁用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right" align="center">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button link type="success" size="small" @click="runSingle(row)">
                <el-icon><VideoPlay /></el-icon>执行
              </el-button>
              <span class="action-sep"></span>
              <el-button link type="primary" size="small" @click="editCase(row)">
                <el-icon><Edit /></el-icon>编辑
              </el-button>
              <span class="action-sep"></span>
              <el-button link type="danger" size="small" @click="deleteCase(row)">
                <el-icon><Delete /></el-icon>删除
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <div v-if="filteredCases.length > pageSize" class="pagination-bar">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :total="filteredCases.length"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @size-change="currentPage = 1"
        />
      </div>

        </el-tab-pane>

        <!-- Tab 2：场景覆盖 -->
        <el-tab-pane name="scene-coverage">
          <template #label>
            <span>
              场景覆盖
              <el-badge v-if="sceneStats.total > 0" :value="`${sceneStats.covered}/${sceneStats.total}`"
                :type="sceneStats.covered === sceneStats.total ? 'success' : 'warning'"
                style="margin-left:4px" />
            </span>
          </template>

          <!-- 无场景规划时引导 -->
          <div v-if="!scenePlanCache.length" class="scene-coverage-empty">
            <el-empty description="当前任务还没有 AI 场景规划">
              <el-button type="primary" @click="goScenePlanner" :disabled="!filterTaskId">
                <el-icon><MagicStick /></el-icon>去 AI 规划场景
              </el-button>
            </el-empty>
          </div>

          <!-- 有场景规划 -->
          <div v-else>
            <!-- 总览进度 -->
            <div class="scene-overview">
              <div class="scene-overview-stats">
                <span class="ov-num">{{ sceneStats.covered }}</span>
                <span class="ov-sep">/</span>
                <span class="ov-total">{{ sceneStats.total }}</span>
                <span class="ov-label">个场景已覆盖</span>
              </div>
              <el-progress
                :percentage="sceneStats.total ? Math.round(sceneStats.covered / sceneStats.total * 100) : 0"
                :status="sceneStats.covered === sceneStats.total ? 'success' : ''"
                :stroke-width="10"
                style="flex:1;max-width:400px"
              />
              <el-button size="small" text @click="goScenePlanner" :disabled="!filterTaskId">
                <el-icon><Refresh /></el-icon>重新规划
              </el-button>
            </div>

            <!-- 场景卡片网格 -->
            <div class="scene-grid">
              <div
                v-for="scene in scenePlanCache"
                :key="scene.id"
                class="scene-cov-card"
                :class="{ 'covered': scene.recorded, 'uncovered': !scene.recorded }"
              >
                <div class="scene-cov-header">
                  <el-tag
                    size="small"
                    :type="scene.priority === 'P0' ? 'danger' : scene.priority === 'P1' ? 'warning' : 'info'"
                    effect="plain"
                  >{{ scene.priority }}</el-tag>
                  <span class="scene-cov-name">{{ scene.name }}</span>
                  <el-tag v-if="scene.recorded" size="small" type="success" effect="dark">✓ 已覆盖</el-tag>
                  <el-tag v-else size="small" type="danger" effect="plain">待录制</el-tag>
                </div>
                <div class="scene-cov-desc">{{ scene.description }}</div>
                <!-- 关联用例 -->
                <div v-if="getCasesForScene(scene).length" class="scene-cov-cases">
                  <div v-for="c in getCasesForScene(scene)" :key="c.id" class="scene-cov-case-item">
                    <el-icon size="12" color="#67c23a"><SuccessFilled /></el-icon>
                    <span>{{ c.name }}</span>
                    <el-button link size="small" type="primary" @click="runSingleById(c)" style="margin-left:auto">执行</el-button>
                  </div>
                </div>
                <!-- 操作 -->
                <div class="scene-cov-actions">
                  <el-button
                    v-if="!scene.recorded"
                    type="primary" size="small"
                    @click="startSceneRecording(scene)"
                  >
                    <el-icon><VideoCamera /></el-icon>去录制
                  </el-button>
                  <el-button
                    v-else size="small" plain
                    @click="startSceneRecording(scene)"
                  >
                    <el-icon><Refresh /></el-icon>重新录制
                  </el-button>
                </div>
              </div>
            </div>
          </div>
        </el-tab-pane>

      </el-tabs>
    </el-card>

    <!-- 生成/优化进度浮层 -->
    <Transition name="gen-toast">
      <div v-if="showProgress" class="gen-toast">
        <!-- 顶部标题栏 -->
        <div class="gen-toast-header">
          <span class="gen-toast-icon">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" style="vertical-align:middle">
              <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"
                fill="currentColor" class="gen-star-fill"/>
            </svg>
          </span>
          <span class="gen-toast-title">{{ progressTitle }}</span>
          <span class="gen-toast-pct">{{ progressPct }}%</span>
        </div>

        <!-- 步骤轨道 -->
        <div class="gen-track">
          <template v-for="(step, i) in genSteps" :key="i">
            <div class="gen-node" :class="{
              'is-done':   progressPct >= step.done,
              'is-active': progressPct >= step.from && progressPct < step.done,
            }">
              <span class="gen-node-ring">
                <svg v-if="progressPct >= step.done" width="10" height="10" viewBox="0 0 12 12">
                  <polyline points="2,6 5,9 10,3" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <span v-else-if="progressPct >= step.from" class="gen-node-pulse"/>
                <span v-else class="gen-node-idx">{{ i + 1 }}</span>
              </span>
              <span class="gen-node-label">{{ step.label }}</span>
            </div>
            <div v-if="i < genSteps.length - 1" class="gen-rail"
              :class="{ 'is-filled': progressPct >= step.done }"/>
          </template>
        </div>

        <!-- 进度条 -->
        <div class="gen-bar-bg">
          <div class="gen-bar-fill" :style="{ width: progressPct + '%' }"/>
        </div>

        <!-- 状态文字 -->
        <div class="gen-stage">
          <span class="gen-stage-dot"/>
          <span class="gen-stage-text">{{ progressStage }}</span>
        </div>

        <!-- 用例计数 -->
        <Transition name="fade">
          <div v-if="genCaseCount > 0" class="gen-count">
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" style="flex-shrink:0">
              <rect x="1" y="3" width="14" height="10" rx="2" stroke="currentColor" stroke-width="1.5"/>
              <path d="M5 7h6M5 9.5h4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
            已生成 <b>{{ genCaseCount }}</b> 条用例
          </div>
        </Transition>

        <!-- 取消按钮 -->
        <div v-if="canCancelGen" class="gen-footer">
          <button class="gen-cancel-btn" @click="cancelGeneration">取消生成</button>
        </div>
      </div>
    </Transition>

    <!-- 用例修正结果弹窗 -->
    <el-dialog v-model="showFixResult" title="用例修正结果" width="680px">
      <div v-if="fixResult" class="fix-result-body">
        <div class="fix-stats">
          <el-tag v-if="fixResult.corrected?.length" type="success">修正 {{ fixResult.corrected.length }} 条</el-tag>
          <el-tag v-if="fixResult.new_cases?.length" type="primary">新增 {{ fixResult.new_cases.length }} 条</el-tag>
        </div>
        <el-collapse v-if="fixResult.corrected?.length">
          <el-collapse-item v-for="(item, idx) in fixResult.corrected" :key="'corr-'+idx" :name="idx">
            <template #title>
              <div class="fix-item-title">
                <el-tag :type="item.confidence === 'high' ? 'success' : item.confidence === 'low' ? 'warning' : 'primary'" size="small" effect="plain">
                  {{ item.confidence === 'high' ? '高' : '低' }}
                </el-tag>
                <span class="fix-case-name">{{ item.case_name || item.name }}</span>
              </div>
            </template>
            <div class="fix-compare">
              <div class="fix-before"><strong>原步骤：</strong><pre>{{ item.steps }}</pre></div>
              <div class="fix-after" v-if="item.corrected_steps"><strong>修正后：</strong><pre>{{ item.corrected_steps }}</pre></div>
              <div class="fix-note" v-if="item.fix_note"><el-icon><InfoFilled /></el-icon>{{ item.fix_note }}</div>
            </div>
          </el-collapse-item>
        </el-collapse>
        <div v-if="fixResult.new_cases?.length" style="margin-top:12px">
          <el-divider>补充用例（{{ fixResult.new_cases.length }} 条）</el-divider>
          <div v-for="(nc, idx) in fixResult.new_cases" :key="'nc-'+idx" class="new-case-item">
            <el-tag :type="nc.priority === 'P0' ? 'danger' : nc.priority === 'P2' ? 'info' : 'warning'" size="small">{{ nc.priority || 'P1' }}</el-tag>
            <span>{{ nc.name }}</span>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button size="small" @click="showFixResult = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 登录用例设置弹窗（方案三：storage_state）-->
    <el-dialog v-model="showSetupCaseDialog" title="🔑 登录用例设置" width="500px" :close-on-click-modal="false">
      <el-alert type="info" :closable="false" style="margin-bottom:18px">
        <template #title>
          配置后，批量执行前会自动跑一次指定的登录用例并保存浏览器登录态（cookie/token），
          后续用例直接复用登录态，<b>无需每条用例重复登录</b>。<br>
          快照过期后会自动重新执行登录用例刷新。
        </template>
      </el-alert>
      <el-form label-width="90px" label-position="left">
        <el-form-item label="登录用例">
          <el-select v-model="setupCaseForm.setup_case_id" placeholder="选择一条录制的登录用例" clearable style="width:100%">
            <el-option :value="null" label="不使用登录用例（每条用例独立执行）" />
            <el-option
              v-for="c in currentTaskCases"
              :key="c.id"
              :label="`[${c.id}] ${c.name}`"
              :value="c.id"
            >
              <span>{{ c.name }}</span>
              <el-tag size="small" :type="c.source === 'recorded' ? 'success' : 'warning'"
                style="margin-left:8px">{{ c.source === 'recorded' ? '录制' : c.source === 'ai_generated' ? 'AI' : '手动' }}</el-tag>
            </el-option>
          </el-select>
          <div style="font-size:12px;color:#909399;margin-top:4px">建议选择「录制」来源的登录用例，稳定性更高</div>
        </el-form-item>
        <el-form-item label="快照有效期">
          <el-input-number v-model="setupCaseForm.storage_ttl_minutes"
            :min="0" :max="1440" :step="30" controls-position="right" style="width:140px"/>
          <span style="margin-left:8px;font-size:13px;color:#606266">分钟（0 = 每次执行都重新登录）</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showSetupCaseDialog = false">取消</el-button>
        <el-button type="primary" @click="saveSetupCase" :loading="savingSetupCase">保存设置</el-button>
      </template>
    </el-dialog>

    <!-- AI 生成用例配置弹窗 -->
    <el-dialog v-model="showGenDialog" title="🤖 AI 生成用例" width="540px" :close-on-click-modal="false">
      <el-form :model="genForm" label-width="90px" label-position="left">

        <el-form-item label="测试重点">
          <el-input
            v-model="genForm.user_prompt"
            type="textarea"
            :rows="4"
            placeholder="可选。用自然语言描述你的测试重点、特殊要求或背景，AI 会按此生成更贴合的用例。

示例：重点测试登录校验逻辑，包括密码错误次数限制；忽略注册流程。"
          />
        </el-form-item>

        <el-form-item>
          <template #label>
            <span>指定模块</span>
            <el-tooltip content="只生成指定模块的用例，多个模块用逗号或换行分隔。不填则生成全部模块。" placement="top">
              <el-icon style="margin-left:4px;color:#909399;cursor:help"><QuestionFilled /></el-icon>
            </el-tooltip>
          </template>
          <el-input
            v-model="genForm.focus_modules"
            type="textarea"
            :rows="2"
            placeholder="可选，示例：登录模块, 搜索模块"
          />
        </el-form-item>

        <el-form-item>
          <template #label>
            <span>用例数量</span>
            <el-tooltip content="期望生成的用例总数，AI 会按模块均匀分配。留空则由 AI 自动决定（通常 8-12 条/模块）。" placement="top">
              <el-icon style="margin-left:4px;color:#909399;cursor:help"><QuestionFilled /></el-icon>
            </el-tooltip>
          </template>
          <el-input-number
            v-model="genForm.target_count"
            :min="0"
            :max="200"
            :step="5"
            placeholder="留空由 AI 决定"
            style="width:160px"
            controls-position="right"
          />
          <span style="margin-left:8px;color:#909399;font-size:12px">条（0 = 不限制）</span>
        </el-form-item>

        <el-form-item label="重新抓取">
          <el-switch v-model="reparseBeforeGen" />
          <span style="margin-left:8px;color:#909399;font-size:12px">重新抓取页面元素（页面已更新时开启）</span>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showGenDialog = false">取消</el-button>
        <el-button type="warning" @click="confirmGenDialog">
          <el-icon><MagicStick /></el-icon>开始生成
        </el-button>
      </template>
    </el-dialog>

    <!-- 新建/编辑弹窗 -->
    <el-dialog v-model="showCreateDialog" :title="editingCase ? '编辑用例' : '新建用例'"
      width="860px" :close-on-click-modal="false">
      <el-tabs v-model="caseEditTab" type="border-card" style="min-height:360px">

        <!-- Tab 1：基本信息 -->
        <el-tab-pane label="基本信息" name="info">
          <el-form :model="caseForm" label-width="90px" style="padding:8px 4px 0">
            <el-form-item label="所属任务">
              <el-select v-model="caseForm.task_id" style="width:100%">
                <el-option v-for="task in taskStore.tasks" :key="task.id" :label="task.name" :value="task.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="用例名称">
              <el-input v-model="caseForm.name" placeholder="请输入用例名称" />
            </el-form-item>
            <el-form-item label="所属模块">
              <el-input v-model="caseForm.module" placeholder="请输入所属模块" />
            </el-form-item>
            <el-form-item label="优先级">
              <el-select v-model="caseForm.priority" style="width:100%">
                <el-option label="P0 - 核心必测" value="P0" />
                <el-option label="P1 - 常规测试" value="P1" />
                <el-option label="P2 - 次要场景" value="P2" />
              </el-select>
            </el-form-item>
            <el-form-item label="前置条件">
              <el-input v-model="caseForm.preconditions" type="textarea" :rows="2" />
            </el-form-item>
            <el-form-item label="测试步骤">
              <el-input v-model="caseForm.steps" type="textarea" :rows="3"
                placeholder="文字描述，步骤编辑器中可编辑结构化步骤" />
            </el-form-item>
            <el-form-item label="预期结果" required>
              <el-input v-model="caseForm.expected_results" type="textarea" :rows="2"
                placeholder="必填，如：登录成功，跳转到首页" />
            </el-form-item>
            <el-form-item label="启用状态">
              <el-switch v-model="caseForm.enabled" />
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <!-- Tab 2：步骤编辑器（仅编辑已有用例时可用） -->
        <el-tab-pane name="steps-editor" :disabled="!editingCase">
          <template #label>
            <el-tooltip :content="editingCase ? '' : '新建用例保存后才能编辑步骤'" placement="top">
              <span>
                步骤编辑器
                <el-tag v-if="editingCase && stepsJson.length" size="small" type="info"
                  style="margin-left:4px">{{ stepsJson.length }}步</el-tag>
              </span>
            </el-tooltip>
          </template>

          <!-- 工具栏 -->
          <div class="step-editor-toolbar">
            <el-button size="small" type="primary" plain @click="addStep">
              <el-icon><Plus /></el-icon>添加步骤
            </el-button>
            <el-button size="small" :loading="stepsLoading" @click="reloadSteps" :disabled="!editingCase">
              <el-icon><Refresh /></el-icon>重新加载
            </el-button>
            <div style="margin-left:auto;display:flex;align-items:center;gap:8px">
              <span style="font-size:12px;color:#909399">健壮度：</span>
              <el-tag size="small" type="success" effect="plain">A 稳定</el-tag>
              <el-tag size="small" type="warning" effect="plain">B 一般</el-tag>
              <el-tag size="small" type="info" effect="plain">C 可用</el-tag>
              <el-tag size="small" type="danger" effect="plain">D 风险</el-tag>
            </div>
          </div>

          <!-- 步骤列表 -->
          <div v-if="stepsLoading" style="text-align:center;padding:40px 0;color:#909399">
            <el-icon class="is-loading"><Loading /></el-icon> 加载中...
          </div>
          <div v-else-if="!stepsJson.length" style="text-align:center;padding:40px 0">
            <el-empty description="暂无结构化步骤">
              <el-button size="small" type="primary" @click="addStep">添加第一个步骤</el-button>
            </el-empty>
          </div>
          <div v-else class="step-table">
            <!-- 表头 -->
            <div class="step-row step-header">
              <div class="step-col col-num">#</div>
              <div class="step-col col-grade">健壮度</div>
              <div class="step-col col-action">Action</div>
              <div class="step-col col-selector">Selector（点击切换备选）</div>
              <div class="step-col col-value">Value / Expected</div>
              <div class="step-col col-opts">超时/可选</div>
              <div class="step-col col-ops">操作</div>
            </div>

            <div v-for="(step, idx) in stepsJson" :key="step.id || idx" class="step-row"
              :class="{ 'step-row-danger': step.robustness === 'D', 'step-row-auto': step._auto_inserted }">

              <!-- 序号 -->
              <div class="step-col col-num">
                <span class="step-seq">{{ idx + 1 }}</span>
              </div>

              <!-- 健壮度 -->
              <div class="step-col col-grade">
                <el-tooltip v-if="step.robustness"
                  :content="gradeDesc(step.robustness)" placement="top">
                  <el-tag :type="gradeType(step.robustness)" size="small" effect="plain"
                    class="grade-badge">
                    {{ step.robustness || '-' }}
                  </el-tag>
                </el-tooltip>
                <span v-else style="color:#c0c4cc;font-size:12px">-</span>
              </div>

              <!-- Action -->
              <div class="step-col col-action">
                <el-select v-model="step.action" size="small" style="width:100%"
                  @change="onActionChange(step)">
                  <el-option-group label="交互">
                    <el-option label="navigate — 跳转页面" value="navigate" />
                    <el-option label="click — 点击" value="click" />
                    <el-option label="fill — 填写输入框（清空后输入）" value="fill" />
                    <el-option label="type — 逐字输入（追加）" value="type" />
                    <el-option label="select — 下拉选择" value="select" />
                    <el-option label="check — 勾选复选框" value="check" />
                    <el-option label="uncheck — 取消勾选" value="uncheck" />
                    <el-option label="hover — 鼠标悬停" value="hover" />
                    <el-option label="dblclick — 双击" value="dblclick" />
                    <el-option label="rightclick — 右键" value="rightclick" />
                    <el-option label="press — 按键（Enter/Tab…）" value="press" />
                    <el-option label="scroll — 滚动到元素" value="scroll" />
                    <el-option label="upload — 上传文件" value="upload" />
                    <el-option label="submit — 提交表单" value="submit" />
                    <el-option label="keydown — 键盘事件" value="keydown" />
                    <el-option label="wait — 固定等待（ms）" value="wait" />
                  </el-option-group>
                  <el-option-group label="断言">
                    <el-option label="assert_text — 断言文本内容" value="assert_text" />
                    <el-option label="assert_visible — 断言元素可见" value="assert_visible" />
                    <el-option label="assert_hidden — 断言元素隐藏" value="assert_hidden" />
                    <el-option label="assert_url — 断言当前 URL" value="assert_url" />
                    <el-option label="assert_title — 断言页面标题" value="assert_title" />
                    <el-option label="assert_count — 断言元素数量" value="assert_count" />
                  </el-option-group>
                  <el-option-group label="其他">
                    <el-option label="wait_for — 等待元素/URL 出现" value="wait_for" />
                    <el-option label="screenshot — 截图检查点" value="screenshot" />
                    <el-option label="evaluate — 执行 JS 代码" value="evaluate" />
                  </el-option-group>
                </el-select>
              </div>

              <!-- Selector（带备选下拉） -->
              <div class="step-col col-selector">
                <template v-if="needsSelector(step.action)">
                  <el-popover
                    v-if="(step.selectors || []).length > 1"
                    placement="bottom-start" :width="320" trigger="click">
                    <template #reference>
                      <div class="selector-pill"
                        :class="'grade-' + (step.robustness || 'D').toLowerCase()">
                        <el-icon v-if="step.robustness === 'D'" color="#f56c6c" size="12">
                          <WarningFilled />
                        </el-icon>
                        <span class="selector-text">{{ step.selector || '点击设置' }}</span>
                        <el-icon size="10" color="#909399"><ArrowDown /></el-icon>
                      </div>
                    </template>
                    <!-- 备选列表 -->
                    <div class="sel-candidates">
                      <div style="font-size:12px;color:#909399;margin-bottom:8px">
                        选择备选 Selector（按稳定性排序）：
                      </div>
                      <div v-for="(cand, ci) in (step.selectors || [])" :key="ci"
                        class="sel-candidate-item"
                        :class="{ 'sel-active': cand === step.selector }"
                        @click="applySelector(step, cand)">
                        <el-tag :type="gradeType(selectorGrade(cand))" size="small" effect="plain"
                          style="flex-shrink:0">{{ selectorGrade(cand) }}</el-tag>
                        <span class="sel-cand-text">{{ cand }}</span>
                        <el-icon v-if="cand === step.selector" color="#67c23a"><Select /></el-icon>
                      </div>
                      <div style="margin-top:8px;border-top:1px solid #f0f0f0;padding-top:8px">
                        <SelectorInput v-model="step.selector" size="small"
                          placeholder="或手动输入，@ 触发别名补全"
                          :aliases="aliasList"
                          @change="updateStepGrade(step); saveSteps(true)" />
                      </div>
                    </div>
                  </el-popover>
                  <SelectorInput v-else v-model="step.selector" size="small"
                    placeholder="selector，@ 触发别名补全"
                    :aliases="aliasList"
                    @change="updateStepGrade(step); saveSteps(true)" />
                </template>
                <!-- navigate/assert_url 用 url/expected 字段 -->
                <template v-else-if="step.action === 'navigate'">
                  <el-input v-model="step.url" size="small" placeholder="https://..." />
                </template>
                <span v-else style="color:#c0c4cc;font-size:12px">—</span>
              </div>

              <!-- Value / Expected -->
              <div class="step-col col-value">
                <el-input
                  v-if="needsValue(step.action)"
                  v-model="step.value" size="small"
                  :placeholder="valuePlaceholder(step.action)" />
                <el-input
                  v-else-if="needsExpected(step.action)"
                  v-model="step.expected" size="small"
                  :placeholder="'期望：' + (step.action === 'assert_url' ? 'URL 关键词' : '文本/正则')" />
                <span v-else style="color:#c0c4cc;font-size:12px">—</span>
              </div>

              <!-- 超时 / optional -->
              <div class="step-col col-opts">
                <el-input-number v-model="step.timeout" size="small" :min="500" :max="60000"
                  :step="1000" style="width:90px" controls-position="right" />
                <el-tooltip content="可选：失败不中断" placement="top">
                  <el-checkbox v-model="step.optional" size="small" style="margin-left:4px" />
                </el-tooltip>
              </div>

              <!-- 操作 -->
              <div class="step-col col-ops">
                <el-button-group>
                  <el-button size="small" :disabled="idx === 0" @click="moveStep(idx, -1)"
                    title="上移">↑</el-button>
                  <el-button size="small" :disabled="idx === stepsJson.length - 1"
                    @click="moveStep(idx, 1)" title="下移">↓</el-button>
                </el-button-group>
                <el-button size="small" type="danger" plain @click="removeStep(idx)"
                  style="margin-left:4px"><el-icon><Delete /></el-icon></el-button>
              </div>
            </div>
          </div>

          <!-- 末尾快速添加步骤按钮 -->
          <div class="add-step-btn" @click="addStep">
            <el-icon><Plus /></el-icon>
            <span>添加步骤</span>
          </div>

        </el-tab-pane>

        <!-- Tab 3：前置步骤（方案一）-->
        <el-tab-pane name="setup-steps" :disabled="!editingCase">
          <template #label>
            <el-tooltip :content="editingCase ? '' : '新建用例保存后才能编辑前置步骤'" placement="top">
              <span>
                前置步骤
                <el-tag v-if="editingCase && setupStepsJson.length" size="small" type="warning"
                  style="margin-left:4px">{{ setupStepsJson.length }}步</el-tag>
              </span>
            </el-tooltip>
          </template>

          <div style="padding:12px 0 4px">
            <el-alert type="info" :closable="false" style="margin-bottom:14px">
              <template #title>
                <b>前置步骤</b>在主步骤之前执行，与主步骤共用同一个浏览器页面。<br>
                适合：导航到特定页面、展开弹窗等操作。登录态请在<b>任务设置 → 登录用例</b>中配置。
              </template>
            </el-alert>

            <div class="steps-editor-wrap" style="max-height:300px;overflow-y:auto">
              <div v-if="!setupStepsJson.length"
                style="padding:24px;text-align:center;color:#c0c4cc;font-size:13px">
                暂无前置步骤
              </div>
              <div v-for="(step, idx) in setupStepsJson" :key="step.id || idx" class="step-row">
                <span class="step-idx">{{ idx + 1 }}</span>

                <!-- Action 下拉（同主步骤编辑器） -->
                <el-select v-model="step.action" size="small" style="width:136px;flex-shrink:0"
                  @change="onSetupActionChange(step)">
                  <el-option-group label="交互">
                    <el-option label="navigate — 跳转页面" value="navigate" />
                    <el-option label="click — 点击" value="click" />
                    <el-option label="fill — 填写输入框" value="fill" />
                    <el-option label="type — 逐字输入" value="type" />
                    <el-option label="select — 下拉选择" value="select" />
                    <el-option label="check — 勾选" value="check" />
                    <el-option label="uncheck — 取消勾选" value="uncheck" />
                    <el-option label="hover — 悬停" value="hover" />
                    <el-option label="dblclick — 双击" value="dblclick" />
                    <el-option label="press — 按键" value="press" />
                    <el-option label="scroll — 滚动" value="scroll" />
                    <el-option label="submit — 提交表单" value="submit" />
                    <el-option label="wait — 固定等待(ms)" value="wait" />
                  </el-option-group>
                  <el-option-group label="断言">
                    <el-option label="assert_text — 断言文本" value="assert_text" />
                    <el-option label="assert_visible — 断言可见" value="assert_visible" />
                    <el-option label="assert_hidden — 断言隐藏" value="assert_hidden" />
                    <el-option label="assert_url — 断言URL" value="assert_url" />
                  </el-option-group>
                  <el-option-group label="其他">
                    <el-option label="wait_for — 等待元素" value="wait_for" />
                    <el-option label="screenshot — 截图" value="screenshot" />
                    <el-option label="evaluate — 执行JS" value="evaluate" />
                  </el-option-group>
                </el-select>

                <!-- navigate → url 字段；有 selector 的 action → selector；其他 → 占位 -->
                <template v-if="step.action === 'navigate'">
                  <el-input v-model="step.url" size="small" placeholder="https://..." style="flex:1;min-width:0"/>
                </template>
                <template v-else-if="needsSelector(step.action)">
                  <el-input v-model="step.selector" size="small" placeholder="selector" style="flex:1;min-width:0"/>
                </template>
                <template v-else>
                  <span style="flex:1"/>
                </template>

                <!-- Value / Expected -->
                <el-input
                  v-if="needsValue(step.action)"
                  v-model="step.value" size="small"
                  :placeholder="valuePlaceholder(step.action)"
                  style="width:110px;flex-shrink:0"/>
                <el-input
                  v-else-if="needsExpected(step.action)"
                  v-model="step.expected" size="small"
                  :placeholder="step.action === 'assert_url' ? 'URL 关键词' : '期望文本'"
                  style="width:110px;flex-shrink:0"/>
                <span v-else style="width:110px;flex-shrink:0"/>

                <!-- 说明 -->
                <el-input v-model="step.description" size="small" placeholder="说明（可选）"
                  style="width:110px;flex-shrink:0"/>

                <el-button link type="danger" size="small" @click="setupStepsJson.splice(idx,1)">
                  <el-icon><Delete /></el-icon>
                </el-button>
              </div>
            </div>

            <div class="add-step-btn" @click="addSetupStep" style="margin-top:10px">
              <el-icon><Plus /></el-icon><span>添加前置步骤</span>
            </div>

            <el-divider style="margin:14px 0 10px"/>
            <div style="display:flex;align-items:center;gap:10px">
              <el-switch v-model="caseUseStorage" />
              <span style="font-size:13px;color:#606266">
                执行时加载任务级登录态快照
              </span>
              <el-tooltip content="关闭后以全新浏览器状态运行，适合「登录用例」本身" placement="top">
                <el-icon style="color:#909399;cursor:help"><QuestionFilled /></el-icon>
              </el-tooltip>
            </div>
          </div>
        </el-tab-pane>

      </el-tabs>

      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button v-if="caseEditTab === 'steps-editor' && editingCase"
          type="success" @click="saveSteps" :loading="saving">
          保存步骤
        </el-button>
        <el-button v-else-if="caseEditTab === 'setup-steps' && editingCase"
          type="warning" @click="saveSetupSteps" :loading="saving">
          保存前置步骤
        </el-button>
        <el-button v-else type="primary" @click="saveCase" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- ══ 元素别名库管理弹窗 ══ -->
    <el-dialog v-model="aliasDialogVisible" title="元素别名库" width="660px"
      :close-on-click-modal="false" destroy-on-close>
      <div style="margin-bottom:12px;display:flex;align-items:center;justify-content:space-between">
        <span style="font-size:13px;color:#606266">
          用 <code style="background:#f5f5f5;padding:1px 4px;border-radius:3px">@别名</code>
          在步骤 selector 里引用，执行时自动按优先级尝试候选列表
        </span>
        <el-button type="primary" size="small" @click="openAliasForm()">
          <el-icon><Plus /></el-icon>新建别名
        </el-button>
      </div>

      <el-table :data="aliasList" size="small" stripe style="width:100%" v-loading="aliasLoading">
        <el-table-column prop="name" label="别名（@名称）" width="130">
          <template #default="{ row }">
            <code style="color:#409eff">@{{ row.name }}</code>
          </template>
        </el-table-column>
        <el-table-column label="Selector 列表（优先级从高到低）" min-width="220">
          <template #default="{ row }">
            <div v-for="(sel, i) in (row.selectors || [])" :key="i"
              style="display:flex;align-items:center;gap:4px;margin-bottom:2px">
              <el-tooltip :content="gradeDesc(selectorGrade(sel))" placement="top">
                <el-tag :type="gradeType(selectorGrade(sel))" size="small" effect="plain" style="flex-shrink:0">
                  {{ selectorGrade(sel) }}
                </el-tag>
              </el-tooltip>
              <span style="font-size:12px;color:#303133;word-break:break-all">{{ sel }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="说明" min-width="100" show-overflow-tooltip />
        <el-table-column label="操作" width="100" align="center">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openAliasForm(row)">编辑</el-button>
            <el-button link type="danger" size="small" @click="deleteAlias(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!aliasLoading && !aliasList.length" description="暂无别名，点击「新建别名」添加" />
    </el-dialog>

    <!-- 别名编辑子弹窗 -->
    <el-dialog v-model="aliasFormVisible"
      :title="editingAlias ? '编辑别名' : '新建别名'"
      width="520px" append-to-body>
      <el-form :model="aliasForm" label-width="80px" size="small">
        <el-form-item label="别名名称">
          <el-input v-model="aliasForm.name" placeholder="如：登录按钮（引用时用 @登录按钮）" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="aliasForm.description" placeholder="可选，描述这个元素的作用" />
        </el-form-item>
        <el-form-item label="Selector">
          <div v-for="(sel, i) in aliasForm.selectors" :key="i"
            style="display:flex;gap:6px;margin-bottom:6px;align-items:center">
            <el-tooltip :content="gradeDesc(selectorGrade(sel))" placement="top">
              <el-tag :type="gradeType(selectorGrade(sel))" size="small" effect="plain"
                style="flex-shrink:0;width:28px;text-align:center">
                {{ selectorGrade(sel) }}
              </el-tag>
            </el-tooltip>
            <el-input v-model="aliasForm.selectors[i]" size="small"
              :placeholder="`Selector ${i+1}（优先级第 ${i+1} 位）`" style="flex:1" />
            <el-button link type="danger" size="small" @click="aliasForm.selectors.splice(i,1)">×</el-button>
          </div>
          <el-button size="small" text @click="aliasForm.selectors.push('')" style="margin-top:4px">
            <el-icon><Plus /></el-icon>添加 Selector
          </el-button>
          <div style="font-size:12px;color:#909399;margin-top:6px">
            A 级最稳（data-testid / role= / label=），D 级最脆（纯 class / tag），建议 A→D 顺序填写
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="aliasFormVisible = false">取消</el-button>
        <el-button type="primary" @click="saveAlias" :loading="aliasSaving">保存</el-button>
      </template>
    </el-dialog>

    <!-- ══ 环境变量 dialog ══ -->
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

    <!-- ══ 录制 dialog ══ -->
    <el-dialog v-model="recordingDialogVisible" title="录制操作" width="520px" :close-on-click-modal="false">
      <el-alert v-if="recordingStarting" type="info" show-icon :closable="false" style="margin-bottom:12px;">
        <template #title>
          <el-icon class="is-loading" style="margin-right:6px"><Loading /></el-icon>
          浏览器启动中，请稍候（约 15-20 秒）...
        </template>
      </el-alert>
      <el-alert v-else-if="isRecording" type="warning" show-icon :closable="false" style="margin-bottom:12px;">
        浏览器已弹出，请在页面中操作，步骤会实时预览。完成后点击「停止录制」。
      </el-alert>
      <template v-if="!isRecording && !recordingStarting && recordedSteps.length">
        <el-alert type="success" show-icon :closable="false" style="margin-bottom:12px;">
          录制完成，共 {{ recordedSteps.length }} 个步骤
        </el-alert>
        <el-input v-model="recordingCaseName" placeholder="用例名称" style="margin-bottom:10px;" />
      </template>
      <el-scrollbar max-height="300px" v-if="recordedSteps.length">
        <div class="rec-step-list">
          <div v-for="(s, i) in recordedSteps" :key="i" class="rec-step-item">
            <span class="rec-step-num">{{ i + 1 }}</span>
            <el-tag size="small" :type="actionTagType(s.action)" effect="plain" class="rec-step-tag">{{ s.action }}</el-tag>
            <div class="rec-step-body">
              <span class="rec-step-desc">{{ s.description || (s.action === 'navigate' ? s.url : s.selector) || s.value || '' }}</span>
              <span v-if="s.selector && s.action !== 'navigate'" class="rec-step-sel">{{ s.selector }}</span>
              <span v-if="s.value && ['fill','type','select'].includes(s.action)" class="rec-step-val">= {{ s.value }}</span>
            </div>
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
    <el-drawer v-model="scenePlannerVisible" direction="rtl" size="540px"
      :close-on-click-modal="false" class="scene-planner-drawer">
      <template #header>
        <div class="scene-drawer-header">
          <div class="scene-drawer-title">
            <div class="scene-drawer-icon-wrap">
              <el-icon size="16"><MagicStick /></el-icon>
            </div>
            <span>AI 场景规划</span>
            <el-tag v-if="scenes.length" size="small" round class="scene-count-badge">
              {{ scenes.length }} 个场景
            </el-tag>
          </div>
          <template v-if="scenes.length">
            <div class="scene-drawer-progress">
              <span class="scene-progress-label">
                <span class="scene-progress-done">{{ scenes.filter(s=>s.recorded).length }}</span>
                <span class="scene-progress-sep">/</span>
                <span>{{ scenes.length }}</span>
                <span class="scene-progress-unit">已录制</span>
              </span>
              <el-progress
                :percentage="Math.round(scenes.filter(s=>s.recorded).length/scenes.length*100)"
                :stroke-width="6" style="width:80px"
                :status="scenes.every(s=>s.recorded) ? 'success' : ''"
              />
            </div>
          </template>
        </div>
      </template>

      <!-- 输入区（未生成时） -->
      <div v-if="!scenes.length" class="scene-input-area">
        <!-- 信息卡 -->
        <div class="scene-intro-card">
          <div class="scene-intro-hero">
            <div class="scene-intro-icon-wrap">
              <el-icon size="22" color="#fff"><MagicStick /></el-icon>
            </div>
            <div class="scene-intro-text">
              <div class="scene-intro-title">智能场景规划</div>
              <div class="scene-intro-subtitle">AI 将从以下维度自动分析并生成测试场景</div>
            </div>
          </div>
          <div class="scene-dimensions">
            <span v-for="d in sceneDimensions" :key="d.name" :class="`dim-pill dim-${d.type}`">
              <span class="dim-dot"></span>{{ d.name }}
            </span>
          </div>
        </div>

        <!-- 状态提示行 -->
        <div class="scene-status-row">
          <div v-if="!hasPageElements" class="scene-status-item scene-status-warn">
            <div class="scene-status-icon-wrap warn">
              <el-icon size="13"><WarningFilled /></el-icon>
            </div>
            <div class="scene-status-content">
              <span class="scene-status-text">未抓取页面元素</span>
              <span class="scene-status-sub">规划精度有限，建议先抓取</span>
            </div>
            <el-button size="small" type="warning" plain :loading="parsingPage"
              @click="parseCurrentPage" class="scene-status-btn">
              {{ parsingPage ? '抓取中...' : '去抓取' }}
            </el-button>
          </div>
          <div v-else class="scene-status-item scene-status-ok">
            <div class="scene-status-icon-wrap ok">
              <el-icon size="13"><SuccessFilled /></el-icon>
            </div>
            <div class="scene-status-content">
              <span class="scene-status-text">已抓取页面元素</span>
              <span class="scene-status-sub">AI 将结合元素精准规划</span>
            </div>
            <el-button size="small" link @click="parseCurrentPage" :loading="parsingPage"
              class="scene-status-link">重新抓取</el-button>
          </div>
          <div v-if="hasDocument" class="scene-status-item scene-status-doc">
            <div class="scene-status-icon-wrap doc">
              <el-icon size="13"><DocumentChecked /></el-icon>
            </div>
            <div class="scene-status-content">
              <span class="scene-status-text">已关联需求文档</span>
              <span class="scene-status-sub">AI 将自动参考文档内容</span>
            </div>
          </div>
        </div>

        <!-- 描述输入 -->
        <div class="scene-desc-input">
          <div class="scene-desc-label">
            页面功能描述
            <span class="scene-desc-opt">选填 · 补充后规划更精准</span>
          </div>
          <el-input v-model="sceneDescription" type="textarea" :rows="3"
            class="scene-desc-textarea"
            placeholder="例：登录页，支持账号密码登录和短信验证码登录，登录失败有错误提示，支持记住密码" />
        </div>

        <!-- 生成按钮 -->
        <el-button type="primary" class="scene-gen-btn"
          :loading="scenePlanning" @click="planScenes(false)">
          <template v-if="!scenePlanning">
            <el-icon style="margin-right:6px"><MagicStick /></el-icon>
            开始生成场景
          </template>
          <template v-else>
            <span class="scene-gen-loading-dot"></span>
            AI 分析中，约需 15-30 秒…
          </template>
        </el-button>
      </div>

      <!-- 场景列表 -->
      <div v-else class="scene-list-area">
        <!-- 工具栏 -->
        <div class="scene-toolbar">
          <div class="scene-toolbar-left">
            <el-icon size="13" color="#b0b8c4"><InfoFilled /></el-icon>
            <span class="scene-toolbar-tip">点击「录制」完成场景覆盖</span>
          </div>
          <div class="scene-toolbar-right">
            <el-button size="small" plain :loading="scenePlanning" @click="planScenes(true)" class="scene-toolbar-btn">
              <el-icon><Plus /></el-icon>追加场景
            </el-button>
            <el-button size="small" text type="danger" @click="resetScenes" class="scene-toolbar-btn-danger">
              <el-icon><Refresh /></el-icon>重新规划
            </el-button>
          </div>
        </div>

        <!-- 场景卡片列表 -->
        <el-scrollbar class="scene-scrollbar">
          <div class="scene-list">
            <div v-for="(scene, idx) in scenes" :key="scene.id"
              class="scene-card" :class="{
                'scene-recorded': scene.recorded,
                'scene-p0': scene.priority === 'P0',
                'scene-p1': scene.priority === 'P1',
              }">

              <!-- 卡头 -->
              <div class="scene-card-header">
                <div class="scene-card-meta">
                  <span class="scene-index">{{ idx + 1 }}</span>
                  <span :class="`scene-priority scene-priority-${(scene.priority||'').toLowerCase()}`">
                    {{ scene.priority }}
                  </span>
                  <span v-if="scene.dimension" class="scene-dim-tag">{{ scene.dimension }}</span>
                </div>
                <div class="scene-card-title-row">
                  <template v-if="editingSceneId === scene.id">
                    <el-input v-model="scene.name" size="small" style="flex:1"
                      @blur="editingSceneId = null" @keyup.enter="editingSceneId = null"
                      @keyup.esc="editingSceneId = null" autofocus />
                  </template>
                  <span v-else class="scene-name" @click="editingSceneId = scene.id">{{ scene.name }}</span>
                  <div v-if="scene.recorded" class="scene-done-badge">
                    <el-icon size="10"><SuccessFilled /></el-icon> 已录制
                  </div>
                  <el-button v-else link size="small" type="info" @click="removeScene(scene.id)"
                    class="scene-remove-btn">
                    <el-icon><Close /></el-icon>
                  </el-button>
                </div>
              </div>

              <!-- 描述 -->
              <div v-if="editingSceneId === scene.id" class="scene-desc-edit">
                <el-input v-model="scene.description" size="small" type="textarea" :rows="2"
                  placeholder="场景描述" />
              </div>
              <p v-else class="scene-desc" @click="editingSceneId = scene.id">{{ scene.description }}</p>

              <!-- 步骤预览 -->
              <div v-if="scene.steps_desc && scene.steps_desc.length"
                class="scene-expand-btn" @click="toggleExpandScene(scene.id)">
                <div class="scene-expand-icon">
                  <el-icon size="10"><ArrowDown v-if="expandedSceneId !== scene.id" /><ArrowUp v-else /></el-icon>
                </div>
                {{ expandedSceneId === scene.id ? '收起步骤' : `查看 ${scene.steps_desc.length} 个步骤` }}
              </div>
              <el-collapse-transition>
                <div v-if="expandedSceneId === scene.id" class="scene-steps">
                  <div v-for="(step, i) in scene.steps_desc" :key="i" class="scene-step-item">
                    <span class="scene-step-num">{{ i + 1 }}</span>
                    <span class="scene-step-text">{{ step }}</span>
                  </div>
                  <div v-if="scene.expected" class="scene-expected">
                    <el-icon size="12" color="#22c55e"><SuccessFilled /></el-icon>
                    <span>{{ scene.expected }}</span>
                  </div>
                </div>
              </el-collapse-transition>

              <!-- 操作 -->
              <div class="scene-actions">
                <el-button v-if="!scene.recorded" type="primary" size="small"
                  @click="startSceneRecording(scene)" :loading="scene.id === recordingSceneId"
                  class="scene-record-btn">
                  <el-icon><VideoCamera /></el-icon>开始录制
                </el-button>
                <el-button v-else size="small" class="scene-rerecord-btn" @click="startSceneRecording(scene)">
                  <el-icon><Refresh /></el-icon>重新录制
                </el-button>
              </div>
            </div>
          </div>
        </el-scrollbar>

        <!-- 全部完成 -->
        <transition name="scene-done-fade">
          <div v-if="scenes.length && scenes.every(s => s.recorded)" class="scene-done-banner">
            <div class="scene-done-confetti">🎉</div>
            <div class="scene-done-title">所有场景已录制完成！</div>
            <div class="scene-done-sub">用例已保存，可在下方列表查看并执行</div>
          </div>
        </transition>
      </div>
    </el-drawer>

    </template>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onActivated, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useTaskStore } from '../stores/task'
import { useWorkspaceStore } from '../stores/workspace'
import { useAuthStore } from '../stores/auth'
import WorkspaceRequired from '../components/WorkspaceRequired.vue'
import SelectorInput from '../components/SelectorInput.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useWebSocket } from '../composables/useWebSocket'
import { useFailedCases } from '../composables/useFailedCases'
import { caseApi, elementAliasApi, recordingApi, pytestExportApi, envVarApi } from '../api/index'
import {
  Plus, MagicStick, VideoPlay, VideoCamera, Edit, Delete, Refresh,
  Hide, View, Search, ArrowDown, InfoFilled, RefreshLeft, SuccessFilled,
  WarningFilled, Loading, Select, CollectionTag, Download, Setting, Connection, Close, ArrowUp, DocumentChecked, QuestionFilled,
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const taskStore = useTaskStore()
const wsStore = useWorkspaceStore()
const auth = useAuthStore()

// ── 任务 & 筛选 ──
const filterTaskId = ref(null)
const searchText = ref('')
const filterPriority = ref(null)
const filterModule = ref(null)
const filterStatus = ref(null)
const filterFailedIds = ref(new Set())  // quickShowFailures 专用：按执行失败 case id 过滤

// ── 废弃显示 ──
const showDeprecated = ref(false)

// ── 表格 ──
const tableRef = ref(null)
const selectedCases = ref([])

// ── 用例表单 ──
const showCreateDialog = ref(false)
const editingCase = ref(null)
const saving = ref(false)
const batchDeleting = ref(false)
const caseForm = reactive({
  task_id: null, name: '', module: '通用', priority: 'P1',
  preconditions: '', steps: '', expected_results: '', enabled: true,
})

// ── AI 生成 ──
const generating = ref(false)
const optimizing = ref(false)
const showProgress = ref(false)
const progressTitle = ref('')
const progressPct = ref(0)
const progressStage = ref('')
const genCaseCount = ref(0)
const canCancelGen = ref(false)

// 步骤轨道：根据任务类型动态切换
const genSteps = computed(() => {
  const t = progressTitle.value
  if (t.includes('优化')) return [
    { label: '分析覆盖', from: 3,  done: 40 },
    { label: '补全用例', from: 40, done: 90 },
    { label: '完成',     from: 90, done: 100 },
  ]
  if (t.includes('修正') || t.includes('修复')) return [
    { label: '分析失败', from: 3,  done: 30 },
    { label: 'AI 修正',  from: 30, done: 90 },
    { label: '完成',     from: 90, done: 100 },
  ]
  // 默认：生成用例
  return [
    { label: '页面分析', from: 3,  done: 15 },
    { label: '模块划分', from: 15, done: 30 },
    { label: '用例生成', from: 30, done: 95 },
    { label: '完成',     from: 95, done: 100 },
  ]
})
let _genAbortCtrl = null

// ── 用例修正 & 补全 ──
const fixing = ref(false)
const autoFixing = ref(false)
const showFixResult = ref(false)
const fixResult = ref(null)

const { lastExecutionFailed, lastExecutionResults, lastExecutionSummary, failedCount, hasFailed, executionResultMap, fetchLatestFailed: fetchLatestFailedCases, removeResult, removeResults } = useFailedCases(filterTaskId)

// ── 生成选项 ──
const reparseBeforeGen = ref(false)

// ── AI 生成用例弹窗 ──
const showGenDialog    = ref(false)
const genForm = ref({
  user_prompt:    '',
  focus_modules:  '',
  target_count:   0,
})
const openGenDialog = () => {
  if (!filterTaskId.value) { ElMessage.warning('请先选择任务'); return }
  genForm.value = { user_prompt: '', focus_modules: '', target_count: 0 }
  showGenDialog.value = true
}
const confirmGenDialog = () => {
  showGenDialog.value = false
  generateCases()
}

// ── 录制 ──────────────────────────────────────────────────────────────────────
const isRecording       = ref(false)
const recordingLoading  = ref(false)
const recordingStarting = ref(false)
const recordingDialogVisible = ref(false)
const recordedSteps     = ref([])
const recordingCaseName = ref('')
let _recordingSessionId = null
let _recWsDisconnectFn  = null

// 录制专用 WebSocket（独立于 AI 进度 WS）
const { connect: _recWsConnect, disconnect: _recWsDisconnectFnRef } = useWebSocket((msg) => {
  if (msg.type === 'recording_ready') {
    _recordingSessionId = msg.session_id
    isRecording.value = true
    recordingStarting.value = false
    recordingLoading.value = false
    ElMessage.success('浏览器已就绪，请在浏览器中操作')
  } else if (msg.type === 'recording_failed') {
    recordingStarting.value = false
    recordingLoading.value = false
    isRecording.value = false
    ElMessage.error('录制启动失败：' + (msg.error || '未知错误'))
    _recWsDisconnectFn?.()
  } else if (msg.type === 'rec_step') {
    if (msg.step) recordedSteps.value.push(msg.step)
  }
})
_recWsDisconnectFn = _recWsDisconnectFnRef

// 行内操作标签颜色
const actionTagType = (a) => {
  if (!a) return 'info'
  if (a.startsWith('assert')) return 'success'
  if (a === 'navigate') return 'primary'
  if (a === 'fill') return 'warning'
  return 'info'
}

const startRecording = async () => {
  if (!filterTaskId.value) return
  recordingLoading.value = true
  recordingStarting.value = true
  recordingDialogVisible.value = true
  recordedSteps.value = []
  try {
    const task = taskStore.tasks.find(t => t.id === filterTaskId.value)
    _recWsConnect(`rec_${filterTaskId.value}`)
    const res = await recordingApi.start(filterTaskId.value, task?.url || '', task?.browser || 'chromium')
    _recordingSessionId = res.session_id
    ElMessage.info('浏览器启动中，请稍候...')
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
    _recWsDisconnectFn?.()
  }
}

const stopRecording = async () => {
  if (!_recordingSessionId && !filterTaskId.value) return
  recordingLoading.value = true
  try {
    const res = await recordingApi.stop(_recordingSessionId, filterTaskId.value)
    recordedSteps.value = res.steps || []
    isRecording.value = false
    recordingStarting.value = false
    _recordingSessionId = null
    _recWsDisconnectFn?.()
    if (_pendingSceneName.value) recordingCaseName.value = _pendingSceneName.value
    ElMessage.success(`录制完成，共 ${recordedSteps.value.length} 个步骤`)
  } catch (e) { ElMessage.error('停止录制失败：' + e.message) }
  finally { recordingLoading.value = false }
}

const saveRecording = async () => {
  if (!recordedSteps.value.length || !filterTaskId.value) return
  recordingLoading.value = true
  try {
    const name = recordingCaseName.value.trim() || ''
    const pageTitle = recordedSteps.value[0]?.url || document.title
    await recordingApi.save(filterTaskId.value, recordedSteps.value, name, pageTitle)
    ElMessage.success(`已保存为用例「${name || '自动命名'}」`)
    recordingDialogVisible.value = false
    recordedSteps.value = []
    recordingCaseName.value = ''
    _recordingSessionId = null
    // 刷新用例列表
    await taskStore.fetchCases(filterTaskId.value)
    // 场景录制完成：标记并重新打开场景抽屉
    if (recordingSceneId.value) {
      const sceneId = recordingSceneId.value
      recordingSceneId.value = null
      _pendingSceneName.value = ''
      console.log('[saveRecording] 开始标记场景录制:', { taskId: filterTaskId.value, sceneId })
      try {
        const r = await caseApi.markSceneRecorded(filterTaskId.value, sceneId, true)
        console.log('[saveRecording] markSceneRecorded 后端响应:', r)
      } catch (e) {
        console.warn('[saveRecording] markSceneRecorded 失败:', e)
      }
      // 强制从后端重载两份场景数据
      console.log('[saveRecording] 重载场景数据...')
      await loadPersistedScenes()
      await loadScenePlan()
      console.log('[saveRecording] scenes 重载后:', { len: scenes.value.length, recorded: scenes.value.filter(s=>s.recorded).map(s=>s.id) })
      console.log('[saveRecording] scenePlanCache 重载后:', { len: scenePlanCache.value.length, recorded: scenePlanCache.value.filter(s=>s.recorded).map(s=>s.id) })
      setTimeout(() => { scenePlannerVisible.value = true }, 300)
    }
  } catch (e) { ElMessage.error('保存失败：' + e.message) }
  finally { recordingLoading.value = false }
}

// ── 环境变量 ──────────────────────────────────────────────────────────────────
const envVarDialogVisible = ref(false)
const envVars    = ref([])
const envVarLoading = ref(false)
const newEnvVar  = ref({ key: '', value: '', is_secret: false })

const loadEnvVars = async () => {
  if (!filterTaskId.value) return
  try { envVars.value = await envVarApi.list(filterTaskId.value) } catch {}
}
const saveEnvVar = async () => {
  if (!newEnvVar.value.key.trim()) { ElMessage.warning('Key 不能为空'); return }
  envVarLoading.value = true
  try {
    await envVarApi.create(filterTaskId.value, newEnvVar.value)
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

// ── pytest 导出 ──────────────────────────────────────────────────────────────
const exportLoading = ref(false)
const exportPytest = async () => {
  if (!filterTaskId.value) return
  exportLoading.value = true
  try {
    const blob = await pytestExportApi.export(filterTaskId.value)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = `pytest_task_${filterTaskId.value}.zip`; a.click()
    URL.revokeObjectURL(url)
  } catch (e) { ElMessage.error('导出失败：' + e.message) }
  finally { exportLoading.value = false }
}

// ── AI 场景规划 ──────────────────────────────────────────────────────────────
const scenePlannerVisible = ref(false)
const scenePlanning       = ref(false)
const sceneDescription    = ref('')
const scenes              = ref([])
const recordingSceneId    = ref(null)
const editingSceneId      = ref(null)
const expandedSceneId     = ref(null)
const _pendingSceneName   = ref('')

// 抽屉打开时总是从后端加载最新场景（含录制状态），避免展示过期数据
watch(scenePlannerVisible, (v) => { if (v) loadPersistedScenes() })

const sceneDimensions = [
  { name: '核心业务流程', type: 'success' },
  { name: '表单验证',     type: 'warning' },
  { name: '数据增删改',   type: 'primary' },
  { name: '列表与筛选',   type: 'info'    },
  { name: '异常与错误反馈', type: 'danger' },
]

const hasPageElements = computed(() => {
  const task = taskStore.tasks.find(t => t.id === filterTaskId.value)
  return task?.page_elements?.length > 0
})

const hasDocument = computed(() => {
  const task = taskStore.tasks.find(t => t.id === filterTaskId.value)
  return !!task?.document_path
})

const parsingPage = ref(false)
const parseCurrentPage = async () => {
  if (!filterTaskId.value) return
  const task = taskStore.tasks.find(t => t.id === filterTaskId.value)
  if (!task?.url) { ElMessage.warning('任务没有配置 URL，无法抓取页面元素'); return }
  parsingPage.value = true
  try {
    await taskStore.parsePage(task.url, task.browser || 'chromium', filterTaskId.value)
    await taskStore.fetchTasks(wsStore.currentId)
    ElMessage.success('页面元素抓取完成，AI 规划将更加精准')
  } catch (e) {
    ElMessage.error('抓取失败：' + (e?.response?.data?.detail || e?.message || ''))
  } finally { parsingPage.value = false }
}

const openScenePlanner = () => { scenePlannerVisible.value = true }

// 场景覆盖页跳转到场景规划抽屉（去 AI 规划场景 / 重新规划）
const goScenePlanner = async () => {
  scenePlannerVisible.value = true
  await loadPersistedScenes()
}

const loadPersistedScenes = async () => {
  if (!filterTaskId.value) return
  try {
    const res = await caseApi.getScenePlan(filterTaskId.value)
    if (res.scenes?.length) scenes.value = res.scenes
  } catch {}
}

const planScenes = async (append = false) => {
  if (!filterTaskId.value) return
  scenePlanning.value = true
  try {
    const res = await caseApi.planScenes(filterTaskId.value, { description: sceneDescription.value, append })
    scenes.value = res.scenes || []
    if (!scenes.value.length) {
      ElMessage.warning('未能生成场景，请补充页面功能描述后重试')
    } else {
      ElMessage.success(append ? `已追加 ${res.scenes.length} 个场景` : `已生成 ${res.scenes.length} 个场景`)
    }
  } catch (e) {
    ElMessage.error('场景规划失败：' + (e?.response?.data?.detail || e?.message || ''))
  } finally { scenePlanning.value = false }
}

const resetScenes = async () => {
  try {
    await ElMessageBox.confirm(
      '重新规划会清空所有未录制的场景（已录制的会保留），确认继续？',
      '重新规划', { type: 'warning', confirmButtonText: '确认', cancelButtonText: '取消' }
    )
    scenes.value = scenes.value.filter(s => s.recorded)
    if (!scenes.value.length) scenes.value = []
    sceneDescription.value = ''
  } catch {}
}

const removeScene = (sceneId) => {
  scenes.value = scenes.value.filter(s => s.id !== sceneId)
  if (filterTaskId.value) caseApi.markSceneRecorded(filterTaskId.value, sceneId, false).catch(() => {})
}

const toggleExpandScene = (sceneId) => {
  expandedSceneId.value = expandedSceneId.value === sceneId ? null : sceneId
}

const startSceneRecording = async (scene) => {
  recordingSceneId.value = scene.id
  scenePlannerVisible.value = false
  _pendingSceneName.value = scene.name
  await startRecording()
}

// ═══════════════════════════════════════════════════════════
// Computed
// ═══════════════════════════════════════════════════════════

// 可用模块列表（从当前任务用例中提取）
const availableModules = computed(() => {
  const base = filterTaskId.value
    ? taskStore.cases.filter(c => c.task_id === filterTaskId.value)
    : taskStore.cases
  return [...new Set(base.map(c => c.module).filter(Boolean))].sort()
})

const filteredCases = computed(() => {
  let base = filterTaskId.value
    ? taskStore.cases.filter(c => c.task_id === filterTaskId.value)
    : taskStore.cases

  // 废弃筛选
  if (!showDeprecated.value) base = base.filter(c => !c.deprecated)

  // 优先级筛选
  if (filterPriority.value) base = base.filter(c => c.priority === filterPriority.value)

  // 模块筛选
  if (filterModule.value) base = base.filter(c => c.module === filterModule.value)

  // 状态筛选
  if (filterStatus.value === 'enabled') base = base.filter(c => c.enabled && !c.deprecated)
  else if (filterStatus.value === 'disabled') base = base.filter(c => !c.enabled && !c.deprecated)
  else if (filterStatus.value === 'deprecated') base = base.filter(c => c.deprecated)

  // 搜索
  if (searchText.value.trim()) {
    const q = searchText.value.trim().toLowerCase()
    base = base.filter(c =>
      c.name?.toLowerCase().includes(q) ||
      c.steps?.toLowerCase().includes(q) ||
      c.module?.toLowerCase().includes(q) ||
      String(c.id).includes(q)
    )
  }

  // 仅看失败（quickShowFailures 触发，按 case id 精确过滤）
  if (filterFailedIds.value.size) {
    base = base.filter(c => filterFailedIds.value.has(c.id))
  }

  return base
})

// ── 分页 ──────────────────────────────────────────────────────────────────────
const currentPage = ref(1)
const pageSize    = ref(20)

// 筛选/搜索条件变化时回到第 1 页
watch(
  [filterTaskId, filterPriority, filterModule, filterStatus, searchText, showDeprecated],
  () => { currentPage.value = 1 }
)

const pagedCases = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredCases.value.slice(start, start + pageSize.value)
})

const allCases = computed(() => {
  return filterTaskId.value
    ? taskStore.cases.filter(c => c.task_id === filterTaskId.value)
    : taskStore.cases
})

const isAllSelected = computed(() =>
  pagedCases.value.length > 0 &&
  pagedCases.value.every(c => selectedCases.value.some(s => s.id === c.id))
)

const deprecatedCount = computed(() => {
  const base = filterTaskId.value
    ? taskStore.cases.filter(c => c.task_id === filterTaskId.value)
    : taskStore.cases
  return base.filter(c => c.deprecated).length
})

const hasActiveFilters = computed(() =>
  !!filterPriority.value || !!filterModule.value || !!filterStatus.value || showDeprecated.value || filterFailedIds.value.size > 0
)

function resetFilters() {
  filterPriority.value = null
  filterModule.value = null
  filterStatus.value = null
  showDeprecated.value = false
  searchText.value = ''
  filterFailedIds.value = new Set()
}

// ═══════════════════════════════════════════════════════════
// Functions
// ═══════════════════════════════════════════════════════════

function getPriorityType(p) {
  return p === 'P0' ? 'danger' : p === 'P2' ? 'info' : 'warning'
}

// ── WebSocket ──
const _wsClientId = computed(() => `cases_gen_${auth.username || 'anon'}_${Date.now()}`)
let _wsClientIdFixed = null
const { connect: connectWs, disconnect: disconnectWs } = useWebSocket((msg) => {
  if (msg.type === 'cases_gen_progress' || msg.type === 'cases_opt_progress') {
    progressPct.value = msg.percent ?? progressPct.value
    progressStage.value = msg.stage ?? progressStage.value
    genCaseCount.value = msg.case_count ?? genCaseCount.value
    if (msg.percent >= 100) setTimeout(() => { showProgress.value = false }, 800)
  }
  if (msg.type === 'cases_correct_progress' || msg.type === 'cases_gap_progress' || msg.type === 'cases_auto_fix_progress') {
    progressPct.value = msg.percent ?? progressPct.value
    progressStage.value = msg.stage ?? progressStage.value
    genCaseCount.value = msg.case_count ?? genCaseCount.value
    if (msg.percent >= 100) setTimeout(() => { showProgress.value = false }, 1000)
  }
  // 执行完成后收集失败用例 — execution_saved 含 summary
  if (msg.type === 'execution_saved') {
    const fc = msg.summary?.failed_cases || []
    lastExecutionFailed.value = fc
    if (fc.length) ElMessage.info(`本次执行有 ${fc.length} 条失败，可在「更多操作 → 修正失败用例」中自动修正`)
  }
})
function getWsClientId() {
  if (!_wsClientIdFixed) _wsClientIdFixed = `cases_gen_${auth.username || 'anon'}_${Date.now()}`
  return _wsClientIdFixed
}

// ── 任务切换 ──
const onTaskSelect = async () => {
  selectedCases.value = []
  filterModule.value = null
  aliasList.value = []
  filterFailedIds.value = new Set()
  if (filterTaskId.value) {
    await taskStore.fetchCases(filterTaskId.value)
    fetchLatestFailedCases()
  }
}

// ── 执行 ──
const runSingle = (row) => {
  if (!row.enabled) { ElMessage.warning('该用例已禁用，无法执行'); return }
  router.push({ name: 'Execution', query: { taskId: row.task_id, caseIds: String(row.id) } })
}
const runBatch = () => {
  if (!selectedCases.value.length) { ElMessage.warning('请先勾选要执行的用例'); return }
  const disabledCases = selectedCases.value.filter(c => !c.enabled)
  if (disabledCases.length) {
    ElMessage.warning(`已选用例中有 ${disabledCases.length} 条已禁用，请取消勾选后重试`); return
  }
  const taskId = selectedCases.value[0].task_id
  if (!selectedCases.value.every(c => c.task_id === taskId)) {
    ElMessage.warning('批量执行只支持同一任务下的用例，请筛选任务后再选择'); return
  }
  router.push({ name: 'Execution', query: { taskId, caseIds: selectedCases.value.map(c => c.id).join(',') } })
}

// ── AI 生成 ──
const generateCases = async () => {
  if (!filterTaskId.value) { ElMessage.warning('请先选择任务'); return }
  generating.value = true
  showProgress.value = true
  progressTitle.value = 'AI 生成用例'
  progressPct.value = 0
  progressStage.value = '准备中...'
  genCaseCount.value = 0
  canCancelGen.value = true
  if (_genAbortCtrl) { _genAbortCtrl.abort(); _genAbortCtrl = null }
  _genAbortCtrl = new AbortController()
  const wsClientId = getWsClientId()
  connectWs(wsClientId)

  // 解析弹窗参数
  const focusMods = genForm.value.focus_modules
    ? genForm.value.focus_modules.split(/[，,、\n]+/).map(s => s.trim()).filter(Boolean)
    : []
  const tCount = genForm.value.target_count || 0

  try {
    await caseApi.generate(filterTaskId.value, {
      reparse_page:  reparseBeforeGen.value,
      ws_client_id:  wsClientId,
      user_prompt:   genForm.value.user_prompt.trim(),
      focus_modules: focusMods,
      target_count:  tCount,
    }, { signal: _genAbortCtrl.signal, timeout: 600000 })
    await taskStore.fetchCases(filterTaskId.value)
    taskStore.fetchTotalCaseCount(wsStore.currentId)
    ElMessage.success('AI 用例生成完成')
  } catch (e) {
    if (e?.name === 'AbortError' || e?.code === 'ERR_CANCELED') {
      ElMessage.info('已取消生成')
    } else {
      ElMessage.error('生成失败: ' + (e?.response?.data?.detail || e.message))
    }
  } finally {
    generating.value = false
    showProgress.value = false
    canCancelGen.value = false
    _genAbortCtrl = null
  }
}
const cancelGeneration = () => {
  if (_genAbortCtrl) { _genAbortCtrl.abort(); _genAbortCtrl = null }
}

// ── 优化 ──
const optimizeCases = async () => {
  if (!filterTaskId.value) { ElMessage.warning('请先选择任务'); return }
  optimizing.value = true
  showProgress.value = true
  progressTitle.value = '优化用例'
  progressPct.value = 0
  progressStage.value = '准备中...'
  genCaseCount.value = 0
  const wsClientId = getWsClientId()
  connectWs(wsClientId)
  try {
    await caseApi.optimize(filterTaskId.value, { ws_client_id: wsClientId }, { timeout: 600000 })
    await taskStore.fetchCases(filterTaskId.value)
    taskStore.fetchTotalCaseCount(wsStore.currentId)
    ElMessage.success('用例优化完成')
  } catch (e) {
    ElMessage.error('优化失败: ' + (e?.response?.data?.detail || e.message))
  } finally {
    optimizing.value = false
    showProgress.value = false
  }
}

// ── 从 API 加载最近一次执行的失败用例 ──
// (now managed by useFailedCases composable)

function getCaseExecStatus(row) {
  // 优先按 case_id 匹配
  if (row.id && executionResultMap.value[row.id]) {
    return executionResultMap.value[row.id].status
  }
  // 回退按名称匹配
  const nameKey = '_name_' + row.name
  if (executionResultMap.value[nameKey]) {
    return executionResultMap.value[nameKey].status
  }
  return null
}
function getCaseExecError(row) {
  if (row.id && executionResultMap.value[row.id]) {
    return executionResultMap.value[row.id].error
  }
  const nameKey = '_name_' + row.name
  return executionResultMap.value[nameKey]?.error || ''
}
function formatTime(isoStr) {
  if (!isoStr) return ''
  const d = new Date(isoStr)
  const pad = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
function quickShowFailures() {
  // 按 case_id 精确过滤失败用例，不污染搜索框，支持多条失败同时显示
  const failedIds = new Set(lastExecutionFailed.value.map(f => f.case_id).filter(Boolean))
  if (failedIds.size) {
    filterFailedIds.value = failedIds
    currentPage.value = 1
  }
}

// ── 修正 & 补全 ──
const fixCases = async () => {
  if (!filterTaskId.value) return
  if (!lastExecutionFailed.value.length) {
    ElMessage.info('没有需要修正的失败用例，请先执行一次测试')
    return
  }
  // 弹出选择对话框：AI修正 or 录制替换
  try {
    await ElMessageBox.confirm(
      `共有 ${lastExecutionFailed.value.length} 条失败用例，请选择处理方式：`,
      '修正失败用例',
      {
        confirmButtonText: '🎬 去录制替换（推荐）',
        cancelButtonText: '🤖 AI 自动修正',
        distinguishCancelAndClose: true,
        type: 'warning',
      }
    )
    // 点了"去录制替换"
    router.push({ name: 'Execution', query: { taskId: filterTaskId.value, startRecord: '1', from: 'cases' } })
  } catch (action) {
    if (action === 'cancel') {
      // 点了"AI 自动修正"
      await _doAiFixCases()
    }
    // close：点了 X，什么也不做
  }
}

const _doAiFixCases = async () => {
  fixing.value = true
  showProgress.value = true
  progressTitle.value = 'AI 修正失败用例'
  progressPct.value = 0
  progressStage.value = '正在分析失败用例...'
  genCaseCount.value = 0
  const wsClientId = 'cases_correct_' + Date.now()
  connectWs(wsClientId)
  try {
    const res = await caseApi.selfCorrect(filterTaskId.value, {
      failed_cases: lastExecutionFailed.value,
      ws_client_id: wsClientId,
    })
    fixResult.value = res
    showFixResult.value = true
    const stats = res.stats || {}
    ElMessage.success(`修正完成：${stats.total || res.corrected?.length || 0} 条`)
    await taskStore.fetchCases(filterTaskId.value)
  } catch (e) {
    ElMessage.error('修正失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    fixing.value = false
    showProgress.value = false
    disconnectWs()
  }
}

// ── 来源标签辅助 ──
function sourceLabel(source) {
  if (source === 'recorded') return { text: '🎬录制', type: 'success', tip: '由录制操作生成，执行可靠性高' }
  if (source === 'ai_generated') return { text: '🤖AI', type: 'warning', tip: 'AI推断生成，建议执行失败后用录制替换' }
  return { text: '✏️手动', type: 'info', tip: '手动创建的用例' }
}

// ── AI 规划场景 / 录制 已内嵌，原跳转函数替换 ──
const reRecordCase = (row) => {
  _pendingSceneName.value = row.name
  startRecording()
}

// ── T5：场景覆盖视图 ──────────────────────────────────────────────────────────
const mainTab = ref('list')
const scenePlanCache = ref([])

// 切换到场景覆盖 Tab 时加载持久化场景
watch(mainTab, async (tab) => {
  if (tab === 'scene-coverage' && filterTaskId.value) {
    await loadScenePlan()
  }
})

const loadScenePlan = async () => {
  if (!filterTaskId.value) return
  try {
    const res = await caseApi.getScenePlan(filterTaskId.value)
    scenePlanCache.value = res.scenes || []
  } catch { scenePlanCache.value = [] }
}

// 任务切换时清空场景缓存
watch(filterTaskId, () => { scenePlanCache.value = [] })

// 场景覆盖统计
const sceneStats = computed(() => {
  const total = scenePlanCache.value.length
  const covered = scenePlanCache.value.filter(s => s.recorded).length
  return { total, covered }
})

// 根据场景名模糊匹配该场景对应的用例
const getCasesForScene = (scene) => {
  return taskStore.cases.filter(c =>
    c.name.includes(scene.name) || scene.name.includes(c.name.replace(/（.*）|\(.*\)/, '').trim())
  )
}

// 在场景覆盖 Tab 执行单条用例
const runSingleById = (caseRow) => {
  if (!caseRow.enabled) { ElMessage.warning('该用例已禁用，无法执行'); return }
  router.push({
    name: 'Execution',
    query: { taskId: caseRow.task_id, caseIds: String(caseRow.id) }
  })
}

const autoFixAll = async () => {
  if (!filterTaskId.value) return
  autoFixing.value = true
  showProgress.value = true
  progressTitle.value = '一键修正 & 补全'
  progressPct.value = 0
  progressStage.value = '正在启动...'
  genCaseCount.value = 0
  const wsClientId = 'auto_fix_' + Date.now()
  connectWs(wsClientId)
  try {
    const res = await caseApi.autoFix(filterTaskId.value, {
      failed_cases: lastExecutionFailed.value,
      existing_cases: filteredCases.value,
      execution_results: [],
      ws_client_id: wsClientId,
    })
    fixResult.value = res
    showFixResult.value = true
    if (res.new_cases?.length) {
      for (const nc of res.new_cases) {
        await taskStore.createCase({ ...nc, task_id: filterTaskId.value, status: 'draft' })
      }
    }
    const stats = res.stats || {}
    ElMessage.success(`修正补全完成：${stats.corrected_count || 0} 条修正 + ${stats.gap_count || 0} 条补充`)
    await taskStore.fetchCases(filterTaskId.value)
  } catch (e) {
    ElMessage.error('修正补全失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    autoFixing.value = false
    showProgress.value = false
    disconnectWs()
  }
}

// ── 表格操作 ──
const handleSelectionChange = (sel) => { selectedCases.value = sel }
const toggleAllSelection = () => tableRef.value?.toggleAllSelection()
const batchEnabling  = ref(false)
const batchDisabling = ref(false)
const batchEnable = async () => {
  if (!selectedCases.value.length) { ElMessage.warning('请先选择用例'); return }
  const count = selectedCases.value.length  // 提前保存，异步更新后 selectedCases 会被清空
  batchEnabling.value = true
  try {
    await Promise.all(selectedCases.value.map(c => taskStore.updateCase(c.id, { enabled: true })))
    ElMessage.success(`已启用 ${count} 条用例`)
  } catch { ElMessage.error('部分用例启用失败') } finally { batchEnabling.value = false }
}
const batchDisable = async () => {
  if (!selectedCases.value.length) { ElMessage.warning('请先选择用例'); return }
  const count = selectedCases.value.length  // 提前保存，异步更新后 selectedCases 会被清空
  batchDisabling.value = true
  try {
    await Promise.all(selectedCases.value.map(c => taskStore.updateCase(c.id, { enabled: false })))
    ElMessage.success(`已禁用 ${count} 条用例`)
  } catch { ElMessage.error('部分用例禁用失败') } finally { batchDisabling.value = false }
}
const batchDelete = async () => {
  if (!selectedCases.value.length) { ElMessage.warning('请先选择用例'); return }
  const count = selectedCases.value.length
  try {
    await ElMessageBox.confirm(`确定要删除选中的 ${count} 个用例吗？此操作不可恢复。`, '批量删除', { type: 'warning' })
    batchDeleting.value = true
    const deletedIds = new Set(selectedCases.value.map(c => c.id))
    for (const c of selectedCases.value) await taskStore.deleteCase(c.id)
    // 清理本地失败记录
    removeResults([...deletedIds])
    selectedCases.value = []
    ElMessage.success('批量删除成功')
    taskStore.fetchTotalCaseCount(wsStore.currentId)
  } catch (err) { if (err !== 'cancel') ElMessage.error('删除失败: ' + (err?.message || err)) }
  finally { batchDeleting.value = false }
}

const saveCase = async () => {
  if (!caseForm.name || !caseForm.steps || !caseForm.expected_results) {
    ElMessage.warning('请填写用例名称、测试步骤和预期结果')
    return
  }
  saving.value = true
  try {
    if (editingCase.value) {
      await taskStore.updateCase(editingCase.value.id, caseForm)
      ElMessage.success('更新成功')
    } else {
      await taskStore.createCase(caseForm)
      ElMessage.success('创建成功')
      taskStore.fetchTotalCaseCount(wsStore.currentId)
    }
    showCreateDialog.value = false
    resetForm()
  } catch (e) {
    const detail = e?.response?.data?.detail
    const msg = Array.isArray(detail)
      ? detail.map(d => d.msg || JSON.stringify(d)).join('；')
      : (detail || e?.message || '未知错误')
    ElMessage.error('保存失败: ' + msg)
  } finally { saving.value = false }
}
const deleteCase = async (row) => {
  try {
    await ElMessageBox.confirm('确定要删除这个用例吗?', '提示', { type: 'warning' })
    await taskStore.deleteCase(row.id)
    // 清理本地失败记录
    removeResult(row.id)
    ElMessage.success('删除成功')
    taskStore.fetchTotalCaseCount(wsStore.currentId)
  } catch (err) { if (err !== 'cancel') ElMessage.error('删除失败') }
}
const resetForm = () => {
  caseForm.task_id = filterTaskId.value || null
  caseForm.name = ''; caseForm.module = '通用'; caseForm.priority = 'P1'
  caseForm.preconditions = ''; caseForm.steps = ''; caseForm.expected_results = ''
  caseForm.enabled = true; editingCase.value = null
}

const openCreateDialog = () => {
  resetForm()
  caseEditTab.value = 'info'
  stepsJson.value = []
  showCreateDialog.value = true
}

// ── 步骤编辑器 ────────────────────────────────────────────────────────────────
const caseEditTab = ref('info')
const stepsJson   = ref([])
const stepsLoading = ref(false)

// 从 stepsJson 实时生成可读文本，同步到基本信息 Tab 的「测试步骤」
function _stepsToText(arr) {
  return arr.map((s, i) => {
    const a = s.action || ''
    const d = s.description || ''
    const sel = s.selector || ''
    const val = s.value || ''
    if (d) return `${i + 1}. ${d}` + ((a === 'fill' || a === 'type' || a === 'select') && val && !d.includes('=') ? ` = ${val}` : '')
    const m = { navigate: `导航到 ${s.url || ''}`, click: `点击 ${sel}`, dblclick: `双击 ${sel}`,
      rightclick: `右键 ${sel}`, fill: `填写 ${sel} = ${val}`, type: `输入 ${sel} = ${val}`,
      select: `选择 ${sel} → ${val}`, check: `勾选 ${sel}`, uncheck: `取消勾选 ${sel}`, hover: `悬停 ${sel}`,
      press: `按键 ${val}`, scroll: `滚动到 ${sel}`, wait_for: `等待 ${sel || s.url || ''}`,
      assert_text: `断言 ${sel} 文本 = ${s.expected || ''}`, assert_visible: `断言 ${sel} 可见`,
      assert_hidden: `断言 ${sel} 不可见`, assert_url: `断言 URL = ${s.expected || ''}`,
      assert_title: `断言标题 = ${s.expected || ''}`, screenshot: `截图`, evaluate: `执行 JS`,
    }
    return `${i + 1}. ${m[a] || a}`
  }).join('\n')
}

// 步骤编辑器内变更后，实时同步可读文本到基本信息 Tab（空时不覆盖原有文字）
watch(stepsJson, (val) => {
  if (editingCase.value && val.length > 0) caseForm.steps = _stepsToText(val)
}, { deep: true })

// ── 前置步骤（方案一） ────────────────────────────────────────────────────────
const setupStepsJson = ref([])
const caseUseStorage = ref(true)

const addSetupStep = () => {
  setupStepsJson.value.push({
    id: `ss${Date.now()}`, action: 'navigate', url: '', selector: '', value: '', expected: '', description: ''
  })
}

const saveSetupSteps = async () => {
  if (!editingCase.value) return
  saving.value = true
  try {
    await taskStore.updateCase(editingCase.value.id, {
      setup_steps: setupStepsJson.value,
      use_storage: caseUseStorage.value,
    })
    ElMessage.success('前置步骤已保存')
  } catch (e) {
    ElMessage.error('保存失败: ' + (e?.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

// ── 登录用例设置（方案三：storage_state）────────────────────────────────────
const showSetupCaseDialog = ref(false)
const savingSetupCase = ref(false)
const setupCaseForm = ref({ setup_case_id: null, storage_ttl_minutes: 60 })

const currentTaskSetupCaseId = computed(() => {
  const task = taskStore.tasks.find(t => t.id === filterTaskId.value)
  return task?.setup_case_id ?? null
})

const currentTaskCases = computed(() =>
  taskStore.cases.filter(c => c.task_id === filterTaskId.value)
)

const openSetupCaseDialog = () => {
  const task = taskStore.tasks.find(t => t.id === filterTaskId.value)
  setupCaseForm.value = {
    setup_case_id: task?.setup_case_id ?? null,
    storage_ttl_minutes: task?.storage_ttl_minutes ?? 60,
  }
  showSetupCaseDialog.value = true
}

const saveSetupCase = async () => {
  if (!filterTaskId.value) return
  savingSetupCase.value = true
  try {
    await taskStore.updateTask(filterTaskId.value, {
      setup_case_id: setupCaseForm.value.setup_case_id || null,
      storage_ttl_minutes: setupCaseForm.value.storage_ttl_minutes,
    })
    showSetupCaseDialog.value = false
    ElMessage.success('登录用例设置已保存')
  } catch (e) {
    ElMessage.error('保存失败: ' + (e?.response?.data?.detail || e.message))
  } finally {
    savingSetupCase.value = false
  }
}

// action 分类
const interactActions = ['navigate','click','dblclick','rightclick','fill','type',
  'select','check','uncheck','hover','press','scroll','upload','submit','keydown','wait']
const assertActions   = ['assert_text','assert_visible','assert_hidden',
  'assert_url','assert_title','assert_count']
const otherActions    = ['wait_for','screenshot','evaluate']

// 打开编辑时如果切到步骤 Tab 则加载 steps_json，顺带预热别名列表
watch(caseEditTab, async (tab) => {
  if (tab === 'steps-editor' && editingCase.value) {
    await reloadSteps()
    // 预加载别名列表供 SelectorInput 补全使用（已有则跳过）
    if (!aliasList.value.length && filterTaskId.value) {
      try {
        const res = await elementAliasApi.list(filterTaskId.value)
        aliasList.value = res.data || res
      } catch (_) {}
    }
  }
})

const reloadSteps = async () => {
  if (!editingCase.value) return
  stepsLoading.value = true
  try {
    const res = await caseApi.getSteps(editingCase.value.id)
    stepsJson.value = (res.steps_json || []).map(s => ({ ...s }))
  } catch { ElMessage.error('加载步骤失败') }
  finally { stepsLoading.value = false }
}

// selector 评级（前端版本，对应后端 selector_grade 规则）
const _gradeA = [/\[data-testid=/,/\[data-test=/,/\[data-cy=/,/\[aria-label=/,
  /\[name=/,/\[placeholder=/,/\[role="/, /^role=/, /^label=/, /^alt=/]
const _gradeB = [/:has-text\(/,/text=/,/\[type="submit"/,/\[type="button"/,/\[aria-/,/\[role=/]
const selectorGrade = (sel) => {
  if (!sel) return 'D'
  if (/^#\w*\d{5,}/.test(sel) || /--[a-f0-9]{4,}/.test(sel)) return 'D'
  if (_gradeA.some(r => r.test(sel))) return 'A'
  if (_gradeB.some(r => r.test(sel))) return 'B'
  if (/\.\w/.test(sel) || /\[class/.test(sel) || /^#[a-zA-Z]/.test(sel)) return 'C'
  return 'D'
}

const gradeType = (g) => ({ A: 'success', B: 'warning', C: 'info', D: 'danger' }[g] || 'info')
const gradeDesc = (g) => ({
  A: 'A级：data-testid/aria-label/name，最稳定',
  B: 'B级：:has-text/type=submit，较稳定',
  C: 'C级：class/id，可能随重构变化',
  D: 'D级：动态id/纯tag，建议替换',
}[g] || '')

// ── 元素别名库 ────────────────────────────────────────────────────────────────
const aliasDialogVisible = ref(false)
const aliasList          = ref([])
const aliasLoading       = ref(false)
const aliasFormVisible   = ref(false)
const aliasSaving        = ref(false)
const editingAlias       = ref(null)
const aliasForm          = ref({ name: '', description: '', selectors: [''] })

const openAliasManager = async () => {
  if (!filterTaskId.value) return
  aliasDialogVisible.value = true
  aliasLoading.value = true
  try {
    const res = await elementAliasApi.list(filterTaskId.value)
    aliasList.value = res.data || res
  } catch (e) { ElMessage.error('加载失败：' + e.message) }
  finally { aliasLoading.value = false }
}

const openAliasForm = (row = null) => {
  editingAlias.value = row
  aliasForm.value = row
    ? { name: row.name, description: row.description || '', selectors: [...(row.selectors || [''])] }
    : { name: '', description: '', selectors: [''] }
  aliasFormVisible.value = true
}

const saveAlias = async () => {
  const form = aliasForm.value
  if (!form.name.trim()) { ElMessage.warning('别名名称不能为空'); return }
  const sels = form.selectors.map(s => s.trim()).filter(Boolean)
  if (!sels.length) { ElMessage.warning('至少填写一个 selector'); return }
  aliasSaving.value = true
  try {
    const payload = { name: form.name.trim(), description: form.description, selectors: sels }
    if (editingAlias.value) {
      const res = await elementAliasApi.update(filterTaskId.value, editingAlias.value.id, payload)
      const updated = res.data || res
      const idx = aliasList.value.findIndex(a => a.id === editingAlias.value.id)
      if (idx >= 0) aliasList.value[idx] = updated
    } else {
      const res = await elementAliasApi.create(filterTaskId.value, payload)
      aliasList.value.push(res.data || res)
    }
    aliasFormVisible.value = false
    ElMessage.success('保存成功')
  } catch (e) { ElMessage.error('保存失败：' + e.message) }
  finally { aliasSaving.value = false }
}

const deleteAlias = async (row) => {
  try {
    await ElMessageBox.confirm(`删除别名 @${row.name}？`, '确认删除', { type: 'warning' })
    await elementAliasApi.delete(filterTaskId.value, row.id)
    aliasList.value = aliasList.value.filter(a => a.id !== row.id)
    ElMessage.success('已删除')
  } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败：' + e.message) }
}

const updateStepGrade = (step) => {
  step.robustness = selectorGrade(step.selector)
  if (step.selector && step.selector.startsWith('@')) {
    // 别名引用：清空 selectors[]，执行时由 _resolve_alias 展开，不走多候选回退
    step.selectors = []
  } else if (!step.selectors || !step.selectors.includes(step.selector)) {
    // 普通 selector：确保在候选列表里且排第一
    const rest = (step.selectors || []).filter(s => s !== step.selector)
    step.selectors = step.selector ? [step.selector, ...rest] : rest
  }
}

const applySelector = async (step, cand) => {
  step.selector = cand
  step.robustness = selectorGrade(cand)
  // 把选中项提到 selectors[0]，执行时多候选按此顺序回退
  const rest = (step.selectors || []).filter(s => s !== cand)
  step.selectors = [cand, ...rest]
  // 立即持久化，避免用户忘记点「保存步骤」导致执行侧仍用旧 selector
  await saveSteps(true)
}

// 判断该 action 是否需要对应字段
const needsSelector = (action) => ['click','dblclick','rightclick','fill','type','select',
  'check','uncheck','hover','scroll','upload','submit','wait_for',
  'assert_text','assert_visible','assert_hidden','assert_count'].includes(action)
const needsValue    = (action) => ['fill','type','select','press','evaluate','upload','wait'].includes(action)
const needsExpected = (action) => ['assert_text','assert_url','assert_title','assert_count'].includes(action)
const valuePlaceholder = (action) => ({
  fill: '填写内容', type: '输入内容', select: '选项值', press: 'Enter/Tab/Escape',
  evaluate: 'JS 表达式', upload: '文件路径', wait: '等待毫秒数(可选)',
}[action] || '值')

// action 切换时重置无关字段
const onActionChange = (step) => {
  if (!needsSelector(step.action))  step.selector = ''
  if (!needsValue(step.action))     step.value    = ''
  if (!needsExpected(step.action))  step.expected = ''
  if (step.action === 'navigate')   { step.selector = ''; step.value = '' }
  step.robustness = selectorGrade(step.selector)
}

// 前置步骤 action 切换（同上，但不需要 robustness 评级）
const onSetupActionChange = (step) => {
  if (!needsSelector(step.action))  step.selector = ''
  if (!needsValue(step.action))     step.value    = ''
  if (!needsExpected(step.action))  step.expected = ''
  if (step.action === 'navigate')   { step.selector = ''; step.value = '' }
}

// 步骤操作
const addStep = () => {
  const newStep = {
    id: `s${String(stepsJson.value.length + 1).padStart(3, '0')}`,
    action: 'click', selector: '', selectors: [], value: '',
    url: '', expected: '', description: '', timeout: 30000,
    optional: false, robustness: 'D',
  }
  stepsJson.value.push(newStep)
}

const removeStep = (idx) => { stepsJson.value.splice(idx, 1) }

const moveStep = (idx, dir) => {
  const arr = stepsJson.value
  const target = idx + dir
  if (target < 0 || target >= arr.length) return;
  [arr[idx], arr[target]] = [arr[target], arr[idx]]
}

// 保存步骤（步骤编辑器 Tab 专用按钮）
const saveSteps = async (silent = false) => {
  if (!editingCase.value) return
  saving.value = true
  try {
    const updated = await taskStore.updateCase(editingCase.value.id, { steps_json: stepsJson.value })
    // 后端自动把 steps_json 转成可读文字写入 steps 字段，同步到基础信息 Tab
    caseForm.steps = updated?.steps || ''
    if (!silent) ElMessage.success('步骤已保存')
  } catch (e) {
    ElMessage.error('保存失败: ' + (e?.response?.data?.detail || e.message))
  } finally { saving.value = false }
}

// editCase 补充加载 steps_json
const editCase = (row) => {
  editingCase.value = row
  Object.assign(caseForm, {
    task_id: row.task_id, name: row.name, module: row.module,
    priority: row.priority, preconditions: row.preconditions,
    steps: row.steps, expected_results: row.expected_results, enabled: row.enabled,
  })
  caseEditTab.value = 'info'
  stepsJson.value = []
  // 加载前置步骤和 use_storage
  setupStepsJson.value = (row.setup_steps || []).map(s => ({ ...s }))
  caseUseStorage.value = row.use_storage !== false
  showCreateDialog.value = true
}

// ═══════════════════════════════════════════════════════════
// Lifecycle
// ═══════════════════════════════════════════════════════════
onMounted(async () => {
  connectWs(getWsClientId())
  if (wsStore.initialized) await taskStore.fetchTasks(wsStore.currentId)
  if (route.query.taskId) {
    filterTaskId.value = parseInt(route.query.taskId)
    caseForm.task_id = filterTaskId.value
  } else if (!filterTaskId.value && taskStore.tasks.length > 0) {
    // 没有指定任务时，默认选第一个任务
    filterTaskId.value = taskStore.tasks[0].id
    caseForm.task_id = filterTaskId.value
  }
  if (filterTaskId.value) {
    await taskStore.fetchCases(filterTaskId.value)
    fetchLatestFailedCases()
  } else {
    taskStore.setCases([])
  }
  // 来自任务管理的「录制」按钮直接触发录制
  if (route.query.startRecord === '1' && filterTaskId.value) {
    await startRecording()
  }
})

// 从 Execution 页录制完成后跳回来时，自动刷新用例列表
onActivated(async () => {
  if (route.query.refresh === '1' && filterTaskId.value) {
    await taskStore.fetchCases(filterTaskId.value)
  }
})
watch(showDeprecated, () => { selectedCases.value = [] })
watch(() => wsStore.currentId, async (id) => {
  filterTaskId.value = null; caseForm.task_id = null; taskStore.setCases([])
  selectedCases.value = []
  showCreateDialog.value = false; editingCase.value = null
  if (_genAbortCtrl) { _genAbortCtrl.abort(); _genAbortCtrl = null }
  showProgress.value = false
  await taskStore.fetchTasks(id)
  // 切换工作空间后默认选第一个任务
  if (taskStore.tasks.length > 0) {
    filterTaskId.value = taskStore.tasks[0].id
    caseForm.task_id = filterTaskId.value
    await taskStore.fetchCases(filterTaskId.value)
    fetchLatestFailedCases()
  }
})
watch(() => wsStore.initialized, async (ready) => {
  if (ready) await taskStore.fetchTasks(wsStore.currentId)
})
</script>

<style scoped>
.cases-page { padding: 0; }
.card-header { display: flex; flex-direction: column; gap: 8px; }
.header-row { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; }
.header-controls { display: flex; align-items: center; gap: 10px; }
.page-title { font-size: 16px; font-weight: 600; white-space: nowrap; }
.filter-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.filter-label { color: #909399; font-size: 13px; }
.filter-count { color: #909399; font-size: 13px; white-space: nowrap; }
.action-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

.execution-summary-bar {
  padding: 6px 12px; background: #fafbfc; border-radius: 6px; border: 1px solid #ebeef5;
  display: flex; align-items: center; gap: 10px;
}
.exec-summary-label { color: #606266; font-size: 13px; font-weight: 500; }
.exec-summary-time { color: #909399; font-size: 12px; }
.exec-unknown { color: #c0c4cc; font-size: 12px; }

/* action bar */

.pagination-bar {
  display: flex; justify-content: flex-end;
  padding: 14px 4px 4px;
}

.row-actions { display: flex; align-items: center; justify-content: center; gap: 0; white-space: nowrap; }
.row-actions .el-button { padding: 2px 6px; font-size: 12px; }
.action-sep { display: inline-block; width: 1px; height: 12px; background: #dcdfe6; margin: 0 4px; flex-shrink: 0; }

/* progress */
/* ── AI 生成进度浮层 ─────────────────────────────────────────── */
.gen-toast {
  position: fixed;
  right: 28px;
  bottom: 32px;
  z-index: 3000;
  width: 320px;
  background: #fff;
  border-radius: 14px;
  box-shadow: 0 8px 32px rgba(0,0,0,.14), 0 2px 8px rgba(0,0,0,.08);
  padding: 16px 18px 14px;
  border: 1px solid rgba(64,158,255,.15);
  overflow: hidden;
}
/* 顶部渐变装饰条 */
.gen-toast::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 3px;
  background: linear-gradient(90deg, #409eff 0%, #a855f7 50%, #f59e0b 100%);
  background-size: 200% 100%;
  animation: genRainbow 2.4s linear infinite;
}
@keyframes genRainbow {
  0%   { background-position: 0 0 }
  100% { background-position: 200% 0 }
}

/* 标题栏 */
.gen-toast-header {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 14px;
}
.gen-toast-icon {
  color: #f59e0b;
  display: flex;
  align-items: center;
  animation: genStar 1.4s ease-in-out infinite alternate;
}
@keyframes genStar {
  from { opacity: .7; transform: scale(.9) rotate(-8deg); }
  to   { opacity: 1;  transform: scale(1.1) rotate(8deg); }
}
.gen-star-fill { animation: none; }
.gen-toast-title {
  flex: 1;
  font-size: 14px;
  font-weight: 600;
  color: #1a1a2e;
  letter-spacing: .01em;
}
.gen-toast-pct {
  font-size: 20px;
  font-weight: 700;
  color: #409eff;
  letter-spacing: -.5px;
  line-height: 1;
}

/* 步骤轨道 */
.gen-track {
  display: flex;
  align-items: flex-start;
  gap: 0;
  margin-bottom: 14px;
}
.gen-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  flex-shrink: 0;
}
.gen-node-ring {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  border: 2px solid #dde1e7;
  background: #f5f7fa;
  color: #c0c4cc;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  transition: all .35s ease;
  position: relative;
}
.gen-node.is-active .gen-node-ring {
  border-color: #409eff;
  background: #ecf5ff;
  color: #409eff;
  box-shadow: 0 0 0 4px rgba(64,158,255,.15);
}
.gen-node.is-done .gen-node-ring {
  border-color: #67c23a;
  background: #67c23a;
  color: #fff;
  box-shadow: none;
}
.gen-node-pulse {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #409eff;
  animation: genPulse 1s ease-in-out infinite;
}
@keyframes genPulse {
  0%, 100% { transform: scale(1); opacity: 1; }
  50%       { transform: scale(1.5); opacity: .6; }
}
.gen-node-idx { font-size: 11px; font-weight: 700; color: #c0c4cc; }
.gen-node-label {
  font-size: 10px;
  color: #909399;
  white-space: nowrap;
  transition: color .3s;
}
.gen-node.is-active .gen-node-label { color: #409eff; font-weight: 600; }
.gen-node.is-done  .gen-node-label { color: #67c23a; font-weight: 600; }

.gen-rail {
  flex: 1;
  height: 2px;
  background: #ebeef5;
  margin: 12px 4px 0;  /* margin-top=12px 使连接线垂直居中于圆圈 */
  border-radius: 1px;
  position: relative;
  overflow: hidden;
  transition: background .3s;
}
.gen-rail.is-filled { background: #67c23a; }
.gen-rail:not(.is-filled)::after {
  content: '';
  position: absolute;
  top: 0; left: -100%; width: 100%; height: 100%;
  background: linear-gradient(90deg, transparent 0%, #409eff 50%, transparent 100%);
  animation: genSweep 1.8s ease-in-out infinite;
}
@keyframes genSweep {
  0%   { left: -100% }
  100% { left:  100% }
}

/* 进度条 */
.gen-bar-bg {
  width: 100%;
  height: 6px;
  background: #f0f2f5;
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 10px;
}
.gen-bar-fill {
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(90deg, #409eff 0%, #a855f7 60%, #f59e0b 100%);
  background-size: 200% 100%;
  animation: genRainbow 1.8s linear infinite;
  transition: width .6s cubic-bezier(.4,0,.2,1);
  min-width: 4px;
}

/* 状态文字 */
.gen-stage {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}
.gen-stage-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #409eff;
  flex-shrink: 0;
  animation: genPulse 1.2s ease-in-out infinite;
}
.gen-stage-text {
  font-size: 12px;
  color: #606266;
  line-height: 1.4;
  flex: 1;
}

/* 用例计数 */
.gen-count {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: #409eff;
  font-weight: 500;
  margin-bottom: 4px;
}
.gen-count b { font-weight: 700; }

/* 取消按钮 */
.gen-footer { margin-top: 10px; display: flex; justify-content: flex-end; }
.gen-cancel-btn {
  font-size: 12px;
  color: #909399;
  background: none;
  border: 1px solid #dde1e7;
  border-radius: 6px;
  padding: 4px 12px;
  cursor: pointer;
  transition: all .2s;
}
.gen-cancel-btn:hover { color: #f56c6c; border-color: #f56c6c; background: #fef0f0; }

/* 浮层进出动画 */
.gen-toast-enter-active { animation: genSlideIn .3s cubic-bezier(.34,1.56,.64,1); }
.gen-toast-leave-active { animation: genSlideIn .2s ease-in reverse; }
@keyframes genSlideIn {
  from { opacity: 0; transform: translateY(20px) scale(.95); }
  to   { opacity: 1; transform: translateY(0)   scale(1); }
}

/* 通用 fade */
.fade-enter-active, .fade-leave-active { transition: opacity .3s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

/* coverage */
.coverage-panel { padding: 0 4px; }
.score-block { display: flex; align-items: center; gap: 20px; padding: 8px 0; }
.score-meta { display: flex; flex-direction: column; gap: 4px; }
.score-title { font-size: 16px; font-weight: 600; }
.score-total { color: #909399; font-size: 13px; }
.section-title { font-weight: 600; margin: 4px 0 10px; color: #303133; }
.priority-bars { display: flex; flex-direction: column; gap: 8px; }
.priority-row { display: flex; align-items: center; }
.count-label { width: 38px; text-align: right; color: #606266; font-size: 13px; }
.elem-coverage { padding: 4px 0; }
.elem-note { margin: 8px 0 0; color: #909399; font-size: 13px; }
.suggestions { padding-left: 18px; margin: 4px 0; }
.suggestions li { line-height: 1.8; color: #606266; font-size: 13px; }
.zero-warn { color: #f56c6c; font-weight: 600; }
.coverage-empty { display: flex; justify-content: center; align-items: center; height: 200px; }

/* deprecated */
.case-deprecated { text-decoration: line-through; color: #c0c4cc; }

/* 来源标签 — 字号小一号，不抢主视觉 */
.source-tag { font-size: 11px; padding: 0 5px; height: 18px; line-height: 18px; }

/* fix result */
.fix-result-body { padding: 4px 0; }
.fix-stats { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.fix-item-title { display: flex; align-items: center; gap: 10px; }
.fix-case-name { font-size: 14px; font-weight: 500; }
.fix-compare { margin: 4px 0 10px; }
.fix-before, .fix-after { margin-bottom: 10px; }
.fix-before pre, .fix-after pre {
  margin: 6px 0 0; padding: 10px 12px; border-radius: 6px;
  font-size: 12px; line-height: 1.6; white-space: pre-wrap; word-break: break-all; max-height: 160px; overflow-y: auto;
}
.fix-before pre { background: #fef0f0; border: 1px solid #fde2e2; color: #c0392b; }
.fix-after pre { background: #f0f9eb; border: 1px solid #e1f3d8; color: #27ae60; }
.fix-note { display: flex; align-items: center; gap: 6px; padding: 8px 12px; border-radius: 6px; background: #ecf5ff; color: #409eff; font-size: 13px; }
.new-case-item { display: flex; align-items: center; gap: 8px; padding: 6px 10px; margin-bottom: 4px; border-radius: 4px; background: #f5f7fa; font-size: 13px; }

/* ── 场景覆盖视图 ── */
.scene-coverage-empty { padding: 40px 0; }
.scene-overview {
  display: flex; align-items: center; gap: 16px; padding: 14px 16px;
  background: #f8faff; border-radius: 8px; margin-bottom: 16px;
}
.scene-overview-stats { display: flex; align-items: baseline; gap: 4px; white-space: nowrap; }
.ov-num { font-size: 28px; font-weight: 700; color: #409eff; }
.ov-sep { font-size: 18px; color: #c0c4cc; }
.ov-total { font-size: 22px; font-weight: 600; color: #606266; }
.ov-label { font-size: 13px; color: #909399; margin-left: 4px; }

.scene-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}
.scene-cov-card {
  border: 1px solid #e4e7ed; border-radius: 10px; padding: 14px 16px;
  background: #fff; transition: box-shadow .2s, border-color .2s;
}
.scene-cov-card:hover { box-shadow: 0 2px 12px rgba(0,0,0,.08); }
.scene-cov-card.covered { border-color: #b7ebc8; background: #f6fff9; }
.scene-cov-card.uncovered { border-color: #fcd3d3; background: #fff8f8; }
.scene-cov-header {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 8px;
}
.scene-cov-name {
  flex: 1; font-size: 14px; font-weight: 600; color: #303133;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.scene-cov-desc { font-size: 13px; color: #606266; margin-bottom: 10px; line-height: 1.5; }
.scene-cov-cases { margin-bottom: 10px; }
.scene-cov-case-item {
  display: flex; align-items: center; gap: 6px; font-size: 12px; color: #606266;
  padding: 4px 0; border-bottom: 1px dashed #f0f0f0;
}
.scene-cov-actions { display: flex; justify-content: flex-end; }

/* ── 步骤编辑器 ── */
.step-editor-toolbar {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 4px 12px; border-bottom: 1px solid #f0f0f0; margin-bottom: 10px;
}
.step-table { display: flex; flex-direction: column; gap: 4px; }

.step-header { background: #f5f7fa !important; font-weight: 600; font-size: 12px;
  color: #606266; border-radius: 6px; }

.step-row {
  display: grid;
  grid-template-columns: 32px 52px 130px 1fr 140px 130px 80px;
  gap: 6px; align-items: center;
  padding: 6px 8px; border-radius: 6px;
  border: 1px solid #f0f0f0; background: #fff;
  transition: background .15s;
}
.step-row:hover { background: #fafbff; }
.step-row-danger { border-color: #fde2e2; background: #fff8f8; }
.step-row-auto   { border-style: dashed; opacity: .85; }

.step-col { overflow: hidden; }
.col-num  { display: flex; justify-content: center; }
.step-seq {
  width: 22px; height: 22px;
  border-radius: 50%;
  background: #e8edf5;
  color: #606266;
  font-size: 11px; font-weight: 600;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.col-grade   { display: flex; justify-content: center; }
.col-ops     { display: flex; align-items: center; justify-content: flex-end; }
.col-opts    { display: flex; align-items: center; gap: 4px; }

.grade-badge { cursor: default; font-weight: 700; min-width: 28px; text-align: center; }

/* Selector 胶囊 */
.selector-pill {
  display: flex; align-items: center; gap: 4px; cursor: pointer;
  border: 1px solid #dcdfe6; border-radius: 4px; padding: 3px 8px;
  font-size: 12px; background: #fff; transition: border-color .2s;
  max-width: 100%; overflow: hidden;
}
.selector-pill:hover { border-color: #409eff; }
.selector-pill.grade-a { border-color: #b7ebc8; }
.selector-pill.grade-b { border-color: #fcd3a6; }
.selector-pill.grade-c { border-color: #d8d8d8; }
.selector-pill.grade-d { border-color: #fcd3d3; }
.selector-text { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* 备选列表 */
.sel-candidates { max-height: 260px; overflow-y: auto; }
.sel-candidate-item {
  display: flex; align-items: center; gap: 8px; padding: 6px 8px;
  border-radius: 6px; cursor: pointer; font-size: 12px;
  transition: background .15s;
}
.sel-candidate-item:hover { background: #f0f4ff; }
.sel-candidate-item.sel-active { background: #ecf5ff; }
.sel-cand-text { flex: 1; word-break: break-all; color: #303133; }

/* ── AI 场景规划抽屉 ────────────────────────────────────────────── */

/* 抽屉整体覆盖 */
.scene-planner-drawer :deep(.el-drawer__header) {
  background: linear-gradient(135deg, #f8fbff 0%, #f0f6ff 100%);
  border-bottom: 1px solid #e4edf8;
  padding: 16px 20px;
  margin-bottom: 0;
}
.scene-planner-drawer :deep(.el-drawer__body) {
  padding: 20px;
  background: #f7f9fc;
}

/* 抽屉 header */
.scene-drawer-header {
  display: flex; align-items: center; justify-content: space-between;
  flex: 1; gap: 12px; min-width: 0;
}
.scene-drawer-title {
  display: flex; align-items: center; gap: 10px;
  font-size: 16px; font-weight: 700; color: #1a2540;
}
.scene-drawer-icon-wrap {
  width: 32px; height: 32px; border-radius: 8px;
  background: linear-gradient(135deg, #4f87ff 0%, #2c5af0 100%);
  display: flex; align-items: center; justify-content: center;
  color: #fff; flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(64,100,255,.3);
}
.scene-count-badge {
  font-size: 11px; font-weight: 600;
  background: #eef3ff; color: #4f7fff;
  border-color: #c8d8ff;
}
.scene-drawer-progress {
  display: flex; align-items: center; gap: 10px; flex-shrink: 0;
}
.scene-progress-label {
  font-size: 12px; color: #8a94a6; white-space: nowrap;
  display: flex; align-items: baseline; gap: 2px;
}
.scene-progress-done { font-size: 16px; font-weight: 700; color: #4f87ff; }
.scene-progress-sep  { color: #c0c8d5; }
.scene-progress-unit { margin-left: 3px; }

/* 输入区 */
.scene-input-area { display: flex; flex-direction: column; gap: 14px; }

.scene-intro-card {
  background: linear-gradient(135deg, #2c5af0 0%, #4f87ff 60%, #7ba8ff 100%);
  border-radius: 14px;
  padding: 18px 20px;
  box-shadow: 0 4px 20px rgba(64,100,255,.2);
}
.scene-intro-hero {
  display: flex; align-items: center; gap: 14px; margin-bottom: 16px;
}
.scene-intro-icon-wrap {
  width: 44px; height: 44px; border-radius: 12px;
  background: rgba(255,255,255,.2);
  border: 1px solid rgba(255,255,255,.3);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  backdrop-filter: blur(8px);
}
.scene-intro-text { flex: 1; }
.scene-intro-title {
  font-size: 15px; font-weight: 700; color: #fff;
  margin-bottom: 3px;
}
.scene-intro-subtitle { font-size: 12px; color: rgba(255,255,255,.75); }

.scene-dimensions { display: flex; flex-wrap: wrap; gap: 6px; }
.dim-pill {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 4px 10px; border-radius: 20px;
  font-size: 11px; font-weight: 600;
  border: 1px solid rgba(255,255,255,.25);
  background: rgba(255,255,255,.15);
  color: #fff;
  backdrop-filter: blur(4px);
}
.dim-dot {
  width: 5px; height: 5px; border-radius: 50%;
  background: rgba(255,255,255,.8); flex-shrink: 0;
}
/* 保留旧的颜色类（兼容 scene-coverage 面板） */
.dim-success { background: #f0fff4; color: #27ae60; border-color: #b7ebc8; }
.dim-warning { background: #fffbf0; color: #e6a23c; border-color: #f5dfa0; }
.dim-primary { background: #f0f7ff; color: #409eff; border-color: #c6deff; }
.dim-info    { background: #f4f4f5; color: #909399; border-color: #dcdfe6; }
.dim-danger  { background: #fff5f5; color: #f56c6c; border-color: #fcd3d3; }
/* 抽屉内 dim-pill 覆盖 */
.scene-intro-card .dim-success,
.scene-intro-card .dim-warning,
.scene-intro-card .dim-primary,
.scene-intro-card .dim-info,
.scene-intro-card .dim-danger {
  background: rgba(255,255,255,.15);
  color: #fff;
  border-color: rgba(255,255,255,.25);
}

/* 状态提示行 */
.scene-status-row { display: flex; flex-direction: column; gap: 8px; }
.scene-status-item {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 14px; border-radius: 10px; font-size: 13px;
  background: #fff;
  border: 1px solid #e8edf5;
  box-shadow: 0 1px 4px rgba(0,0,0,.04);
}
.scene-status-icon-wrap {
  width: 26px; height: 26px; border-radius: 8px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
}
.scene-status-icon-wrap.ok   { background: #edfff5; color: #22c55e; }
.scene-status-icon-wrap.warn { background: #fff8ec; color: #f59e0b; }
.scene-status-icon-wrap.doc  { background: #eef3ff; color: #4f87ff; }
.scene-status-content { flex: 1; min-width: 0; }
.scene-status-text { font-size: 13px; font-weight: 600; color: #1a2540; display: block; }
.scene-status-sub  { font-size: 11px; color: #9aa3b2; }
.scene-status-btn  { flex-shrink: 0; }
.scene-status-link { flex-shrink: 0; color: #9aa3b2 !important; font-size: 12px; }
.scene-status-link:hover { color: #4f87ff !important; }

/* 描述输入 */
.scene-desc-input { display: flex; flex-direction: column; gap: 8px; }
.scene-desc-label {
  font-size: 13px; font-weight: 600; color: #1a2540;
  display: flex; align-items: center; gap: 8px;
}
.scene-desc-opt {
  font-weight: 400; color: #9aa3b2; font-size: 12px;
}
.scene-desc-textarea :deep(.el-textarea__inner) {
  border-radius: 10px;
  border-color: #dce4f0;
  background: #fff;
  font-size: 13px;
  resize: none;
}
.scene-desc-textarea :deep(.el-textarea__inner:focus) {
  border-color: #4f87ff;
  box-shadow: 0 0 0 3px rgba(79,135,255,.12);
}

/* 生成按钮 */
.scene-gen-btn {
  width: 100%; height: 46px; font-size: 14px; font-weight: 700;
  border-radius: 12px;
  background: linear-gradient(135deg, #4f87ff 0%, #2c5af0 100%);
  border: none;
  box-shadow: 0 4px 14px rgba(64,100,255,.35);
  letter-spacing: .5px;
  transition: transform .15s, box-shadow .15s;
}
.scene-gen-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 20px rgba(64,100,255,.4);
}
.scene-gen-btn:active { transform: translateY(0); }

/* 场景列表区 */
.scene-list-area { display: flex; flex-direction: column; height: 100%; }
.scene-toolbar {
  display: flex; justify-content: space-between; align-items: center;
  padding: 0 0 12px;
  border-bottom: 1px solid #e8edf5;
  margin-bottom: 12px;
  flex-shrink: 0;
}
.scene-toolbar-left {
  display: flex; align-items: center; gap: 5px;
}
.scene-toolbar-right {
  display: flex; align-items: center; gap: 6px;
}
.scene-toolbar-tip { font-size: 12px; color: #aab4c5; }
.scene-toolbar-btn { border-radius: 8px; font-size: 12px; }
.scene-toolbar-btn-danger {
  font-size: 12px; color: #f56c6c;
}
.scene-toolbar-btn-danger:hover { background: #fff0f0; }

.scene-scrollbar { flex: 1; overflow: hidden; }
.scene-list { display: flex; flex-direction: column; gap: 10px; padding: 2px 2px 12px; }

/* 场景卡片 */
.scene-card {
  border: 1.5px solid #e8edf5;
  border-radius: 12px;
  padding: 14px 16px;
  background: #fff;
  transition: box-shadow .2s, border-color .2s, transform .15s;
  position: relative;
  overflow: hidden;
}
.scene-card::before {
  content: '';
  position: absolute; left: 0; top: 0; bottom: 0;
  width: 3px;
  background: #dce4f0;
  border-radius: 12px 0 0 12px;
  transition: background .2s;
}
.scene-card:hover {
  box-shadow: 0 4px 20px rgba(64,100,255,.1);
  border-color: #b8ceff;
  transform: translateY(-1px);
}
.scene-card:hover::before { background: #4f87ff; }

.scene-recorded {
  border-color: #a8e6c0;
  background: linear-gradient(135deg, #f5fff9 0%, #edfff5 100%);
}
.scene-recorded::before { background: #22c55e; }

.scene-p0::before { background: #ef4444; }
.scene-p1::before { background: #f59e0b; }

.scene-card-header { margin-bottom: 8px; }
.scene-card-meta {
  display: flex; align-items: center; gap: 6px; margin-bottom: 7px;
}
.scene-index {
  width: 20px; height: 20px; border-radius: 6px;
  background: #f0f4fa; color: #6b7a99;
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 700; flex-shrink: 0;
}
.scene-priority {
  padding: 2px 7px; border-radius: 5px;
  font-size: 11px; font-weight: 700;
}
.scene-priority-p0 { background: #fff0f0; color: #ef4444; }
.scene-priority-p1 { background: #fff8ec; color: #f59e0b; }
.scene-priority-p2 { background: #f0f4ff; color: #4f87ff; }
.scene-dim-tag {
  font-size: 11px; color: #9aa3b2;
  background: #f4f6fa; border-radius: 4px;
  padding: 2px 7px;
}

.scene-card-title-row {
  display: flex; align-items: center; gap: 8px;
}
.scene-name {
  flex: 1;
  font-size: 14px; font-weight: 600; color: #1a2540;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  cursor: text;
  transition: color .2s;
}
.scene-name:hover { color: #4f87ff; }
.scene-done-badge {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 2px 8px; border-radius: 20px;
  font-size: 11px; font-weight: 700;
  background: #22c55e; color: #fff;
  flex-shrink: 0;
}
.scene-remove-btn {
  color: #c0c8d5 !important; flex-shrink: 0;
  transition: color .2s;
}
.scene-remove-btn:hover { color: #ef4444 !important; }

.scene-desc {
  font-size: 13px; color: #6b7a99; line-height: 1.65;
  margin-bottom: 10px; cursor: text;
  transition: color .2s;
}
.scene-desc:hover { color: #1a2540; }
.scene-desc-edit { margin-bottom: 10px; }

/* 展开步骤 */
.scene-expand-btn {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 12px; color: #9aa3b2; cursor: pointer;
  margin-bottom: 10px; transition: color .2s;
  user-select: none;
}
.scene-expand-btn:hover { color: #4f87ff; }
.scene-expand-icon {
  width: 16px; height: 16px; border-radius: 4px;
  background: #f0f4fa; display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; transition: background .2s;
}
.scene-expand-btn:hover .scene-expand-icon { background: #eef3ff; }

.scene-steps {
  display: flex; flex-direction: column; gap: 6px;
  background: #f7f9fc; border-radius: 10px;
  padding: 12px 14px; margin-bottom: 10px;
  border: 1px solid #e8edf5;
}
.scene-step-item {
  display: flex; align-items: flex-start; gap: 10px;
  font-size: 12px; color: #5a6a82; line-height: 1.65;
}
.scene-step-num {
  flex-shrink: 0; width: 20px; height: 20px; border-radius: 6px;
  background: linear-gradient(135deg, #4f87ff 0%, #2c5af0 100%);
  color: #fff;
  display: flex; align-items: center; justify-content: center;
  font-size: 10px; font-weight: 700; margin-top: 1px;
}
.scene-step-text { flex: 1; }
.scene-expected {
  display: flex; align-items: flex-start; gap: 7px;
  font-size: 12px; color: #16a34a;
  background: linear-gradient(135deg, #f0fff6 0%, #eafff4 100%);
  border-radius: 8px; border: 1px solid #bbf7d0;
  padding: 8px 12px; line-height: 1.55; margin-top: 4px;
}

.scene-actions {
  display: flex; justify-content: flex-end; margin-top: 10px;
  padding-top: 10px; border-top: 1px solid #f0f4fa;
}
.scene-record-btn {
  border-radius: 8px; font-weight: 600;
  background: linear-gradient(135deg, #4f87ff 0%, #2c5af0 100%);
  border: none;
  box-shadow: 0 2px 8px rgba(64,100,255,.25);
}
.scene-rerecord-btn {
  border-radius: 8px; color: #6b7a99;
  border-color: #dce4f0; background: #f7f9fc;
}
.scene-rerecord-btn:hover { border-color: #4f87ff; color: #4f87ff; background: #eef3ff; }

/* 完成横幅 */
.scene-done-banner {
  margin-top: 12px; flex-shrink: 0;
  background: linear-gradient(135deg, #edfff5 0%, #f0fff9 100%);
  border: 1.5px solid #a8e6c0; border-radius: 14px;
  padding: 22px 20px; text-align: center;
  box-shadow: 0 4px 16px rgba(34,197,94,.1);
}
.scene-done-confetti { font-size: 32px; margin-bottom: 8px; line-height: 1; }
.scene-done-title {
  font-size: 15px; font-weight: 700; color: #16a34a; margin-bottom: 5px;
}
.scene-done-sub { font-size: 13px; color: #4ade80; }

/* 完成横幅过渡 */
.scene-done-fade-enter-active { animation: sceneDoneIn .4s cubic-bezier(.34,1.56,.64,1); }
@keyframes sceneDoneIn {
  from { opacity: 0; transform: translateY(12px) scale(.97); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}

/* 末尾添加步骤按钮 */
.add-step-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-top: 8px;
  padding: 8px;
  border: 1.5px dashed #d0d7e3;
  border-radius: 6px;
  color: #909399;
  font-size: 13px;
  cursor: pointer;
  transition: border-color .2s, color .2s, background .2s;
}
.add-step-btn:hover {
  border-color: #409eff;
  color: #409eff;
  background: #f0f7ff;
}

/* 录制步骤列表 */
.rec-step-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 6px;
  background: #f8fafc;
  border: 1px solid #eef0f3;
  transition: background .15s;
}
.rec-step-item:hover { background: #f0f4ff; border-color: #c6d8f5; }
.rec-step-num {
  flex-shrink: 0;
  width: 20px; height: 20px;
  border-radius: 50%;
  background: #e8edf5;
  color: #606266;
  font-size: 11px; font-weight: 600;
  display: flex; align-items: center; justify-content: center;
  margin-top: 1px;
}
.rec-step-tag { flex-shrink: 0; margin-top: 1px; }
.rec-step-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.rec-step-desc {
  font-size: 13px;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.rec-step-sel {
  font-size: 11px;
  color: #909399;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: 'SFMono-Regular', Consolas, monospace;
}
.rec-step-val {
  font-size: 11px;
  color: #67c23a;
  font-family: 'SFMono-Regular', Consolas, monospace;
}
</style>
