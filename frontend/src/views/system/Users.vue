<template>
  <div class="page">
    <PageTitle
      title="用户管理"
      subtitle="账号、所属角色与启停状态；角色决定这个人能看到和能改动什么"
      icon-key="UserFilled"
    >
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>新建用户
      </el-button>
    </PageTitle>

    <div class="card" style="padding:0;overflow:hidden">
      <el-table :data="users" v-loading="loading" stripe class="data-table">
        <el-table-column label="用户" min-width="200">
          <template #default="{ row }">
            <div class="user-cell">
              <span class="avatar" :class="{ off: !row.is_active }">
                {{ (row.display_name || row.username).slice(0, 1) }}
              </span>
              <div>
                <div class="u-name">
                  {{ row.display_name || row.username }}
                  <el-tag v-if="row.id === auth.user?.id" size="small" effect="plain">当前登录</el-tag>
                </div>
                <div class="u-sub">@{{ row.username }}</div>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="角色" width="150">
          <template #default="{ row }">
            <el-tag v-if="row.role_name" size="small" effect="plain"
                    :type="row.role_key === 'admin' ? 'danger' : 'primary'">
              {{ row.role_name }}
            </el-tag>
            <span v-else class="cell-empty">未分配</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-switch :model-value="row.is_active" :disabled="row.id === auth.user?.id"
                       @change="v => toggleActive(row, v)" />
          </template>
        </el-table-column>
        <el-table-column label="需要改密" width="110">
          <template #default="{ row }">
            <el-tag v-if="row.must_change_password" size="small" type="warning" effect="plain">待首次改密</el-tag>
            <span v-else class="cell-empty">—</span>
          </template>
        </el-table-column>
        <el-table-column label="最近登录" width="170">
          <template #default="{ row }">
            <span class="cell-number">{{ row.last_login_at ? formatTime(row.last_login_at) : '从未登录' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="openEdit(row)">
              <el-icon><Edit /></el-icon>编辑
            </el-button>
            <el-button size="small" link @click="resetPassword(row)">
              <el-icon><Key /></el-icon>重置密码
            </el-button>
            <el-button size="small" link type="danger" :disabled="row.id === auth.user?.id"
                       @click="del(row)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="!loading && !users.length" class="empty-state" style="border:none">
        <div class="empty-title">还没有用户</div>
      </div>
    </div>

    <el-dialog v-model="dialogOpen" :title="form.id ? '编辑用户' : '新建用户'"
               width="520px" class="rich-dialog" :close-on-click-modal="false">
      <div class="dialog-summary">
        <el-icon :size="18"><UserFilled /></el-icon>
        <span>用户必须归属一个角色；角色里的权限决定了这个账号能访问的页面与数据范围。</span>
      </div>
      <el-form :model="form" label-width="90px">
        <el-form-item label="用户名" required>
          <el-input v-model="form.username" :disabled="!!form.id" placeholder="登录账号，英文/数字" />
        </el-form-item>
        <el-form-item label="显示名">
          <el-input v-model="form.display_name" placeholder="页面上展示的名字" />
        </el-form-item>
        <el-form-item :label="form.id ? '重置密码' : '初始密码'" :required="!form.id">
          <el-input v-model="form.password" type="password" show-password
                    :placeholder="form.id ? '留空表示不修改' : '至少 8 位'" />
          <div class="form-hint" v-if="form.id">填写后该用户下次登录会被要求再改一次。</div>
        </el-form-item>
        <el-form-item label="角色" required>
          <el-select v-model="form.role_id" placeholder="选择角色" style="width:100%">
            <el-option v-for="r in roles" :key="r.id" :label="`${r.name}（${r.key}）`" :value="r.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Api } from '../../api'
import { formatTime } from '../../utils/format'
import { useAuthStore } from '../../stores/auth'
import PageTitle from '../../components/PageTitle.vue'

const auth = useAuthStore()
const users = ref([])
const roles = ref([])
const loading = ref(false)
const saving = ref(false)
const dialogOpen = ref(false)
const form = reactive({
  id: null, username: '', display_name: '', password: '', role_id: null, is_active: true,
})

async function load() {
  loading.value = true
  try {
    const [u, r] = await Promise.all([Api.listUsers(), Api.listRoles()])
    users.value = u.items || []
    roles.value = r.items || []
  } catch (e) { /* 拦截器已提示 */ } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(form, {
    id: null, username: '', display_name: '', password: '', is_active: true,
    role_id: roles.value.find(r => r.key === 'editor')?.id || roles.value[0]?.id || null,
  })
  dialogOpen.value = true
}

function openEdit(row) {
  Object.assign(form, {
    id: row.id, username: row.username, display_name: row.display_name,
    password: '', role_id: row.role_id, is_active: row.is_active,
  })
  dialogOpen.value = true
}

async function save() {
  if (!form.username.trim()) { ElMessage.warning('请填写用户名'); return }
  if (!form.id && (form.password || '').length < 8) { ElMessage.warning('初始密码至少 8 位'); return }
  saving.value = true
  try {
    if (form.id) {
      const patch = {
        display_name: form.display_name,
        role_id: form.role_id,
        is_active: form.is_active,
      }
      if (form.password) patch.password = form.password
      await Api.updateUser(form.id, patch)
    } else {
      await Api.createUser({
        username: form.username.trim(), password: form.password,
        display_name: form.display_name, role_id: form.role_id, is_active: form.is_active,
      })
    }
    ElMessage.success('已保存')
    dialogOpen.value = false
    await load()
  } catch (e) { /* 拦截器已提示 */ } finally {
    saving.value = false
  }
}

async function toggleActive(row, value) {
  try {
    await Api.updateUser(row.id, { is_active: value })
    row.is_active = value
    ElMessage.success(value ? '已启用' : '已停用（该账号的登录状态已失效）')
  } catch (e) { /* 拦截器已提示 */ }
}

async function resetPassword(row) {
  try {
    const { value } = await ElMessageBox.prompt(
      `为「${row.display_name || row.username}」设置新密码（至少 8 位）。\n该用户下次登录时会被要求再改一次。`,
      '重置密码',
      { inputType: 'password', confirmButtonText: '重置', cancelButtonText: '取消' },
    )
    if ((value || '').length < 8) { ElMessage.warning('密码至少 8 位'); return }
    await Api.updateUser(row.id, { password: value })
    ElMessage.success('已重置')
    await load()
  } catch (e) { /* 取消 */ }
}

async function del(row) {
  try {
    await ElMessageBox.confirm(
      `删除用户「${row.display_name || row.username}」后该账号立即失效，且不可恢复。`,
      '删除用户', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await Api.deleteUser(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) { /* 取消 */ }
}

onMounted(load)
</script>

<style scoped>
.user-cell { display: flex; align-items: center; gap: 10px; }
.avatar {
  width: 34px; height: 34px; border-radius: 50%;
  background: var(--primary-grad); color: #fff;
  display: flex; align-items: center; justify-content: center;
  font-weight: 700; flex-shrink: 0;
}
.avatar.off { background: var(--bg-subtle); color: var(--text-tertiary); }
.u-name { display: flex; align-items: center; gap: 6px; font-weight: 600; }
.u-sub { font-size: var(--text-xs); color: var(--text-tertiary); }
.cell-empty { color: var(--text-tertiary); }
.cell-number { font-variant-numeric: tabular-nums; color: var(--text-secondary); font-size: var(--text-sm); }
.form-hint { font-size: var(--text-xs); color: var(--text-tertiary); margin-top: 6px; }
</style>
