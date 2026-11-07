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
        <!-- gi 只用来判断「是不是第一组」：第一组不需要那么大的组间留白 -->
        <template v-for="(g, gi) in navGroups" :key="g.title">
          <div v-show="!collapsed" class="nav-group-title" :class="{ 'is-first': gi === 0 }">
            {{ g.title }}
          </div>
          <!-- 折叠后分组标题没了，用一条短横线保留分组边界，
               否则一列图标看不出谁跟谁是一组 -->
          <div v-if="collapsed" class="nav-group-divider" :class="{ 'is-first': gi === 0 }" />
          <el-menu-item v-for="item in g.items" :key="item.path" :index="item.path">
            <el-icon><component :is="item.icon" /></el-icon>
            <template #title>{{ item.label }}</template>
          </el-menu-item>
        </template>
        <div v-if="!navGroups.length" class="nav-group-title nav-group-empty">
          当前账号没有任何页面权限
        </div>
      </el-menu>

      <div class="sidebar-footer">
        <!-- 底部两个动作排在同一行：
             「收起侧边栏」本来就是图标动作（一个箭头），
             配一段「收起侧边栏」的文字既占地方又和图标重复说同一件事。
             改成图标按钮并和「自定义导航」并排，底部区立刻省下一整行 ——
             这行原来是被导航挤下去的（实测侧栏 23 个入口，
             800px 高的屏上要溢出 260 多像素，能省一行是一行）。 -->
        <div class="footer-actions">
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
            class="collapse-btn collapse-toggle"
            :title="collapsed ? '展开侧边栏' : '收起侧边栏'"
            :aria-label="collapsed ? '展开侧边栏' : '收起侧边栏'"
            @click="toggleCollapse"
          >
            <el-icon><component :is="collapsed ? 'DArrowRight' : 'DArrowLeft'" /></el-icon>
            <span v-show="!collapsed">收起侧边栏</span>
          </button>
        </div>
        <div v-show="!collapsed" class="kbd-hint">
          <span class="kbd">⌘K</span>
          <span>快速搜索</span>
          <!-- 版本标识：取自后端 /auth/status（auth store），升级后自动变。
               不写死在构建里 —— 离线包升级只换镜像，前端静态资源与后端版本必须同源。
               和 ⌘K 提示并排放在一行：底部区原本 140px 高，
               其中光一个版本号就占了一整行 —— 那点地方留给导航更值。 -->
          <span v-if="auth.sysVersion" class="sys-version" title="系统版本">
            v{{ auth.sysVersion }}
          </span>
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
            class="search-input topbar-search"
            placeholder="搜索知识、记录、文件…"
            size="default"
            clearable
            @keyup.enter="onSearch"
            @focus="searchFocused = true"
            @blur="searchFocused = false"
            :class="{ focused: searchFocused }"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
            <template #suffix>
              <span class="search-kbd">⌘K</span>
            </template>
          </el-input>
          <el-button
            circle
            plain
            @click="genePickerOpen = true"
            title="引用养料库里的知识（任何页面都能用）"
            class="gene-btn"
          >
            <el-icon><DataBoard /></el-icon>
          </el-button>
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
    <GenePicker v-model="genePickerOpen" mode="copy" />

    <el-drawer
      v-model="drawerOpen"
      direction="ltr"
      size="260px"
      :with-header="false"
      class="mobile-drawer"
    >
      <div class="brand mobile-brand">
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
        <template v-for="(g, gi) in navGroups" :key="g.title">
          <div class="nav-group-title" :class="{ 'is-first': gi === 0 }">{{ g.title }}</div>
          <el-menu-item v-for="item in g.items" :key="item.path" :index="item.path">
            <el-icon><component :is="item.icon" /></el-icon>
            <!-- 用 title 插槽而不是裸 span：和侧栏的菜单项生成完全一样的 DOM，
                 两边才真的是「同一套」而不是「长得像」 -->
            <template #title>{{ item.label }}</template>
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
import GenePicker from './GenePicker.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Collection, Menu, Plus, DataBoard } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'
import { isDark, toggleTheme } from '../utils/theme'
import { sameVersion, normVersion } from '../utils/update'
import { useNavItems, mergeNavGroups } from '../composables/useNavItems'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const navItems = useNavItems()
/** 版本号定期核对的定时器 */
let versionTimer = null

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
    // 养料 DNA：喂给模型的资料的体检报告与基因图谱（只读）
    // 图标用 DataLine —— Element Plus 里没有 DNA 图标，别写不存在的名字
    { path: '/dna', label: '养料 DNA', icon: 'DataLine', perm: 'dna' },
    // 养料库：基因层操作台（吸收、蒸馏销毁、离线直答、打包带走）
    { path: '/dna-library', label: '养料库', icon: 'DataBoard', perm: 'dna' },
    // 软件开发：把喂养的源码知识变成项目（在线协同 / 离线闭环）
    // 图标用 Cpu —— Element Plus 里确实有这个图标
    { path: '/dev', label: '软件开发', icon: 'Cpu', perm: 'dev' },
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
/* 顶栏「引用养料库」：任何页面都能把库里的一条知识拿去用 */
const genePickerOpen = ref(false)
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

  // 定期核对版本号
  //
  // 版本号原来只在首次加载时拉一次（拉过就再也不拉）——
  // 所以「一键升级」完成、用户刷新了页面，侧栏还是显示升级前的版本
  // （用户反馈「显示升级完成，请刷新页面，怎么还是 0.6.8」）。
  //
  // 每 5 分钟核一次：后端被升级/换镜像后，不用等用户手动刷新，
  // 界面上的版本号自己就跟上。顺带检测到不一致时提示重新加载。
  versionTimer = setInterval(async () => {
    if (document.hidden) return          // 页面在后台就不打扰
    const before = auth.sysVersion
    const now = await auth.refreshVersion()
    // 用共享的版本比较（utils/update.js）：
    // 「v0.6.9」与「0.6.9」指的是同一个版本，
    // 直接比字符串会白白误报一次「请刷新页面」。
    //
    // ⚠️ 注意方向：这里是**后端**跑新版本、**页面**还停在旧版本，
    // 与升级弹窗那边（后端压根没换成功）正好相反 ——
    // 措辞不能照抄那边的「当前运行版本…期望…」，那样说会把谁新谁旧讲反。
    if (before && now && !sameVersion(before, now)) {
      ElMessage.warning(
        `后端已升级到 v${normVersion(now)}，`
        + `当前页面显示的还是 v${normVersion(before)}，建议刷新页面`,
        { duration: 8000 }
      )
    }
  }, 5 * 60 * 1000)
})
onUnmounted(() => {
  if (versionTimer) clearInterval(versionTimer)
  window.removeEventListener('keydown', handleKey)
  window.removeEventListener('resize', checkMobile)
})
</script>

