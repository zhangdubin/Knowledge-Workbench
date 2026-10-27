/**
 * 升级指引的版本分支（纯函数单测）
 *
 * 背景：升级脚本 scripts/upgrade.sh 是 v0.4.0 才进仓库的。
 * 旧版本的前端提示里若写死这条命令，用户照做只会得到
 * "No such file or directory" —— 正是踩坑的人最需要指引的时刻。
 */
import assert from 'node:assert/strict'
import {
  parseVersion,
  hasUpgradeScript,
  upgradeCommand,
  upgradeTip,
  UPGRADE_SCRIPT_SINCE,
  DEPLOY_MODE,
} from '../src/utils/update.js'

let n = 0
const eq = (a, b, msg) => { assert.deepEqual(a, b, msg); n++ }
const ok = (v, msg) => { assert.ok(v, msg); n++ }

// ---------- parseVersion ----------
eq(parseVersion('0.4.1'), [0, 4, 1], '三段版本号')
eq(parseVersion('1.0'), [1, 0, 0], '缺省修订号补 0')
eq(parseVersion('v2.10.3'), [2, 10, 3], '带 v 前缀也能解析')
eq(parseVersion('0.3.4'), [0, 3, 4], 'v0.3.4')
eq(parseVersion(''), null, '空串解析不出来')
eq(parseVersion(null), null, 'null 解析不出来')
eq(parseVersion('abc'), null, '非版本号解析不出来')
eq(parseVersion(undefined), null, 'undefined 解析不出来')

// ---------- hasUpgradeScript ----------
ok(Array.isArray(UPGRADE_SCRIPT_SINCE), '起点版本是数组')
eq(hasUpgradeScript('0.3.4'), false, 'v0.3.4 没有升级脚本')
eq(hasUpgradeScript('0.4.0'), true, 'v0.4.0 起有升级脚本')
eq(hasUpgradeScript('0.4.1'), true, 'v0.4.1 有升级脚本')
eq(hasUpgradeScript('1.0.0'), true, 'v1.0.0 有升级脚本')
eq(hasUpgradeScript('0.5.0'), true, 'v0.5.0 有升级脚本')
eq(hasUpgradeScript('0.2.9'), false, '更早的版本没有')
eq(hasUpgradeScript(''), false, '版本号拿不到时不谎称有脚本')
eq(hasUpgradeScript('x.y.z'), false, '版本号是脏数据时不谎称有脚本')

// ---------- upgradeCommand ----------
eq(
  upgradeCommand('0.3.4', 'v0.4.1'),
  'git fetch origin --tags && git checkout v0.4.1 && docker compose build && docker compose up -d',
  '旧版本给手动切 tag 的命令',
)
eq(
  upgradeCommand('0.4.1', 'v0.4.2'),
  './scripts/upgrade.sh',
  '新版本给一键升级命令',
)
ok(
  upgradeCommand('0.3.4', '').includes('v<版本号>'),
  '没有目标 tag 时给占位符',
)
ok(
  upgradeCommand('0.3.4', 'v0.4.1').includes('docker compose build'),
  '手动命令要包含重建镜像这一步',
)
ok(
  !upgradeCommand('0.3.4', 'v0.4.1').includes('upgrade.sh'),
  '旧版本绝不能提示跑 upgrade.sh（那文件不在旧代码里）',
)

// ---------- upgradeTip ----------
ok(upgradeTip('0.4.1').includes('回滚'), '新版本提示里说明有回滚')
ok(upgradeTip('0.3.4').includes('手动升级'), '旧版本提示改走手动升级')
ok(!upgradeTip('0.3.4').includes('失败自动回滚'), '旧版本别承诺回滚（没有脚本）')

