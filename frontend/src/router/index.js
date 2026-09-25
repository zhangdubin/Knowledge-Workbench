import { createRouter, createWebHashHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

// meta.perm 与后端 services/permissions.py 的 PAGES 一一对应，
// 改这里必须同步改那边，否则会出现「菜单能看见但接口 403」的错位。
const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/Login.vue'),
    meta: { title: '登录', public: true },
  },
  {
    path: '/',
    component: () => import('../components/Layout.vue'),
    children: [
      { path: '', name: 'dashboard', component: () => import('../views/Dashboard.vue'), meta: { title: '工作台', perm: 'dashboard' } },
      // 可视化驾驶舱
      { path: 'dashboards', name: 'dashboards', component: () => import('../views/Dashboards.vue'), meta: { title: '可视化驾驶舱', perm: 'dashboards' } },
      { path: 'dashboards/:id', name: 'dashboard-view', component: () => import('../views/DashboardView.vue'), meta: { title: '驾驶舱', perm: 'dashboards' } },
      { path: 'apps', name: 'apps', component: () => import('../views/Apps.vue'), meta: { title: '应用中心', perm: 'apps' } },
      { path: 'apps/:appKey', name: 'app-detail', component: () => import('../views/AppDetail.vue'), meta: { title: '应用详情', perm: 'apps' } },
      { path: 'types', name: 'entity-types', component: () => import('../views/EntityTypes.vue'), meta: { title: '数据模型', perm: 'types' } },
      { path: 'types/:id/edit', name: 'type-edit', component: () => import('../views/TypeEditor.vue'), meta: { title: '编辑模型', perm: 'types' } },
      { path: 'types/new', name: 'type-new', component: () => import('../views/TypeEditor.vue'), meta: { title: '新建模型', perm: 'types' } },
      { path: 'records/:typeId', name: 'records', component: () => import('../views/Records.vue'), meta: { title: '记录', perm: 'records' } },
      { path: 'relations', name: 'relations', component: () => import('../views/Relations.vue'), meta: { title: '关联定义', perm: 'relations' } },
      { path: 'graph', name: 'graph', component: () => import('../views/GraphView.vue'), meta: { title: '关联图谱', perm: 'graph' } },
      { path: 'search', name: 'search', component: () => import('../views/SearchView.vue'), meta: { title: '全局搜索', perm: 'search' } },
      // 知识库（笔记）
      { path: 'notes', name: 'notes', component: () => import('../views/Notes.vue'), meta: { title: '知识库', perm: 'notes' } },
      { path: 'notes/:id', name: 'note-detail', component: () => import('../views/NoteDetail.vue'), meta: { title: '笔记详情', perm: 'notes' } },
      { path: 'knowledge/graph', name: 'knowledge-graph', component: () => import('../views/KnowledgeGraph.vue'), meta: { title: '知识图谱', perm: 'knowledge_graph' } },
      // 数据中心
      { path: 'library', name: 'library', component: () => import('../views/Library.vue'), meta: { title: '数据中心', perm: 'library' } },
      // 系统管理
      { path: 'system/users', name: 'sys-users', component: () => import('../views/system/Users.vue'), meta: { title: '用户管理', perm: 'system' } },
      { path: 'system/roles', name: 'sys-roles', component: () => import('../views/system/Roles.vue'), meta: { title: '角色权限', perm: 'system' } },
      { path: 'system/audit', name: 'sys-audit', component: () => import('../views/system/AuditLog.vue'), meta: { title: '审计日志', perm: 'system' } },
      { path: 'system/recycle', name: 'sys-recycle', component: () => import('../views/system/Recycle.vue'), meta: { title: '回收站', perm: 'system' } },
      { path: 'system/storage', name: 'sys-storage', component: () => import('../views/system/Storage.vue'), meta: { title: '存储与备份', perm: 'system' } },
      { path: 'system/settings', name: 'sys-settings', component: () => import('../views/system/Settings.vue'), meta: { title: '系统设置', perm: 'system' } },
      // AI
      { path: 'ai-settings', name: 'ai-settings', component: () => import('../views/AISettings.vue'), meta: { title: 'AI 设置', perm: 'ai' } },
      // 使用指南
      { path: 'guide', name: 'guide', component: () => import('../views/Guide.vue'), meta: { title: '使用指南', perm: 'guide' } },
      // 403 / 404
      { path: 'forbidden', name: 'forbidden', component: () => import('../views/Forbidden.vue'), meta: { title: '无权访问', public: true } },
      { path: ':pathMatch(.*)*', name: 'not-found', component: () => import('../views/NotFound.vue'), meta: { title: '页面未找到', public: true } },
    ],
  },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

/**
 * 守卫职责：先确定登录态 → 再判页面权限
 *
 * bootstrap() 只在首次调用时请求 /auth/status，之后走缓存，
 * 因此不会给每次跳转增加一次往返。
 */
router.beforeEach(async (to) => {
  const auth = useAuthStore()

  if (!auth.ready) {
    try {
      await auth.bootstrap()
    } catch {
      // 后端不可达时也要让人进得去登录页，否则会白屏
      auth.ready = true
    }
  }

  // 后端关闭了鉴权：等同于本机管理员，全部放行
  if (!auth.authEnabled) return true

  if (to.meta?.public) {
    if (to.path === '/login' && auth.isLoggedIn && !auth.mustChangePassword) {
      return { path: '/' }
    }
    return true
  }

  if (!auth.isLoggedIn) {
    return { path: '/login', query: to.fullPath === '/' ? {} : { redirect: to.fullPath } }
  }
  // 初始口令未改：后端只放行 /api/auth/*，前端必须跟着停在登录页
  if (auth.mustChangePassword) return { path: '/login' }

  const perm = to.meta?.perm
  if (perm && !auth.canPage(perm)) {
    return { path: '/forbidden', query: { from: to.path, perm } }
  }
  return true
})

router.afterEach((to) => {
  const base = '知识工作台'
  document.title = to.meta?.title ? `${to.meta.title} · ${base}` : base
})

export default router
