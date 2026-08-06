<template>
  <div id="app">
    <!-- 登录页单独渲染，不带侧边栏 -->
    <router-view v-if="route.name === 'Login'" />

    <!-- 主布局 -->
    <el-container v-else class="layout-container">
      <el-aside width="220px" class="layout-aside">
        <!-- Logo -->
        <div class="logo">
          <div class="logo-icon-wrap">
            <el-icon size="18"><Monitor /></el-icon>
          </div>
          <div class="logo-text">
            <span class="logo-title">AI 测试平台</span>
          </div>
        </div>

        <el-menu
          :default-active="$route.path"
          :default-openeds="defaultOpenedMenus"
          router
          class="layout-menu"
          background-color="transparent"
          text-color="#bfcbd9"
          active-text-color="#409eff"
          @open="onMenuOpen"
          @close="onMenuClose"
        >
          <!-- 首页独立置顶 -->
          <el-menu-item index="/">
            <el-icon><House /></el-icon>
            <span>首页</span>
          </el-menu-item>

          <!-- AI 能力（可折叠，与其他模块保持一致） -->
          <el-sub-menu index="ai">
            <template #title>
              <el-icon><MagicStick /></el-icon>
              <span>AI 能力</span>
            </template>
            <el-menu-item index="/ai-cases">
              <el-icon><MagicStick /></el-icon>
              <span>AI 用例生成</span>
            </el-menu-item>
          </el-sub-menu>

          <!-- WebUI 自动化（可折叠） -->
          <el-sub-menu index="webui">
            <template #title>
              <el-icon><Monitor /></el-icon>
              <span>WebUI 自动化</span>
            </template>
            <el-menu-item index="/tasks">
              <el-icon><FolderOpened /></el-icon>
              <span>任务管理</span>
            </el-menu-item>
            <el-menu-item index="/cases">
              <el-icon><Document /></el-icon>
              <span>用例管理</span>
            </el-menu-item>
            <el-menu-item index="/execution">
              <el-icon><VideoPlay /></el-icon>
              <span>测试执行</span>
            </el-menu-item>
            <el-menu-item index="/reports">
              <el-icon><DataAnalysis /></el-icon>
              <span>报告查看</span>
            </el-menu-item>
          </el-sub-menu>

          <!-- 接口自动化（可折叠） -->
          <el-sub-menu index="apitest">
            <template #title>
              <el-icon><Tickets /></el-icon>
              <span>接口自动化</span>
            </template>
            <el-menu-item index="/api-test">
              <el-icon><Tickets /></el-icon>
              <span>接口测试</span>
            </el-menu-item>
            <el-menu-item index="/test-plan">
              <el-icon><Memo /></el-icon>
              <span>测试计划</span>
            </el-menu-item>
            <el-menu-item index="/pentest">
              <el-icon><Warning /></el-icon>
              <span>渗透测试</span>
            </el-menu-item>
            <el-menu-item index="/mock">
              <el-icon><Connection /></el-icon>
              <span>Mock 服务</span>
            </el-menu-item>
          </el-sub-menu>

          <!-- 系统设置（可折叠） -->
          <el-sub-menu index="settings">
            <template #title>
              <el-icon><Setting /></el-icon>
              <span>系统设置</span>
            </template>
            <el-menu-item index="/workspaces">
              <el-icon><Folder /></el-icon>
              <span>工作空间</span>
            </el-menu-item>
            <el-menu-item index="/skills">
              <el-icon><Box /></el-icon>
              <span>技能管理</span>
            </el-menu-item>
            <el-menu-item index="/llm">
              <el-icon><Cpu /></el-icon>
              <span>大模型配置</span>
            </el-menu-item>
          </el-sub-menu>
        </el-menu>
      </el-aside>

      <el-container>
        <el-header class="layout-header">
          <div class="header-left">
            <h2>{{ pageTitle }}</h2>
          </div>
          <div class="header-right">
            <!-- 工作空间切换器：admin 可清空（看全部），普通用户必选 -->
            <el-select
              v-model="wsStore.currentId"
              :placeholder="auth.role === 'admin' ? '全部数据' : '请选择工作空间'"
              :clearable="auth.role === 'admin'"
              size="small"
              style="width:170px;margin-right:12px"
              @change="wsStore.switchWorkspace($event)"
            >
              <el-option
                v-for="w in wsStore.workspaces"
                :key="w.id"
                :label="w.name"
                :value="w.id"
              />
            </el-select>
            <el-tooltip content="刷新页面数据" placement="bottom">
              <el-button circle text :icon="RefreshRight" @click="refreshPage" style="margin-right:8px" />
            </el-tooltip>
            <el-popover
              trigger="click"
              :width="320"
              :visible="notifyVisible"
              placement="bottom-end"
            >
              <template #reference>
                <el-badge :value="notificationCount" :hidden="notificationCount === 0" style="cursor:pointer">
                  <el-icon size="20" @click="notifyVisible = !notifyVisible"><Bell /></el-icon>
                </el-badge>
              </template>
              <div style="max-height:260px;overflow-y:auto">
                <template v-if="notifications.length">
                  <div
                    v-for="(n, i) in notifications"
                    :key="i"
                    style="padding:8px 0;border-bottom:1px solid #f0f0f0;font-size:13px;display:flex;align-items:flex-start;gap:8px"
                  >
                    <el-tag :type="n.tag" size="small" style="flex-shrink:0;margin-top:1px">{{ n.label }}</el-tag>
                    <span style="color:#303133;line-height:1.5">{{ n.text }}</span>
                  </div>
                </template>
                <div v-else style="text-align:center;color:#c0c4cc;padding:20px 0;font-size:13px">
                  暂无通知
                </div>
              </div>
              <div style="text-align:right;padding-top:8px;border-top:1px solid #f0f0f0" v-if="notifications.length">
                <el-button size="small" text @click="clearNotifications">清空</el-button>
              </div>
            </el-popover>
            <el-divider direction="vertical" style="margin:0 12px;height:16px" />
            <span style="font-size:13px;color:#606266;margin-right:8px">{{ auth.username }}</span>
            <el-button v-if="auth.role === 'admin'" size="small" text @click="openUserMgr" style="margin-right:4px">用户管理</el-button>
            <el-button size="small" text type="danger" @click="handleLogout">退出</el-button>
          </div>
        </el-header>

        <el-main class="layout-main">
          <router-view v-slot="{ Component, route }">
            <keep-alive :include="['Execution']">
              <component :is="Component" :key="route.name" />
            </keep-alive>
          </router-view>
        </el-main>
      </el-container>
    </el-container>

    <el-dialog v-model="wsDialogVisible" title="WebSocket连接状态" width="400px">
      <el-tag :type="wsConnected ? 'success' : 'danger'">
        {{ wsConnected ? '已连接' : '未连接' }}
      </el-tag>
      <template #footer>
        <el-button @click="connectWebSocket">重新连接</el-button>
      </template>
    </el-dialog>

    <!-- 用户管理 Dialog -->
    <el-dialog v-model="userMgrVisible" title="用户管理" width="600px" destroy-on-close>
      <div style="margin-bottom:12px">
        <el-button type="primary" size="small" :icon="Plus" @click="showCreateUser = true">新建用户</el-button>
      </div>

      <!-- 新建用户表单 -->
      <el-form v-if="showCreateUser" :model="newUserForm" label-width="72px" size="small"
        style="background:#f8fafc;border-radius:8px;padding:14px 16px;margin-bottom:12px;border:1px solid #ebeef5">
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="用户名">
              <el-input v-model="newUserForm.username" placeholder="登录用户名" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="密码">
              <el-input v-model="newUserForm.password" type="password" show-password placeholder="不少于6位" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="角色">
              <el-select v-model="newUserForm.role" style="width:100%">
                <el-option label="普通用户" value="user" />
                <el-option label="管理员" value="admin" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <div style="display:flex;justify-content:flex-end;gap:8px">
          <el-button size="small" @click="showCreateUser = false">取消</el-button>
          <el-button size="small" type="primary" :loading="creatingUser" @click="handleCreateUser">确认创建</el-button>
        </div>
      </el-form>

      <!-- 用户列表 -->
      <el-table :data="userList" size="small" stripe v-loading="loadingUsers">
        <el-table-column prop="username" label="用户名" />
        <el-table-column prop="role" label="角色" width="90">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'danger' : 'info'" size="small">
              {{ row.role === 'admin' ? '管理员' : '普通用户' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="160">
          <template #default="{ row }">{{ formatUserTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" align="center">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="handleResetPwd(row)">重置密码</el-button>
            <el-button size="small" text type="danger"
              :disabled="row.username === auth.username"
              @click="handleDeleteUser(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useTaskStore } from './stores/task'
import { useAuthStore } from './stores/auth'
import { useWorkspaceStore } from './stores/workspace'
import { RefreshRight, Plus, Warning, Bell, Connection } from '@element-plus/icons-vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import { userApi } from './api'

const route = useRoute()
const router = useRouter()
const taskStore = useTaskStore()
const auth = useAuthStore()
const wsStore = useWorkspaceStore()

// ── 折叠菜单状态（localStorage 持久化）────────────────────────────────────────
const MENU_STORAGE_KEY = 'menu_opened'
const ALL_SUBMENUS = ['ai', 'webui', 'apitest', 'settings']

// 路由 → 所属子菜单 index 的映射
const ROUTE_TO_SUBMENU = {
  '/ai-cases': 'ai',
  '/tasks': 'webui', '/cases': 'webui', '/execution': 'webui', '/reports': 'webui',
  '/api-test': 'apitest', '/test-plan': 'apitest', '/pentest': 'apitest', '/mock': 'apitest',
  '/workspaces': 'settings', '/skills': 'settings', '/llm': 'settings',
}

function loadOpenedMenus() {
  try {
    const saved = localStorage.getItem(MENU_STORAGE_KEY)
    if (saved) return JSON.parse(saved)
  } catch {}
  // 默认：当前路由所在的子菜单展开，其余收起
  const cur = ROUTE_TO_SUBMENU[route.path]
  return cur ? [cur] : ['webui']
}

const defaultOpenedMenus = ref(loadOpenedMenus())

const onMenuOpen = (index) => {
  if (!defaultOpenedMenus.value.includes(index)) {
    defaultOpenedMenus.value.push(index)
  }
  localStorage.setItem(MENU_STORAGE_KEY, JSON.stringify(defaultOpenedMenus.value))
}

const onMenuClose = (index) => {
  defaultOpenedMenus.value = defaultOpenedMenus.value.filter(i => i !== index)
  localStorage.setItem(MENU_STORAGE_KEY, JSON.stringify(defaultOpenedMenus.value))
}

// 路由切换时，确保当前路由所在的子菜单展开
watch(() => route.path, (path) => {
  const submenu = ROUTE_TO_SUBMENU[path]
  if (submenu && !defaultOpenedMenus.value.includes(submenu)) {
    defaultOpenedMenus.value.push(submenu)
    localStorage.setItem(MENU_STORAGE_KEY, JSON.stringify(defaultOpenedMenus.value))
  }
})

const wsConnected = ref(false)
const wsDialogVisible = ref(false)
const notificationCount = ref(0)
const notifyVisible = ref(false)
const notifications = ref([])

const pushNotify = (label, tag, text) => {
  notifications.value.unshift({ label, tag, text })
  if (notifications.value.length > 50) notifications.value.pop()
  notificationCount.value++
}

const clearNotifications = () => {
  notifications.value = []
  notificationCount.value = 0
  notifyVisible.value = false
}

const refreshPage = () => {
  router.go(0)
}

const handleLogout = async () => {
  await ElMessageBox.confirm('确定退出登录？', '提示', { type: 'warning', confirmButtonText: '退出' })
  _wsManualClose = true
  if (_wsReconnectTimer) clearTimeout(_wsReconnectTimer)
  if (ws) ws.close()
  auth.logout()
  ElMessage.success('已退出登录')
  router.push('/login')
}

// ── 用户管理 ─────────────────────────────────────────────────────────────────
const userMgrVisible = ref(false)
const userList = ref([])
const loadingUsers = ref(false)
const showCreateUser = ref(false)
const creatingUser = ref(false)
const newUserForm = reactive({ username: '', password: '', role: 'user' })

const formatUserTime = (iso) => {
  if (!iso) return ''
  const d = new Date(iso.includes('Z') ? iso : iso + 'Z')
  const pad = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const openUserMgr = async () => {
  userMgrVisible.value = true
  showCreateUser.value = false
  loadingUsers.value = true
  try {
    userList.value = await userApi.list()
  } finally {
    loadingUsers.value = false
  }
}

const handleCreateUser = async () => {
  if (!newUserForm.username.trim() || !newUserForm.password) {
    return ElMessage.warning('用户名和密码不能为空')
  }
  creatingUser.value = true
  try {
    const u = await userApi.create({ ...newUserForm })
    userList.value.push(u)
    showCreateUser.value = false
    Object.assign(newUserForm, { username: '', password: '', role: 'user' })
    ElMessage.success(`用户 ${u.username} 创建成功`)
  } finally {
    creatingUser.value = false
  }
}

const handleResetPwd = async (row) => {
  const { value: pwd } = await ElMessageBox.prompt(
    `请输入「${row.username}」的新密码（不少于6位）`, '重置密码',
    { confirmButtonText: '确认', cancelButtonText: '取消', inputType: 'password',
      inputValidator: v => v && v.length >= 6 ? true : '密码不能少于6位' }
  )
  await userApi.resetPassword(row.username, pwd)
  ElMessage.success('密码已重置')
}

const handleDeleteUser = async (row) => {
  await ElMessageBox.confirm(`确定删除用户「${row.username}」？`, '警告', { type: 'warning' })
  await userApi.delete(row.username)
  userList.value = userList.value.filter(u => u.username !== row.username)
  ElMessage.success('已删除')
}

const pageTitle = computed(() => {
  const titles = {
    '/': '首页',
    '/tasks': '任务管理',
    '/cases': '用例管理',
    '/execution': '测试执行',
    '/reports': '报告查看',
    '/ai-cases': 'AI用例生成',
    '/api-test': '接口测试',
    '/test-plan': '测试计划',
    '/skills': '技能管理',
    '/llm': '大模型配置',
    '/workspaces': '工作空间管理',
    '/pentest': '渗透测试',
    '/mock': 'Mock 服务'
  }
  return titles[route.path] || 'AI测试工具平台'
})

let ws = null
let _wsReconnectTimer = null
let _wsManualClose = false   // 标记是主动关闭（logout/unmount），不触发重连

const connectWebSocket = () => {
  // 使用相对路径协议和当前 host（不硬编码 8000 端口），
  // 避免开发模式 vite proxy 和生产模式端口不一致的问题
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const wsUrl = `${proto}://${window.location.host}/ws?client_id=app_global`
  ws = new WebSocket(wsUrl)

  ws.onopen = () => {
    wsConnected.value = true
    _wsManualClose = false
    console.log('WebSocket connected')
    // 连接成功后立即发送工作空间订阅
    sendWsSubscribe()
  }

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      // 回 pong，防止服务端因超时主动断开
      if (data.type === 'ping') {
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'pong' }))
        }
        return
      }
      handleWebSocketMessage(data)
    } catch (e) {
      console.error('WebSocket message parse error:', e)
    }
  }

  ws.onclose = () => {
    wsConnected.value = false
    console.log('WebSocket disconnected')
    // 非主动关闭时 5 秒后自动重连
    if (!_wsManualClose) {
      _wsReconnectTimer = setTimeout(() => {
        console.log('WebSocket reconnecting...')
        connectWebSocket()
      }, 5000)
    }
  }

  ws.onerror = (error) => {
    console.error('WebSocket error:', error)
    wsConnected.value = false
  }
}

