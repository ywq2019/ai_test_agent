<template>
  <div id="app">
    <el-container class="layout-container">
      <el-aside width="200px" class="layout-aside">
        <div class="logo">
          <el-icon><Monitor /></el-icon>
          <span>UI测试Agent</span>
        </div>
        <el-menu
          :default-active="$route.path"
          router
          class="layout-menu"
        >
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
            <el-badge :value="notificationCount" :hidden="notificationCount === 0">
              <el-icon size="20"><Bell /></el-icon>
            </el-badge>
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
import { useRoute } from 'vue-router'
import { useTaskStore } from './stores/task'

const route = useRoute()
const taskStore = useTaskStore()

const wsConnected = ref(false)
const wsDialogVisible = ref(false)
const notificationCount = ref(0)

const pageTitle = computed(() => {
  const titles = {
    '/': '首页',
    '/tasks': '任务管理',
    '/cases': '用例管理',
    '/execution': '测试执行',
    '/reports': '报告查看',
    '/skills': '技能管理',
    '/llm': '大模型配置'
  }
  return titles[route.path] || '自动化UI测试Agent'
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
