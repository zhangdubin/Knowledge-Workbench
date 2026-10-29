<template>
  <el-container class="layout">
    <el-aside :width="sidebarWidth" class="sidebar" :class="{ 'is-collapsed': collapsed }">
      <div class="brand">
        <div class="brand-logo">
          <el-icon :size="19"><Collection /></el-icon>
        </div>
        <div v-show="!collapsed" class="brand-text">
          <div class="brand-title">知识工作台</div>
          <div class="brand-sub">Knowledge Workbench</div>
        </div>
      </div>

      <!-- 折叠态用 Element Plus 自己的 collapse：它会把标题收进悬浮气泡，
           鼠标停上去还能看到全名，比自己写一套更稳 -->
      <el-menu
        :default-active="activeMenu"
        :router="true"
        :collapse="collapsed"
        :collapse-width="64"
        class="nav-menu"
      >
        <template v-for="g in navGroups" :key="g.title">
          <div v-show="!collapsed" class="nav-group-title">{{ g.title }}</div>
          <!-- 折叠后分组标题没了，用一条细线保留分组边界，
               否则一列图标看不出谁跟谁是一组 -->
          <div v-if="collapsed" class="nav-group-divider" />
          <el-menu-item v-for="item in g.items" :key="item.path" :index="item.path">
            <el-icon><component :is="item.icon" /></el-icon>
            <template #title>{{ item.label }}</template>
          </el-menu-item>
        </template>
        <div v-if="!navGroups.length" class="nav-group-title">当前账号没有任何页面权限</div>
      </el-menu>

      <div class="sidebar-footer">
        <!-- 自定义导航：管理员能直接在这里加一项，不用去「导航管理」页 -->
        <button
          v-if="canManageNav"
          type="button"
          class="collapse-btn nav-add-btn"
          title="给左侧导航加一项"
          @click="goNavManager"
        >
          <el-icon><Plus /></el-icon>
          <span v-show="!collapsed">自定义导航</span>
        </button>
        <button
          type="button"
          class="collapse-btn"
          :title="collapsed ? '展开侧边栏' : '收起侧边栏'"
          :aria-label="collapsed ? '展开侧边栏' : '收起侧边栏'"
          @click="toggleCollapse"
        >
          <el-icon><component :is="collapsed ? 'DArrowRight' : 'DArrowLeft'" /></el-icon>
          <span v-show="!collapsed">收起侧边栏</span>
        </button>
        <div v-show="!collapsed" class="kbd-hint">
          <span class="kbd">⌘K</span>
          <span>快速搜索</span>
        </div>
        <!-- 版本标识：取自后端 /auth/status（auth store），升级后自动变。
             不写死在构建里 —— 离线包升级只换镜像，前端静态资源与后端版本必须同源。 -->
        <div v-if="auth.sysVersion" class="sys-version" title="系统版本">
          v{{ auth.sysVersion }}
        </div>
      </div>
    </el-aside>

    <el-container>
      <el-header class="topbar">
        <div class="topbar-left">
          <el-button
            v-if="isMobile"
            class="mobile-menu-btn"
            circle
            plain
            @click="drawerOpen = true"
            title="菜单"
          >
            <el-icon><Menu /></el-icon>
          </el-button>
          <!-- 当前上下文：面包屑给出层级，页面名给出当前位置 -->
          <el-breadcrumb separator="/" class="breadcrumb">
            <el-breadcrumb-item :to="{ path: '/' }">
              <el-icon><HomeFilled /></el-icon>
            </el-breadcrumb-item>
            <el-breadcrumb-item v-for="(crumb, i) in breadcrumbs" :key="i">
              {{ crumb }}
            </el-breadcrumb-item>
          </el-breadcrumb>
          <span class="page-title">{{ pageTitle }}</span>
        </div>
        <div class="topbar-right">
          <el-input
            v-model="searchKw"
            placeholder="搜索知识、记录、文件…"
            size="default"
            clearable
            @keyup.enter="onSearch"
            @focus="searchFocused = true"
            @blur="searchFocused = false"
            class="search-input"
            :class="{ focused: searchFocused }"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
            <template #suffix>
              <span class="search-kbd">⌘K</span>
            </template>
          </el-input>
          <el-button
            v-if="auth.can('ai')"
            circle
            plain
            @click="agentOpen = true"
            title="AI 助理：对话查询系统数据"
            class="agent-btn"
          >
            <el-icon><MagicStick /></el-icon>
          </el-button>
          <el-button
            circle
            plain
            @click="toggleTheme"
            title="切换主题"
          >
            <el-icon><Sunny v-if="isDark" /><Moon v-else /></el-icon>
          </el-button>

          <!-- 用户菜单：身份、改密、退出 -->
          <el-dropdown trigger="click" @command="onUserCommand">
            <button class="user-chip" type="button">
              <span class="user-avatar">{{ avatarText }}</span>
              <span class="user-meta">
                <span class="user-name">{{ auth.displayName }}</span>
                <span class="user-role">{{ auth.isSuper ? '超级管理员' : '受限角色' }}</span>
              </span>
              <el-icon class="user-caret"><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="password">
                  <el-icon><Key /></el-icon>修改密码
                </el-dropdown-item>
                <el-dropdown-item command="guide">
                  <el-icon><Compass /></el-icon>使用指南
                </el-dropdown-item>
                <el-dropdown-item v-if="!auth.authEnabled" command="noauth" disabled>
                  <el-icon><InfoFilled /></el-icon>鉴权已关闭
                </el-dropdown-item>
                <el-dropdown-item v-else command="logout" divided>
                  <el-icon><SwitchButton /></el-icon>退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <el-main class="main">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>

    <!-- 移动端抽屉导航 -->
    <el-drawer
      v-model="drawerOpen"
      direction="ltr"
      size="260px"
      :with-header="false"
      class="mobile-drawer"
    >
      <div class="mobile-brand">
        <div class="brand-logo">
          <el-icon :size="19"><Collection /></el-icon>
        </div>
        <div class="brand-text">
          <div class="brand-title">知识工作台</div>
          <div class="brand-sub">Knowledge Workbench</div>
        </div>
      </div>

      <el-menu
        :default-active="activeMenu"
        :router="true"
        class="nav-menu"
        @select="drawerOpen = false"
      >
        <template v-for="g in navGroups" :key="g.title">
          <div class="nav-group-title">{{ g.title }}</div>
          <el-menu-item v-for="item in g.items" :key="item.path" :index="item.path">
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
          </el-menu-item>
        </template>
      </el-menu>
    </el-drawer>

    <!-- 修改密码 -->
    <el-dialog v-model="pwOpen" title="修改密码" width="440px" class="rich-dialog"
               :close-on-click-modal="false">
      <div class="dialog-summary">
        <el-icon :size="18"><Key /></el-icon>
        <span>修改成功后，所有设备上的登录状态都会失效，需要重新登录。</span>
      </div>
      <el-form :model="pwForm" label-width="88px">
        <el-form-item label="当前密码">
          <el-input v-model="pwForm.old_password" type="password" show-password />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="pwForm.new_password" type="password" show-password
                    placeholder="至少 8 位" />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input v-model="pwForm.confirm" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwOpen = false">取消</el-button>
        <el-button type="primary" :loading="pwSaving" @click="savePassword">确认修改</el-button>
      </template>
    </el-dialog>

    <!-- 全局 AI 助理：对话式查询系统数据（模型/记录/统计/文件） -->
    <AgentChat v-model="agentOpen" />
  </el-container>