const sendWsSubscribe = () => {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: 'subscribe_workspace',
      workspace_id: wsStore.currentId || 0,
    }))
  }
}

// 工作空间切换时重新订阅
watch(() => wsStore.currentId, () => {
  sendWsSubscribe()
})

const handleWebSocketMessage = (data) => {
  switch (data.type) {
    case 'task_created':
      taskStore.addTask(data.task)
      pushNotify('任务', 'primary', `新任务「${data.task?.name || '未知'}」已创建`)
      break
    case 'execution_progress':
      taskStore.updateExecutionProgress(data)
      break
    case 'cases_generated':
      taskStore.setCases(data.cases || [])
      if (data.source === 'api_test') {
        pushNotify('接口用例', 'success', `接口用例生成完成，共 ${data.case_count || 0} 条`)
      } else {
        pushNotify('用例', 'success', `${data.cases?.length || data.case_count || 0} 条 AI 用例已生成`)
      }
      break
    case 'report_generated':
      taskStore.setReportPath(data.report_path)
      pushNotify('报告', 'warning', `测试报告已生成，点击查看`)
      break
    case 'plan_done':
      pushNotify('计划', 'success', `测试计划「${data.plan_name || data.plan_id || ''}」执行完成，${data.passed || 0}/${data.total || 0} 通过`)
      break
    case 'plan_step_done':
      // 计划步骤完成 → 仅在全部步骤完成后再通知（由 plan_done 统一处理）
      break
    case 'document_parsed':
      pushNotify('解析', 'info', `文档解析完成（${data.page_count || 0} 页）`)
      break
    case 'page_parsed':
      pushNotify('解析', 'info', `页面元素解析完成（${data.element_count || 0} 个元素）`)
      break
    case 'pentest_started':
      pushNotify('渗透', 'warning', `渗透扫描「${data.task_name || data.task_id}」已启动`)
      break
    case 'pentest_done':
      pushNotify('渗透', 'success', `渗透扫描完成，发现 ${data.high_count || 0} 高危 / ${data.medium_count || 0} 中危漏洞`)
      break
    case 'pentest_error':
      pushNotify('渗透', 'danger', `渗透扫描失败: ${data.error || '未知错误'}`)
      break
    case 'pentest_cancelled':
      pushNotify('渗透', 'info', `渗透扫描已取消`)
      break
  }
}

