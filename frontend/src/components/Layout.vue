<template>
  <el-container class="layout workspace-layout">
    <el-aside class="sidebar workspace-sidebar" :width="collapsed ? '64px' : '224px'">
      <div class="workspace-brand" :class="{ 'is-compact': collapsed }">
        <span class="workspace-mark"><el-icon aria-hidden="true"><Collection /></el-icon></span>
        <span v-if="!collapsed">知识工作台</span>
      </div>

      <WorkspaceNavigation v-bind="navigationProps" :compact="collapsed" @catalog="showCatalog" />

      <div class="workspace-sidebar-footer" :class="{ 'is-compact': collapsed }">
        <button
          class="workspace-icon-button"
          type="button"
          :aria-label="collapsed ? '展开侧边栏' : '收起侧边栏'"
          :title="collapsed ? '展开侧边栏' : '收起侧边栏'"
          @click="toggleCollapse"
        >
          <el-icon aria-hidden="true"><DArrowRight v-if="collapsed" /><DArrowLeft v-else /></el-icon>
        </button>
        <span v-if="auth.sysVersion && !collapsed" title="系统版本">v{{ auth.sysVersion }}</span>
      </div>
    </el-aside>

    <el-container class="workspace-content">
      <el-header class="topbar workspace-topbar">
        <div class="workspace-location">
          <button
            class="workspace-icon-button workspace-menu-toggle"
            type="button"
            aria-label="打开导航"
            aria-haspopup="dialog"
            @click="drawerOpen = true"
          >
            <el-icon aria-hidden="true"><Menu /></el-icon>
          </button>
          <div class="workspace-title" :title="pageTitle">
            <template v-if="advancedGroup">
              <button type="button" class="workspace-context" @click="showCatalog">{{ advancedGroup }}</button>
              <el-icon class="workspace-context" aria-hidden="true"><ArrowRight /></el-icon>
            </template>
            <span>{{ pageTitle }}</span>
          </div>
        </div>

        <div class="workspace-header-actions">
          <button
            class="workspace-header-search"
            type="button"
            aria-label="快速搜索"
            aria-haspopup="dialog"
            @click="commandOpen = true"
          >
            <el-icon aria-hidden="true"><Search /></el-icon>
            <span>搜索功能或内容</span>
            <kbd aria-hidden="true">{{ shortcutLabel }}</kbd>
          </button>
          <button
            v-if="canUseAI"
            class="workspace-assistant-button"
            type="button"
            aria-haspopup="dialog"
            @click="openAssistant()"
          >
            <el-icon aria-hidden="true"><MagicStick /></el-icon>AI 助手
          </button>
          <button class="workspace-icon-button" type="button" aria-label="切换主题" title="切换主题" @click="toggleTheme">
            <el-icon aria-hidden="true"><Sunny v-if="isDark" /><Moon v-else /></el-icon>
          </button>

          <el-dropdown trigger="click" @command="onUserCommand">
            <button class="workspace-user" type="button" :aria-label="`账号菜单 · ${auth.displayName}`">
              <span class="workspace-avatar" aria-hidden="true">{{ avatarText }}</span>
              <span class="workspace-user-name">{{ auth.displayName }}</span>
              <el-icon class="workspace-user-caret" aria-hidden="true"><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item disabled>{{ auth.displayName }} · {{ auth.roleLabel }}</el-dropdown-item>
                <el-dropdown-item v-if="auth.authEnabled" command="password" divided>
                  <el-icon><Key /></el-icon>修改密码
                </el-dropdown-item>
                <el-dropdown-item v-if="auth.canPage('guide')" command="guide">
                  <el-icon><Compass /></el-icon>使用指南
                </el-dropdown-item>
                <el-dropdown-item v-if="!auth.authEnabled" disabled>
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

      <el-main class="workspace-main">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>

    <el-drawer
      v-model="drawerOpen"
      title="知识工作台"
      direction="ltr"
      size="260px"
      class="workspace-mobile-drawer"
      @closed="afterDrawerClosed"
    >
      <WorkspaceNavigation v-bind="navigationProps" @select="drawerOpen = false" @catalog="showCatalog" />
      <div v-if="auth.sysVersion" class="workspace-drawer-version">v{{ auth.sysVersion }}</div>
    </el-drawer>

    <WorkspaceCommandMenu
      v-model="commandOpen"
      :groups="navigation.groups"
      :primary="navigation.primary"
      :can-search="auth.canPage('search')"
    />
    <WorkspaceCatalog
      v-model="catalogOpen"
      :groups="navigation.groups"
      :can-pick-gene="canPickGene"
      @pick-gene="genePickerOpen = true"
    />
    <GenePicker v-if="canPickGene" v-model="genePickerOpen" mode="copy" />
    <AgentChat
      v-if="canUseAI"
      v-model="assistantOpen"
      :initial-question="assistantQuestion"
      @consume-question="assistantQuestion = null"
    />

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

  </el-container>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { DArrowLeft, DArrowRight } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AgentChat from './AgentChat.vue'
