<template>
  <div class="login-page">
    <!-- 左：品牌舞台。固定深色，不跟随主题 —— 品牌面在明暗两种主题下保持同一张脸，
         跟着变会显得没有主张。 -->
    <section class="stage">
      <div class="stage-deco" aria-hidden="true">
        <span class="orb orb-a"></span>
        <span class="orb orb-b"></span>
        <span class="orb orb-c"></span>
        <!-- 装饰性节点网络：呼应「关系成网」这件事，纯背景纹理，低对比度 -->
        <svg class="net" viewBox="0 0 620 420" fill="none">
          <g class="net-lines">
            <path d="M229 174 L310 115 L391 174 L360 269 L260 269 Z" />
            <path d="M120 70 L229 174" />
            <path d="M120 70 L310 115" />
            <path d="M510 100 L310 115" />
            <path d="M510 100 L391 174" />
            <path d="M548 330 L360 269" />
            <path d="M96 336 L260 269" />
            <path d="M96 336 L229 174" />
          </g>
          <g class="net-dots">
            <circle cx="310" cy="115" r="3.2" />
            <circle cx="391" cy="174" r="3.2" />
            <circle cx="360" cy="269" r="3.2" />
            <circle cx="260" cy="269" r="3.2" />
            <circle cx="229" cy="174" r="3.2" />
            <circle cx="120" cy="70" r="2.5" />
            <circle cx="510" cy="100" r="2.5" />
            <circle cx="548" cy="330" r="2.5" />
            <circle cx="96" cy="336" r="2.5" />
          </g>
          <circle class="net-pulse" cx="310" cy="115" r="6" />
        </svg>
      </div>

      <header class="stage-brand">
        <span class="mark"><el-icon :size="20"><Collection /></el-icon></span>
        <span class="mark-text">
          <b>知识工作台</b>
          <i>Knowledge Workbench</i>
        </span>
      </header>

      <div class="stage-body">
        <h1>把数据与知识<br />沉淀成一张网</h1>
        <p class="lede">
          模型自定义、文件原生入湖、关系自动成网、指标随搭随看 ——
          一套跑在自己机器上的私有数据底座。
        </p>

        <ul class="caps">
          <li>
            <span class="cap-ico"><el-icon :size="14"><Grid /></el-icon></span>
            <span class="cap-tx">
              <b>模型自定义</b>
              <em>数据模型、字段与关联全部由 JSON 定义</em>
            </span>
          </li>
          <li>
            <span class="cap-ico"><el-icon :size="14"><Document /></el-icon></span>
            <span class="cap-tx">
              <b>文件原生</b>
              <em>原文进库，正文抽取 + 全文与向量混合检索</em>
            </span>
          </li>
          <li>
            <span class="cap-ico"><el-icon :size="14"><Share /></el-icon></span>
            <span class="cap-tx">
              <b>关系成网</b>
              <em>记录与文件互相挂接，图谱一屏看清来龙去脉</em>
            </span>
          </li>
          <li>
            <span class="cap-ico"><el-icon :size="14"><DataLine /></el-icon></span>
            <span class="cap-tx">
              <b>可视化驾驶舱</b>
              <em>想要的指标拖成卡片，随时改、随时看</em>
            </span>
          </li>
          <li>
            <span class="cap-ico"><el-icon :size="14"><Lock /></el-icon></span>
            <span class="cap-tx">
              <b>权限与留痕</b>
              <em>角色到页面 / 模型 / 操作三级授权，改动可追溯</em>
            </span>
          </li>
        </ul>
      </div>

      <footer class="stage-foot">
        <span class="dot-live"></span>私有部署 · 数据留在自己手里
        <span v-if="auth.sysVersion" class="foot-version">v{{ auth.sysVersion }}</span>
      </footer>
    </section>

    <!-- 右：表单 -->
    <section class="panel">
      <button class="theme-btn" type="button" title="切换明暗主题" @click="toggleTheme">
        <el-icon :size="16"><Sunny v-if="isDark" /><Moon v-else /></el-icon>
      </button>

      <div class="panel-inner">
        <div class="panel-brand">
          <span class="mark is-small"><el-icon :size="17"><Collection /></el-icon></span>
          <span class="mark-text">
            <b>知识工作台</b>
            <i>Knowledge Workbench</i>
          </span>
        </div>

        <div class="panel-head">
          <h2>{{ forceChange ? '设置新口令' : '欢迎回来' }}</h2>
          <p v-if="forceChange">初始口令已停用，设置新口令后即可继续</p>
          <p v-else>登录以继续使用你的数据底座</p>
        </div>

        <!-- 初始口令强制修改：改完才允许进入系统 -->
        <template v-if="forceChange">
          <div class="notice is-warn">
            <el-icon><WarningFilled /></el-icon>
            <div>
              初始管理员口令是公开的默认值，必须修改后才能继续使用。
              新口令至少 8 位。
            </div>
          </div>
          <el-form :model="pwForm" label-position="top" @submit.prevent="submitPassword">
            <el-form-item label="当前口令">
              <el-input v-model="pwForm.old_password" type="password" show-password
                        placeholder="初始口令" @keyup.enter="submitPassword" />
            </el-form-item>
            <el-form-item label="新口令">
              <el-input v-model="pwForm.new_password" type="password" show-password
                        placeholder="至少 8 位" @keyup.enter="submitPassword" />
            </el-form-item>
            <el-form-item label="确认新口令">
              <el-input v-model="pwForm.confirm" type="password" show-password
                        placeholder="再输一次" @keyup.enter="submitPassword" />
            </el-form-item>
            <el-button type="primary" class="submit" :loading="loading" @click="submitPassword">
              <span>修改口令并重新登录</span>
            </el-button>
          </el-form>
        </template>

        <template v-else>
          <div v-if="!authEnabled" class="notice">
            <el-icon><InfoFilled /></el-icon>
            <div>当前后端已关闭登录鉴权（<code>KB_AUTH_ENABLED=false</code>），以本机管理员身份直接使用。</div>
          </div>
          <el-form v-else :model="form" label-position="top" @submit.prevent="submit">
            <el-form-item label="用户名">
              <el-input v-model="form.username" size="large" placeholder="用户名"
                        autocomplete="username" @keyup.enter="submit">
                <template #prefix><el-icon><User /></el-icon></template>
              </el-input>
            </el-form-item>
            <el-form-item label="密码">
              <el-input v-model="form.password" type="password" show-password size="large"
                        placeholder="密码" autocomplete="current-password" @keyup.enter="submit">
                <template #prefix><el-icon><Lock /></el-icon></template>
              </el-input>
            </el-form-item>
            <el-button type="primary" size="large" class="submit" :loading="loading" @click="submit">
              <span>登录</span>
              <el-icon class="submit-arrow"><Right /></el-icon>
            </el-button>
          </el-form>

          <div v-if="!authEnabled" class="footer">
            <el-button type="primary" size="large" class="submit" @click="enter">
              <span>进入系统</span>
              <el-icon class="submit-arrow"><Right /></el-icon>
            </el-button>
          </div>

          <!-- 提示只在「初始口令确实还没改过」时给初始账号，其余情况给重置出路。
               早先写死「默认 admin12345」是错的：部署时用 KB_ADMIN_PASSWORD
               覆盖过、或口令已被改过之后，那句话会把人直接带进沟里。 -->
          <details v-if="initialPassword" class="setup-hint">
            <summary>首次部署？查看初始账号</summary>
            <div>
              用户名为 <code>admin</code>，口令取自部署后端时设置的环境变量
              <code>KB_ADMIN_PASSWORD</code>（未设置则用后端内置默认值）；
              首次登录后会强制要求修改。
            </div>
          </details>
          <details v-else class="setup-hint">
            <summary>忘记口令了？</summary>
            <div>
              管理员口令只能在服务端重置：在项目目录执行
              <code>./scripts/reset-admin-password.sh</code>，按提示设置新口令即可，
              已有数据不受影响。
            </div>
          </details>
        </template>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'
