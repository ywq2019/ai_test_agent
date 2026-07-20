<template>
  <el-empty
    v-if="show"
    description="请先在顶栏选择工作空间"
    :image-size="120"
    style="padding: 80px 0"
  >
    <template #image>
      <el-icon size="80" color="#c0c4cc"><Folder /></el-icon>
    </template>
  </el-empty>
</template>

<script setup>
import { computed } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useWorkspaceStore } from '../stores/workspace'

const auth = useAuthStore()
const wsStore = useWorkspaceStore()

// 只对普通用户生效；admin 不需要选空间
const show = computed(() => auth.role !== 'admin' && !wsStore.currentId)
</script>