</template>

<script setup>
import { computed, reactive, ref, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AgentChat from './AgentChat.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Collection, Menu, Plus } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'
import { isDark, toggleTheme } from '../utils/theme'
import { useNavItems, mergeNavGroups } from '../composables/useNavItems'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const navItems = useNavItems()

// 导航表：perm 与后端 PAGES 对应；feature 是更细的操作级权限
// （比如「系统管理」页要进得去，还得有 user_manage 才看得到用户管理）
const NAV = [
  { title: '工作区', items: [
    { path: '/', label: '工作台', icon: 'Odometer', perm: 'dashboard' },
    { path: '/dashboards', label: '可视化驾驶舱', icon: 'PieChart', perm: 'dashboards' },
    { path: '/notes', label: '知识库', icon: 'Notebook', perm: 'notes' },
    { path: '/library', label: '数据中心', icon: 'Coin', perm: 'library' },
  ] },
  { title: '应用', items: [
    { path: '/apps', label: '应用中心', icon: 'Grid', perm: 'apps' },
    { path: '/types', label: '数据模型', icon: 'Files', perm: 'types' },
    { path: '/relations', label: '关联定义', icon: 'Connection', perm: 'relations' },
    { path: '/graph', label: '关联图谱', icon: 'Share', perm: 'graph' },
  ] },
  { title: '发现', items: [
    { path: '/knowledge/graph', label: '知识图谱', icon: 'DataAnalysis', perm: 'knowledge_graph' },
    { path: '/search', label: '全局搜索', icon: 'Search', perm: 'search' },
  ] },
  { title: '系统', items: [
    { path: '/system/users', label: '用户管理', icon: 'UserFilled', perm: 'system', feature: 'user_manage' },
    { path: '/system/roles', label: '角色权限', icon: 'Key', perm: 'system', feature: 'role_manage' },
    { path: '/system/audit', label: '审计日志', icon: 'DocumentChecked', perm: 'system', feature: 'audit_view' },
    { path: '/system/recycle', label: '回收站', icon: 'Delete', perm: 'system', feature: 'model_manage' },
    { path: '/system/storage', label: '存储与备份', icon: 'Coin', perm: 'system', feature: 'storage_manage' },
    { path: '/system/nav', label: '导航管理', icon: 'Menu', perm: 'system', feature: 'system_config' },
    { path: '/system/settings', label: '系统设置', icon: 'Setting', perm: 'system', feature: 'system_config' },
    { path: '/guide', label: '使用指南', icon: 'Compass', perm: 'guide' },
    { path: '/ai-settings', label: 'AI 设置', icon: 'MagicStick', perm: 'ai' },
  ] },
]

const navGroups = computed(() => mergeNavGroups(
  NAV
    .map(g => ({
      title: g.title,
      items: g.items.filter(i => auth.canPage(i.perm) && (!i.feature || auth.can(i.feature))),
    }))
    .filter(g => g.items.length),
  navItems.items.value,
  (perm) => auth.canPage(perm),
))

const avatarText = computed(() => (auth.displayName || '?').slice(0, 1))

// 有系统配置权限才能改导航（跟后端 require_feature('system_config') 对齐）
const canManageNav = computed(() => auth.can('system_config'))
function goNavManager() {
  router.push('/system/nav')
}

// ---- 侧边栏折叠 ----
// 折叠状态存到 localStorage：这是「工作台形状」的偏好，
// 不是临时状态，刷新后不该弹回去（每次进来都要重新收起很烦）
const COLLAPSE_KEY = 'kb-sidebar-collapsed'
const collapsed = ref(false)
const sidebarWidth = computed(() => (collapsed.value ? '64px' : '224px'))

function readCollapse() {
  try {
    collapsed.value = localStorage.getItem(COLLAPSE_KEY) === '1'
  } catch (e) { /* 隐私模式下不可用，用默认展开 */ }
}

function toggleCollapse() {
  collapsed.value = !collapsed.value
  try { localStorage.setItem(COLLAPSE_KEY, collapsed.value ? '1' : '0') } catch (e) { /* 忽略 */ }
}

// ---- 改密 ----
const pwOpen = ref(false)
const pwSaving = ref(false)
const pwForm = reactive({ old_password: '', new_password: '', confirm: '' })

function onUserCommand(cmd) {
  if (cmd === 'password') {
    pwForm.old_password = ''
    pwForm.new_password = ''
    pwForm.confirm = ''
    pwOpen.value = true
  } else if (cmd === 'guide') {
    router.push('/guide')
  } else if (cmd === 'logout') {
    doLogout()
  }
}

async function savePassword() {
  if (!pwForm.old_password || !pwForm.new_password) {
    ElMessage.warning('请填写当前密码与新密码')
    return
  }
  if (pwForm.new_password.length < 8) {
    ElMessage.warning('新密码至少 8 位')
    return
  }
  if (pwForm.new_password !== pwForm.confirm) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  pwSaving.value = true
  try {
    await auth.changePassword(pwForm.old_password, pwForm.new_password)
    pwOpen.value = false
    ElMessage.success('密码已修改，请重新登录')
    auth.user = null
    router.replace('/login')
  } catch (e) { /* 拦截器已提示 */ } finally {
    pwSaving.value = false
  }
}

async function doLogout() {
  try {
    await ElMessageBox.confirm('确定要退出登录吗？', '退出登录', {
      type: 'warning', confirmButtonText: '退出', cancelButtonText: '取消',
    })
  } catch { return }
  await auth.logout()
  router.replace('/login')
}
const searchKw = ref('')
const searchFocused = ref(false)
const drawerOpen = ref(false)
const agentOpen = ref(false)
const isMobile = ref(false)

const mq = ref(null)
function checkMobile() {
  isMobile.value = window.innerWidth < 768
}

const activeMenu = computed(() => {
  if (route.path === '/') return '/'
  if (route.path.startsWith('/notes')) return '/notes'
  if (route.path.startsWith('/library')) return '/library'
  if (route.path.startsWith('/apps')) return '/apps'
  if (route.path.startsWith('/types')) return '/types'
  if (route.path.startsWith('/records')) return '/types'
  if (route.path.startsWith('/relations')) return '/relations'
  if (route.path === '/graph') return '/graph'
  if (route.path.startsWith('/knowledge/graph')) return '/knowledge/graph'
  if (route.path.startsWith('/search')) return '/search'
  if (route.path.startsWith('/dashboards')) return '/dashboards'
  if (route.path.startsWith('/system/')) return route.path
  if (route.path.startsWith('/guide')) return '/guide'
  if (route.path.startsWith('/ai-settings')) return '/ai-settings'
  return '/'
})

const pageTitle = computed(() => route.meta.title || '知识工作台')

const breadcrumbs = computed(() => {
  const segments = route.path.split('/').filter(Boolean)
  const names = []
  const map = {
    notes: '知识库',
    library: '数据中心',
    apps: '应用中心',
    types: '数据模型',
    graph: '关联图谱',
    relations: '关联定义',
    guide: '使用指南',
    knowledge: '知识',
    search: '搜索',
  }
  for (const s of segments) {
    if (map[s]) names.push(map[s])
    else if (!isNaN(parseInt(s))) continue
    else if (s === 'by-title') continue
    else names.push(s)
  }
  return names
})

function onSearch() {
  if (!searchKw.value.trim()) return
  router.push({ name: 'search', query: { kw: searchKw.value.trim() } })
  searchKw.value = ''
}

function handleKey(e) {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault()
    document.querySelector('.search-input input')?.focus()
  }
}