import { isDark, toggleTheme } from '../utils/theme'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const loading = ref(false)
const form = reactive({ username: 'admin', password: '' })
const pwForm = reactive({ old_password: '', new_password: '', confirm: '' })
const authEnabled = computed(() => auth.authEnabled)
const forceChange = computed(() => auth.mustChangePassword)
const initialPassword = computed(() => auth.initialPassword)

onMounted(async () => {
  await auth.bootstrap()
  if (auth.isLoggedIn && !auth.mustChangePassword) {
    router.replace(route.query.redirect || '/')
  }
})

function enter() {
  router.replace(route.query.redirect || '/')
}

async function submit() {
  if (!form.username.trim() || !form.password) {
    ElMessage.warning('请输入用户名与密码')
    return
  }
  loading.value = true
  try {
    await auth.login(form.username.trim(), form.password)
    form.password = ''
    if (auth.mustChangePassword) {
      // 后端此时只放行 /api/auth/*，停在当前页引导改密
      pwForm.old_password = ''
      return
    }
    ElMessage.success('登录成功')
    router.replace(route.query.redirect || '/')
  } catch (e) {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

async function submitPassword() {
  if (!pwForm.old_password || !pwForm.new_password) {
    ElMessage.warning('请填写当前口令与新口令')
    return
  }
  if (pwForm.new_password.length < 8) {
    ElMessage.warning('新口令至少 8 位')
    return
  }
  if (pwForm.new_password !== pwForm.confirm) {
    ElMessage.warning('两次输入的新口令不一致')
    return
  }
  loading.value = true
  try {
    await auth.changePassword(pwForm.old_password, pwForm.new_password)
    ElMessage.success('口令已修改，请用新口令登录')
    auth.user = null
    form.password = ''
    pwForm.old_password = ''
    pwForm.new_password = ''
    pwForm.confirm = ''
  } catch (e) {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  min-height: 100dvh;
  display: grid;
  grid-template-columns: minmax(0, 1.02fr) minmax(0, 1fr);
  background: var(--bg);
}

/* ============================== 品牌舞台 ============================== */
.stage {
  position: relative;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 36px;
  padding: clamp(30px, 4vw, 56px) clamp(30px, 5vw, 76px);
  color: #fff;
  background: linear-gradient(155deg, #1c1d38 0%, #272b58 46%, #141527 100%);
}
/* 细网格 + 边缘淡出：给深色面一点材质，不抢内容 */
.stage::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.048) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.048) 1px, transparent 1px);
  background-size: 34px 34px;
  -webkit-mask-image: radial-gradient(125% 95% at 18% 6%, #000 22%, transparent 76%);
  mask-image: radial-gradient(125% 95% at 18% 6%, #000 22%, transparent 76%);
  pointer-events: none;
}
.stage-deco { position: absolute; inset: 0; pointer-events: none; }
.orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(74px);
  will-change: transform;
}
.orb-a {
  width: 360px; height: 360px; left: -90px; top: -70px;
  background: #5057c8; opacity: 0.5;
  animation: drift-a 24s ease-in-out infinite;
}
.orb-b {
  width: 320px; height: 320px; right: -70px; bottom: -100px;
  background: #2f8091; opacity: 0.34;
  animation: drift-b 30s ease-in-out infinite;
}
.orb-c {
  width: 220px; height: 220px; left: 42%; top: 46%;
  background: #6b5fd0; opacity: 0.22;
  animation: drift-a 34s ease-in-out infinite reverse;
}
@keyframes drift-a {
  0%, 100% { transform: translate(0, 0) scale(1); }
  50% { transform: translate(30px, 26px) scale(1.12); }
}
@keyframes drift-b {
  0%, 100% { transform: translate(0, 0) scale(1); }
  50% { transform: translate(-34px, -22px) scale(1.08); }
}

.net {
  position: absolute;
  right: -9%;
  bottom: -4%;
  width: 66%;
  max-width: 600px;
  color: rgba(255, 255, 255, 0.13);
}
.net-lines { stroke: currentColor; stroke-width: 1; }
.net-dots { fill: rgba(190, 194, 255, 0.45); }
.net-pulse {
  fill: none;
  stroke: rgba(158, 163, 255, 0.8);
  stroke-width: 1.4;
  transform-box: fill-box;
  transform-origin: center;
  animation: ping 3.4s ease-out infinite;
}
@keyframes ping {
  0% { transform: scale(0.55); opacity: 0.85; }
  70%, 100% { transform: scale(2.5); opacity: 0; }
}

.stage-brand,
.stage-body,
.stage-foot { position: relative; z-index: 1; }
.foot-version {
  margin-left: 10px;
  font-family: var(--font-mono);
  font-size: 11px;
  opacity: 0.55;
}

.stage-brand { display: flex; align-items: center; gap: 12px; }
.mark {
  width: 40px; height: 40px;
  flex-shrink: 0;
  border-radius: 12px;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(145deg, rgba(255, 255, 255, 0.22), rgba(255, 255, 255, 0.07));
  border: 1px solid rgba(255, 255, 255, 0.18);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.28);
}
.mark.is-small { width: 36px; height: 36px; border-radius: 10px; }
.mark-text { display: flex; flex-direction: column; line-height: 1.35; }
.mark-text b { font-size: 15px; font-weight: 700; letter-spacing: 0.2px; }
.mark-text i {
  font-style: normal;
  font-size: 10.5px;
  letter-spacing: 0.9px;
  text-transform: uppercase;
  opacity: 0.52;
}

