import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

export default defineConfig({
  plugins: [
    vue(),
    // Element Plus 按需引入：
    // 以前是 app.use(ElementPlus) 整包注册 —— 
    // 整个库（含所有组件、所有方法、全部样式）都进了主包，
    // 实际用到的只有 51 个组件。
    // 这里让构建器按模板里真正用到的组件自动引入，
    // 好处是**不用维护清单**：新增 <el-xxx> 自动就进来了，
    // 删掉也不会残留。
    //
    // importStyle: 'css' —— 样式也按组件引。
    // 以前是整包 element-plus/dist/index.css（356kB），
    // 里面 90% 的样式是本页根本没用到的组件的。
    //
    // ⚠️ 按组件引样式必须同时引 base.css：
    //    Element Plus 的组件样式依赖 :root 上那套 CSS 变量
    //    （--el-color-primary、--el-border-color …），
    //    变量都定义在 base.css 里（见 main.js）。
    //    漏了它页面能渲染但颜色全乱 —— 这种问题比体积大更难发现。
    Components({
      resolvers: [ElementPlusResolver({ importStyle: 'css' })],
      dts: false,
    }),
  ],
  server: {
    port: 5173,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        // 指向后端容器的宿主机端口。compose 里映射的是 8001，
        // 但这里历史上写的是 8000 —— 本地起 vite 时代理全挂，
        // 页面报错长得像「后端挂了」，很容易误判成代码问题。
        // 需要指向别的地址时用 VITE_API_TARGET 覆盖：
        //   VITE_API_TARGET=http://127.0.0.1:8001 npx vite --port 5174
        target: process.env.VITE_API_TARGET || 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})