/**
 * 主题工具
 *
 * 图表的配色必须跟着明/暗主题走。把「当前是否暗色」和「从 CSS 变量取色」
 * 收敛到这里，图表组件就不用各自硬编码两套颜色。
 *
 * 暗色由 Layout.vue 通过 `document.documentElement.classList.toggle('dark')`
 * 控制，因此这里用 MutationObserver 监听 html 的 class，而不是再维护一份状态
 * ——两份状态迟早会不同步。
 */
import { ref } from 'vue'

const THEME_KEY = 'kb-theme'

/** 是否暗色（响应式；html.dark 变化时自动更新） */
export const isDark = ref(false)

function sync() {
  isDark.value = document.documentElement.classList.contains('dark')
}

if (typeof document !== 'undefined') {
  sync()
  new MutationObserver(sync).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['class'],
  })
}

/**
 * 启动时把主题落到 html 上。
 *
 * 必须在 mount 之前调用：早先只有 Layout 在挂载时带主题，于是「登录页永远是浅色、
 * 刷新后主题丢回浅色」——用户存了暗色偏好却每次都被闪一下白屏。偏好存在
 * localStorage，没有存过就跟随系统。
 */
export function initTheme() {
  if (typeof document === 'undefined') return
  let saved = ''
  try { saved = localStorage.getItem(THEME_KEY) || '' } catch (e) { /* 隐私模式下不可用 */ }
  const dark = saved ? saved === 'dark'
    : window.matchMedia?.('(prefers-color-scheme: dark)').matches
  document.documentElement.classList.toggle('dark', !!dark)
  sync()
}

/** 切换主题并记住选择（登录页与主框架共用同一份状态） */
export function toggleTheme() {
  if (typeof document === 'undefined') return
  const next = !document.documentElement.classList.contains('dark')
  document.documentElement.classList.toggle('dark', next)
  try { localStorage.setItem(THEME_KEY, next ? 'dark' : 'light') } catch (e) { /* 忽略 */ }
  sync()
}

/** 读取一个 CSS 设计令牌，取不到时回退 */
export function cssVar(name, fallback = '') {
  if (typeof document === 'undefined') return fallback
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}

/**
 * 图表统一视觉：轴线、文字、色板
 *
 * 色板第一位永远是主色，保证「最重要的一组数据」在各图里颜色一致。
 */
export function chartTheme() {
  const text = cssVar('--text-secondary', '#4b4f59')
  return {
    dark: isDark.value,
    text,
    muted: cssVar('--text-tertiary', '#8a8f9b'),
    line: cssVar('--border', '#e4e6ec'),
    split: cssVar('--border-light', '#eef0f3'),
    card: cssVar('--bg-card', '#ffffff'),
    primary: cssVar('--primary', '#5b5fc7'),
    colors: [
      cssVar('--primary', '#5b5fc7'),
      cssVar('--success', '#0b7a5a'),
      cssVar('--warning', '#c07c17'),
      cssVar('--danger', '#c03e39'),
      cssVar('--info', '#6b7280'),
      '#7c6ce0',
      '#3f9ec9',
      '#d4699c',
    ],
  }
}

/** 折线/柱状图共用的坐标轴样式 */
export function axisStyle() {
  const t = chartTheme()
  return {
    axisLine: { lineStyle: { color: t.line } },
    axisTick: { show: false },
    axisLabel: { color: t.muted, fontSize: 11 },
    splitLine: { lineStyle: { color: t.split, type: 'dashed' } },
  }
}

/** tooltip 样式（背景用卡片色，保证暗色下不像白斑） */
export function tooltipStyle() {
  const t = chartTheme()
  return {
    backgroundColor: t.card,
    borderColor: t.line,
    borderWidth: 1,
    textStyle: { color: t.text, fontSize: 12 },
    extraCssText: 'box-shadow: 0 6px 20px rgba(0,0,0,.12); border-radius: 8px;',
  }
}