onMounted(async () => {
  readCollapse()
  await auth.bootstrap()
  // 自定义导航项：登录后拉一次。拉失败也不影响内置导航（composable 里兜住了）。
  //
  // 不能只在 onMounted 里拉：Layout 在登录页就已经挂载了，
  // 那时还没登录、拉不到东西；等用户登录完，组件不会重新挂载，
  // 于是自定义项永远不出现（踩过）。
  // 所以监听登录状态，登录了就拉一次。
  if (auth.isLoggedIn) navItems.load()
  watch(() => auth.isLoggedIn, (v) => { if (v) navItems.load() })
  window.addEventListener('keydown', handleKey)
  checkMobile()
  window.addEventListener('resize', checkMobile)
})
onUnmounted(() => {
  window.removeEventListener('keydown', handleKey)
  window.removeEventListener('resize', checkMobile)
})
</script>

<style scoped>
.layout {
  height: 100vh;
}

/* ============ 侧边栏 ============ */
.sidebar {
  background: var(--bg-sidebar);
  background-image: linear-gradient(180deg, rgba(255, 255, 255, 0.035) 0%, rgba(255, 255, 255, 0) 42%);
  color: #fff;
  display: flex;
  flex-direction: column;
  border-right: 1px solid rgba(255, 255, 255, 0.05);
  transition: width var(--duration) var(--ease-out);
  overflow: hidden;
}
/* 折叠态：品牌区只剩图标，中间对齐 */
.sidebar.is-collapsed .brand {
  justify-content: center;
  padding-left: 0;
  padding-right: 0;
}

