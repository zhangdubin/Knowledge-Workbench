/**
 * 应用中心的纯函数：搜索 / 筛选 / 排序 / 分组 / 批量导出
 * ---------------------------------------------------------------------------
 * 为什么抽出来：
 * - 卡片视图与表格视图必须给出同一个顺序、同一个命中结果。规则写在视图里
 *   必然出现「卡片按名称排、表格按记录数排」这种割裂，用户来回切视图就会发现
 *   列表变了 —— 这是最伤信任的一类小毛病。
 * - 这些规则都是纯数据计算，可以直接在 tests/apps.test.mjs 里断言，
 *   不用起浏览器就能验证「搜 Key 能搜到」「按记录数排序是降序」这类容易回归的细节。
 *
 * 分组说明（重要）：
 * 后端 App 表目前只有 key / name / icon / description / order 五个字段，没有分组，
 * 所以这里的「分组」是浏览器本地的文件夹（localStorage），键是应用 key、值是分组名。
 * 等后端补上 group 字段后，resolveGroup 会自动优先用后端返回的值，视图不用改。
 */

import { appIcon } from './icons.js'

/** 未归组应用的落点：它是「分组」概念里的默认值，不是一个真实分组 */
export const DEFAULT_GROUP = '未分组'

/** 分组筛选里的「全部分组」哨兵值 */
export const ALL_GROUPS = '__all__'

/** 本地分组表的存储键 */
export const GROUP_STORE_KEY = 'kb_app_groups'

/** 排序选项：视图直接渲染这份列表，避免下拉里的文案和实际排序逻辑对不上 */
export const SORT_OPTIONS = [
  { value: 'updated', label: '最近更新' },
  { value: 'name', label: '名称' },
  { value: 'models', label: '模型数' },
  { value: 'records', label: '记录数' },
]

/** 统一大小写与空白：搜索要能命中「 CRM 」这种带空格的输入 */
function norm(v) {
  return String(v ?? '').trim().toLowerCase()
}

/**
 * 搜索命中：名称 / 描述 / Key 三个字段都参与
 * 为什么连 Key 一起搜：运维人员手里的应用标识就是 Key，让他切到「表格视图找 Key」不现实。
 */
export function matchApp(app, keyword) {
  const k = norm(keyword)
  if (!k) return true
  if (!app) return false
  return [app.name, app.description, app.key].some(v => norm(v).includes(k))
}

/**
 * 取应用所属分组
 * 后端一旦返回 group 就以它为准（未来的服务端分组优先），
 * 现在后端没有这个字段，就用本地分组表兜底。
 */
export function resolveGroup(app, groupMap = {}) {
  if (!app) return DEFAULT_GROUP
  const raw = app.group ?? groupMap[app.key]
  const name = String(raw ?? '').trim()
  return name || DEFAULT_GROUP
}

/**
 * 统计各分组的应用数，供分组筛选下拉展示
 * 返回 [{ name, count }]，按名称排序；未分组排在最后（它是兜底项，不是用户建的组）。
 */
export function collectGroups(apps, groupMap = {}) {
  const counts = new Map()
  for (const a of apps || []) {
    const g = resolveGroup(a, groupMap)
    counts.set(g, (counts.get(g) || 0) + 1)
  }
  const list = [...counts.entries()]
    .filter(([name]) => name !== DEFAULT_GROUP)
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => a.name.localeCompare(b.name, 'zh-Hans-CN'))
  const rest = counts.get(DEFAULT_GROUP) || 0
  if (rest) list.push({ name: DEFAULT_GROUP, count: rest })
  return list
}

/** 过滤：关键词 + 分组，两个条件是「与」的关系 */
export function filterApps(apps, { keyword = '', group = '', groupMap = {} } = {}) {
  return (apps || []).filter(a => {
    if (group && group !== ALL_GROUPS && resolveGroup(a, groupMap) !== group) return false
    return matchApp(a, keyword)
  })
}

/** 名称比较：中文按拼音序，英文按字母序 */
function byName(a, b) {
  return String(a?.name ?? '').localeCompare(String(b?.name ?? ''), 'zh-Hans-CN')
}

/** 后端默认排序口径（order 小的在前，其次 id） */
function byDefaultOrder(a, b) {
  const oa = Number(a?.order ?? 0)
  const ob = Number(b?.order ?? 0)
  if (oa !== ob) return oa - ob
  return Number(a?.id ?? 0) - Number(b?.id ?? 0)
}

