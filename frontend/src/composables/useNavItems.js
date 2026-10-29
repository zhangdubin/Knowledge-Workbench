/**
 * 左侧导航：内置项 + 用户自定义项
 *
 * 内置导航写死在 Layout.vue 的 NAV 常量里；自定义项存在后端（nav_item 表），
 * 换台电脑也在。所有人看到的是同一份自定义导航 —— 这跟「每个人各存一份」
 * 的做法不同，后者换个环境就丢了。
 *
 * 合并规则：
 *   1. 自定义项按 group_name 归到对应的分组；没有对应分组就并到「自定义」组
 *   2. 自定义组排在内置组之后（用户自己加的东西不要插到系统导航中间）
 *   3. 同一个路径只保留一个（自定义项优先 —— 用户是特意把它摆出来的）
 *   4. 自定义项没有 perm 概念（它只是入口，进去之后的权限由目标页自己判），
 *      但路径落在哪个受控页面上时，仍然按那个页面的 perm 过滤 ——
 *      否则普通用户能在侧栏里看到一个点进去就 403 的入口
 */
import { computed, ref } from 'vue'
import { Api } from '../api'

/** 内置导航里每个路径对应的页面权限位 —— 自定义项指向这些页面时要跟着过滤 */
const PATH_PERM = {
  '/': 'dashboard',
  '/dashboards': 'dashboards',
  '/notes': 'notes',
  '/library': 'library',
  '/apps': 'apps',
  '/types': 'types',
  '/relations': 'relations',
  '/graph': 'graph',
  '/knowledge/graph': 'knowledge_graph',
  '/search': 'search',
  '/guide': 'guide',
  '/ai-settings': 'ai',
  '/system/users': 'system',
  '/system/roles': 'system',
  '/system/audit': 'system',
  '/system/recycle': 'system',
  '/system/storage': 'system',
  '/system/settings': 'system',
}

/** 自定义项指向某个页面时，要不要按那个页面的权限过滤 */
export function permForPath(path) {
  const p = String(path || '')
  if (PATH_PERM[p]) return PATH_PERM[p]
  // /apps/xxx、/notes/xxx 这类子路径，归到它所属的父页面
  if (p.startsWith('/apps')) return 'apps'
  if (p.startsWith('/notes')) return 'notes'
  if (p.startsWith('/library')) return 'library'
  if (p.startsWith('/types')) return 'types'
  if (p.startsWith('/system')) return 'system'
  return ''
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
  const taken = new Set(groups.flatMap((g) => g.items.map((i) => i.path)))

  // 自定义项按分组名归类
  const byGroup = new Map()
  for (const raw of customItems || []) {
    const item = {
      path: raw.path,
      label: raw.label,
      icon: raw.icon || 'Link',
      custom: true,
      id: raw.id,
      description: raw.description || '',
    }
    // 同一个路径已经有过（内置的）就跳过 —— 别把系统导航顶掉
    if (taken.has(item.path)) continue
    const perm = permForPath(item.path)
    // 指向受控页面时，没权限就不显示这个入口
    if (perm && canPage && !canPage(perm)) continue
    taken.add(item.path)
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