import GenePicker from './GenePicker.vue'
import WorkspaceNavigation from './workspace/WorkspaceNavigation.vue'
import WorkspaceCommandMenu from './workspace/WorkspaceCommandMenu.vue'
import WorkspaceCatalog from './workspace/WorkspaceCatalog.vue'
import { useAuthStore } from '../stores/auth'
import { useNavItems } from '../composables/useNavItems'
import { useWorkspaceActions } from '../composables/useWorkspaceActions'
import { activeWorkspacePath, getWorkspaceNavigation } from '../utils/workspaceNavigation'
import { isDark, toggleTheme } from '../utils/theme'
import { normVersion, sameVersion } from '../utils/update'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const navItems = useNavItems()
const { commandOpen, catalogOpen, assistantOpen, assistantQuestion, openAssistant } = useWorkspaceActions()
const canUseAI = computed(() => auth.can('ai'))
const canPickGene = computed(() => auth.canPage('dna'))
const avatarText = computed(() => (auth.displayName || '?').slice(0, 1))
const navigation = computed(() => getWorkspaceNavigation({
  canPage: auth.canPage,
  canFeature: auth.can,
  customItems: navItems.items.value,
}))
const activePath = computed(() => activeWorkspacePath(route.path, navigation.value.primary))
const navigationProps = computed(() => ({
  primary: navigation.value.primary,
  shortcuts: navigation.value.shortcuts,
  activePath: activePath.value,
  currentLocation: route.fullPath,
}))
const pageTitle = computed(() =>
  navigation.value.primary.find(item => item.path === route.path)?.label
  || route.meta.title
  || '知识工作台',
)
const advancedGroup = computed(() => {
  if (activePath.value) return ''
  const group = navigation.value.groups.find(group => activeWorkspacePath(route.path, group.items))
  if (group) return group.title
  if (route.name === 'records') return '应用'
  return ''
})

const COLLAPSE_KEY = 'kb-sidebar-collapsed'
const collapsed = ref(false)
const drawerOpen = ref(false)
const genePickerOpen = ref(false)
const shortcutLabel = /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘ K' : 'Ctrl K'
let catalogAfterDrawer = false
let versionTimer

function toggleCollapse() {
  collapsed.value = !collapsed.value
  try { localStorage.setItem(COLLAPSE_KEY, collapsed.value ? '1' : '0') } catch { /* 存储不可用 */ }
}

function showCatalog() {
  if (drawerOpen.value) {
    catalogAfterDrawer = true
    drawerOpen.value = false
    return
  }
  catalogOpen.value = true
}

function afterDrawerClosed() {
  if (!catalogAfterDrawer) return
  catalogAfterDrawer = false
  catalogOpen.value = true
}

