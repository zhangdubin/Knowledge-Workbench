import {
  matchesPathSegment,
  mergeNavGroups,
  workspacePathname,
} from '../composables/useNavItems.js'

const catalog = [
  { title: '工作区', items: [
    { path: '/', label: '工作台', icon: 'HomeFilled', perm: 'dashboard', description: '提问、导入资料和访问最近内容' },
    { path: '/library', label: '资料库', icon: 'FolderOpened', perm: 'library', description: '数据中心 · 上传、管理和预览文件' },
    { path: '/notes', label: '知识笔记', icon: 'Notebook', perm: 'notes', description: '知识库 · 编写和组织笔记' },
    { path: '/knowledge/graph', label: '知识图谱', icon: 'DataAnalysis', perm: 'knowledge_graph', description: '浏览笔记与资料之间的关联' },
    { path: '/search', label: '全局搜索', icon: 'Search', perm: 'search', description: '检索笔记、业务记录和文件' },
  ] },
  { title: '应用', items: [
    { path: '/apps', label: '业务应用', icon: 'Grid', perm: 'apps', description: '应用中心 · 管理业务应用及其记录' },
    { path: '/dashboards', label: '可视化驾驶舱', icon: 'PieChart', perm: 'dashboards', description: '查看业务看板和报表' },
    { path: '/ontology', label: '本体工作室', icon: 'Connection', perm: 'types', description: '修订业务概念、加工资料与核验事实证据' },
    { path: '/types', label: '数据模型', icon: 'Files', perm: 'types', description: '管理实体类型和字段' },
    { path: '/relations', label: '关联定义', icon: 'Connection', perm: 'relations', description: '设置数据模型之间的关系' },
    { path: '/graph', label: '关联图谱', icon: 'Share', perm: 'graph', description: '查看业务记录之间的联系' },
  ] },
  { title: '发现', items: [
    { path: '/dna', label: '养料 DNA', icon: 'DataLine', perm: 'dna', description: '查看资料质量和关联分析' },
    { path: '/dna-library', label: '养料库', icon: 'DataBoard', perm: 'dna', description: '浏览和管理已吸收的资料' },
    { path: '/dev', label: '软件开发', icon: 'Cpu', perm: 'dev', description: '打开开发项目工作台' },
  ] },
  { title: '系统', items: [
    { path: '/system/users', label: '用户管理', icon: 'UserFilled', perm: 'system', feature: 'user_manage', description: '管理账号与成员' },
    { path: '/system/roles', label: '角色权限', icon: 'Key', perm: 'system', feature: 'role_manage', description: '配置角色与访问权限' },
    { path: '/system/audit', label: '审计日志', icon: 'DocumentChecked', perm: 'system', feature: 'audit_view', description: '查看系统操作历史' },
    { path: '/system/recycle', label: '回收站', icon: 'Delete', perm: 'system', feature: 'model_manage', description: '恢复或清理已删除内容' },
    { path: '/system/storage', label: '存储与备份', icon: 'Coin', perm: 'system', feature: 'storage_manage', description: '管理存储与系统备份' },
    { path: '/system/nav', label: '导航管理', icon: 'Menu', perm: 'system', feature: 'system_config', description: '添加与整理自定义快捷方式' },
    { path: '/system/settings', label: '系统设置', icon: 'Setting', perm: 'system', feature: 'system_config', description: '管理系统配置与更新' },
    { path: '/guide', label: '使用指南', icon: 'Compass', perm: 'guide', description: '查阅知识工作台的使用方法' },
    { path: '/ai-settings', label: 'AI 设置', icon: 'MagicStick', perm: 'ai', description: '配置模型与 AI 服务' },
  ] },
]

const featureItems = catalog.flatMap(group => group.items).filter(item => item.feature)

export function getWorkspaceNavigation({ canPage, canFeature, customItems = [] }) {
  const visibleCatalog = catalog.map(group => ({
    ...group,
    items: group.items.filter(item => canPage(item.perm) && (!item.feature || canFeature(item.feature))),
  }))

  const visibleCustom = customItems.filter(item => {
    const pathname = workspacePathname(item.path)
    const controlled = featureItems.find(item => matchesPathSegment(pathname, item.path))
    return !controlled || canFeature(controlled.feature)
  })
  const groups = mergeNavGroups(visibleCatalog, visibleCustom, canPage)
  const builtin = visibleCatalog.flatMap(group => group.items)
  const graph = canPage('knowledge_graph') ? '/knowledge/graph' : '/graph'
  const primary = ['/', '/library', '/notes', graph, '/apps']
    .map(path => builtin.find(item => item.path === path))
    .filter(Boolean)
  const shortcuts = groups.flatMap(group => group.items).filter(item => item.custom).slice(0, 3)

  return { primary, shortcuts, groups }
}

export function searchWorkspaceCommands(groups, query) {
  const term = String(query ?? '').trim().toLowerCase()
  return groups.flatMap(group => group.items).filter(item =>
    [item.label, item.description, item.path].some(value => String(value ?? '').toLowerCase().includes(term)),
  )
}

export function activeWorkspacePath(path, primary) {
  const pathname = workspacePathname(path)
  return primary.find(item => matchesPathSegment(pathname, item.path))?.path || ''
}