<style scoped>
.layout {
  height: 100vh;
}

/* ============ 侧边栏 ============ */
/* 侧栏的文字/表面色令牌（--nav-*）定义在 main.css 的「侧边栏 / 移动端抽屉」段。
   放全局是因为移动端抽屉是 teleport 出来的，拿不到本文件的 scoped 属性 ——
   侧栏与抽屉必须共用同一份令牌，否则两边各写各的，迟早漂移。 */
.sidebar {
  background: var(--bg-sidebar);
  color: var(--nav-fg);
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--nav-hairline);
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
  gap: 10px;
  padding: 13px 16px 12px;
  border-bottom: 1px solid var(--nav-hairline);
  min-height: 62px;
  /* 抽屉里品牌块压在菜单之上，菜单一长就会被挤扁 —— 固定住 */
  flex-shrink: 0;
  /* 顶部那点柔光挪到品牌块里：
     原来整条侧栏从上到下都带一层渐变，结果是**菜单区不干净** ——
     分组标题想吸顶就得有个实底去盖住滚上来的内容，
     而渐变底色没法盖（盖上去就是一块色差明显的方块）。
     挪到品牌块之后，菜单区回到纯色，吸顶标题才能严丝合缝。 */
  background-image: linear-gradient(180deg, rgba(255, 255, 255, 0.055) 0%, rgba(255, 255, 255, 0) 100%);
}
.brand-logo {
  width: 32px;
  height: 32px;
  border-radius: 9px;
  background: var(--primary-grad);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  /* 外发光走主题色：明暗两套主题的品牌色不同，写死会有一边不搭 */
  box-shadow: 0 1px 0 rgba(255, 255, 255, 0.18) inset, 0 3px 10px var(--primary-glow);
  flex-shrink: 0;
}
.brand-text { min-width: 0; }
.brand-title {
  font-size: 14px;
  font-weight: 650;
  letter-spacing: 0.2px;
  color: var(--nav-fg);
  white-space: nowrap;
}
.brand-sub {
  font-size: 11px;
  /* 原来是 --nav-fg-ghost（0.30 白）—— 对深色底只有 2.6:1，
     11px 的小字这个亮度基本是「看不见但知道那儿有字」。
     提到 0.48 白（4.9:1），副标题能读了，又明显比主标题弱。 */
  color: var(--nav-fg-dim);
  margin-top: 2px;
  /* 这一行是英文：字距与全大写在这里是刻意的。
     和下面中文分组标题不是同一套规则 —— 中文不吃这套 */
  letter-spacing: 0.6px;
  text-transform: uppercase;
  white-space: nowrap;
  /* 「Knowledge Workbench」这行比侧栏宽，
     不截断的话会把侧栏撑宽、或者压到右边去 ——
     侧栏宽度是定死的，溢出就是布局破了 */
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

/* ============ 导航菜单 ============ */
/* 展开态与折叠态共用这一段：折叠态是「同一套设计去掉文字」，
   不是另画一套。所有状态色都走 --nav-* 令牌，
   改一处主题，明暗两套主题同时生效。 */
.nav-menu {
  flex: 1;
  border-right: none;
  background: transparent;
  /* 上内边距必须是 0：吸顶标题是按内容盒定位的，
     菜单留 4px 上内边距，标题就吸在菜单顶边下方 4px ——
     那一道 4px 的缝里会漏出滚过去的内容，看着像没对齐。
     顶部留白改由第一个分组标题自己的 padding 承担。 */
  padding: 0 0 16px;
  overflow-y: auto;
  overflow-x: hidden;
  /* 全局滚动条是浅灰滑块，落在深色侧栏上亮得刺眼 */
  scrollbar-width: thin;
  scrollbar-color: rgba(255, 255, 255, 0.16) transparent;
  /* 让 Element Plus 菜单融入深色侧栏 */
  --el-menu-bg-color: transparent;
  --el-menu-text-color: var(--nav-fg-muted);
  --el-menu-active-color: #ffffff;
  --el-menu-hover-bg-color: var(--nav-surface);
  --el-menu-hover-text-color: var(--nav-fg);
}
.nav-menu::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.14);
  background-clip: padding-box;
  border: 2px solid transparent;
}
.nav-menu::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.22);
  background-clip: padding-box;
  border: 2px solid transparent;
}
/* 底部渐隐：菜单装不下时，最后一行会被硬生生切一半，
   看着像「排版坏了」而不是「下面还有，滚一下」。
   一层从底色渐隐出去的薄雾，就自然了。 */