.brand {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 18px 18px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.055);
  min-height: 69px;
}
.brand-logo {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  background: var(--primary-grad);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  box-shadow: 0 1px 0 rgba(255, 255, 255, 0.18) inset, 0 3px 10px rgba(74, 78, 180, 0.35);
  flex-shrink: 0;
}
.brand-text { min-width: 0; }
.brand-title {
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.2px;
  color: rgba(255, 255, 255, 0.94);
  white-space: nowrap;
}
.brand-sub {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.32);
  margin-top: 3px;
  letter-spacing: 0.6px;
  text-transform: uppercase;
  white-space: nowrap;
}

.nav-menu {
  flex: 1;
  border-right: none;
  background: transparent;
  padding: 6px 0 14px;
  overflow-y: auto;
  overflow-x: hidden;
  /* 让 Element Plus 菜单融入深色侧栏 */
  --el-menu-bg-color: transparent;
  --el-menu-text-color: rgba(255, 255, 255, 0.66);
  --el-menu-active-color: #ffffff;
  --el-menu-hover-bg-color: rgba(255, 255, 255, 0.055);
  --el-menu-hover-text-color: rgba(255, 255, 255, 0.94);
}
.nav-menu :deep(.el-menu-item) {
  border-radius: 7px;
  margin: 1px 10px;
  padding: 0 11px !important;
  height: 38px;
  line-height: 38px;
  font-size: 13.5px;
  font-weight: 450;
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  transition: background var(--duration-fast) var(--ease-out), color var(--duration-fast) var(--ease-out);
}
.nav-menu :deep(.el-menu-item:focus) {
  background: transparent;
  color: rgba(255, 255, 255, 0.94);
}
.nav-menu :deep(.el-menu-item .el-icon) {
  color: rgba(255, 255, 255, 0.5);
  font-size: 16px;
  transition: color var(--duration-fast) var(--ease-out);
}
.nav-menu :deep(.el-menu-item:hover) .el-icon {
  color: rgba(255, 255, 255, 0.78);
}
/* 当前项：背景 + 字重 + 左侧高亮条，三重指示 ——
   只靠颜色区分在深色侧栏上不够明显，只靠背景又不够「当前位置」 */
