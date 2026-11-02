/**
 * 打印小工具
 *
 * 为什么要有这个文件：
 *   打印这件事有三个坑，散在各个页面里各写一遍，一定会各写错一遍：
 *   1) 空页面 —— 没有内容时打出来是一张白纸，用户以为程序坏了；
 *   2) el-table 的表头 —— 表头在另一个 table 里，浏览器不会每页重复它；
 *   3) 打印时间 —— 只有真要打印的那一刻才算数，
 *      页面挂载时算好的时间会骗人（用户可能开着页面看了一下午）。
 *
 * 打印样式不在这里 —— 那是全局的一份（styles/print.css），
 * 这里只管「打印前做什么、打印后还原什么」。
 */
import { ElMessage } from 'element-plus'

/** 页面里标「这块是要打印的正文」的属性 */
export const PRINT_ROOT_ATTR = 'data-print-root'
/** 页面里标「这块只在打印时出现」的属性 */
export const PRINT_ONLY_ATTR = 'data-print-only'
/** 页面里标「这块不要打印」的属性 */
export const PRINT_HIDE_ATTR = 'data-print-hide'
/** 打印按钮的标记（验收脚本靠它找按钮） */
export const PRINT_TRIGGER_ATTR = 'data-print-trigger'

/** 找出页面上所有「要打印的正文」区域 */
export function findPrintRoots() {
  if (typeof document === 'undefined') return []
  return Array.from(document.querySelectorAll('[' + PRINT_ROOT_ATTR + ']'))
}

/**
 * 这个区域有没有可打印的内容
 *
 * 判定方法（从便宜到贵）：
 *   1) 页面自己说了「这里是空的」（data-print-empty="true"）→ 直接判空；
 *   2) 区域里有没有能看懂的文字 → 有就能打。
 *
 * 为什么不看「元素个数」：一个只有图标和占位的空壳照样会被打印出来，
 * 打出来还是白纸 —— 用户看到的是「打了但什么都没有」。
 */
export function hasPrintableContent(root) {
  if (!root) return false
  if (root.getAttribute && root.getAttribute('data-print-empty') === 'true') return false
  const text = (root.innerText || root.textContent || '').replace(/\s+/g, ' ').trim()
  return text.length > 0
}

/**
 * 给 el-table 造一个真正的 thead
 *
 * 为什么：
 *   浏览器要「每页重复表头」，要求表头在表体同一个 table 的 thead 里。
 *   Element Plus 把表头放在另一个 table（.el-table__header-wrapper）里，
 *   所以直接打印 = 表头只出现在第一页，后面几页全是没头的行。
 *   这里在打印前把表头克隆一份塞进表体的 thead，打印完再撤掉，
 *   页面照常能用（表头还是原来那份）。
 *
 * 注意固定列：el-table 的固定列是另外浮在表体上的一层，
 * 打印时已经由 print.css 藏掉了，否则会重影。
 */
function prepareTablesForPrint() {
  const restores = []
  if (typeof document === 'undefined') return () => {}

  document.querySelectorAll('.el-table').forEach((tbl) => {
    const headTable = tbl.querySelector('.el-table__header-wrapper table')
    const bodyTable = tbl.querySelector('.el-table__body-wrapper table')
    if (!headTable || !bodyTable) return
    // 已经有 thead 的（原生表格）不用管，浏览器自己会重复
    if (bodyTable.querySelector('thead')) return

    const headRow = headTable.querySelector('thead tr') || headTable.querySelector('tr')
    if (!headRow) return

    const thead = document.createElement('thead')
    thead.setAttribute('data-print-thead', '1')
    thead.appendChild(headRow.cloneNode(true))
    bodyTable.insertBefore(thead, bodyTable.firstChild)

    // 原来的表头要藏起来，不然纸上会出现两个表头
    const wrap = tbl.querySelector('.el-table__header-wrapper')
    if (wrap) wrap.setAttribute(PRINT_HIDE_ATTR, '1')

    restores.push(() => {
      if (thead.parentNode) thead.parentNode.removeChild(thead)
      if (wrap) wrap.removeAttribute(PRINT_HIDE_ATTR)
    })
  })

  return () => { restores.forEach((fn) => { try { fn() } catch { /* 页面已经卸载了就算了 */ } }) }
}

/** 把「打印时间」填上 —— 只有真的要打印时才填 */
function stampPrintTime() {
  const now = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  const text = now.getFullYear() + '-' + pad(now.getMonth() + 1) + '-' + pad(now.getDate())
    + ' ' + pad(now.getHours()) + ':' + pad(now.getMinutes())
  document.querySelectorAll('[data-print-time]').forEach((el) => {
    el.textContent = '打印时间：' + text
  })
}

/**
 * 打印当前页面
 *
 * 返回 true = 真的调起了打印；false = 页面是空的，什么都没打。
 */
export function printPage(options = {}) {
  const roots = options.root ? [options.root] : findPrintRoots()
  const empty = roots.length === 0 || roots.every((r) => !hasPrintableContent(r))
  if (empty) {
    // 空白纸最伤：用户以为程序坏了，还以为打印机有问题。
    // 说清楚「没有可打印的内容」，比默默打一张白纸强。
    ElMessage.warning('没有可打印的内容')
    return false
  }

  stampPrintTime()
  const restore = prepareTablesForPrint()
  try {
    window.print()
  } finally {
    // window.print 在多数浏览器里是同步阻塞的，afterprint 不一定触发，
    // 所以两都做：谁先到谁还原。
    window.addEventListener('afterprint', restore, { once: true })
    setTimeout(restore, 800)
  }
  return true
}