.nav-menu::after {
  content: '';
  position: sticky;
  bottom: -1px;
  display: block;
  height: 24px;
  margin-top: -24px;
  background: linear-gradient(to top, var(--bg-sidebar) 15%, transparent);
  pointer-events: none;
}

/* 菜单项：一格 32px（31 高的行 + 上下各 1px），
   分组标题也占一格 —— 标题与项落在同一套网格上，节奏才一致。
   比原来的 38px 收一点：实测这台机器上侧栏有 23 个入口、4 个分组，
   800px 高的笔记本屏上按 34px 排要滚 376px 才够得着最后一组；
   收到 32px、再把分组标题也压一压，能露出来的就多出一大截。 */
.nav-menu :deep(.el-menu-item) {
  /* 「这一格的底色」交给一个局部变量承载：
     hover / 当前项只是改这个变量的值，
     状态之间就不会互相覆盖打架（以前是三处规则各写各的背景）。 */
  --nav-item-bg: transparent;
  background: var(--nav-item-bg);
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  height: 32px;
  line-height: 32px;
  margin: 1px 10px;
  padding: 0 11px !important;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 450;
  color: var(--nav-fg-muted);
  transition: background var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out);
}
/* hover 与 focus 都要看得见：菜单项能拿到焦点（EP 给的是 tabindex="-1"，
   鼠标点过就会聚焦），只靠背景色一档变化在深色侧栏上分辨不出来。 */
