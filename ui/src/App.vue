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
            <el-tooltip content="刷新页面数据" placement="bottom">
              <el-button circle text :icon="RefreshRight" @click="refreshPage" style="margin-right:8px" />
            </el-tooltip>
            <el-badge :value="notificationCount" :hidden="notificationCount === 0">
              <el-icon size="20"><Bell /></el-icon>
            </el-badge>
            <el-divider direction="vertical" style="margin:0 12px;height:16px" />
            <span style="font-size:13px;color:#606266;margin-right:8px">{{ auth.username }}</span>
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
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useTaskStore } from './stores/task'
import { useAuthStore } from './stores/auth'
import { RefreshRight } from '@element-plus/icons-vue'
import { ElMessageBox, ElMessage } from 'element-plus'

const route = useRoute()
const router = useRouter()
const taskStore = useTaskStore()
const auth = useAuthStore()

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
    '/llm': '大模型配置'
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

onMounted(() => {
  connectWebSocket()
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