// ---------- 部署模式 ----------
// 离线包部署的机器上没有 git，给它 git 命令只会得到 "git: command not found"
ok(
  !upgradeCommand('0.4.2', 'v0.5.0', DEPLOY_MODE.OFFLINE).includes('git '),
  '离线包部署绝不能提示 git 命令',
)
ok(
  upgradeCommand('0.4.2', 'v0.5.0', DEPLOY_MODE.OFFLINE).includes('install.sh'),
  '离线包部署提示走安装脚本',
)
ok(
  upgradeCommand('0.3.4', 'v0.5.0', DEPLOY_MODE.OFFLINE).includes('install.sh'),
  '离线包部署时旧版本也走安装脚本（没有 upgrade.sh 这回事）',
)
ok(
  upgradeTip('0.4.2', DEPLOY_MODE.OFFLINE).includes('离线包'),
  '离线包部署的提示要说明是离线包升级',
)
ok(
  !upgradeTip('0.4.2', DEPLOY_MODE.OFFLINE).includes('回滚'),
  '离线包安装脚本没有回滚机制，别承诺',
)
ok(
  upgradeCommand('0.4.2', 'v0.5.0', DEPLOY_MODE.GIT) === './scripts/upgrade.sh',
  '源码部署的默认行为不变',
)
ok(
  upgradeCommand('0.4.2', 'v0.5.0').includes('upgrade.sh'),
  '不传模式时默认按源码部署处理',
)

console.log(`✅ 升级指引 ${n} 项断言全部通过`)

// ============ v0.5.1：一键升级弹窗的纯函数 ============
{
  const { planSummary, assetSize, autoUpgradeSupported, enableCommands } = await import('../src/utils/update.js')

  // 步骤摘要
  assert.equal(planSummary([]), '', '没有步骤时摘要为空')
  assert.equal(planSummary(undefined), '', '传入 undefined 不应崩')
  assert.equal(
    planSummary([{ title: '拉取远端 tag' }, { title: '切换到目标版本' }]),
    '拉取远端 tag → 切换到目标版本',
    '步骤应按顺序拼成一句话'
  )
  assert.equal(
    planSummary([{ title: '下载镜像' }, { title: '' }, { title: '导入镜像' }]),
    '下载镜像 → 导入镜像',
    '空标题的步骤应被跳过'
  )

  // 资产大小
  assert.equal(assetSize(0), '', '0 应返回空串')
  assert.equal(assetSize(undefined), '', 'undefined 应返回空串')
  assert.equal(assetSize(-1), '', '负数应返回空串')
  assert.equal(assetSize(512), '512 B', '字节')
  assert.equal(assetSize(1024 * 40), '40 KB', 'KB')
  assert.equal(assetSize(1024 * 1024 * 91), '91 MB', 'MB')

  // 自动升级支持性
  assert.equal(autoUpgradeSupported(null), true, '老后端不返回该字段时按支持处理')
  assert.equal(autoUpgradeSupported({}), true, '空计划按支持处理')
  assert.equal(autoUpgradeSupported({ auto_upgrade_supported: false }), false, '明确不支持时要认')
  assert.equal(autoUpgradeSupported({ auto_upgrade_supported: true }), true, '明确支持时要认')

  // 开启命令
  assert.deepEqual(enableCommands(null), [], '没有计划时为空数组')
  assert.deepEqual(enableCommands({}), [], '计划里没有该字段时为空数组')
  assert.deepEqual(
    enableCommands({ enable_commands: ['bash enable.sh', '  ', 'docker ps'] }),
    ['bash enable.sh', 'docker ps'],
    '空字符串应被剔除'
  )
  console.log('\n✅ 一键升级弹窗纯函数断言全部通过')
}

// ============ v0.6.1：「已是最新版本」的判定 ============
// 为什么要单独判：弹窗一上来就是「当前环境不能自动升级」+ 一串障碍，
// 读起来像系统坏了 —— 其实只是没有更新的版本而已。
{
  const { isLatestPlan } = await import('../src/utils/update.js')

  assert.equal(
    isLatestPlan({ target: 'v0.6.0', current: '0.6.0', has_update: false }),
    true,
    '当前版本 == 目标版本 ⇒ 已是最新',
  )
  assert.equal(
    isLatestPlan({ target: 'v0.7.0', current: '0.6.0', has_update: true }),
    false,
    '有新版 ⇒ 不是最新',
  )
  assert.equal(
    isLatestPlan({ target: '', has_update: false }),
    false,
    '查不到目标版本时不能算「已是最新」（那是「不知道」不是「没有」）',
  )
  assert.equal(isLatestPlan({ has_update: false }), false, '没有 target ⇒ 不是最新')
  assert.equal(isLatestPlan(null), false, '空计划 ⇒ 不是最新')
  assert.equal(
    isLatestPlan({ target: 'v0.6.0' }),
    false,
    '没有 has_update 字段 ⇒ 按「不是最新」处理（别乱下结论）',
  )
  console.log('✅ 「已是最新版本」判定 6 项断言全部通过')
}
