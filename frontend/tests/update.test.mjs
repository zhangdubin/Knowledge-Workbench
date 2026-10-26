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

console.log(`✅ 升级指引 ${n} 项断言全部通过`)
