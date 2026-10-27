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
 * 部署模式。
 *
 * 为什么必须区分：
 * 两种部署形态的升级方式根本不同，但升级面板只有一份文案。
 * 离线包安装的机器上**没有 git**（很多人是直接下载压缩包解压部署的），
 * 给它 "git fetch origin --tags && git checkout ..." 只会得到
 * "git: command not found" —— 而这恰恰是用户最需要正确指引的时刻。
 */
export const DEPLOY_MODE = {
  /** 源码部署：目录里有 .git，编排文件带 build:，能自己拉代码重建 */
  GIT: 'git',
  /** 离线包部署：机器上只有镜像与编排文件，靠新离线包替换镜像 */
  OFFLINE: 'offline',
}

/**
 * 给用户复制用的升级命令。
 *
 * @param {string} current  当前版本
 * @param {string} latest   目标版本（可空）
 * @param {string} mode     部署模式，见 DEPLOY_MODE
 */
export function upgradeCommand(current, latest, mode = DEPLOY_MODE.GIT) {
  if (mode === DEPLOY_MODE.OFFLINE) {
    // 离线包里自带 install.sh，升级就是重跑它：保留 .env 与数据，导入新镜像后重建容器
    return 'bash install.sh -d <安装目录>'
  }
  if (hasUpgradeScript(current)) return './scripts/upgrade.sh'
  const tag = latest || 'v<版本号>'
  return `git fetch origin --tags && git checkout ${tag} && docker compose build && docker compose up -d`
}

/** 升级说明的一句话提示 */
export function upgradeTip(current, mode = DEPLOY_MODE.GIT) {
  if (mode === DEPLOY_MODE.OFFLINE) {
    return '当前是离线包部署：下载新版离线安装包并解压，然后执行上面的命令。安装脚本会保留 .env 与全部数据，导入新镜像后重建容器。'
  }
  if (hasUpgradeScript(current)) {
    return '脚本会自动拉取最新 tag → 备份 .env → 切换版本 → 重建镜像 → 健康检查，失败自动回滚。'
  }
  return '当前版本还没有升级脚本（v0.4.0 起才附带），先用上面的命令手动升级；升到 v0.4.0 及以上后，后续就能一键升级了。'
}
