import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'

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
app.use(ElementPlus)

for (const [key, comp] of Object.entries(ElementPlusIconsVue)) {
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