onMounted(async () => {
  // 登录页不执行初始化请求，避免 401 → 跳登录页 → 再次请求的死循环
  if (route.name === 'Login') return
  connectWebSocket()
  wsStore.restoreFromSession()
  await wsStore.fetchWorkspaces()
  // 普通用户：若未选空间则自动选第一个
  if (auth.role !== 'admin' && !wsStore.currentId && wsStore.workspaces.length > 0) {
    wsStore.switchWorkspace(wsStore.workspaces[0].id)
  }
  // workspace 就绪后主动触发一次任务刷新，解决子页面比 App.vue 先 mounted 的竞态
  await taskStore.fetchTasks(wsStore.currentId)
  wsStore.markReady()
})

onUnmounted(() => {
  _wsManualClose = true
  if (_wsReconnectTimer) clearTimeout(_wsReconnectTimer)
  if (ws) {
    ws.close()
  }
})
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

#app {
  height: 100vh;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

.layout-container {
  height: 100%;
}

/* ── 侧边栏 ── */
.layout-aside {
  background: linear-gradient(180deg, #1a2332 0%, #243447 100%);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 2px 0 8px rgba(0,0,0,0.18);
}

/* Logo 区 */
.logo {
  height: 64px;
  display: flex;
  align-items: center;
  padding: 0 18px;
  gap: 10px;
  border-bottom: 1px solid rgba(255,255,255,0.07);
  flex-shrink: 0;
}

.logo-icon-wrap {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: linear-gradient(135deg, #409eff 0%, #36cfc9 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}

.logo-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.logo-title {
  font-size: 15px;
  font-weight: 700;
  color: #fff;
  letter-spacing: 0.3px;
  line-height: 1.2;
}

.logo-sub {
  font-size: 10px;
  color: rgba(255,255,255,0.35);
  letter-spacing: 0.2px;
  line-height: 1;
}

/* 菜单 */
.layout-menu {
  border-right: none !important;
  background: transparent !important;
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 8px 0 16px;
}

/* 滚动条美化 */
.layout-menu::-webkit-scrollbar { width: 3px; }
.layout-menu::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }

/* 分组标题 */
.menu-group-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 1.2px;
  text-transform: uppercase;
  color: rgba(255,255,255,0.28);
  padding-left: 4px;
}

.layout-menu :deep(.el-menu-item-group__title) {
  padding: 14px 18px 4px !important;
  line-height: 1 !important;
}

/* sub-menu 标题行 */
.layout-menu :deep(.el-sub-menu__title) {
  height: 40px !important;
  line-height: 40px !important;
  margin: 1px 10px !important;
  border-radius: 7px !important;
  padding: 0 12px !important;
  color: rgba(191, 203, 217, 0.9) !important;
  font-size: 13.5px !important;
  transition: all 0.18s ease !important;
}
.layout-menu :deep(.el-sub-menu__title:hover) {
  background: rgba(255,255,255,0.07) !important;
  color: #fff !important;
}
/* 折叠箭头颜色 */
.layout-menu :deep(.el-sub-menu__icon-arrow) {
  color: rgba(255,255,255,0.35) !important;
}
/* sub-menu 展开时标题高亮 */
.layout-menu :deep(.el-sub-menu.is-opened > .el-sub-menu__title) {
  color: rgba(255,255,255,0.95) !important;
}
/* sub-menu 内部列表去掉背景 */
.layout-menu :deep(.el-menu--inline) {
  background: transparent !important;
}
/* sub-menu 图标 */
.layout-menu :deep(.el-sub-menu__title .el-icon) {
  margin-right: 8px !important;
  font-size: 15px !important;
}

/* 菜单项 */
.layout-menu :deep(.el-menu-item) {
  height: 40px !important;
  line-height: 40px !important;
  margin: 1px 10px !important;
  border-radius: 7px !important;
  padding: 0 12px !important;
  color: rgba(191, 203, 217, 0.85) !important;
  transition: all 0.18s ease !important;
  font-size: 13.5px !important;
}

.layout-menu :deep(.el-menu-item:hover) {
  background: rgba(255,255,255,0.07) !important;
  color: #fff !important;
}

.layout-menu :deep(.el-menu-item.is-active) {
  background: linear-gradient(90deg, rgba(64,158,255,0.18) 0%, rgba(64,158,255,0.06) 100%) !important;
  color: #409eff !important;
  position: relative;
}

/* 活跃项左侧指示条 */
.layout-menu :deep(.el-menu-item.is-active)::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 20px;
  border-radius: 0 3px 3px 0;
  background: #409eff;
}

/* 图标与文字间距 */
.layout-menu :deep(.el-menu-item .el-icon) {
  margin-right: 8px;
  font-size: 15px;
}

/* ── Header ── */
.layout-header {
  background-color: #fff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.06);
  border-bottom: 1px solid #f0f0f0;
  height: 56px !important;
  flex-shrink: 0;
}

.header-left h2 {
  font-size: 16px;
  font-weight: 600;
  color: #1a2332;
  letter-spacing: 0.2px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 0;
}

/* ── Main ── */
.layout-main {
  background-color: #f5f7fa;
  padding: 20px;
  overflow-y: auto;
}
</style>