.nav-menu :deep(.el-menu-item.is-active) {
  background: rgba(255, 255, 255, 0.085) !important;
  color: #fff !important;
  font-weight: 600;
  box-shadow: 0 1px 0 rgba(255, 255, 255, 0.06) inset;
}
.nav-menu :deep(.el-menu-item.is-active:focus) {
  background: rgba(255, 255, 255, 0.085);
}
.nav-menu :deep(.el-menu-item.is-active) .el-icon {
  color: #a7aae8;
}
.nav-menu :deep(.el-menu-item.is-active)::before {
  content: '';
  position: absolute;
  left: -10px;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 18px;
  background: linear-gradient(180deg, #8a8ee0, #5b5fc7);
  border-radius: 0 3px 3px 0;
}
/* 折叠态：图标居中，悬浮时用 Element Plus 的气泡显示全名 */
.sidebar.is-collapsed :deep(.el-menu-item) {
  margin: 1px 8px;
  padding: 0 !important;
  justify-content: center;
}
.sidebar.is-collapsed :deep(.el-menu-item::before) {
  left: -8px;
}

.nav-group-title {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.34);
  letter-spacing: 1.1px;
  padding: 17px 21px 7px;
  font-weight: 600;
  text-transform: uppercase;
}
/* 折叠态：分组标题换成一条分隔线，保留「谁跟谁一组」的线索 */
.nav-group-divider {
  height: 1px;
  margin: 10px 16px;
  background: rgba(255, 255, 255, 0.07);
}
.nav-group-divider:first-of-type { margin-top: 4px; }