.stage-body { max-width: 500px; }
.stage-body h1 {
  margin: 0 0 14px;
  font-family: var(--font-display);
  font-size: clamp(26px, 2.7vw, 36px);
  font-weight: 800;
  line-height: 1.24;
  letter-spacing: -0.9px;
}
.lede {
  margin: 0;
  max-width: 430px;
  font-size: 13.5px;
  line-height: 1.85;
  color: rgba(255, 255, 255, 0.6);
}

.caps { list-style: none; margin: 32px 0 0; padding: 0; display: grid; gap: 15px; }
.caps li { display: flex; gap: 12px; align-items: flex-start; }
.cap-ico {
  flex: 0 0 28px; height: 28px; margin-top: 1px;
  border-radius: 9px;
  display: flex; align-items: center; justify-content: center;
  background: rgba(255, 255, 255, 0.085);
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: #ccd0f8;
}
.cap-tx { display: flex; flex-direction: column; }
.cap-tx b { font-size: 13.5px; font-weight: 600; }
.cap-tx em {
  font-style: normal;
  font-size: 12px;
  line-height: 1.6;
  color: rgba(255, 255, 255, 0.52);
}

.stage-foot {
  display: flex; align-items: center; gap: 8px;
  font-size: 11.5px;
  letter-spacing: 0.3px;
  color: rgba(255, 255, 255, 0.42);
}
.dot-live {
  width: 6px; height: 6px; border-radius: 50%;
  background: #4ad3a4;
  box-shadow: 0 0 0 3px rgba(74, 211, 164, 0.18);
}

