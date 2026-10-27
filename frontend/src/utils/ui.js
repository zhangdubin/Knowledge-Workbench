/**
 * 设计系统的纯函数
 *
 * 为什么要单独抽出来：尺寸档位（弹窗宽度、表格密度、空态图标大小）
 * 如果散落在各个 .vue 里，迟早会出现「同一个 sm 在两个页面宽度不同」，
 * 而且没人说得清哪个是对的。收敛成纯函数之后：
 *   1) 档位只有一份定义，改一次全局生效；
 *   2) 可以直接用 node 跑单测，不用起浏览器、不用起 vite。
 */

/* ============ 弹窗尺寸档位 ============ */

/**
 * 弹窗四档宽度（px）。
 * sm  确认框 / 简单表单：一行标题 + 两三个字段
 * md  标准表单：默认档
 * lg  带表格或分栏的编辑
 * xl  宽表格 / 多栏布局
 * 这四档是按「内容密度」定的，不是按像素随意排的。
 */
export const DIALOG_SIZES = Object.freeze({
  sm: 420,
  md: 560,
  lg: 760,
  xl: 1040,
})

export const DIALOG_SIZE_LIST = Object.freeze(Object.keys(DIALOG_SIZES))

/**
 * 算出弹窗宽度。
 * 传了 width 就用 width（数字按 px 处理，字符串原样用，
 * 这样 '50%' 这种写法也能用）；没传才落到 size 档位。
 */
export function dialogWidth(size = 'md', width = '') {
  if (width !== '' && width !== null && width !== undefined) {
    return typeof width === 'number' ? `${width}px` : String(width)
  }
  const px = DIALOG_SIZES[size] ?? DIALOG_SIZES.md
  return `${px}px`
}

/* ============ 表格密度档位 ============ */

/**
 * 表格密度三档。
 * 密度只管「行高和内边距」，不管字号 —— 这是刻意的：
 * 之前用 Element Plus 的 size="small" 做紧凑表格，它把字号一起调小了，
 * 一屏没多看几行，眼睛倒先累了。
 */
export const TABLE_DENSITIES = Object.freeze(['compact', 'default', 'comfortable'])

/** 密度档位 → class 名；非法值一律回落到 default（而不是抛错，避免渲染整页崩） */
export function tableDensityClass(density = 'default') {
  return TABLE_DENSITIES.includes(density)
    ? `table-density-${density}`
    : 'table-density-default'
}

/* ============ 空状态图标尺寸 ============ */

export const EMPTY_ICON_SIZES = Object.freeze({
  sm: 40,
  md: 56,
  lg: 72,
})

/**
 * 空状态图标尺寸。传数字直接用；传 'sm'/'md'/'lg' 走档位；
 * 其它字符串按非法处理，回落到 md。
 */
export function emptyIconSize(size = 'md') {
  if (typeof size === 'number' && Number.isFinite(size) && size > 0) return size
  return EMPTY_ICON_SIZES[size] ?? EMPTY_ICON_SIZES.md
}

/* ============ class 名拼接 ============ */

/**
 * class 名拼接（classnames 的极简版）。
 * 规则：
 *   - false / null / undefined / '' 一律丢掉
 *   - 数组递归展开
 *   - 对象按 key 为真值取 key
 *   - 0 会保留（它是合法的 class 名），但字符串 'false' 也保留
 *     （那是用户自己写的，不是布尔值）
 */
export function cx(...args) {
  const out = []
  for (const arg of args) {
    if (arg === null || arg === undefined || arg === false || arg === '') continue
    if (typeof arg === 'string' || typeof arg === 'number') {
      out.push(String(arg))
    } else if (Array.isArray(arg)) {
      const nested = cx(...arg)
      if (nested) out.push(nested)
    } else if (typeof arg === 'object') {
      for (const key of Object.keys(arg)) {
        if (arg[key]) out.push(key)
      }
    }
  }
  return out.join(' ')
}