.sidebar-footer {
  padding: 12px 18px 14px;
  border-top: 1px solid rgba(255, 255, 255, 0.055);
}
.collapse-btn {
  display: flex;
  align-items: center;
  gap: 7px;
  width: 100%;
  min-height: 28px;
  padding: 4px 8px;
  margin-bottom: 8px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: rgba(255, 255, 255, 0.42);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out), color var(--duration-fast) var(--ease-out);
}
.collapse-btn:hover {
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.85);
}
.collapse-btn:focus-visible {
  outline: 2px solid var(--primary-light);
  outline-offset: 1px;
}
.sidebar.is-collapsed .collapse-btn { justify-content: center; padding: 4px 0; }
.kbd-hint {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.36);
  display: flex;
  align-items: center;
  gap: 7px;
}
.kbd {
  background: rgba(255, 255, 255, 0.07);
  border: 1px solid rgba(255, 255, 255, 0.07);
  padding: 1px 6px;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: rgba(255, 255, 255, 0.6);
}
.sys-version {
  margin-top: 8px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: rgba(255, 255, 255, 0.3);
  letter-spacing: 0.2px;
}

/* ============ 顶栏 ============ */
.topbar {
  background: var(--bg-card);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 26px;
  height: 58px;
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: var(--z-sticky);
}
.topbar-left {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}
.breadcrumb {
  font-size: 12.5px;
  /* 别让面包屑被挤成竖排（一两个字一行） */
  white-space: nowrap;
  flex-shrink: 0;
}
.breadcrumb :deep(.el-breadcrumb__inner) {
  color: var(--text-tertiary);
  font-weight: 450;
}
.breadcrumb :deep(.el-breadcrumb__inner.is-link:hover) {
  color: var(--primary);
}
.breadcrumb :deep(.el-breadcrumb__separator) {
  color: var(--text-disabled);
  margin: 0 7px;
}
.breadcrumb :deep(.el-breadcrumb__item:last-child .el-breadcrumb__inner) {
  color: var(--text-secondary);
  font-weight: 500;
}
/* 当前位置：比面包屑更重，告诉用户「你现在在这」 */
.page-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  padding-left: 14px;
  border-left: 1px solid var(--border);
  letter-spacing: -0.1px;
  white-space: nowrap;
}
.topbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.search-input {
  width: 300px;
  transition: width var(--duration) var(--ease-out);
}
.search-input.focused {
  width: 400px;
}
.search-input :deep(.el-input__wrapper) {
  background: var(--bg-subtle);
  border: 1px solid transparent;
  box-shadow: none !important;
  border-radius: var(--radius);
}
.search-input :deep(.el-input__wrapper:hover) {
  background: var(--bg-subtle);
  border-color: var(--border);
}
.search-input :deep(.el-input__wrapper.is-focus) {
  background: var(--bg-card);
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-ring) !important;
}
.search-kbd {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-tertiary);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 0 5px;
  line-height: 18px;
}