/* ============================== 表单面板 ============================== */
.panel {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px 32px;
  background:
    radial-gradient(760px 420px at 82% 6%, var(--primary-50), transparent 66%),
    var(--bg);
}
.theme-btn {
  position: absolute;
  top: 20px; right: 22px;
  width: 34px; height: 34px;
  display: flex; align-items: center; justify-content: center;
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
  background: var(--bg-card);
  color: var(--text-tertiary);
  cursor: pointer;
  transition: color var(--duration), border-color var(--duration), transform var(--duration) var(--ease-out);
}
.theme-btn:hover {
  color: var(--primary);
  border-color: var(--primary-200);
  transform: translateY(-1px);
}

.panel-inner { width: 100%; max-width: 380px; }

.panel-brand {
  display: none;
  align-items: center;
  gap: 11px;
  margin-bottom: 30px;
  color: var(--text-primary);
}
.panel-brand .mark {
  background: var(--primary-grad);
  border: none;
  color: #fff;
  box-shadow: 0 6px 16px -8px rgba(74, 78, 180, 0.9);
}
.panel-brand .mark-text b { font-size: 14.5px; }
.panel-brand .mark-text i { color: var(--text-tertiary); opacity: 1; }

.panel-head { margin-bottom: 26px; }
.panel-head h2 {
  margin: 0 0 7px;
  font-family: var(--font-display);
  font-size: 25px;
  font-weight: 750;
  letter-spacing: -0.6px;
  color: var(--text-primary);
}
.panel-head p {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-tertiary);
}

