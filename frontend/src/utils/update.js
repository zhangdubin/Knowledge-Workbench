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

/**
 * 去掉版本号里的 v 前缀与空白
 *
 * 为什么需要：目标版本来自 git tag（"v0.6.9"），
 * 运行版本来自后端接口（"0.6.9"）—— 指的是同一个版本，
 * 但字符串不相等。两边各写一份「去掉 v」的逻辑，
 * 早晚有一处漏掉，于是「明明升好了」被说成「升级没生效」。
 */
export function normVersion(v) {
  return String(v == null ? '' : v).trim().replace(/^v/i, '')
}

/**
 * 两个版本号是不是同一个版本
 *
 * 拿不到版本号时一律判「不同」——
 * 「不知道」不能当成「一样」，否则界面会为一个没核对过的状态报成功。
 *
 * @param {string} a
 * @param {string} b
 * @returns {boolean}
 */
export function sameVersion(a, b) {
  const na = normVersion(a)
  const nb = normVersion(b)
  if (!na || !nb) return false
  return na === nb
}

/**
 * 版本没对上时给用户看的一句话
 *
 * 为什么要统一：升级弹窗与侧栏版本核对是两条不同的路径，
 * 但它们要回答的是同一个问题 —— 「现在跑的到底是不是新版本」。
 * 两处措辞不一致，用户会以为系统自相矛盾。
 *
 * @param {string} running 现在运行的版本
 * @param {string} target  期望的版本
 * @returns {string}
 */
export function versionMismatchText(running, target) {
  const r = normVersion(running)
  const t = normVersion(target)
  if (!r) return '无法确认当前运行的版本号'
  if (!t) return `当前运行版本 v${r}`
  return `当前运行版本 v${r}，期望 v${t}`
}

/**
 * 服务端核验结论里的「层」。
 *
 * 为什么要有层：以前界面只能说「升级没有真正生效，请检查日志」——
 * 而日志在容器里，用户多半看不到，也看不懂。
 * 现在后端自己看得到镜像、容器与源码，于是能说清
 * 「**是哪一层**没换成功」，每一层的处置办法完全不同：
 *   source    —— 源码没换：目标 tag 里的代码就不是这一版
 *   image     —— 镜像没换：镜像里装的还是旧版本
 *   container —— 容器没重建：镜像是对的，容器还在跑旧的
 *   cache     —— 缓存没刷新：拿到的还是旧响应
 */
export const VERIFY_LAYER = {
  OK: 'ok',
  SOURCE: 'source',
  IMAGE: 'image',
  CONTAINER: 'container',
  CACHE: 'cache',
}

/** 每一层的中文说法（给用户看的那一句） */
export const VERIFY_LAYER_TEXT = {
  ok: '升级已生效',
  source: '源码没换（目标 tag 里的代码不是这一版）',
  image: '镜像没换（镜像里装的还是旧版本）',
  container: '容器没重建（镜像是对的，容器还在跑旧的）',
  cache: '缓存没刷新（拿到的还是旧响应）',
}

/**
 * 把服务端的核验结论渲染成一句能照着做的话
 *
 * 为什么要有这个函数：核验在后端做（它才看得见镜像与容器），
 * 但话要说给用户听。老后端没有这个接口时退回原来那套说法 ——
 * 宁可少给点信息，也不能让界面空着。
 *
 * @param {object} verify 后端 /api/system/update/verify 的返回
 * @param {string} running 兜底：当前运行版本
 * @param {string} target  兜底：目标版本
 * @returns {string} 空串表示核验通过（没有需要说的话）
 */
export function verifyFailureText(verify, running = '', target = '') {
  if (!verify || typeof verify !== 'object') {
    // 老后端没有核验接口 → 退回原来的说法
    if (!running || !target) return ''
    return '服务已恢复，但'
      + versionMismatchText(running, target)
      + ' —— 升级没有真正生效。'
      + '请检查 docker compose logs backend 与镜像标签是否换成功。'
  }
  if (verify.ok) return ''
  const r = normVersion(verify.running || running)
  const t = normVersion(verify.target || target)
  const head = (r && t)
    ? `服务已恢复，但${versionMismatchText(r, t)} —— 升级没有真正生效。`
    : '服务已恢复，但拿不到运行版本号 —— 升级可能没有真正生效。'
  const parts = [head]
  const layer = String(verify.layer || '')
  const layerText = VERIFY_LAYER_TEXT[layer]
  if (layerText && layer !== VERIFY_LAYER.OK) parts.push(layerText + '。')
  const reason = String(verify.reason || '')
  if (reason) parts.push(reason + '。')
  const cmds = Array.isArray(verify.commands)
    ? verify.commands.filter((c) => typeof c === 'string' && c.trim())
    : []
  if (cmds.length) {
    parts.push('请在服务器上执行：\n' + cmds.map((c) => '  ' + c).join('\n'))
  } else if (verify.fix) {
    parts.push('下一步：' + verify.fix)
  }
  return parts.join('')
}

