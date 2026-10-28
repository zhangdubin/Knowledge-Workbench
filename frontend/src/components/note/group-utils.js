/**
 * 分组的纯函数（不依赖 axios / Vue，方便单测）
 * ---------------------------------------------------------------------------
 * 分组的形状在前后端各有一份「口径」：
 *   · 后端返回 {id, name, color, count, sort_order, ...}
 *   · 笔记（记录形态）里的归属存在 data.group_id：null / 缺键 = 未分组
 * 这里把两边对齐的规整逻辑集中一处，别散在组件里各写各的。
 */

/** 分组默认色：主色（呼应 --primary #5b5fc7 那套色系） */
export const DEFAULT_GROUP_COLOR = '#5b5fc7'

/**
 * 预设色板：都取自主色的邻近色相（靛蓝 → 紫 → 青 → 绿 → 琥珀 → 玫红），
 * 这样任意组合放在一起都不会打架。
 * 用 hex 是因为颜色是「用户选的数据」，要存进后端；
 * 界面自身的配色仍然一律走 main.css 里的设计变量。
 */
export const GROUP_COLOR_PRESETS = [
  { value: '#5b5fc7', label: '靛蓝' },
  { value: '#7b6bd6', label: '紫罗兰' },
  { value: '#4a7fd4', label: '天蓝' },
  { value: '#3f9b8f', label: '青绿' },
  { value: '#5c9e5c', label: '草绿' },
  { value: '#c08a2e', label: '琥珀' },
  { value: '#c76a5a', label: '砖红' },
  { value: '#9a5fa8', label: '梅紫' },
]

/** 分组名长度上限（与后端列宽一致：40） */
export const GROUP_NAME_MAX = 40

/** 把后端返回的一条分组规整成前端统一形状（字段缺失/类型不对都不炸） */
export function normalizeGroup(raw, index = 0) {
  if (!raw || typeof raw !== 'object') return null
  const id = Number(raw.id)
  if (!Number.isFinite(id)) return null
  const name = String(raw.name ?? '').trim()
  const color = String(raw.color ?? '').trim()
  const count = Number(raw.count)
  const sort = Number(raw.sort_order)
  return {
    id,
    name: name || `分组 ${id}`,
    color: color || DEFAULT_GROUP_COLOR,
    count: Number.isFinite(count) ? count : 0,
    sort_order: Number.isFinite(sort) ? sort : index,
  }
}

/** 列表规整：兼容裸数组和 {items:[...]} 两种返回，并按 sort_order 排序 */
export function normalizeGroups(raw) {
  const list = Array.isArray(raw) ? raw : (Array.isArray(raw?.items) ? raw.items : [])
  return list
    .map((r, i) => normalizeGroup(r, i))
    .filter(Boolean)
    .sort((a, b) => a.sort_order - b.sort_order || a.id - b.id)
}

/** 把接口错误翻译成一句人话（409 重名是分组功能最常见的失败） */
export function groupErrorMessage(e, fallback = '分组操作失败') {
  const status = e?.response?.status
  if (status === 409) return e?.response?.data?.detail || '分组名已存在，换一个名字试试'
  if (status === 404) return '分组不存在（可能刚被删掉了）'
  if (status === 400) return e?.response?.data?.detail || '请求不合法'
  return e?.response?.data?.detail || e?.message || fallback
}

/** 分组名是否可用（本地先挡一道，重名以服务端 409 为准） */
export function validateGroupName(name, groups = [], currentId = null) {
  const v = String(name ?? '').trim()
  if (!v) return '给分组起个名字'
  // 上限跟后端对齐（40 字），两边不一致会出现「前端能填、后端 400」
  if (v.length > GROUP_NAME_MAX) return `分组名最多 ${GROUP_NAME_MAX} 个字`
  const dup = (groups || []).some(
    g => g.id !== currentId && String(g.name || '').toLowerCase() === v.toLowerCase()
  )
  if (dup) return '已经有同名分组了'
  return ''
}

/** 笔记（记录形态）里的分组 id：null / 缺键 = 未分组（0） */
export function noteGroupId(note) {
  return Number(note?.data?.group_id || 0)
}
