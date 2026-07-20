<template>
  <div class="workspaces-page">
    <!-- 顶部操作栏 -->
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>工作空间管理</span>
          <el-button type="primary" :icon="Plus" @click="openCreate">新建工作空间</el-button>
        </div>
      </template>

      <el-table :data="workspaces" v-loading="loading" stripe>
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip />
        <el-table-column prop="owner" label="创建人" width="120" />
        <el-table-column prop="role" label="我的角色" width="100">
          <template #default="{ row }">
            <el-tag :type="row.role === 'owner' ? 'warning' : 'info'" size="small">
              {{ row.role === 'owner' ? 'Owner' : '成员' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="160">
          <template #default="{ row }">{{ fmtDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" align="center">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="openMembers(row)">成员</el-button>
            <el-button v-if="canEdit(row)" size="small" text @click="openEdit(row)">编辑</el-button>
            <el-button v-if="canEdit(row)" size="small" text type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建 / 编辑 Dialog -->
    <el-dialog v-model="editVisible" :title="editForm.id ? '编辑工作空间' : '新建工作空间'" width="440px" destroy-on-close>
      <el-form :model="editForm" label-width="72px">
        <el-form-item label="名称" required>
          <el-input v-model="editForm.name" placeholder="工作空间名称" maxlength="50" show-word-limit />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="editForm.description" type="textarea" :rows="2" placeholder="选填" maxlength="200" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">确定</el-button>
      </template>
    </el-dialog>

    <!-- 成员管理 Dialog -->
    <el-dialog v-model="memberVisible" :title="`成员管理 — ${activeName}`" width="560px" destroy-on-close>
      <!-- 邀请 -->
      <div v-if="canEdit(activeRow)" style="display:flex;gap:8px;margin-bottom:16px">
        <el-input v-model="inviteUsername" placeholder="输入用户名" style="width:180px" clearable />
        <el-select v-model="inviteRole" style="width:110px">
          <el-option label="成员" value="member" />
          <el-option label="Owner" value="owner" />
        </el-select>
        <el-button type="primary" :loading="inviting" @click="handleInvite">邀请</el-button>
      </div>

      <el-table :data="members" v-loading="loadingMembers" size="small" stripe>
        <el-table-column prop="username" label="用户名" />
        <el-table-column prop="role" label="角色" width="90">
          <template #default="{ row }">
            <el-tag :type="row.role === 'owner' ? 'warning' : 'info'" size="small">
              {{ row.role === 'owner' ? 'Owner' : '成员' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="joined_at" label="加入时间" width="150">
          <template #default="{ row }">{{ fmtDate(row.joined_at) }}</template>
        </el-table-column>
        <el-table-column v-if="canEdit(activeRow)" label="操作" width="80" align="center">
          <template #default="{ row }">
            <el-button
              v-if="row.username !== activeRow?.owner"
              size="small" text type="danger"
              @click="handleRemove(row.username)"
            >移除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { workspaceApi } from '../api'
import { useAuthStore } from '../stores/auth'
import { useWorkspaceStore } from '../stores/workspace'

const auth = useAuthStore()
const wsStore = useWorkspaceStore()

const workspaces = ref([])
const loading = ref(false)

// 新建/编辑
const editVisible = ref(false)
const saving = ref(false)
const editForm = ref({ id: null, name: '', description: '' })

// 成员管理
const memberVisible = ref(false)
const activeRow = ref(null)
const activeName = ref('')
const members = ref([])
const loadingMembers = ref(false)
const inviteUsername = ref('')
const inviteRole = ref('member')
const inviting = ref(false)

const canEdit = (row) =>
  auth.role === 'admin' || row?.role === 'owner'

const fmtDate = (iso) => {
  if (!iso) return ''
  const d = new Date(iso.includes('Z') ? iso : iso + 'Z')
  const p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

const fetchWorkspaces = async () => {
  loading.value = true
  try {
    workspaces.value = await workspaceApi.list()
    wsStore.workspaces = workspaces.value
  } finally {
    loading.value = false
  }
}

const openCreate = () => {
  editForm.value = { id: null, name: '', description: '' }
  editVisible.value = true
}

const openEdit = (row) => {
  editForm.value = { id: row.id, name: row.name, description: row.description }
  editVisible.value = true
}

const handleSave = async () => {
  if (!editForm.value.name.trim()) return ElMessage.warning('名称不能为空')
  saving.value = true
  try {
    if (editForm.value.id) {
      await workspaceApi.update(editForm.value.id, editForm.value)
      ElMessage.success('已更新')
    } else {
      await workspaceApi.create(editForm.value)
      ElMessage.success('创建成功')
    }
    editVisible.value = false
    await fetchWorkspaces()
  } finally {
    saving.value = false
  }
}

const handleDelete = async (row) => {
  await ElMessageBox.confirm(`确定删除工作空间「${row.name}」？该空间内的数据不会被删除，但数据将不再归属此空间。`, '删除确认', { type: 'warning' })
  await workspaceApi.delete(row.id)
  if (wsStore.currentId === row.id) wsStore.switchWorkspace(null)
  ElMessage.success('已删除')
  await fetchWorkspaces()
}

const openMembers = async (row) => {
  activeRow.value = row
  activeName.value = row.name
  memberVisible.value = true
  inviteUsername.value = ''
  loadingMembers.value = true
  try {
    members.value = await workspaceApi.listMembers(row.id)
  } finally {
    loadingMembers.value = false
  }
}

const handleInvite = async () => {
  if (!inviteUsername.value.trim()) return ElMessage.warning('请输入用户名')
  inviting.value = true
  try {
    await workspaceApi.inviteMember(activeRow.value.id, {
      username: inviteUsername.value.trim(),
      role: inviteRole.value,
    })
    ElMessage.success('邀请成功')
    inviteUsername.value = ''
    members.value = await workspaceApi.listMembers(activeRow.value.id)
  } finally {
    inviting.value = false
  }
}

const handleRemove = async (username) => {
  await ElMessageBox.confirm(`确定移除成员「${username}」？`, '移除确认', { type: 'warning' })
  await workspaceApi.removeMember(activeRow.value.id, username)
  members.value = members.value.filter(m => m.username !== username)
  ElMessage.success('已移除')
}

onMounted(fetchWorkspaces)
</script>

<style scoped>
.workspaces-page { padding: 0; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
</style>
