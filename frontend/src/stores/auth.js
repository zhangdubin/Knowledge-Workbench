/**
 * 认证与权限状态
 *
 * 用 Pinia 而不是组合式单例：登录态要被路由守卫、侧边栏、按钮显隐
 * 同时读到，且必须在首次路由跳转前就绪（见 router/index.js 的守卫）。
 *
 * 权限判定全部收敛在这里的三个方法（canPage / can / modelLevel），
 * 页面里只写 `auth.can('file_delete')`，不再各自拼字符串。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { Api } from '../api'

export const useAuthStore = defineStore('auth', () => {
  const ready = ref(false)            // 是否已完成首次 /auth/status
  const authEnabled = ref(true)       // 后端是否开启了鉴权
  const initialPassword = ref(false)  // 后端是否仍处于「初始口令未修改」状态
  const sysVersion = ref('')          // 系统版本标识（来自后端，前端不写死）
  const user = ref(null)
  const meta = ref({ pages: [], features: [], levels: [] })

  const isLoggedIn = computed(() => !!user.value)
  const isSuper = computed(() => !!user.value?.is_super)
  const mustChangePassword = computed(() => !!user.value?.must_change_password)
  const displayName = computed(() =>
    user.value?.display_name || user.value?.username || '未登录')
  const roleLabel = computed(() => (isSuper.value ? '超级管理员' : '受限角色'))

  function canPage(page) {
    if (!user.value) return false
    if (user.value.is_super) return true
    return (user.value.perms?.pages || []).includes(page)
  }

  function can(feature) {
    if (!user.value) return false
    if (user.value.is_super) return true
    return !!(user.value.perms?.features || {})[feature]
  }

  const LEVEL_ORDER = { none: 0, read: 1, write: 2 }

  function modelLevel(key) {
    if (!user.value) return 'none'
    if (user.value.is_super) return 'write'
    const models = user.value.perms?.models || {}
    return models[key] ?? models['*'] ?? 'none'
  }

  function canModel(key, need = 'read') {
    return (LEVEL_ORDER[modelLevel(key)] || 0) >= (LEVEL_ORDER[need] || 1)
  }

  /** 首次进入应用时调用：拿登录态（未登录不报错，交给路由守卫处理） */
  async function bootstrap() {
    if (ready.value) return user.value
    try {
      const s = await Api.authStatus()
      authEnabled.value = !!s.auth_enabled
      initialPassword.value = !!s.initial_password
      sysVersion.value = s.version || ''
      user.value = s.authenticated ? s.user : null
    } catch {
      user.value = null
    } finally {
      ready.value = true
    }
    return user.value
  }

  async function login(username, password) {
    const r = await Api.login(username, password)
    user.value = r.user
    // 登录成功说明口令来自当前库，提示里的「初始口令」状态同步刷新
    initialPassword.value = !!r.user?.must_change_password
    return r.user
  }

  async function logout() {
    try { await Api.logout() } catch { /* 会话可能已失效，忽略 */ }
    user.value = null
  }

  /** 改密后后端会清空所有会话，前端同步登出 */
  async function changePassword(oldPassword, newPassword) {
    const r = await Api.changePassword(oldPassword, newPassword)
    initialPassword.value = false
    return r
  }

  async function refresh() {
    try {
      user.value = await Api.me()
    } catch {
      user.value = null
    }
    return user.value
  }

  async function loadMeta() {
    if (meta.value.pages.length) return meta.value
    try { meta.value = await Api.authMeta() } catch { /* 保持空 */ }
    return meta.value
  }

  return {
    ready, authEnabled, initialPassword, sysVersion, user, meta,
    isLoggedIn, isSuper, mustChangePassword, displayName, roleLabel,
    canPage, can, modelLevel, canModel,
    bootstrap, login, logout, changePassword, refresh, loadMeta,
  }
})
