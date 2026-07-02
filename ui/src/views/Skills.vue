<template>
  <div class="skills-page">
    <!-- 顶部标题栏 -->
    <div class="page-header">
      <div class="page-title">
        <el-icon size="22" class="title-icon"><Grid /></el-icon>
        <span>技能管理</span>
        <el-tag type="info" size="small" style="margin-left:10px;">{{ skills.length }} 个技能</el-tag>
      </div>
      <div class="header-actions">
        <el-input
          v-model="searchText"
          placeholder="搜索技能名称或描述..."
          style="width: 240px;"
          clearable
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-select v-model="filterCategory" placeholder="全部类别" style="width:150px;" clearable>
          <el-option
            v-for="cat in allCategories"
            :key="cat"
            :label="cat"
            :value="cat"
          />
        </el-select>
        <el-button type="primary" @click="loadSkills" :loading="loading">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
      </div>
    </div>

    <!-- 统计栏 -->
    <el-row :gutter="16" class="stats-row">
      <el-col :span="6">
        <div class="stat-card stat-total">
          <div class="stat-icon"><el-icon size="28"><Grid /></el-icon></div>
          <div class="stat-body">
            <div class="stat-value">{{ skills.length }}</div>
            <div class="stat-label">技能总数</div>
          </div>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="stat-card stat-enabled">
          <div class="stat-icon"><el-icon size="28"><CircleCheck /></el-icon></div>
          <div class="stat-body">
            <div class="stat-value">{{ enabledCount }}</div>
            <div class="stat-label">已启用</div>
          </div>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="stat-card stat-category">
          <div class="stat-icon"><el-icon size="28"><Menu /></el-icon></div>
          <div class="stat-body">
            <div class="stat-value">{{ categoryCount }}</div>
            <div class="stat-label">技能类别</div>
          </div>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="stat-card stat-formats">
          <div class="stat-icon"><el-icon size="28"><Document /></el-icon></div>
          <div class="stat-body">
            <div class="stat-value">{{ docFormatsCount }}</div>
            <div class="stat-label">文档格式</div>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 技能卡片网格 -->
    <div v-loading="loading" class="skills-grid">
      <div
        v-for="skill in filteredSkills"
        :key="skill.name"
        class="skill-card"
        :class="{ 'skill-disabled': isDisabled(skill.name) }"
      >
        <!-- 卡片头部 -->
        <div class="skill-card-header">
          <div class="skill-card-icon" :class="`icon-${skill.category}`">
            <el-icon size="24"><component :is="getCategoryIcon(skill.category)" /></el-icon>
          </div>
          <div class="skill-card-title">
            <div class="skill-name">{{ skill.name }}</div>
            <div class="skill-meta">
              <el-tag :type="getCategoryType(skill.category)" size="small">{{ skill.category }}</el-tag>
              <el-tag type="info" size="small">v{{ skill.version }}</el-tag>
            </div>
          </div>
          <el-switch
            :model-value="!isDisabled(skill.name)"
            size="small"
            class="skill-switch"
            @change="(val) => toggleEnabled(skill.name, val)"
          />
        </div>

        <!-- 描述 -->
        <div class="skill-desc">{{ skill.description }}</div>

        <!-- 文档格式标签（仅文档解析技能） -->
        <div v-if="skill.category === 'document-parsing'" class="skill-formats">
          <el-tag
            v-for="fmt in docFormats"
            :key="fmt"
            :type="getFormatType(fmt)"
            size="small"
            class="fmt-tag"
          >{{ fmt }}</el-tag>
        </div>

        <!-- 触发词 -->
        <div v-else class="skill-triggers">
          <el-tag
            v-for="(t, i) in (skill.triggers || []).slice(0, 3)"
            :key="i"
            type="success"
            size="small"
            class="trigger-tag"
          >{{ t }}</el-tag>
          <span v-if="(skill.triggers || []).length > 3" class="trigger-more">+{{ skill.triggers.length - 3 }}</span>
        </div>

        <!-- 操作栏 -->
        <div class="skill-card-footer">
          <el-button size="small" type="primary" link @click="viewSkillDetail(skill)">
            <el-icon><InfoFilled /></el-icon> 详情
          </el-button>
          <el-divider direction="vertical" />
          <el-button size="small" type="success" link @click="viewSkillFiles(skill)">
            <el-icon><FolderOpened /></el-icon> 文件
          </el-button>
          <el-divider direction="vertical" />
          <el-button size="small" type="warning" link @click="reloadSkill(skill)">
            <el-icon><RefreshRight /></el-icon> 重载
          </el-button>
          <el-divider direction="vertical" />
          <el-button size="small" link @click="executeSkill(skill)" style="color:#409eff;">
            <el-icon><VideoPlay /></el-icon> 执行
          </el-button>
        </div>
      </div>

      <!-- 空态 -->
      <div v-if="!loading && filteredSkills.length === 0" class="skills-empty">
        <el-empty :description="searchText || filterCategory ? '没有匹配的技能' : '暂无技能，请点击刷新'" />
      </div>
    </div>

    <!-- ===== 技能详情 ===== -->
    <el-dialog v-model="showDetailDialog" :title="`技能详情 · ${currentSkill?.name || ''}`" width="760px">
      <div v-if="currentSkill" class="skill-detail">
        <el-tabs v-model="detailTab">
          <el-tab-pane label="基本信息" name="info">
            <el-descriptions :column="2" border>
              <el-descriptions-item label="技能名称">{{ currentSkill.name }}</el-descriptions-item>
              <el-descriptions-item label="版本">v{{ currentSkill.version }}</el-descriptions-item>
              <el-descriptions-item label="类别">
                <el-tag :type="getCategoryType(currentSkill.category)">{{ currentSkill.category }}</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="状态">
                <el-tag :type="isDisabled(currentSkill.name) ? 'danger' : 'success'">
                  {{ isDisabled(currentSkill.name) ? '已禁用' : '已启用' }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="描述" :span="2">{{ currentSkill.description }}</el-descriptions-item>
              <el-descriptions-item label="文件路径" :span="2">
                <el-text type="info" size="small">{{ currentSkill.file_path }}</el-text>
              </el-descriptions-item>
            </el-descriptions>

            <template v-if="currentSkill.category === 'document-parsing'">
              <el-divider>支持的文档格式</el-divider>
              <div class="format-tags">
                <el-tag
                  v-for="fmt in docFormats"
                  :key="fmt"
                  :type="getFormatType(fmt)"
                  style="margin-right:8px;margin-bottom:8px;"
                >{{ fmt }}</el-tag>
              </div>
            </template>

            <el-divider>触发词</el-divider>
            <div class="tag-wrap">
              <el-tag
                v-for="(trigger, i) in currentSkill.triggers"
                :key="i"
                type="success"
                style="margin-right:8px;margin-bottom:8px;"
              >{{ trigger }}</el-tag>
            </div>

            <el-divider>使用示例</el-divider>
            <div v-if="currentSkill.examples?.length">
              <el-card
                v-for="(example, i) in currentSkill.examples"
                :key="i"
                shadow="never"
                style="margin-bottom:8px;background:#f5f7fa;"
              >
                <code>{{ example }}</code>
              </el-card>
            </div>
            <el-empty v-else description="暂无示例" :image-size="60" />
          </el-tab-pane>

          <el-tab-pane label="技能文档" name="doc">
            <div v-loading="skillDocLoading" style="min-height:80px;">
              <div v-if="skillDocContent" class="skill-doc-content">
                <pre>{{ skillDocContent }}</pre>
              </div>
              <el-empty v-else-if="!skillDocLoading" description="暂无文档" />
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>
      <template #footer>
        <el-button @click="showDetailDialog = false">关闭</el-button>
        <el-button
          :type="isDisabled(currentSkill?.name) ? 'success' : 'danger'"
          @click="toggleEnabled(currentSkill?.name, isDisabled(currentSkill?.name))"
        >{{ isDisabled(currentSkill?.name) ? '启用技能' : '禁用技能' }}</el-button>
        <el-button type="primary" @click="executeSkill(currentSkill)">执行技能</el-button>
      </template>
    </el-dialog>

    <!-- ===== 技能文件 ===== -->
    <el-dialog v-model="showFilesDialog" :title="`技能文件 · ${currentSkill?.name || ''}`" width="800px">
      <div v-if="skillFiles">
        <el-alert :title="`路径: ${skillFiles.path}`" type="info" :closable="false" style="margin-bottom:14px;" />
        <el-table :data="skillFiles.files" stripe max-height="400">
          <el-table-column prop="name" label="文件名" min-width="200" />
          <el-table-column prop="path" label="路径" min-width="250" show-overflow-tooltip />
          <el-table-column prop="type" label="类型" width="80">
            <template #default="{ row }">
              <el-tag size="small" type="info">{{ row.type || 'file' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="size" label="大小" width="100">
            <template #default="{ row }">{{ formatSize(row.size) }}</template>
          </el-table-column>
        </el-table>
      </div>
      <template #footer>
        <el-button @click="showFilesDialog = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- ===== 执行技能 ===== -->
    <el-dialog v-model="showExecuteDialog" :title="`执行技能 · ${executeForm.skillName}`" width="620px">
      <el-form :model="executeForm" label-width="120px">
        <el-form-item label="技能名称">
          <el-input v-model="executeForm.skillName" disabled />
        </el-form-item>
        <template v-if="executeForm.skillName === 'document_parser'">
          <el-form-item label="文档路径" required>
            <el-input v-model="executeForm.documentPath" placeholder="输入文档文件的绝对路径" />
          </el-form-item>
          <el-form-item label="文档格式">
            <el-select v-model="executeForm.fileType" style="width:100%">
              <el-option label="自动检测 (auto)" value="auto" />
              <el-option-group label="文档类">
                <el-option label="PDF (.pdf)" value="pdf" />
                <el-option label="Word (.docx)" value="docx" />
                <el-option label="Word 97-2003 (.doc)" value="doc" />
              </el-option-group>
              <el-option-group label="表格类">
                <el-option label="Excel (.xlsx)" value="xlsx" />
                <el-option label="Excel 97-2003 (.xls)" value="xls" />
                <el-option label="CSV (.csv)" value="csv" />
              </el-option-group>
              <el-option-group label="演示类">
                <el-option label="PowerPoint (.pptx)" value="pptx" />
              </el-option-group>
              <el-option-group label="文本类">
                <el-option label="Markdown (.md)" value="md" />
                <el-option label="纯文本 (.txt)" value="txt" />
                <el-option label="HTML (.html)" value="html" />
                <el-option label="JSON (.json)" value="json" />
              </el-option-group>
            </el-select>
          </el-form-item>
        </template>
        <template v-else>
          <el-form-item label="测试套件" v-if="executeForm.hasSuite">
            <el-select v-model="executeForm.suite" style="width:100%">
              <el-option label="冒烟测试 (smoke)" value="smoke" />
              <el-option label="回归测试 (regression)" value="regression" />
              <el-option label="完整测试 (full)" value="full" />
            </el-select>
          </el-form-item>
          <el-form-item label="无头模式">
            <el-switch v-model="executeForm.headless" />
          </el-form-item>
        </template>
      </el-form>
      <div v-if="executeResult" class="execute-result">
        <el-divider>执行结果</el-divider>
        <el-alert
          :type="executeResult.status === 'success' ? 'success' : 'error'"
          :title="executeResult.status === 'success' ? '执行成功' : '执行失败'"
          :closable="false"
        >
          <pre>{{ executeResult.stdout || executeResult.message }}</pre>
        </el-alert>
      </div>
      <template #footer>
        <el-button @click="showExecuteDialog = false">关闭</el-button>
        <el-button type="primary" @click="confirmExecute" :loading="executing">执行</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import request from '../api'

const STORAGE_KEY = 'uitest_skills_disabled'

const skills = ref([])
const loading = ref(false)
const searchText = ref('')
const filterCategory = ref('')
const disabledSkills = ref(new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')))

const showDetailDialog = ref(false)
const showFilesDialog = ref(false)
const showExecuteDialog = ref(false)
const currentSkill = ref(null)
const skillFiles = ref(null)
const executing = ref(false)
const executeResult = ref(null)
const detailTab = ref('info')
const skillDocContent = ref('')
const skillDocLoading = ref(false)

const executeForm = reactive({
  skillName: '',
  suite: 'smoke',
  headless: true,
  hasSuite: false,
  documentPath: '',
  fileType: 'auto',
})

const docFormats = ['PDF', 'DOCX', 'DOC', 'XLSX', 'XLS', 'PPTX', 'MD', 'TXT', 'CSV', 'HTML', 'JSON']

// ── computed ──────────────────────────────────────────────────────────────
const allCategories = computed(() => [...new Set(skills.value.map(s => s.category).filter(Boolean))])

const filteredSkills = computed(() => {
  let list = skills.value
  if (filterCategory.value) list = list.filter(s => s.category === filterCategory.value)
  const q = searchText.value.trim().toLowerCase()
  if (q) list = list.filter(s => s.name?.toLowerCase().includes(q) || s.description?.toLowerCase().includes(q))
  return list
})

const enabledCount = computed(() => skills.value.filter(s => !disabledSkills.value.has(s.name)).length)
const categoryCount = computed(() => allCategories.value.length)
const docFormatsCount = computed(() => skills.value.some(s => s.category === 'document-parsing') ? docFormats.length : 0)

// ── 状态 ──────────────────────────────────────────────────────────────────
const isDisabled = (name) => disabledSkills.value.has(name)

const toggleEnabled = (name, val) => {
  if (!name) return
  const next = new Set(disabledSkills.value)
  if (val) next.delete(name)
  else next.add(name)
  disabledSkills.value = next
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...next]))
}

// ── 数据加载 ──────────────────────────────────────────────────────────────
const loadSkills = async () => {
  loading.value = true
  try {
    const res = await request.get('/skills')
    skills.value = res.skills || []
    ElMessage.success(`已加载 ${skills.value.length} 个技能`)
  } catch (err) {
    ElMessage.error('加载技能失败: ' + err.message)
  } finally {
    loading.value = false
  }
}

// ── 详情 / 文档 ────────────────────────────────────────────────────────────
const viewSkillDetail = async (skill) => {
  currentSkill.value = skill
  detailTab.value = 'info'
  skillDocContent.value = ''
  showDetailDialog.value = true
}

watch(detailTab, async (tab) => {
  if (tab === 'doc' && currentSkill.value && !skillDocContent.value) {
    skillDocLoading.value = true
    try {
      const res = await request.get(`/skills/${currentSkill.value.name}/file-content`, {
        params: { path: 'SKILL.md' }
      })
      skillDocContent.value = res.content || '暂无文档'
    } catch {
      skillDocContent.value = '加载文档失败'
    } finally {
      skillDocLoading.value = false
    }
  }
})

const viewSkillFiles = async (skill) => {
  currentSkill.value = skill
  try {
    const res = await request.get(`/skills/${skill.name}/files`)
    skillFiles.value = res
    showFilesDialog.value = true
  } catch (err) {
    ElMessage.error('获取技能文件失败: ' + err.message)
  }
}

const reloadSkill = async (skill) => {
  try {
    await request.post(`/skills/${skill.name}/reload`)
    ElMessage.success(`技能 "${skill.name}" 已重载`)
    await loadSkills()
  } catch (err) {
    ElMessage.error('重载技能失败: ' + err.message)
  }
}

const executeSkill = (skill) => {
  if (!skill) return
  showDetailDialog.value = false
  currentSkill.value = skill
  executeForm.skillName = skill.name
  executeForm.hasSuite = skill.name.includes('web') || skill.name.includes('test')
  executeForm.documentPath = ''
  executeForm.fileType = 'auto'
  executeResult.value = null
  showExecuteDialog.value = true
}

const confirmExecute = async () => {
  executing.value = true
  executeResult.value = null
  try {
    let message = `执行${executeForm.skillName}`
    if (executeForm.skillName === 'document_parser' && executeForm.documentPath) {
      message = `解析文档 ${executeForm.documentPath}`
    }
    const res = await request.post('/command', { message })
    executeResult.value = res.result || res
    ElMessage.success('技能执行完成')
  } catch (err) {
    executeResult.value = { status: 'error', message: err.message }
    ElMessage.error('执行技能失败: ' + err.message)
  } finally {
    executing.value = false
  }
}

// ── 工具函数 ──────────────────────────────────────────────────────────────
const getCategoryType = (category) => {
  const map = {
    'web-testing': 'success', 'api-testing': 'warning',
    'test-generation': 'primary', 'reporting': 'info',
    'execution': 'danger', 'document-parsing': '',
  }
  return map[category] || ''
}

const getCategoryIcon = (category) => {
  const map = {
    'web-testing': 'Monitor', 'api-testing': 'Connection',
    'test-generation': 'MagicStick', 'reporting': 'DataLine',
    'execution': 'VideoPlay', 'document-parsing': 'Document',
  }
  return map[category] || 'Grid'
}

const getFormatType = (fmt) => {
  const map = {
    PDF: 'danger', DOCX: 'primary', DOC: 'primary',
    XLSX: 'success', XLS: 'success', CSV: 'success',
    PPTX: 'warning', MD: 'info', TXT: 'info', HTML: 'info', JSON: 'info',
  }
  return map[fmt] || ''
}

const formatSize = (bytes) => {
  if (!bytes) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

onMounted(() => { loadSkills() })
</script>

<style scoped>
.skills-page {
  padding: 0;
}

/* ── 顶部标题栏 ── */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  background: #fff;
  border-radius: 8px;
  padding: 16px 20px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}

.page-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 18px;
  font-weight: 600;
  color: #303133;
}