/* ============ 主区 ============ */
.main {
  padding: 0;
  background: var(--bg);
  overflow-y: auto;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* ============ 移动端抽屉 ============ */
.mobile-menu-btn {
  display: none;
  margin-right: 8px;
  color: var(--text-secondary);
}

.mobile-drawer :deep(.el-drawer__body) {
  padding: 0 !important;
  background: var(--bg-sidebar);
  color: #fff;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.mobile-drawer .mobile-brand {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.055);
  flex-shrink: 0;
}

/* ============ 响应式 ============ */
/* 面包屑在窄屏上是多余的：顶栏已经有页面标题了，
   挤在那儿只会被压成竖排（一两个字一行，很难看） */
@media (max-width: 960px) {
  .breadcrumb { display: none; }
}

@media (max-width: 768px) {
  .sidebar,
  .sidebar-footer {
    display: none;
  }

  .mobile-menu-btn {
    display: inline-flex;
  }

  /* ---- 顶栏在手机上的排版 ----
     之前右组是 flex: 1 0 0（按比例分到一半宽度），但它自己的内容
     （搜索框 min-width 96 + AI 按钮 + 主题按钮 + 头像）要 232px，
     塞进 181px 的盒子里就会向左溢出、压在页面标题上（实测压住 63px）。
     现在：顶栏允许换行，右组用 display:contents 让子元素直接参与顶栏布局，
     搜索框收成一个放大镜图标，点开才展开独占一整行。 */
  .topbar {
    height: auto;
    min-height: 54px;
    padding: 0 10px 0 12px;
    flex-wrap: wrap;
    align-content: center;
    justify-content: flex-start;
    column-gap: 8px;
    row-gap: 8px;
  }

  .topbar-left {
    gap: 8px;
    flex: 1 1 auto;
    min-width: 0;
  }

  .breadcrumb {
    display: none;
  }

  .page-title {
    padding-left: 0;
    border-left: none;
    font-size: 16px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1 1 auto;
    min-width: 0;
  }

  /* 右组不再是一个盒子：它的子元素直接排进顶栏，
     这样搜索框才能换到第二行，而不是把三个按钮顶出边界 */
  .topbar-right {
    display: contents;
  }

  /* 顶栏从左到右：菜单 → 标题 → 搜索 → AI → 主题 → 头像 */
  .topbar-right > .el-button,
  .topbar-right > .el-dropdown {
    order: 20;
  }

  .search-input {
    order: 10;
    width: 34px;
    flex: 0 0 34px;
    min-width: 0;
    max-width: none;
  }

  /* 展开：独占一整行，宽度给满。
     order 调到 30（按钮是 20）：这样它换行时不会把 AI/主题/头像挤到第三行 */
  .search-input.focused {
    order: 30;
    width: 100%;
    flex: 1 0 100%;
    max-width: none;
  }

  /* 收起时只留放大镜图标：文字输入框透明，
     点一下（拿到焦点）就展开成整行输入框 */
  .search-input:not(.focused) :deep(.el-input__inner) {
    opacity: 0;
  }
  .search-input:not(.focused) :deep(.el-input__clear) {
    display: none;
  }
  .search-input:not(.focused) :deep(.el-input__wrapper) {
    padding-left: 7px;
    padding-right: 7px;
  }

  .search-input :deep(.el-input__wrapper) {
    padding-left: 10px;
    padding-right: 8px;
  }

  .search-kbd {
    display: none;
  }
}

/* ============ 顶栏用户菜单 ============ */
.user-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px 4px 4px;
  border-radius: var(--radius-full);
  border: 1px solid var(--border);
  background: var(--bg-card);
  cursor: pointer;
  transition: all 0.16s ease;
}
.user-chip:hover { border-color: var(--primary-light); background: var(--primary-50); }
.user-chip:focus-visible {
  outline: var(--focus-ring-width) solid var(--focus-ring-color);
  outline-offset: var(--focus-ring-offset);
}
.user-avatar {
  width: 28px; height: 28px; border-radius: 50%;
  background: var(--primary-grad); color: #fff;
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 700; flex-shrink: 0;
}
.user-meta { display: flex; flex-direction: column; line-height: 1.25; text-align: left; }
.user-name { font-size: var(--text-sm); font-weight: 600; color: var(--text-primary); }
.user-role { font-size: 12px; color: var(--text-tertiary); }
.user-caret { color: var(--text-tertiary); font-size: 12px; }

@media (max-width: 768px) {
  .user-meta { display: none; }
  .user-chip { padding: 4px; border: none; background: transparent; }
}
</style>
