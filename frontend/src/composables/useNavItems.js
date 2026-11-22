import { ref } from 'vue'
import { Api } from '../api'

// Route prefixes match complete segments, including the routes used only by deep links.
const PATH_PERM = {
  '/': 'dashboard',
  '/dashboards': 'dashboards',
  '/notes': 'notes',
  '/library': 'library',
  '/dev': 'dev',
  '/apps': 'apps',
  '/types': 'types',
  '/ontology': 'types',
  '/records': 'records',
  '/relations': 'relations',
  '/graph': 'graph',
  '/knowledge/graph': 'knowledge_graph',
  '/dna': 'dna',
  '/dna-library': 'dna',
  '/search': 'search',
  '/guide': 'guide',
  '/ai-settings': 'ai',
  '/system': 'system',
}

function resolveInternalPath(path) {
  if (typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//') || path.includes('\\')) return null
  try {
    return new URL(path, 'https://workspace.invalid')
  } catch {
    return null
  }
}

export function workspacePathname(path) {
  const url = resolveInternalPath(path)
  return url ? url.pathname.toLowerCase().replace(/\/+$/, '') || '/' : ''
}

export function matchesPathSegment(pathname, base) {
  return pathname === base || (base !== '/' && pathname.startsWith(base + '/'))
}

export function permForPath(path) {
  const pathname = workspacePathname(path)
  const match = Object.keys(PATH_PERM).find(base => matchesPathSegment(pathname, base))
  return match ? PATH_PERM[match] : ''
}

// Keep the route parameter's case while matching Vue Router's static segments.
const PARAMETERIZED_PATH = /^(\/(?:apps|dashboards|dev|notes|records|types)\/)([^/]+)(.*)$/i
const STATIC_SUBROUTES = new Set(['/dev/settings', '/types/new'])

function navigationKey(path) {
  const url = resolveInternalPath(path)
  if (!url) return ''

  const pathname = url.pathname.replace(/\/+$/, '') || '/'
  let identity = pathname.toLowerCase()
  const route = pathname.match(PARAMETERIZED_PATH)
  if (route && !STATIC_SUBROUTES.has(identity)) {
    const [, prefix, parameter, suffix] = route
    identity = prefix.toLowerCase() + parameter + suffix.toLowerCase()
  }

  return identity + url.search + url.hash
}

const items = ref([])
const loaded = ref(false)
const loading = ref(false)

export function useNavItems() {
  async function load() {
    if (loading.value) return
    loading.value = true
    try {
      const rows = await Api.listNavItems()
      items.value = Array.isArray(rows) ? rows : []
      loaded.value = true
    } catch {
      // 拉不到自定义项不该让整个侧栏挂掉 —— 内置导航照常用
      items.value = []
      loaded.value = true
    } finally {
      loading.value = false
    }
  }

  return { items, loaded, loading, load }
}

/**
 * 把自定义项并进内置分组。
 *
 * @param {Array} navGroups 内置分组 [{ title, items }]
 * @param {Array} customItems 自定义项
 * @param {(perm:string)=>boolean} canPage 页面权限判定
 */
export function mergeNavGroups(navGroups, customItems, canPage) {
  const groups = navGroups.map((g) => ({
    title: g.title,
    items: g.items.slice(),
  }))
  const taken = new Set(groups.flatMap((g) => g.items.map((i) => navigationKey(i.path))))

  // 自定义项按分组名归类
  const byGroup = new Map()
  for (const raw of customItems || []) {
    const key = navigationKey(raw.path)
    if (!key || taken.has(key)) continue
    const perm = permForPath(raw.path)
    if (perm && canPage && !canPage(perm)) continue

    const item = {
      path: raw.path,
      label: raw.label,
      icon: raw.icon || 'Link',
      custom: true,
      id: raw.id,
      description: raw.description || '',
      perm,
    }
    taken.add(key)
    const gname = raw.group_name || '自定义'
    if (!byGroup.has(gname)) byGroup.set(gname, [])
    byGroup.get(gname).push(item)
  }

  // 内置分组里已经有的组名，自定义项直接并进去；否则新建一个组
  for (const [gname, list] of byGroup) {
    const target = groups.find((g) => g.title === gname)
    if (target) {
      target.items.push(...list)
    } else {
      groups.push({ title: gname, items: list })
    }
  }

  return groups.filter((g) => g.items.length)
}