.title-icon {
  color: #409eff;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* ── 统计栏 ── */
.stats-row {
  margin-bottom: 20px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 16px;
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}

.stat-icon {
  width: 52px;
  height: 52px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}

.stat-total   .stat-icon { background: linear-gradient(135deg,#667eea,#764ba2); }
.stat-enabled .stat-icon { background: linear-gradient(135deg,#52c41a,#73d13d); }
.stat-category .stat-icon { background: linear-gradient(135deg,#fa8c16,#ffc53d); }
.stat-formats .stat-icon { background: linear-gradient(135deg,#1890ff,#36cfc9); }

.stat-value {
  font-size: 26px;
  font-weight: 700;
  color: #1f1f1f;
  line-height: 1.1;
}

.stat-label {
  font-size: 13px;
  color: #8c8c8c;
  margin-top: 2px;
}

/* ── 卡片网格 ── */
.skills-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}

.skills-empty {
  grid-column: 1 / -1;
  padding: 60px 0;
  background: #fff;
  border-radius: 10px;
}

/* ── 单个技能卡片 ── */
.skill-card {
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px 14px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  border: 1px solid #f0f0f0;
  transition: box-shadow 0.25s, border-color 0.25s;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.skill-card:hover {
  box-shadow: 0 4px 16px rgba(64,158,255,0.14);
  border-color: #b3d8ff;
}

.skill-card.skill-disabled {
  opacity: 0.55;
}

.skill-card-header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.skill-card-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}

.icon-web-testing    { background: linear-gradient(135deg,#52c41a,#95de64); }
.icon-api-testing    { background: linear-gradient(135deg,#fa8c16,#ffc53d); }
.icon-test-generation{ background: linear-gradient(135deg,#1890ff,#69b1ff); }
.icon-reporting      { background: linear-gradient(135deg,#722ed1,#b37feb); }
.icon-execution      { background: linear-gradient(135deg,#f5222d,#ff7875); }
.icon-document-parsing{ background: linear-gradient(135deg,#13c2c2,#36cfc9); }

.skill-card-title {
  flex: 1;
  min-width: 0;
}

.skill-name {
  font-size: 15px;
  font-weight: 600;
  color: #1f1f1f;
  margin-bottom: 5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.skill-meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.skill-switch {
  flex-shrink: 0;
  margin-top: 2px;
}

.skill-desc {
  font-size: 13px;
  color: #595959;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.skill-formats,
.skill-triggers {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.fmt-tag,
.trigger-tag {
  margin: 0;
}

.trigger-more {
  font-size: 12px;
  color: #8c8c8c;
  align-self: center;
}

.skill-card-footer {
  display: flex;
  align-items: center;
  padding-top: 8px;
  border-top: 1px solid #f5f5f5;
  gap: 2px;
}

/* ── 详情对话框 ── */
.skill-detail {
  padding: 4px 0;
}

.tag-wrap,
.format-tags {
  display: flex;
  flex-wrap: wrap;
  padding: 4px 0;
}

.skill-doc-content {
  max-height: 460px;
  overflow-y: auto;
  background: #f8f9fa;
  border-radius: 6px;
  padding: 16px;
}

.skill-doc-content pre {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  color: #303133;
}

.execute-result pre {
  margin: 0;
  max-height: 260px;
  overflow: auto;
  font-size: 12px;
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 10px;
  border-radius: 4px;
}
</style>