.nav-menu :deep(.el-menu-item:hover) {
  --nav-item-bg: var(--nav-surface);
  color: var(--nav-fg);
}
.nav-menu :deep(.el-menu-item:focus) {
  --nav-item-bg: var(--nav-surface);
  color: var(--nav-fg);
}
.nav-menu :deep(.el-menu-item:focus-visible) {
  outline: 2px solid var(--nav-accent);
  outline-offset: -2px;
}
/* 图标比文字更沉一层：这一列是图标导航，文字才是主信息 */
.nav-menu :deep(.el-menu-item .el-icon) {
  color: var(--nav-fg-icon);
  font-size: 16px;
  /* Element Plus 默认给图标 5px 右外边距，和这里的 gap 叠成 15px，
     图标与文字离得太远 */
  margin-right: 0;
  transition: color var(--duration-fast) var(--ease-out);
}
.nav-menu :deep(.el-menu-item:hover) .el-icon {
  color: var(--nav-fg-strong);
}

/* 当前项：一片主色淡染的底 + 一条贴着底色左缘的主色条。
   以前这里是「一层白」，整条侧栏只有 logo 带颜色 ——
   当前位置和别的项的差别全靠「白了一点」和一条竖条，
   在深色底上看着发闷，而且和 logo 对不上。
   改成主色淡染之后，当前项与 logo 是同一个色系，
   侧栏终于有了一个视觉重心，不再是一片灰。

   淡染用 color-mix 而不是固定 rgba：主色在明暗两套主题里不同，
   固定 rgba 会出现「一边刚好、一边发灰」。 */
.nav-menu :deep(.el-menu-item.is-active) {
  --nav-item-bg: linear-gradient(90deg,
    var(--nav-accent-tint) 0%,
    var(--nav-accent-tint-soft) 68%,
    transparent 100%);
  color: #fff;
  font-weight: 600;
}
.nav-menu :deep(.el-menu-item.is-active:hover) {
  --nav-item-bg: linear-gradient(90deg,
    var(--nav-accent-tint-hover) 0%,
    var(--nav-accent-tint) 68%,
    var(--nav-accent-tint-soft) 100%);
}
.nav-menu :deep(.el-menu-item.is-active) .el-icon {
  color: var(--nav-accent);
}
.nav-menu :deep(.el-menu-item.is-active)::before {
  content: '';
  position: absolute;
  left: 1px;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 16px;
  border-radius: 2px;
  /* 与品牌 logo 同一套主色渐变：「主色 = 当前所在」 */
  background: var(--nav-accent-grad);
}

/* ============ 折叠态 ============ */
/* 折叠态不是另一套设计，是同一套设计去掉文字：
   同样的圆角、同样的图标规则、同样的「主色 = 当前所在」。
   展开态把主色做成一条小竖条；64px 宽里没有横向空间，
   就把它做成一块方块 —— 规则一致，形态随空间变。 */
