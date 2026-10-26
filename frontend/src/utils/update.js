/**
 * 升级指引相关的小工具（纯函数，便于单测）。
 *
 * 为什么需要按版本分支：
 * 升级脚本 `scripts/upgrade.sh` 是 v0.4.0 才进仓库的。旧版本的前端里
 * 根本没有这个文件，如果提示里写死 "./scripts/upgrade.sh"，
 * 用户照着做只会得到 "No such file or directory" ——
 * 恰好是踩坑的人最需要正确指引的时刻，却给了条跑不通的命令。
 */

/** 解析版本号 → [主, 次, 修]；解析不出来返回 null */
export function parseVersion(v) {
  // 允许带 v 前缀：GitHub 的 tag 就是 "v0.4.1" 这种写法
  const m = /^v?(\d+)\.(\d+)(?:\.(\d+))?/.exec(String(v || ''))
  if (!m) return null
  return [Number(m[1]), Number(m[2]), Number(m[3] || 0)]
}

/** 升级脚本从哪个版本起才随仓库提供 */
export const UPGRADE_SCRIPT_SINCE = [0, 4, 0]

/** 当前版本是否自带升级脚本 */
export function hasUpgradeScript(current) {
  const p = parseVersion(current)
  if (!p) return false
  for (let i = 0; i < 3; i++) {
    if (p[i] < UPGRADE_SCRIPT_SINCE[i]) return false
    if (p[i] > UPGRADE_SCRIPT_SINCE[i]) return true
  }
  return true
}

/**
 * 给用户复制用的升级命令。
 * 有脚本就一键升级，没有就退回手动切 tag 的命令（任何版本都能跑）。
 */
export function upgradeCommand(current, latest) {
  if (hasUpgradeScript(current)) return './scripts/upgrade.sh'
  const tag = latest || 'v<版本号>'
  return `git fetch origin --tags && git checkout ${tag} && docker compose build && docker compose up -d`
}

/** 升级说明的一句话提示 */
export function upgradeTip(current) {
  if (hasUpgradeScript(current)) {
    return '脚本会自动拉取最新 tag → 备份 .env → 切换版本 → 重建镜像 → 健康检查，失败自动回滚。'
  }
  return '当前版本还没有升级脚本（v0.4.0 起才附带），先用上面的命令手动升级；升到 v0.4.0 及以上后，后续就能一键升级了。'
}
