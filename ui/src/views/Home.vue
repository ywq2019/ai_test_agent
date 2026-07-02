<template>
  <div class="home">
    <el-row :gutter="20">
      <el-col :span="12">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-icon blue">
            <el-icon size="32"><FolderOpened /></el-icon>
          </div>
          <div class="stat-content">
            <div class="stat-value">{{ taskStore.taskCount }}</div>
            <div class="stat-label">测试任务</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-icon green">
            <el-icon size="32"><Document /></el-icon>
          </div>
          <div class="stat-content">
            <div class="stat-value">{{ taskStore.totalCaseCount }}</div>
            <div class="stat-label">测试用例</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" style="margin-top: 20px;">
      <el-col :span="16">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>快速开始</span>
            </div>
          </template>
          <div class="quick-start">
            <el-steps direction="vertical" :space="60" :active="4" finish-status="success">
              <el-step title="创建测试任务" description="输入URL和上传需求文档" />
              <el-step title="AI解析页面元素" description="自动抓取页面交互元素" />
              <el-step title="生成测试用例" description="AI智能生成测试用例" />
              <el-step title="执行测试" description="对话式控制测试执行" />
              <el-step title="查看报告" description="生成可视化测试报告" />
            </el-steps>
          </div>
        </el-card>
      </el-col>

      <el-col :span="8">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>系统状态</span>
            </div>
          </template>
          <div class="system-status">
            <el-descriptions :column="1" border>
              <el-descriptions-item label="API状态">
                <el-tag type="success">正常运行</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="WebSocket">
                <el-tag :type="wsConnected ? 'success' : 'danger'">
                  {{ wsConnected ? '已连接' : '未连接' }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="Playwright">
                <el-tag type="success">就绪</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="数据库">
                <el-tag type="success">已连接</el-tag>
              </el-descriptions-item>
            </el-descriptions>
          </div>
        </el-card>

        <el-card shadow="hover" style="margin-top: 20px;">
          <template #header>
            <div class="card-header">
              <span>最近任务</span>
            </div>
          </template>
          <div class="recent-tasks">
            <el-timeline>
              <el-timeline-item
                v-for="task in recentTasks"
                :key="task.id"
                :timestamp="formatTime(task.created_at)"
                placement="top"
              >
                {{ task.name }}
              </el-timeline-item>
              <el-timeline-item v-if="recentTasks.length === 0" placement="top">
                暂无任务
              </el-timeline-item>
            </el-timeline>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useTaskStore } from '../stores/task'

const taskStore = useTaskStore()
const wsConnected = ref(true)

const recentTasks = computed(() => {
  return taskStore.tasks.slice(0, 5)
})

function formatTime(isoStr) {
  if (!isoStr) return ''
  try {
    const d = new Date(isoStr.includes('T') ? isoStr : isoStr.replace(' ', 'T'))
    const pad = n => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  } catch {
    return isoStr
  }
}

onMounted(async () => {
  await Promise.all([
    taskStore.fetchTasks(),
    taskStore.fetchTotalCaseCount()
  ])
})
</script>

<style scoped>
.home {
  padding: 0;
}

.stat-card {
  display: flex;
  align-items: center;
  padding: 20px;
}

.stat-icon {
  width: 60px;
  height: 60px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: 16px;
  color: #fff;
}

.stat-icon.blue { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
.stat-icon.green { background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }
.stat-icon.success { background: linear-gradient(135deg, #52c41a 0%, #73d13d 100%); }
.stat-icon.danger { background: linear-gradient(135deg, #ff4d4f 0%, #ff7875 100%); }

.stat-content {
  flex: 1;
}

.stat-value {
  font-size: 28px;
  font-weight: bold;
  color: #333;
}

.stat-label {
  font-size: 14px;
  color: #999;
  margin-top: 4px;
}

.card-header {
  font-weight: 600;
  font-size: 16px;
}

.quick-start {
  padding: 20px 0;
}

.system-status {
  padding: 10px 0;
}

.recent-tasks {
  padding: 10px 0;
}
</style>