/**
 * 判断「拿到的是不是缓存里的旧响应」
 *
 * 为什么要单独判：后端核验说「跑的是目标版本」，
 * 而 /api/health 报的还是另一版 —— 那两者之间隔着一层缓存
 * （浏览器、反代、CDN）。这时候版本其实已经对了，
 * 用户看到的还是旧号，提示必须说「刷新一下」而不是「升级失败」。
 *
 * @param {object} verify 服务端核验结论
 * @param {object} health /api/health 的响应体
 * @returns {string} 层的名字；不是缓存问题时返回空串
 */
export function detectCacheLayer(verify, health) {
  if (!verify || !verify.ok) return ''
  const hv = normVersion(health?.version || '')
  const vv = normVersion(verify.running || '')
  if (hv && vv && hv !== vv) return VERIFY_LAYER.CACHE
  return ''
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

/**
 * 把「升级计划里的步骤」拼成一句人话。
 *
 * 为什么要有这个：弹窗里原来那句「拉取版本 → 切换版本 → 重建镜像 → 重启服务」
 * 是写死的，可离线包部署走的根本不是这四步（是「下载镜像 → 导入镜像 → 重建容器」），
 * 写死的话用户看到的说明和实际发生的事对不上。
 *
 * @param {Array<{title?: string}>} steps 计划里的步骤
 * @returns {string} 形如「下载镜像 → 导入镜像 → 重建容器」；没有步骤时返回空串
 */
export function planSummary(steps) {
  if (!Array.isArray(steps)) return ''
  const titles = steps.map((s) => (s && s.title ? String(s.title).trim() : '')).filter(Boolean)
  return titles.join(' → ')
}

/**
 * 资产大小的人类可读写法。
 *
 * @param {number} bytes 字节数
 * @returns {string} 形如「91 MB」；没有大小信息时返回空串
 */
export function assetSize(bytes) {
  const n = Number(bytes)
  if (!Number.isFinite(n) || n <= 0) return ''
  if (n >= 1024 * 1024) return `${Math.round(n / 1024 / 1024)} MB`
  if (n >= 1024) return `${Math.round(n / 1024)} KB`
  return `${Math.round(n)} B`
}

/**
 * 这套部署形态支不支持自动升级。
 *
 * 后端没给这个字段时按「支持」处理 —— 老版本后端不返回它，
 * 但那时也只有源码部署一条路，不支持就没意义了。
 *
 * @param {object} plan 升级计划
 * @returns {boolean}
 */
export function autoUpgradeSupported(plan) {
  if (!plan || typeof plan !== 'object') return true
  return plan.auto_upgrade_supported !== false
}

/**
 * 从计划里取出「在宿主机上执行就能开启自动升级」的命令。
 *
 * 跟手动升级命令不是一回事：手动命令是「这次怎么升」，
 * 开启命令是「把自动升级这个能力装上」，装好之后每次升级都不用再跑命令。
 *
 * @param {object} plan 升级计划
 * @returns {string[]}
 */
export function enableCommands(plan) {
  if (!plan || !Array.isArray(plan.enable_commands)) return []
  return plan.enable_commands.filter((c) => typeof c === 'string' && c.trim())
}

/**
 * 计划是不是「当前已是最新版本，没有可升的东西」。
 *
 * 为什么单独拎出来：弹窗一上来如果就是「当前环境不能自动升级」
 * 加一串障碍，读起来像系统坏了 —— 其实只是没有更新的版本而已。
 * 所以要先说「已是最新」，再把障碍说成「为下次升级做准备」。
 *
 * 注意必须要有 target 才算「已是最新」：
 * 查不到目标版本时后端会返回 has_update=false，
 * 但那是「不知道有没有新版」，不是「确认没有新版」——
 * 这两种情况不能混，否则会把「查不到」说成「已是最新」。
 *
 * @param {object} plan 升级计划
 * @returns {boolean}
 */
export function isLatestPlan(plan) {
  if (!plan || typeof plan !== 'object') return false
  if (!plan.target) return false
  return plan.has_update === false
}
