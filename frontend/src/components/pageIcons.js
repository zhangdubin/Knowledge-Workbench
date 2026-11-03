// ============================================================
// 页面标题图标：只放页面真正用到的那几个
//
// 为什么不能整包取：
//   PageTitle 按名字动态取图标（icon-key="MagicStick"），
//   以前用 `import * as ElementPlusIcons` 整包拿 ——
//   命名空间是动态访问，rollup 没法摇树，
//   于是 @element-plus/icons-vue 的 2900 多个图标（未压缩 316kB）
//   全被打进主包，用户首屏白白多下几十 kB。
//
// 为什么这里放一份清单还不够（以前的坑）：
//   原来有一份 ICON_MAP + 一份 validator 数组，两处都得同步 ——
//   漏一处就静默回退成工作台图标，
//   踩过：回收站与导航管理两个页面的标题图标长得一模一样。
//   用户看到的是「图标一样」，不是「报错了」，比报错更难查。
//
// 现在怎么办：
//   这份清单只留一份；漏了会在**构建期**被验收脚本抓住
//   （scripts/verify-page-icons.py 扫全项目的 icon-key，
//     清单里没有就直接失败），不用等到用户看见。
// ============================================================
import {
  Coin, Compass, Connection, Cpu, DataBoard, DataLine, Delete, Document,
  Files, Grid, Lock, MagicStick, Menu, Monitor, Notebook, Search,
  Setting, Share, UserFilled, Odometer
} from '@element-plus/icons-vue'

/** 页面标题图标表：key 是页面里 icon-key 写的名字 */
export const PAGE_ICONS = {
  Coin, Compass, Connection, Cpu, DataBoard, DataLine, Delete, Document, Files, Grid, Lock, MagicStick, Menu, Monitor, Notebook, Search, Setting, Share, UserFilled,
}

/** 兜底图标：名字不认识时用它（但验收脚本会让这种漏配在构建期就暴露） */
export const FALLBACK_ICON = Odometer
