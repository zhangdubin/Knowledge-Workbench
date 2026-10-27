/**
 * 设计系统纯函数单测
 *
 * 背景：弹窗尺寸档位、表格密度、空态图标大小这些规则，
 * 如果只写在 .vue 里，就只能靠人肉记住「sm 是 420 还是 480」。
 * 抽成纯函数之后，这里把档位表钉死 —— 以后谁想改宽度，
 * 先看这个测试，就会知道会影响到哪些页面。
 */
import assert from 'node:assert/strict'
import {
  cx,
  dialogWidth,
  tableDensityClass,
  emptyIconSize,
  DIALOG_SIZES,
  DIALOG_SIZE_LIST,
  TABLE_DENSITIES,
  EMPTY_ICON_SIZES,
} from '../src/utils/ui.js'

let n = 0
const eq = (a, b, msg) => { assert.deepEqual(a, b, msg); n++ }
const ok = (v, msg) => { assert.ok(v, msg); n++ }

// ---------- DIALOG_SIZES ----------
eq(DIALOG_SIZE_LIST, ['sm', 'md', 'lg', 'xl'], '弹窗四档尺寸齐全')
eq(DIALOG_SIZES.sm, 420, 'sm 档宽度')
eq(DIALOG_SIZES.md, 560, 'md 档宽度')
eq(DIALOG_SIZES.lg, 760, 'lg 档宽度')
eq(DIALOG_SIZES.xl, 1040, 'xl 档宽度')
// 档位必须单调递增，否则「比 md 大的档」会反而更窄
for (let i = 1; i < DIALOG_SIZE_LIST.length; i++) {
  ok(
    DIALOG_SIZES[DIALOG_SIZE_LIST[i]] > DIALOG_SIZES[DIALOG_SIZE_LIST[i - 1]],
    `${DIALOG_SIZE_LIST[i]} 比 ${DIALOG_SIZE_LIST[i - 1]} 宽`,
  )
}

// ---------- dialogWidth ----------
eq(dialogWidth('sm'), '420px', '按档位取宽度')
eq(dialogWidth('md'), '560px', 'md 档默认宽度')
eq(dialogWidth('xl'), '1040px', 'xl 档宽度')
eq(dialogWidth('md', 800), '800px', '数字宽度按 px 处理')
eq(dialogWidth('md', '50%'), '50%', '字符串宽度原样保留')
eq(dialogWidth('md', ''), '560px', '空宽度回落到档位')
eq(dialogWidth('md', null), '560px', 'null 宽度回落到档位')
eq(dialogWidth('md', undefined), '560px', 'undefined 宽度回落到档位')
// 非法档位不能崩，回落到 md
eq(dialogWidth('xxl'), '560px', '未知档位回落到 md')
eq(dialogWidth(), '560px', '不传档位时用 md')
eq(dialogWidth('md', 0), '0px', '0 是合法宽度（不是缺省）')

// ---------- TABLE_DENSITIES ----------
eq(TABLE_DENSITIES, ['compact', 'default', 'comfortable'], '表格三档密度')
eq(tableDensityClass('compact'), 'table-density-compact', '紧凑密度类名')
eq(tableDensityClass('default'), 'table-density-default', '默认密度类名')
eq(tableDensityClass('comfortable'), 'table-density-comfortable', '宽松密度类名')
eq(tableDensityClass('unknown'), 'table-density-default', '未知密度回落到 default')
eq(tableDensityClass(), 'table-density-default', '不传密度时用 default')

// ---------- emptyIconSize ----------
eq(emptyIconSize('sm'), EMPTY_ICON_SIZES.sm, '小号图标尺寸')
eq(emptyIconSize('lg'), EMPTY_ICON_SIZES.lg, '大号图标尺寸')
eq(emptyIconSize('md'), EMPTY_ICON_SIZES.md, '中号图标尺寸')
eq(emptyIconSize(40), 40, '数字尺寸原样使用')
eq(emptyIconSize('huge'), EMPTY_ICON_SIZES.md, '未知档位回落到 md')
eq(emptyIconSize(), EMPTY_ICON_SIZES.md, '不传时用 md')
eq(emptyIconSize(0), EMPTY_ICON_SIZES.md, '0 不是合法尺寸')
// 图标不能大到把空态撑破
ok(emptyIconSize('lg') <= 96, '图标尺寸有上限')

// ---------- cx ----------
eq(cx('a', 'b'), 'a b', '两个字符串')
eq(cx('a', false, 'b'), 'a b', 'false 被丢掉')
eq(cx('a', null, undefined, ''), 'a', '空值被丢掉')
eq(cx('a', ['b', 'c']), 'a b c', '数组递归展开')
eq(cx('a', { b: true, c: false }), 'a b', '对象按真值取 key')
eq(cx(), '', '空参数得到空串')
eq(cx(null, undefined, false), '', '全是空值得到空串')
eq(cx('a', 0), 'a 0', '0 是合法 class 名，要保留')
eq(cx({ 'is-active': true, 'is-disabled': false }), 'is-active', '单个对象')
// 结果里不能有连续空格，否则 class 字符串会很难看
ok(!/\s\s/.test(cx('a', false, 'b')), '结果里没有连续空格')

console.log(`✅ 设计系统纯函数 ${n} 项断言全部通过`)
