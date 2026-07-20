import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { workspaceApi } from '../api'

export const useWorkspaceStore = defineStore('workspace', () => {
  const workspaces = ref([])
  const currentId = ref(null)   // null = 全部（不过滤工作空间）
  const initialized = ref(false)  // App.vue 完成 workspace 初始化后置为 true

  const current = computed(() =>
    workspaces.value.find(w => w.id === currentId.value) || null
  )

  const currentLabel = computed(() =>
    current.value ? current.value.name : '全部数据'
  )

  async function fetchWorkspaces() {
    try {
      workspaces.value = await workspaceApi.list()
    } catch {
      workspaces.value = []
    }
  }

  function switchWorkspace(id) {
    currentId.value = id
    if (id) sessionStorage.setItem('workspace_id', String(id))
    else sessionStorage.removeItem('workspace_id')
  }

  function restoreFromSession() {
    const saved = sessionStorage.getItem('workspace_id')
    if (saved) currentId.value = parseInt(saved)
  }

  // App.vue 初始化完毕后调用
  function markReady() {
    initialized.value = true
  }

  // 等待初始化完成的工具函数（子页面 onMounted 调用）
  function waitReady() {
    if (initialized.value) return Promise.resolve()
    return new Promise(resolve => {
      const stop = watch(initialized, (v) => { if (v) { stop(); resolve() } })
    })
  }

  return {
    workspaces, currentId, initialized, current, currentLabel,
    fetchWorkspaces, switchWorkspace, restoreFromSession, markReady, waitReady,
  }
})