function handleKey(event) {
  if (event.defaultPrevented || event.isComposing || !(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 'k') return
  if (drawerOpen.value || catalogOpen.value || assistantOpen.value || genePickerOpen.value || pwOpen.value) return
  event.preventDefault()
  commandOpen.value = true
}

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

watch(() => auth.isLoggedIn, loggedIn => {
  if (loggedIn) navItems.load()
}, { immediate: true })

onMounted(() => {
  try { collapsed.value = localStorage.getItem(COLLAPSE_KEY) === '1' } catch { /* 存储不可用 */ }
  auth.bootstrap()
  window.addEventListener('keydown', handleKey)

  versionTimer = setInterval(async () => {
    if (document.hidden) return
    const before = auth.sysVersion
    const now = await auth.refreshVersion()
    if (before && now && !sameVersion(before, now)) {
      ElMessage.warning(
        `后端已升级到 v${normVersion(now)}，`
        + `当前页面显示的还是 v${normVersion(before)}，建议刷新页面`,
        { duration: 8000 },
      )
    }
  }, 5 * 60 * 1000)
})

onUnmounted(() => {
  clearInterval(versionTimer)
  window.removeEventListener('keydown', handleKey)
  commandOpen.value = false
  catalogOpen.value = false
  assistantOpen.value = false
  assistantQuestion.value = null
})
</script>

<style scoped>
.workspace-layout { height: 100vh; height: 100dvh; }
.workspace-content { min-width: 0; }
.workspace-sidebar {
  display: flex;
  flex-direction: column;
  background: color-mix(in srgb, var(--bg-card) 60%, var(--bg-subtle));
  border-right: 1px solid var(--border);
}
.workspace-brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-height: 75px;
  padding: 0 var(--space-5);
  color: var(--text-primary);
  font-size: var(--text-md);
  font-weight: 680;
  white-space: nowrap;
}
.workspace-brand.is-compact { justify-content: center; padding: 0; }
.workspace-mark {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: var(--radius);
  color: #fff;
  background: var(--primary-grad);
}
.workspace-mark .el-icon { font-size: 17px; }
.workspace-sidebar-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  margin: auto var(--space-3) 0;
  padding: var(--space-3) var(--space-1);
  border-top: 1px solid var(--border);
  color: var(--text-tertiary);
  font-size: var(--text-xs);
  font-variant-numeric: tabular-nums;
}
.workspace-sidebar-footer.is-compact { justify-content: center; }
.workspace-topbar {
  --el-header-height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: 0 var(--space-6);
  border-bottom: 1px solid var(--border);
  background: var(--bg-card);
}
.workspace-location, .workspace-title, .workspace-header-actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.workspace-location,
.workspace-title { min-width: 0; }
.workspace-title { gap: var(--space-2); font-size: var(--text-base); font-weight: 650; }
.workspace-title span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.workspace-context {
  flex: none;
  border: 0;
  padding: 0;
  background: transparent;
  color: var(--text-tertiary);
  font: inherit;
  font-weight: 400;
}
button.workspace-context { cursor: pointer; }
button.workspace-context:hover { color: var(--primary); }
.workspace-header-actions { flex: none; gap: var(--space-2); }
.workspace-icon-button, .workspace-header-search, .workspace-assistant-button, .workspace-user {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  min-width: 36px;
  min-height: 36px;
  padding: 0 var(--space-2);
  border: 1px solid transparent;
  border-radius: var(--radius);
  background: transparent;
  color: var(--text-secondary);
  font: inherit;
  white-space: nowrap;
  cursor: pointer;
}
.workspace-icon-button:hover, .workspace-user:hover { background: var(--bg-subtle); }
.workspace-icon-button .el-icon, .workspace-header-search .el-icon, .workspace-assistant-button .el-icon { font-size: 16px; }
.workspace-header-search {
  justify-content: flex-start;
  width: clamp(150px, 22vw, 248px);
  padding: 0 var(--space-3);
  border-color: var(--border);
  background: var(--bg);
  color: var(--text-tertiary);
  font-size: var(--text-sm);
}
.workspace-header-search:hover { border-color: var(--border-strong); }
.workspace-header-search kbd {
  margin-left: auto;
  padding: 1px 5px;
  border: 1px solid var(--border);
  border-radius: var(--radius-xs);
  background: var(--bg-card);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  line-height: 1.3;
}
.workspace-assistant-button {
  padding: 0 var(--space-3);
  color: var(--primary);
  font-weight: 600;
}
.workspace-assistant-button:hover { background: var(--primary-bg); }
.workspace-avatar {
  display: grid;
  place-items: center;
  width: 27px;
  height: 27px;
  border-radius: var(--radius-full);
  background: var(--primary-bg-strong);
  color: var(--primary);
  font-size: var(--text-xs);
  font-weight: 650;
}
.workspace-user-name { max-width: 80px; overflow: hidden; text-overflow: ellipsis; font-size: var(--text-sm); }
.workspace-user-caret { font-size: 12px; }
.workspace-menu-toggle { display: none; }
.workspace-main { min-width: 0; padding: 0; background: var(--bg); overflow-y: auto; }
.fade-enter-active, .fade-leave-active { transition: opacity var(--duration-fast) ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
@media (prefers-reduced-motion: reduce) {
  .fade-enter-active, .fade-leave-active { transition: none; }
}
.workspace-drawer-version { padding: var(--space-4) var(--space-6); color: var(--text-tertiary); }
.dialog-summary { display: flex; align-items: center; gap: var(--space-2); margin-bottom: var(--space-4); }
@media (max-width: 767px) {
  .workspace-sidebar { display: none; }
  .workspace-topbar {
    --el-header-height: 56px;
    gap: var(--space-2);
    padding: 0 var(--space-3);
  }
  .workspace-menu-toggle { display: inline-flex; }
  .workspace-location { gap: var(--space-1); }
  .workspace-header-actions { gap: 2px; }
  .workspace-header-search { width: 36px; justify-content: center; padding: 0; border-color: transparent; background: transparent; }
  .workspace-header-search span, .workspace-header-search kbd, .workspace-user-name, .workspace-user-caret,
  .workspace-context { display: none; }
  .workspace-assistant-button { padding: 0 var(--space-2); }
}
</style>

<style>
.workspace-mobile-drawer { background: var(--bg-card); }
.workspace-mobile-drawer .el-drawer__header { margin-bottom: 0; border-bottom: 1px solid var(--border); }
.workspace-mobile-drawer .el-drawer__body { padding: 0 !important; }
@media (max-width: 767px) {
  .el-drawer.workspace-mobile-drawer { max-width: min(290px, 86vw) !important; }
}
</style>
