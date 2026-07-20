<template>
  <div id="app">
    <!-- 登录页单独渲染，不带侧边栏 -->
    <router-view v-if="route.name === 'Login'" />

    <!-- 主布局 -->
    <el-container v-else class="layout-container">
      <el-aside width="200px" class="layout-aside">
        <div class="logo">
          <el-icon><Monitor /></el-icon>
          <span>AI测试工具平台</span>
        </div>
        <el-menu
          :default-active="$route.path"
          router
          class="layout-menu"
          background-color="#304156"
          text-color="#bfcbd9"
          active-text-color="#409eff"
        >
          <el-menu-item index="/ai-cases">
            <el-icon><MagicStick /></el-icon>
            <span>AI用例生成</span>
          </el-menu-item>
          <el-sub-menu index="webui-group">
            <template #title>
              <el-icon><Monitor /></el-icon>
              <span>WebUI 自动化</span>
            </template>
            <el-menu-item index="/">
              <el-icon><House /></el-icon>
              <span>首页</span>
            </el-menu-item>
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
          <el-sub-menu index="api-group">
            <template #title>
              <el-icon><Connection /></el-icon>
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
          </el-sub-menu>
          <el-divider />
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
            <el-badge :value="notificationCount" :hidden="notificationCount === 0">
              <el-icon size="20"><Bell /></el-icon>
            </el-badge>
            <el-divider direction="vertical" style="margin:0 12px;height:16px" />
            <span style="font-size:13px;color:#606266;margin-right:8px">{{ auth.username }}</span>
            <el-button v-if="auth.role === 'admin'" size="small" text @click="openUserMgr" style="margin-right:4px">用户管理</el-button>
            <el-button size="small" text type="danger" @click="handleLogout">退出</el-button>
          </div>
        </el-header>

        <el-main class="layout-main">
          <router-view />
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
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useTaskStore } from './stores/task'
import { useAuthStore } from './stores/auth'
import { useWorkspaceStore } from './stores/workspace'
import { RefreshRight, Plus } from '@element-plus/icons-vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import { userApi } from './api'

const route = useRoute()
const router = useRouter()
const taskStore = useTaskStore()
const auth = useAuthStore()
const wsStore = useWorkspaceStore()

const wsConnected = ref(false)
const wsDialogVisible = ref(false)
const notificationCount = ref(0)

const refreshPage = () => {
  router.go(0)
}

const handleLogout = async () => {
  await ElMessageBox.confirm('确定退出登录？', '提示', { type: 'warning', confirmButtonText: '退出' })
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
    '/workspaces': '工作空间管理'
  }
  return titles[route.path] || 'AI测试工具平台'
})

let ws = null

const connectWebSocket = () => {
  const wsUrl = `ws://${window.location.hostname}:8000/ws?client_id=ui`
  ws = new WebSocket(wsUrl)

  ws.onopen = () => {
    wsConnected.value = true
    console.log('WebSocket connected')
  }

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      handleWebSocketMessage(data)
    } catch (e) {
      console.error('WebSocket message parse error:', e)
    }
  }

  ws.onclose = () => {
    wsConnected.value = false
    console.log('WebSocket disconnected')
  }

  ws.onerror = (error) => {
    console.error('WebSocket error:', error)
    wsConnected.value = false
  }
}

const handleWebSocketMessage = (data) => {
  switch (data.type) {
    case 'task_created':
      taskStore.addTask(data.task)
      notificationCount.value++
      break
    case 'execution_progress':
      taskStore.updateExecutionProgress(data)
      break
    case 'cases_generated':
      taskStore.setCases(data.cases || [])
      break
    case 'report_generated':
      taskStore.setReportPath(data.report_path)
      notificationCount.value++
      break
  }
}

onMounted(async () => {
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
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

.layout-container {
  height: 100%;
}

.layout-aside {
  background-color: #304156;
  color: #fff;
}

.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-size: 18px;
  font-weight: bold;
  color: #fff;
  border-bottom: 1px solid #3d4a5c;
}

.layout-menu {
  border-right: none;
  background-color: #304156;
}

.layout-menu .el-menu-item {
  color: #bfcbd9;
}

.layout-menu .el-menu-item:hover,
.layout-menu .el-menu-item.is-active {
  background-color: #263445;
  color: #409eff;
}

/* 子菜单标题行 */
.layout-menu :deep(.el-sub-menu__title) {
  color: #bfcbd9 !important;
  background-color: #304156 !important;
}
.layout-menu :deep(.el-sub-menu__title:hover) {
  background-color: #263445 !important;
  color: #409eff !important;
}

/* 子菜单展开的内嵌列表 */
.layout-menu :deep(.el-menu) {
  background-color: #263445 !important;
}
.layout-menu :deep(.el-menu .el-menu-item) {
  color: #bfcbd9 !important;
  background-color: #263445 !important;
  padding-left: 40px !important;
}
.layout-menu :deep(.el-menu .el-menu-item:hover),
.layout-menu :deep(.el-menu .el-menu-item.is-active) {
  background-color: #1f2d3d !important;
  color: #409eff !important;
}

.layout-header {
  background-color: #fff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
}

.header-left h2 {
  font-size: 18px;
  font-weight: 500;
  color: #333;
}

.layout-main {
  background-color: #f5f7fa;
  padding: 20px;
}
</style>
