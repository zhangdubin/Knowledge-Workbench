/**
 * 统一「提示 / 确认」的按钮文案
 *
 * 为什么需要这个文件：
 *   Element Plus 的 ElMessageBox 在没显式传按钮文案时，
 *   默认显示英文的 "OK" / "Cancel"。
 *   本项目 18 个界面、33 处弹窗用的都是中文正文，
 *   弹出一半英文的按钮，看起来像漏了个别语言的组件。
 *
 * 为什么在入口统一兜底，而不是挨个改调用点：
 *   33 处调用点分布在 18 个文件里。逐个加 confirmButtonText 很容易漏，
 *   以后新加弹窗又得记得写一遍 —— 这种「靠记性维护」的事情迟早会漏。
 *   这里在应用入口打一次底：
 *     · 默认给中文；
 *     · 调用点**显式传了**按钮文案的，仍然以它为准
 *       （比如一键升级那个框要的是「开始升级 / 再想想」，不能被改掉）。
 *
 * 适用范围：
 *   只改**按钮**文案。弹窗正文是本项目自己写的中文，不受影响。
 *
 * 注意（为什么用打补丁而不是 el-config-provider）：
 *   <el-config-provider> 管的是模板里的组件；
 *   ElMessageBox.confirm 是命令式调用，它自己 createVNode 渲染，
 *   拿不到组件树里的 provide —— 全局语言包对它不生效。
 *   与其依赖 Element Plus 的内部约定，不如老老实实把文案传进去。
 */
import { ElMessageBox } from 'element-plus'

const ZH_BUTTONS = {
  confirmButtonText: '确定',
  cancelButtonText: '取消',
}

// 重复 import 本模块时不要重复打补丁（ES 模块只会执行一次，
// 但这里再挡一道，免得将来有人改成普通函数调用而踩坑）
if (!ElMessageBox.__kbZhPatched) {
  for (const method of ['confirm', 'alert', 'prompt']) {
    const raw = ElMessageBox[method]
    if (typeof raw !== 'function') continue
    ElMessageBox[method] = (message, title, options = {}) =>
      raw.call(ElMessageBox, message, title, { ...ZH_BUTTONS, ...options })
  }
  ElMessageBox.__kbZhPatched = true
}

export const confirmBox = (...args) => ElMessageBox.confirm(...args)
export const alertBox = (...args) => ElMessageBox.alert(...args)
export const promptBox = (...args) => ElMessageBox.prompt(...args)