/* ---- 输入框：加高、圆角、聚焦时出现柔和光环 ---- */
.panel :deep(.el-form-item) { margin-bottom: 18px; }
.panel :deep(.el-form-item__label) {
  padding-bottom: 7px;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-secondary);
  line-height: 1.4;
}
.panel :deep(.el-input__wrapper) {
  padding: 1px 12px;
  border-radius: var(--radius-md);
  background: var(--bg-card);
  box-shadow: 0 0 0 1px var(--border) inset;
  transition: box-shadow var(--duration) var(--ease-out);
}
.panel :deep(.el-input__wrapper:hover) { box-shadow: 0 0 0 1px var(--border-strong) inset; }
.panel :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--primary) inset, 0 0 0 4px var(--primary-ring);
}
.panel :deep(.el-input__inner) { height: 42px; font-size: var(--text-md); }
.panel :deep(.el-input__prefix) { color: var(--text-disabled); }

/* ---- 主按钮 ---- */
.panel .submit.el-button {
  width: 100%;
  height: 46px;
  margin-top: 6px;
  border: none;
  border-radius: var(--radius-md);
  background: var(--primary-grad);
  color: #fff;
  font-size: var(--text-md);
  font-weight: 600;
  letter-spacing: 0.6px;
  box-shadow: 0 10px 22px -12px rgba(74, 78, 180, 0.95);
  transition: transform var(--duration) var(--ease-out),
              box-shadow var(--duration) var(--ease-out),
              filter var(--duration);
}
.panel .submit.el-button:hover,
.panel .submit.el-button:focus-visible {
  background: var(--primary-grad);
  color: #fff;
  filter: brightness(1.07);
  transform: translateY(-1px);
  box-shadow: 0 14px 28px -12px rgba(74, 78, 180, 1);
}
.panel .submit.el-button:active { transform: translateY(0); filter: brightness(0.98); }
.submit-arrow { margin-left: 7px; transition: transform var(--duration) var(--ease-out); }
.panel .submit.el-button:hover .submit-arrow { transform: translateX(3px); }

/* ---- 提示块 ---- */
.notice {
  display: flex; gap: 9px; align-items: flex-start;
  padding: 11px 13px;
  margin-bottom: 18px;
  border-radius: var(--radius-md);
  background: var(--primary-50);
  border: 1px solid var(--primary-200);
  color: var(--text-secondary);
  font-size: var(--text-xs);
  line-height: 1.7;
}
.notice.is-warn { background: var(--warning-bg); border-color: var(--warning); color: var(--warning); }
.notice .el-icon { margin-top: 2px; flex-shrink: 0; }
.notice code, .setup-hint code {
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--bg-subtle);
  font-family: var(--font-mono);
  font-size: 0.94em;
}

.footer { margin-top: 10px; }

/* ---- 首次部署提示：默认收起，避免默认口令明晃晃挂在首屏 ---- */
.setup-hint {
  margin-top: 26px;
  padding-top: 16px;
  border-top: 1px solid var(--border-light);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
.setup-hint summary {
  display: flex; align-items: center; gap: 6px;
  width: fit-content;
  cursor: pointer;
  list-style: none;
  transition: color var(--duration);
}
.setup-hint summary::-webkit-details-marker { display: none; }
.setup-hint summary:hover { color: var(--primary); }
.setup-hint summary::before {
  content: '';
  width: 5px; height: 5px;
  border-right: 1.5px solid currentColor;
  border-bottom: 1.5px solid currentColor;
  transform: rotate(-45deg) translate(-1px, -1px);
  transition: transform var(--duration) var(--ease-out);
}
.setup-hint[open] summary::before { transform: rotate(45deg); }
.setup-hint > div { margin-top: 10px; line-height: 1.95; }

/* ============================== 响应式 ============================== */
@media (max-width: 1020px) {
  .login-page { grid-template-columns: minmax(0, 1fr); }
  .stage { display: none; }
  .panel { padding: 56px 24px; }
  .panel-brand { display: flex; }
}
@media (max-width: 420px) {
  .panel-head h2 { font-size: 22px; }
}
@media (prefers-reduced-motion: reduce) {
  .orb, .net-pulse { animation: none; }
}
</style>