.sidebar.is-collapsed :deep(.el-menu-item) {
  width: 38px;
  height: 38px;
  line-height: 38px;
  margin: 2px auto;
  padding: 0 !important;
  justify-content: center;
  border-radius: 9px;
}
.sidebar.is-collapsed :deep(.el-menu-item .el-icon) {
  font-size: 17px;
}
/* 折叠态当前项：整块点亮成主色渐变。
   64px 宽里「文字加粗」这个信号已经没了，得给一个看得见的标记；
   方块形状与品牌 logo 同源，一眼就知道是「当前位置」。 */
.sidebar.is-collapsed :deep(.el-menu-item.is-active) {
  --nav-item-bg: var(--nav-accent-grad);
  box-shadow: 0 4px 12px var(--primary-glow);
}
.sidebar.is-collapsed :deep(.el-menu-item.is-active) .el-icon {
  color: #fff;
}
/* 竖条在方块里无处安放，当前位置改由整块主色承担 */
.sidebar.is-collapsed :deep(.el-menu-item.is-active)::before {
  display: none;
}

/* ============ 分组标题 ============ */
/* 中文标题不吃 uppercase 和大字距：uppercase 对中文是空操作，
   剩下的只有「字被拉开了」的怪异间距，看着像排版事故而不是设计。
   改成中文排版的常规做法：小字号、加粗、跟菜单项图标左对齐，
   右边拖一条细线把下面这一组「框」住 ——
   这条线就是标题与菜单项之间唯一的视觉关联：
   没有它，12px 的标题和 13px 的项只是两行字，不成组。 */
.nav-group-title {
  /* 吸顶：侧栏有 23 个入口，800px 高的屏上装不下，
     往下滚的时候不知道自己在哪一组里 —— 标题吸在顶上，
     滚到哪一组就是哪一组的名字。 */
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 0;
  padding: 10px 21px 4px;
  /* 12px：项目里 11px 的小字在 1x 屏上已经发糊 */
  font-size: var(--text-xs);
  font-weight: 600;
  line-height: 16px;
  letter-spacing: 0;
  text-transform: none;
  color: var(--nav-fg-faint);
  white-space: nowrap;
  overflow: hidden;
  /* 吸住的时候要盖住下面滚上来的内容。
     菜单区是纯色（顶部柔光挪到了品牌块），所以盖得住、不留色差。 */
  background: var(--bg-sidebar);
}
.nav-group-title::after {
  content: '';
  flex: 1;
  height: 1px;
  /* 比通用分隔线深一档：这条线有活干 ——
     它得把下面这一组「框」住，太淡就等于没画（0.07 时只有 1.19:1，肉眼找不着）。
     右端渐隐：一条到头齐刷刷断掉的线像被刀切过，渐隐才像「这一组到这里」。 */
  background: linear-gradient(90deg, rgba(255, 255, 255, 0.16), rgba(255, 255, 255, 0));
}
/* 所有分组标题一律同高（30px）：
   吸顶时每一组的标题要正好盖住上一组的那一条带 ——
   高度不一致的话，先吸住的那组会从下面露出半截（第一组原本矮 6px）。
   第一组不再特殊：品牌块下面那点留白，由它自己的 10px 上内边距给，
   刚好和别的组之间的留白一致，横着看也是一排。 */
/* 「没有任何权限」是一句提示，不是一个分组标题，别给它拖条尾巴 */
.nav-group-empty::after { display: none; }

/* 折叠态放不下标题，就用一段短横线交代「这里是另一组」。
   原来是一条 32px、透明度 0.07 的线 —— 在深色底上几乎看不见，
   等于分组信息全丢；现在线更短更实，前后各留一格空隙，
   就算不数线，也能靠「停顿」数出组。 */
.nav-group-divider {
  width: 18px;
  height: 1px;
  margin: 9px auto;
  border-radius: 1px;
  /* 与展开态的分组细线同一档深浅：两处是同一个「分组」概念 */
  background: rgba(255, 255, 255, 0.14);
}
.nav-group-divider.is-first { margin-top: 5px; }

