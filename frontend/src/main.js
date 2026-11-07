import { createApp } from 'vue'
import { createPinia } from 'pinia'
// Element Plus 的基础样式（:root 上的那套 CSS 变量 + 过渡类 + .el-icon）
// 组件样式由构建器按需引入（见 vite.config.js），
// 这里必须留 base.css —— 变量少了，页面颜色会全乱。
import 'element-plus/theme-chalk/base.css'
import 'element-plus/theme-chalk/dark/css-vars.css'

// Element Plus 的「命令式」组件：它们只出现在 JS 里，模板里一个都没有。
//
// 为什么必须在这里手动引样式：
//   vite.config.js 里的 ElementPlusResolver 是**扫模板**的 ——
//   模板里写了 <el-xxx> 才把它的样式带进包。
//   而 ElMessage / ElMessageBox 是这么用的：
//       import { ElMessage, ElMessageBox } from 'element-plus'
//       ElMessage.success('保存成功')
//   模板里找不到它们，扫不到，样式就不进包。
//
// 漏了会怎样（真踩过）：
//   样式没进包 → .el-message-box 身上一条 background 规则都没有，
//   确认框就成了一块**透明**的浮层，字飘在灰色遮罩上看不清；
//   ElMessage 的提示条则没有 fixed 定位、没有图标样式，
//   顶在正文里跑，像页面多长了一段字。
//
// 只影响样式，不影响功能（所以更难被发现 —— 弹窗照样弹，只是看不见）。
// 以后再用到别的命令式组件，记得往这下面加一行。
import 'element-plus/theme-chalk/el-message.css'
import 'element-plus/theme-chalk/el-message-box.css'

// 统一弹窗按钮文案（默认中文）。
// 引入这个模块就完成打补丁，必须在挂载应用之前执行 ——
// 里面的实现见 utils/feedback.js 的注释。
import './utils/feedback.js'

import App from './App.vue'
import router from './router'
import './styles/main.css'
// 手机端排版规则要排在 main.css 之后：层叠看的是源码顺序，
// 放前面会被 main.css 里同名的手机规则压住
// （CSS 的 @import 只能写在文件最前面，Vite 会把它内联到开头，所以没法用 @import）
import './styles/mobile.css'
import { initTheme } from './utils/theme'

// 在挂载前定主题，避免暗色用户先看到一帧白屏
initTheme()

const app = createApp(App)
app.use(createPinia())
app.use(router)
// Element Plus 不再整包注册（app.use(ElementPlus)）：
// 整包注册会把整个库（含没用到的组件和方法）都打进主包。
// 现在由构建器按模板里真正用到的组件自动引入（见 vite.config.js），
// 不用维护清单，也不会漏。

// ============================================================
// 图标：只注册项目里真的用到的那些
//
// 为什么不能整包注册：
//   @element-plus/icons-vue 有 2900 多个图标，
//   `import * as Icons` 再全量注册，会把每一个图标都打进主包 ——
//   实测主包 1256kB（gzip 404kB）里有相当一部分是根本用不到的图标。
//   只注册用到的 92 个，图标这块的体积降一个数量级。
//
// 怎么维护：
//   新增图标时把名字加进这个清单（模板里 <el-icon><名字 /></el-icon> 用到的
//   必须在这里注册，否则页面上那个图标位置是空的）；
//   组件里具名 import 的图标不用登记。
//   跑 `python3 scripts/list-icons.py` 可以重新扫一遍清单。
// ============================================================
import {
  Aim, ArrowDown, ArrowLeft, ArrowRight, Back, Bell, Box, Brush,
  CaretRight, Check, CircleCheck, CircleCheckFilled, CircleCloseFilled,
  Clock, Close, Coin, Collection, Compass, Connection, CopyDocument,
  DataAnalysis, DataBoard, DataLine, Delete, Document, DocumentRemove,
  Download, Edit, EditPen, Files, Filter, FirstAidKit, Folder, FolderAdd,
  FolderOpened, FullScreen, Grid, Headset, Histogram, HomeFilled,
  InfoFilled, Key, Lightning, Link, List, Loading, Lock, MagicStick, Memo,
  Menu, Monitor, Moon, MoreFilled, Notebook, Odometer, Operation, Paperclip,
  Picture, PieChart, Plus, Pointer, Postcard, PriceTag, Printer, Promotion,
  QuestionFilled, Rank, Reading, Refresh, RefreshLeft, RefreshRight, Right,
  Search, Select, SetUp, Setting, Share, StarFilled, Sunny, SwitchButton, Tools,
  Top, TrendCharts, TrophyBase, Upload, UploadFilled, User, UserFilled,
  VideoPlay, View, Warning, WarningFilled, ZoomIn, ZoomOut
} from '@element-plus/icons-vue'

const ICONS = {
  Aim, ArrowDown, ArrowLeft, ArrowRight, Back, Bell, Box, Brush, CaretRight, Check, CircleCheck, CircleCheckFilled, CircleCloseFilled, Clock, Close, Coin, Collection, Compass, Connection, CopyDocument, DataAnalysis, DataBoard, DataLine, Delete, Document, DocumentRemove, Download, Edit, EditPen, Files, Filter, FirstAidKit, Folder, FolderAdd, FolderOpened, FullScreen, Grid, Headset, Histogram, HomeFilled, InfoFilled, Key, Lightning, Link, List, Loading, Lock, MagicStick, Memo, Menu, Monitor, Moon, MoreFilled, Notebook, Odometer, Operation, Paperclip, Picture, PieChart, Plus, Pointer, Postcard, PriceTag, Printer, Promotion, QuestionFilled, Rank, Reading, Refresh, RefreshLeft, RefreshRight, Right, Search, Select, SetUp, Setting, Share, StarFilled, Sunny, SwitchButton, Tools, Top, TrendCharts, TrophyBase, Upload, UploadFilled, User, UserFilled, VideoPlay, View, Warning, WarningFilled, ZoomIn, ZoomOut,
}

for (const [key, comp] of Object.entries(ICONS)) {
  app.component(key, comp)
}

// 把 Vue 的警告变成看得见的错误
//
// 为什么：Vue 对「组件解析不到」「prop 校验不过」这类问题只打一条 warning，
// 编译期不报错、页面照常渲染 —— 于是这类错误能悄悄活很久：
// 踩过两次 —— 「使用指南」漏 import PageTitle，整页页头空白；
// 「回收站/导航管理」的图标名不在白名单里，两个页面显示成同一个图标。
// 两次都是用户先觉得「页面怪怪的」，而不是我们先看到报错。
//
// 所以这里把这两类警告升级成 console.error：它们在开发期一定会被看到。
app.config.warnHandler = (msg, instance, trace) => {
  const isResolveFail = /Failed to resolve component/.test(msg)
  const isPropInvalid = /Invalid prop/.test(msg)
  if (isResolveFail || isPropInvalid) {
    console.error(`[Vue] ${msg}${trace}`)
    return
  }
  console.warn(`[Vue] ${msg}${trace}`)
}

app.mount('#app')