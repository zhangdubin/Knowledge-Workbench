/**
 * 浏览器端触发一次文本文件下载
 *
 * 用 Blob + 临时 <a download> 而不是走后端导出接口：内容已经在手上，
 * 再绕一圈服务端既慢又要在后端拼 Content-Disposition。
 * 用完必须 revokeObjectURL，否则 Blob 会一直挂在内存里直到页面刷新。
 */
export function downloadText(filename, text, mime = 'application/json') {
  const url = URL.createObjectURL(new Blob([text], { type: `${mime};charset=utf-8` }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  // revoke 放在下一个事件循环：Safari 上同步 revoke 会让下载拿不到内容
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

/** 文件名安全化：模型 key 理论上只有字母数字下划线，但用户可能手输中文/斜杠 */
export function safeFileName(name) {
  return String(name || 'model').replace(/[\\/:*?"<>|\s]+/g, '_').slice(0, 80)
}