/* ============ 底部区 ============ */
/* 之前底部的按钮是「透明底 + 12px 小字 + 6px 圆角」，
   和上面的菜单项完全不是一套语言，看着像两个系统拼在一起。
   现在按菜单项的规格重做：同高、同圆角、同一水平对齐轴 ——
   图标都落在距侧栏左边 21px 处，文字都落在 47px 处。 */
.sidebar-footer {
  padding: 6px 10px 8px;
  border-top: 1px solid var(--nav-hairline);
  /* 比导航区略沉一档，把「导航」与「操作」分成两块 */
  background: rgba(255, 255, 255, 0.035);
  flex-shrink: 0;
}
/* 底部动作区：两个动作并排一行 */
.footer-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}
/* 「自定义导航」占满剩下的宽度 */
.footer-actions .nav-add-btn { flex: 1; min-width: 0; }
/* 收起/展开是纯图标动作：给它一个方块，
   宽度和菜单图标方块（折叠态 38px）同一套语言。 */
.footer-actions .collapse-toggle {
  width: 30px;
  flex-shrink: 0;
  justify-content: center;
  padding: 0;
}
.collapse-btn {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  height: 30px;
  padding: 0 11px;
  margin-bottom: 0;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--nav-fg-muted);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out), color var(--duration-fast) var(--ease-out);
}
.collapse-btn:hover {
  background: var(--nav-surface);
  color: var(--nav-fg);
}
.collapse-btn:focus-visible {
  outline: 2px solid var(--nav-accent);
  outline-offset: -2px;
}
.collapse-btn .el-icon {
  font-size: 16px;
  color: var(--nav-fg-faint);
  transition: color var(--duration-fast) var(--ease-out);
}
.collapse-btn:hover .el-icon { color: var(--nav-fg-strong); }
/* 折叠态：按钮只剩图标，收到和菜单图标方块一样的 38px，排得才整齐 */
.sidebar.is-collapsed .sidebar-footer { padding: 8px 12px 10px; }
.sidebar.is-collapsed .footer-actions { flex-direction: column; gap: 6px; }
.sidebar.is-collapsed .collapse-btn {
  justify-content: center;
  padding: 0;
  width: 38px;
  height: 38px;
  margin: 0 auto;
}
.sidebar.is-collapsed .footer-actions .nav-add-btn { flex: none; }

.kbd-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 22px;
  padding: 0 11px;
  font-size: 12px;
  color: var(--nav-fg-ghost);
}
.kbd {
  background: rgba(255, 255, 255, 0.07);
  border: 1px solid rgba(255, 255, 255, 0.09);
  padding: 1px 6px;
  border-radius: 5px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--nav-fg-muted);
}
.sys-version {
  /* 版本号跟提示排在同一行，右对齐 —— 底部区省下一整行 */
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 11px;
  /* 版本号是次要信息，但不能暗到找不着（0.38 时对深色底 3.5:1，
     小字要 4.5:1，所以给到 --nav-fg-dim 的 4.9:1） */
  color: var(--nav-fg-dim);
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

/* 顶栏搜索框的宽度（外观样式见 .search-input） */
.topbar-search { width: 260px; }
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
  /* 顶栏的页面名是「我在哪」的最强信号 ——
     原来 15px，跟正文一样大，看不出是在导航还是在正文 */
  font-size: 16.5px;
  font-weight: 680;
  color: var(--text-primary);
  padding-left: 14px;
  border-left: 1px solid var(--border);
  letter-spacing: -0.2px;
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

/* 抽屉面板是 teleport 出来的，拿不到本文件的 scoped 属性，
   所以「面板外壳」（底色、内边距、滚动方式）只能定义在 main.css 里。
   菜单本体不用再抄一份：抽屉与侧栏共用 .nav-menu 这一个类名，
   样式自然就是同一套 —— 抄第二份只会让两边慢慢漂移。
   抽屉的品牌块也直接复用 .brand（同一个类名），连排版都不用各写一遍。 */

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
