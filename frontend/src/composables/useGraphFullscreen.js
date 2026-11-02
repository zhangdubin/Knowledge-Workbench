import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

/**
 * 图谱「全屏显示」的开关
 *
 * 为什么用「铺满视口的浮层」而不是浏览器的 Fullscreen API：
 *   1. Fullscreen API 必须在用户手势里调用，而且被 iframe 包着时
 *      没有 allowfullscreen 就直接拒绝 —— 这个应用会被嵌进别人的页面里，
 *      用 API 就等于「在别人的地盘上不一定能用」。
 *   2. Fullscreen API 会把整个浏览器 UI 换掉，用户找不到返回按钮，
 *      只能按 Esc —— 在触屏设备上这几乎等于出不来。
 *   3. 浮层方案能保留工具条、图例、提示，跟普通视图的交互完全一致。
 *
 * 代价是浏览器自身的标签栏/地址栏还在 —— 对「把图铺满屏幕看」这个需求，
 * 这个代价可以接受。
 *
 * @param {Function} onChange 尺寸变化后的回调（图要重新测量、重新对中）
 */
export function useGraphFullscreen(onChange) {
  const isFullscreen = ref(false)
  let savedOverflow = ''
  let savedPaddingRight = ''

  function lockScroll() {
    // 铺满视口时，背景页面还能滚的话，滚轮会滚走背景而不是缩放图 ——
    // 这是全屏模式最常见的「不好用」来源。
    const body = document.body
    savedOverflow = body.style.overflow
    savedPaddingRight = body.style.paddingRight
    const gap = window.innerWidth - document.documentElement.clientWidth
    body.style.overflow = 'hidden'
    if (gap > 0) body.style.paddingRight = gap + 'px'
  }

  function unlockScroll() {
    const body = document.body
    body.style.overflow = savedOverflow
    body.style.paddingRight = savedPaddingRight
  }

  /**
   * 等布局落定之后再通知外部
   *
   * 为什么等两帧：
   *   class 加上 → 浏览器要重排 → 图才拿到新尺寸。
   *   立刻回调的话量到的还是旧尺寸，图会停在旧大小上，
   *   看着像「全屏了但没变大」。
   */
  function notifyChanged() {
    nextTick(() => {
      requestAnimationFrame(() => {
        requestAnimationFrame(() => { onChange?.() })
      })
    })
  }

  function enter() {
    if (isFullscreen.value) return
    isFullscreen.value = true
    lockScroll()
    notifyChanged()
  }

  function exit() {
    if (!isFullscreen.value) return
    isFullscreen.value = false
    unlockScroll()
    notifyChanged()
  }

  function toggle() {
    isFullscreen.value ? exit() : enter()
  }

  function onKeydown(e) {
    // Esc 退出全屏：这是用户唯一的「退路」，必须支持
    if (e.key === 'Escape' && isFullscreen.value) {
      e.stopPropagation()
      exit()
    }
  }

  onMounted(() => document.addEventListener('keydown', onKeydown))

  onBeforeUnmount(() => {
    document.removeEventListener('keydown', onKeydown)
    // 组件被销毁时如果还锁着滚动，页面就永久滚不动了 —— 必须解锁
    if (isFullscreen.value) unlockScroll()
  })

  return { isFullscreen, enter, exit, toggle }
}