/**
 * 排序
 * 「最近更新」优先用接口返回的 updated_at；当前 list_apps 没有这个字段，
 * 这时退化成后端默认顺序（order + id），而不是把列表排乱 ——
 * 没有依据的排序比不排更让人困惑。
 */
export function sortApps(apps, sortKey = 'updated') {
  const arr = [...(apps || [])]
  const time = a => (a?.updated_at ? Date.parse(a.updated_at) : NaN)
  switch (sortKey) {
    case 'name':
      return arr.sort(byName)
    case 'models':
      return arr.sort((a, b) =>
        (Number(b?.entity_count) || 0) - (Number(a?.entity_count) || 0) || byName(a, b))
    case 'records':
      return arr.sort((a, b) =>
        (Number(b?.record_count) || 0) - (Number(a?.record_count) || 0) || byName(a, b))
    case 'updated':
    default:
      return arr.sort((a, b) => {
        const ta = time(a)
        const tb = time(b)
        const ha = Number.isNaN(ta)
        const hb = Number.isNaN(tb)
        if (ha && hb) return byDefaultOrder(a, b)
        if (ha) return 1          // 有更新时间的排前面
        if (hb) return -1
        return tb - ta
      })
  }
}

/**
 * 批量改分组：返回新的分组表，不改传入的对象
 * 为什么返回新对象：视图里用 computed 派生列表，就地修改会绕过响应式更新。
 */
export function assignGroup(groupMap, keys, group) {
  const next = { ...(groupMap || {}) }
  const name = String(group ?? '').trim()
  for (const k of keys || []) {
    if (!k) continue
    if (!name) delete next[k]
    else next[k] = name
  }
  return next
}

/** 解析浏览器里存的分组表：任何异常都退回空表，绝不让脏数据把整个页面带崩 */
export function parseGroupMap(raw) {
  if (!raw) return {}
  try {
    const obj = JSON.parse(raw)
    if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return {}
    const out = {}
    for (const [k, v] of Object.entries(obj)) {
      if (typeof v === 'string' && v.trim()) out[k] = v.trim()
    }
    return out
  } catch {
    return {}
  }
}

/** 序列化分组表 */
export function serializeGroupMap(map) {
  return JSON.stringify(map || {})
}

/** 应用图标：后端给的是图标名，给的不是（历史数据是 emoji）就按 key 推导 */
export function resolveAppIcon(app, iconChoices = []) {
  const name = app?.icon
  if (name && iconChoices.includes(name)) return name
  return appIcon(app?.key)
}

/** 描述兜底：卡片上没描述时给一句人话，比空白更清楚 */
export function appDescription(app) {
  const d = String(app?.description ?? '').trim()
  return d || '暂无说明'
}

/** CSV 单元格转义：说明里可能有逗号和引号，不转义会把表格拆乱 */
function csvCell(v) {
  const s = String(v ?? '')
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

/**
 * 批量导出（CSV）
 * 列固定为「名称 / Key / 说明 / 分组 / 模型数 / 记录数」，是给人看的清单；
 * 机器要用的场合走 JSON 导出。
 */
export function appsToCsv(apps, groupMap = {}) {
  const head = ['名称', 'Key', '说明', '分组', '模型数', '记录数']
  const rows = (apps || []).map(a => [
    a?.name ?? '',
    a?.key ?? '',
    a?.description ?? '',
    resolveGroup(a, groupMap),
    Number(a?.entity_count) || 0,
    Number(a?.record_count) || 0,
  ])
  return [head, ...rows].map(r => r.map(csvCell).join(',')).join('\n')
}

/** 批量导出（JSON）：带上导出时间与来源，方便别人回头查这份清单是什么时候导的 */
export function appsToJson(apps, groupMap = {}) {
  return JSON.stringify({
    exported_at: new Date().toISOString(),
    total: (apps || []).length,
    apps: (apps || []).map(a => ({
      key: a?.key ?? '',
      name: a?.name ?? '',
      icon: a?.icon ?? '',
      description: a?.description ?? '',
      group: resolveGroup(a, groupMap),
      order: Number(a?.order) || 0,
      entity_count: Number(a?.entity_count) || 0,
      record_count: Number(a?.record_count) || 0,
    })),
  }, null, 2)
}
