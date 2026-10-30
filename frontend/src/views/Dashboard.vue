<template>
  <div class="page dash-page">
    <!-- 欢迎区：浅色大卡片 + 主色渐变点缀，和下面所有卡片同一套语言 -->
    <section class="hero">
      <div class="hero-content">
        <div class="hero-eyebrow"><span class="hero-dot" />{{ todayLabel }}</div>
        <h1>欢迎回来</h1>
        <p>统一管理结构化与非结构化数据，跨实体关联分析，承载多种业务应用</p>
      </div>
      <div class="hero-actions">
        <el-button type="primary" size="large" @click="$router.push('/notes')">
          <el-icon><EditPen /></el-icon>新建笔记
        </el-button>
        <el-button size="large" class="hero-btn-plain" @click="$router.push('/library')">
          <el-icon><Upload /></el-icon>上传文件
        </el-button>
      </div>
    </section>

    <!-- 上手清单 -->
    <div v-if="showOnboard" class="card onboard-card">
      <div class="card-title">
        <span class="card-title-text">
          <el-icon class="title-ico"><Compass /></el-icon>上手清单
          <span class="badge badge-primary">{{ doneCount }} / {{ onboarding.length }}</span>
        </span>
        <div class="card-actions">
          <el-button text size="small" @click="$router.push('/guide')">
            <el-icon><Reading /></el-icon>完整指南
          </el-button>
          <el-button text size="small" @click="dismissOnboard">
            <el-icon><Close /></el-icon>稍后
          </el-button>
        </div>
      </div>
      <div class="onboard-progress">
        <div class="onboard-bar" :style="{ width: (doneCount / onboarding.length * 100) + '%' }"></div>
      </div>
      <div class="onboard-items">
        <div
          v-for="s in onboarding"
          :key="s.title"
          class="onboard-item"
          :class="{ done: s.done }"
          :role="s.done ? undefined : 'button'"
          :tabindex="s.done ? undefined : 0"
          @click="!s.done && $router.push(s.to)"
          @keydown="!s.done && onCardKey($event, s.to)"
        >
          <el-icon class="ob-check">
            <CircleCheckFilled v-if="s.done" />
            <CircleClose v-else />
          </el-icon>
          <div class="ob-body">
            <div class="ob-title">{{ s.title }}</div>
            <div class="ob-desc">{{ s.desc }}</div>
          </div>
          <el-icon v-if="!s.done" class="ob-go"><ArrowRight /></el-icon>
        </div>
      </div>
    </div>

    <!-- 统计：一个主指标 + 三个次要指标，数字字号拉开层次 -->
    <div class="stat-grid dash-stats">
      <div
        class="stat-card is-lead ac-blue"
        role="button" tabindex="0"
        @click="go('/types')" @keydown="onCardKey($event, '/types')"
      >
        <div class="icon"><el-icon><Files /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ stats.type_count || 0 }}</div>
          <div class="label">数据模型</div>
          <div class="hint">实体与字段结构</div>
        </div>
        <el-icon class="stat-arrow"><ArrowRight /></el-icon>
      </div>

      <div
        class="stat-card ac-green"
        role="button" tabindex="0"
        @click="go('/types')" @keydown="onCardKey($event, '/types')"
      >
        <div class="icon"><el-icon><Document /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ stats.record_count || 0 }}</div>
          <div class="label">数据记录</div>
        </div>
      </div>

      <div
        class="stat-card ac-amber"
        role="button" tabindex="0"
        @click="go('/graph')" @keydown="onCardKey($event, '/graph')"
      >
        <div class="icon"><el-icon><Share /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ stats.relation_count || 0 }}</div>
          <div class="label">关联关系</div>
        </div>
      </div>

      <div
        class="stat-card ac-orange"
        role="button" tabindex="0"
        @click="go('/library')" @keydown="onCardKey($event, '/library')"
      >
        <div class="icon"><el-icon><Coin /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ fileCount }}</div>
          <div class="label">附件文件</div>
        </div>
      </div>
    </div>

    <!-- 快捷入口：常用的三个大而突出，罕用的收成一行小标签 -->
    <div class="card quick-card">
      <div class="card-title">
        <span class="card-title-text">
          <el-icon class="title-ico"><Lightning /></el-icon>快捷入口
        </span>
        <span class="card-title-note">常用的三个放在前面</span>
      </div>

      <div class="quick-grid">
        <div
          v-for="q in quickPrimary"
          :key="q.path"
          class="quick-item"
          :class="`ac-${q.accent}`"
          role="button" tabindex="0"
          @click="go(q.path)" @keydown="onCardKey($event, q.path)"
        >
          <div class="quick-icon">
            <el-icon :size="22"><component :is="q.icon" /></el-icon>
          </div>
          <div class="quick-text">
            <div class="quick-name">{{ q.name }}</div>
            <div class="quick-desc">{{ q.desc }}</div>
          </div>
          <el-icon class="quick-arrow"><ArrowRight /></el-icon>
        </div>
      </div>

      <div class="quick-mini-grid">
        <div
          v-for="q in quickSecondary"
          :key="q.path"
          class="quick-mini"
          :title="q.desc"
          role="button" tabindex="0"
          @click="go(q.path)" @keydown="onCardKey($event, q.path)"
        >
          <el-icon class="quick-mini-ico"><component :is="q.icon" /></el-icon>
          <span class="quick-mini-name">{{ q.name }}</span>
        </div>
      </div>
    </div>

    <div class="dashboard-row">
      <!-- 应用卡片 -->
      <div class="card dash-apps">
        <div class="card-title">
          <span class="card-title-text">
            <el-icon class="title-ico"><Grid /></el-icon>我的应用
          </span>
          <el-button text @click="$router.push('/apps')">
            查看全部 <el-icon><ArrowRight /></el-icon>
          </el-button>
        </div>

        <div v-if="apps.length" class="app-grid">
          <div
            v-for="app in apps.slice(0, 4)"
            :key="app.key"
            class="app-card"
            role="button" tabindex="0"
            @click="go(`/apps/${app.key}`)" @keydown="onCardKey($event, `/apps/${app.key}`)"
          >
            <div class="app-card-header">
              <div class="app-icon" :class="`ac-${appAccent(app.key)}`">
                <el-icon :size="20"><component :is="appIcon(app.key)" /></el-icon>
              </div>
              <div class="app-card-text">
                <div class="app-name">{{ app.name }}</div>
                <div class="app-desc">{{ app.description }}</div>
              </div>
            </div>
            <div class="app-meta">
              <span><el-icon><Files /></el-icon>{{ app.entity_count }} 模型</span>
              <span><el-icon><Document /></el-icon>{{ app.record_count }} 记录</span>
            </div>
          </div>
        </div>

        <EmptyState
          v-else
          icon="Grid"
          title="还没有应用"
          description="应用是一组数据模型的容器，创建后即可在应用下管理数据。"
        >
          <template #default>
            <el-button type="primary" @click="$router.push('/apps')">
              <el-icon><Plus /></el-icon>前往应用中心
            </el-button>
          </template>
        </EmptyState>
      </div>

      <!-- 最近活动：时间线，一眼看清「最近动了什么」 -->
      <div class="card dash-recent">
        <div class="card-title">
          <span class="card-title-text">
            <el-icon class="title-ico"><Clock /></el-icon>最近活动
          </span>
        </div>

        <div v-if="stats.recent?.length" class="recent-list">
          <div
            v-for="r in stats.recent.slice(0, 7)"
            :key="`${r.entity_type_key}-${r.record_id}`"
            class="recent-item"
            role="button"
            tabindex="0"
            :aria-label="`${r.entity_type_name} ${r.data?.name || r.data?.title || r.data?.code || ''}`"
            @click="$router.push(`/records/${r.entity_type_id}?id=${r.record_id}`)"
            @keydown="onCardKey($event, `/records/${r.entity_type_id}?id=${r.record_id}`)"
          >
            <div class="recent-icon">
              <el-icon :size="15"><component :is="entityIcon(r.entity_type_key)" /></el-icon>
            </div>
            <div class="recent-info">
              <div class="recent-title">
                <span class="recent-type-tag">{{ r.entity_type_name }}</span>
                <span class="recent-name">
                  {{ r.data?.name || r.data?.title || r.data?.code || `#${r.record_id}` }}
                </span>
              </div>
              <div class="recent-time">{{ formatTime(r.updated_at) }}</div>
            </div>
          </div>
        </div>

        <EmptyState
          v-else
          icon="Clock"
          title="还没有数据"
          description="开始你的第一条记录，这里会显示最近的活动"
          variant="plain"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Api } from '../api'
import { formatTime } from '../utils/format'
import { entityIcon, appIcon, appAccent } from '../utils/icons'
import EmptyState from '../components/EmptyState.vue'

const router = useRouter()

// 整块可点的卡片（统计卡、快捷入口、应用卡）都是 div + @click：
// 鼠标能点，但键盘用户 Tab 过来会直接跳过它 —— 既没有焦点，
// 也没有「这东西可以点」的语义。
// 统一走这两个函数：role/tabindex 让它进 Tab 序列，Enter/Space 触发同样的跳转。
function go(path) {
  router.push(path)
}
function onCardKey(e, path) {
  if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
    // 空格默认会滚动页面，先抢掉这个键
    e.preventDefault()
    go(path)
  }
}

const stats = ref({})
const apps = ref([])
const fileCount = ref(0)
const onboardDismissed = ref(localStorage.getItem('kb_onboard_dismissed') === '1')

// 欢迎区上的一句话日期：给页头一个「今天」的落点，
// 也让这块大卡片不至于只有一句口号。
const todayLabel = computed(() => {
  const d = new Date()
  const week = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][d.getDay()]
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日 · ${week}`
})

/* 快捷入口分两档：
   - 主入口（常用）：横向大块，图标底板用强调色，一眼能找到
   - 次入口（罕用）：收成一行小标签，中性灰，不跟主入口抢注意力

   颜色按语义分配，不按位置轮换：
   知识库=紫（笔记）、数据中心=橙（文件）、应用中心=青（应用），
   与下面统计卡的 数据模型=蓝 / 数据记录=绿 / 关联关系=琥珀 / 附件=橙 同属一套色板。 */
const quickPrimary = [
  { path: '/notes', name: '知识库', desc: 'Obsidian 风格笔记 · 双链', icon: 'Notebook', accent: 'violet' },
  { path: '/library', name: '数据中心', desc: '统一文件管理 · 在线预览', icon: 'Coin', accent: 'orange' },
  { path: '/apps', name: '应用中心', desc: '模板一键建应用', icon: 'Grid', accent: 'teal' },
]

const quickSecondary = [
  { path: '/types', name: '数据模型', desc: '自定义实体类型与字段', icon: 'Files' },
  { path: '/relations', name: '关联定义', desc: '配置模型之间的关系', icon: 'Connection' },
  { path: '/knowledge/graph', name: '知识图谱', desc: '所有笔记的可视化网络', icon: 'DataAnalysis' },
  { path: '/graph', name: '关联图谱', desc: '业务实体的关联分析', icon: 'Share' },
  { path: '/search', name: '全局搜索', desc: '跨实体的全文检索', icon: 'Search' },
  { path: '/guide', name: '使用指南', desc: '五步跑通一个业务', icon: 'Compass' },
  { path: '/ai-settings', name: 'AI 助手', desc: '配置模型 · 智能摘要问答', icon: 'MagicStick' },
]

// 上手清单：从真实数据推导完成状态
const onboarding = computed(() => [
  {
    title: '建立第一个应用',
    desc: '在应用中心选一个业务模板，模型与字段会自动生成',
    done: apps.value.length > 0,
    to: '/apps',
  },
  {
    title: '拥有数据模型',
    desc: '数据模型定义「有哪些字段」，决定录入表单长什么样',
    done: (stats.value.type_count || 0) > 0,
    to: '/types',
  },
  {
    title: '录入第一条记录',
    desc: '打开模型即可按字段录入业务数据',
    done: (stats.value.record_count || 0) > 0,
    to: '/types',
  },
  {
    title: '定义模型之间的关联',
    desc: '例如「项目 → 任务」，之后可在记录详情挂接',
    done: (stats.value.relation_count || 0) > 0,
    to: '/relations',
  },
  {
    title: '上传一个文件',
    desc: 'PDF / Word / Excel / 图片 都能在线预览',
    done: fileCount.value > 0,
    to: '/library',
  },
  {
    title: '写下第一条笔记',
    desc: '用 [[双链]] 串起知识，业务记录也能沉淀成笔记',
    done: (stats.value.by_app?.knowledge || 0) > 0,
    to: '/notes',
  },
])

const doneCount = computed(() => onboarding.value.filter(s => s.done).length)
const showOnboard = computed(
  () => !onboardDismissed.value && doneCount.value < onboarding.value.length
)

function dismissOnboard() {
  onboardDismissed.value = true
  localStorage.setItem('kb_onboard_dismissed', '1')
}

onMounted(async () => {
  const [s, a, libs] = await Promise.all([
    Api.getStats(),
    Api.listApps(),
    Api.documentStats(),
  ])
  stats.value = s
  apps.value = a
  fileCount.value = libs.total || 0
})
</script>

<style scoped>
/* ======================================================================
   工作台的视觉重做
   ----------------------------------------------------------------------
   原来这里最扎眼的是三件事：
   1. hero 是一整块深色渐变，下面却是一片白卡 —— 两个世界拼在一起
   2. 统计卡 4 个一模一样（字号都是 27px），快捷入口 10 个一模一样，
      用户扫一眼不知道该看哪、该点哪
   3. 图标底板紫橙绿粉蓝一轮马卡龙，颜色没有含义，看着像随机贴上去的

   现在的做法：
   - hero 改成浅色大卡片 + 主色渐变点缀，和下面所有卡片同一套语言
   - 统计卡分主次：1 个主指标（数据模型）大而突出，3 个次要指标收着
   - 快捷入口分主次：3 个常用入口大块 + 7 个罕用入口收成一行小标签
   - 图标底板一律走全局强调色板（ac-*），按语义分配，不再轮换马卡龙
   ====================================================================== */

/* 一层很浅的抬升阴影。
   原来整屏的卡片只有 1~2px 的贴地阴影，看上去像摊平的一张纸；
   这里加一层大面积、极低透明度的投影，卡片之间才分出前后。
   深色主题下投影要用黑色才看得见，所以单独给一份。 */
.dash-page {
  --dash-lift: 0 10px 26px rgba(16, 18, 27, 0.055);
}
:global(html.dark) .dash-page {
  --dash-lift: 0 10px 26px rgba(0, 0, 0, 0.42);
}
.dash-page :deep(.card),
.dash-page .stat-card,
.dash-page .quick-item {
  /* 先写大面积柔光、再写贴地的一层：
     视觉上卡片边缘依然清晰，但「层次」来自那 26px 的大柔光 */
  box-shadow: var(--dash-lift), var(--shadow-card);
}

/* ---------- 欢迎区 ---------- */
.hero {
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-6);
  padding: var(--space-8) var(--space-9);
  margin-bottom: var(--space-5);
  border-radius: var(--radius-xl);
  border: 1px solid var(--border);
  background:
    radial-gradient(70% 150% at 100% -10%, var(--primary-100) 0%, transparent 62%),
    linear-gradient(115deg, var(--primary-50) 0%, var(--bg-card) 46%);
  box-shadow: var(--dash-lift), var(--shadow-card);
}
/* 右下角一团很淡的光晕：没有硬边，不会跟按钮打架，
   只在卡片角落给一点「有光源」的层次 */
.hero::after {
  content: '';
  position: absolute;
  right: -70px;
  bottom: -170px;
  width: 380px;
  height: 380px;
  border-radius: 50%;
  background: radial-gradient(circle, var(--primary-100) 0%, transparent 68%);
  opacity: 0.75;
  pointer-events: none;
}
.hero-content {
  position: relative;
  z-index: 1;
  min-width: 0;
}
.hero-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.6px;
  color: var(--primary);
  margin-bottom: var(--space-3);
}
.hero-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-bg);
}
.hero h1 {
  margin: 0 0 10px;
  font-size: var(--text-4xl);
  font-weight: 680;
  letter-spacing: -1.2px;
  font-family: var(--font-display);
  color: var(--text-primary);
}
.hero p {
  margin: 0;
  color: var(--text-secondary);
  font-size: var(--text-md);
  line-height: 1.65;
  max-width: 620px;
}
.hero-actions {
  display: flex;
  gap: var(--space-3);
  flex-shrink: 0;
  position: relative;
  z-index: 1;
}
.hero-actions .el-button {
  font-weight: 550;
  height: 42px;
  padding: 0 var(--space-5);
  border-radius: var(--radius-md);
}
/* 次要动作是白底描边，跟主按钮拉开一档 */
.hero-btn-plain {
  background: var(--bg-card);
  border: 1px solid var(--border);
  color: var(--text-primary);
}
.hero-btn-plain:hover {
  background: var(--bg-subtle);
  border-color: var(--primary-200);
  color: var(--primary);
}

/* ---------- 统计卡：一个主指标 + 三个次要 ---------- */
.dash-stats {
  display: grid;
  grid-template-columns: 1.42fr 1fr 1fr 1fr;
  gap: var(--space-4);
  margin-bottom: var(--space-5);
}
.dash-stats .stat-card {
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-5);
  border-radius: var(--radius-lg);
  border: 1px solid var(--border);
  background: var(--bg-card);
  cursor: pointer;
  transition:
    transform var(--duration) var(--ease-out),
    box-shadow var(--duration) var(--ease-out),
    border-color var(--duration) var(--ease-out);
}
/* 顶部一道语义色：颜色在卡片上能看见，但不用整块染色去抢注意力 */
.dash-stats .stat-card::before {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  height: 3px;
  background: var(--ac-fg);
  opacity: 0.85;
}
.dash-stats .stat-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-card-hover);
  border-color: var(--ac-line);
}
.dash-stats .icon {
  width: 42px;
  height: 42px;
  border-radius: var(--radius-md);
  background: var(--ac-bg);
  color: var(--ac-fg);
  border: 1px solid var(--ac-line);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  flex-shrink: 0;
}
.dash-stats .value {
  font-size: 26px;
  font-weight: 650;
  line-height: 1.1;
  letter-spacing: -0.7px;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  font-family: var(--font-display);
}
.dash-stats .label {
  color: var(--text-tertiary);
  font-size: var(--text-sm);
  margin-top: 3px;
  font-weight: 500;
  letter-spacing: 0.3px;
}
.dash-stats .hint {
  margin-top: 5px;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
.dash-stats .value-block {
  flex: 1;
  min-width: 0;
}
.dash-stats .stat-arrow {
  color: var(--text-disabled);
  font-size: 15px;
  flex-shrink: 0;
  transition: transform var(--duration) var(--ease-out), color var(--duration) var(--ease-out);
}
.dash-stats .stat-card:hover .stat-arrow {
  color: var(--ac-fg);
  transform: translateX(2px);
}
/* 主指标：卡片更大、数字更大、底色带一点主色的晕 */
.dash-stats .stat-card.is-lead {
  padding: var(--space-6);
  border-color: var(--ac-line);
  background: linear-gradient(135deg, var(--ac-bg) 0%, var(--bg-card) 64%);
}
.dash-stats .stat-card.is-lead .icon {
  width: 56px;
  height: 56px;
  border-radius: var(--radius-lg);
  font-size: 26px;
}
.dash-stats .stat-card.is-lead .value {
  font-size: 42px;
  letter-spacing: -1.6px;
  line-height: 1.05;
}
.dash-stats .stat-card.is-lead .label {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--text-primary);
  margin-top: 2px;
}

/* ---------- 快捷入口 ---------- */
.card-title-note {
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--text-tertiary);
}
.quick-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-4);
}
.quick-item {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  cursor: pointer;
  text-align: left;
  transition:
    transform var(--duration) var(--ease-out),
    box-shadow var(--duration) var(--ease-out),
    border-color var(--duration) var(--ease-out);
}
.quick-item:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-card-hover);
  border-color: var(--ac-line);
}
.quick-icon {
  width: 46px;
  height: 46px;
  border-radius: var(--radius-md);
  background: var(--ac-bg);
  color: var(--ac-fg);
  border: 1px solid var(--ac-line);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.quick-text {
  min-width: 0;
  flex: 1;
}
.quick-name {
  font-weight: 600;
  font-size: var(--text-lg);
  letter-spacing: -0.2px;
  color: var(--text-primary);
}
.quick-desc {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  line-height: 1.45;
  margin-top: 3px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.quick-arrow {
  color: var(--text-disabled);
  flex-shrink: 0;
  transition: transform var(--duration) var(--ease-out), color var(--duration) var(--ease-out);
}
.quick-item:hover .quick-arrow {
  color: var(--ac-fg);
  transform: translateX(2px);
}
/* 次入口：收成一行中性标签，把彩色预算留给主入口 */
.quick-mini-grid {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-4);
  padding-top: var(--space-4);
  border-top: 1px dashed var(--border);
}
.quick-mini {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 34px;
  padding: 0 13px;
  border-radius: var(--radius-full);
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  color: var(--text-secondary);
  font-size: var(--text-sm);
  cursor: pointer;
  transition:
    background var(--duration-fast) var(--ease-out),
    color var(--duration-fast) var(--ease-out),
    border-color var(--duration-fast) var(--ease-out);
}
.quick-mini:hover {
  background: var(--primary-bg);
  border-color: var(--primary-200);
  color: var(--primary);
}
.quick-mini-ico {
  font-size: 15px;
  color: var(--text-tertiary);
}
.quick-mini:hover .quick-mini-ico {
  color: var(--primary);
}

/* ---------- 双栏 ---------- */
.dashboard-row {
  display: grid;
  grid-template-columns: minmax(0, 1.12fr) minmax(0, 1fr);
  gap: var(--space-5);
  align-items: start;
}
.dashboard-row > .card {
  margin-bottom: 0;
}

/* 我的应用：改成横向紧凑卡，一屏能看完 4 个应用 */
.dash-apps .app-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
}
.dash-apps .app-card {
  padding: var(--space-4) var(--space-4) var(--space-3);
  border-radius: var(--radius-lg);
  box-shadow: var(--dash-lift), var(--shadow-card);
  transition:
    transform var(--duration) var(--ease-out),
    box-shadow var(--duration) var(--ease-out),
    border-color var(--duration) var(--ease-out);
}
.dash-apps .app-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-card-hover);
  border-color: var(--primary-200);
}
.dash-apps .app-card-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: 12px;
}
.dash-apps .app-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  font-size: 19px;
}
.dash-apps .app-card-text {
  min-width: 0;
  flex: 1;
}
.dash-apps .app-name {
  margin-bottom: 2px;
  font-size: var(--text-base);
}
.dash-apps .app-desc {
  min-height: 0;
  margin-bottom: 0;
  line-height: 1.45;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dash-apps .app-meta {
  padding-top: 10px;
  margin-top: 14px;
}

/* 最近活动：时间线，一条竖线串起来 */
.recent-list {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.recent-list::before {
  content: '';
  position: absolute;
  left: 14px;
  top: 20px;
  bottom: 20px;
  width: 1px;
  background: var(--border);
}
.recent-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 5px 8px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
}
.recent-item:hover {
  background: var(--bg-subtle);
}
.recent-icon {
  position: relative;
  z-index: 1;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--bg-card);
  border: 1px solid var(--border);
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.recent-item:hover .recent-icon {
  border-color: var(--primary-200);
  color: var(--primary);
}
.recent-info {
  flex: 1;
  min-width: 0;
}
.recent-title {
  font-size: var(--text-base);
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.recent-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 550;
}
.recent-type-tag {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  background: var(--bg-subtle);
  padding: 1px 8px;
  border-radius: var(--radius-full);
  font-weight: 600;
  flex-shrink: 0;
}
.recent-time {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  margin-top: 2px;
  font-variant-numeric: tabular-nums;
}

/* ---------- 上手清单 ---------- */
.onboard-card {
  border-color: var(--primary-light);
  box-shadow: var(--shadow-card);
}
.onboard-progress {
  height: 6px;
  border-radius: var(--radius-full);
  background: var(--bg-subtle);
  overflow: hidden;
  margin-bottom: var(--space-4);
}
.onboard-bar {
  height: 100%;
  border-radius: var(--radius-full);
  background: var(--primary-grad);
  transition: width var(--duration-slow, 0.4s) var(--ease-out);
}
.onboard-items {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--space-3);
}
.onboard-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}
.onboard-item:hover:not(.done) {
  border-color: var(--primary);
  transform: translateY(-1px);
  box-shadow: var(--shadow-sm);
}
.onboard-item.done {
  cursor: default;
  background: var(--bg-subtle);
  opacity: 0.75;
}
.ob-check {
  font-size: 20px;
  color: var(--text-disabled);
  flex-shrink: 0;
}
.onboard-item.done .ob-check { color: var(--success); }
.ob-body { flex: 1; min-width: 0; }
.ob-title {
  font-weight: 600;
  font-size: var(--text-base);
  color: var(--text-primary);
}
.onboard-item.done .ob-title { text-decoration: line-through; color: var(--text-tertiary); }
.ob-desc {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  line-height: 1.55;
  margin-top: 3px;
}
.ob-go { color: var(--text-tertiary); flex-shrink: 0; }
.onboard-item:hover:not(.done) .ob-go { color: var(--primary); }

.card-title-text {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.title-ico { color: var(--primary); font-size: 18px; }

/* ======================================================================
   响应式
   ====================================================================== */
@media (max-width: 1180px) {
  /* 统计卡挤成 2×2：主指标占满第一行，其余三个各占一格 */
  .dash-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .dash-stats .stat-card.is-lead { grid-column: 1 / -1; }
  .quick-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 1100px) {
  .dashboard-row { grid-template-columns: minmax(0, 1fr); }
  .hero { flex-direction: column; align-items: flex-start; }
}

/* 手机端 */
@media (max-width: 768px) {
  .hero {
    padding: var(--space-6) var(--space-5);
    gap: var(--space-5);
  }
  .hero h1 { font-size: var(--text-2xl); letter-spacing: -0.6px; margin-bottom: 6px; }
  .hero p { font-size: var(--text-sm); }
  .hero-actions { width: 100%; flex-wrap: wrap; gap: var(--space-2); }
  .hero-actions .el-button { flex: 1 1 auto; padding: 0 var(--space-3); }

  /* 统计卡：主指标独占一行，次要三个并排一行。
     次要卡用横向排布（图标 + 数字），竖排会把这一行撑到 120px，
     整个统计区就占了屏幕的三分之一。 */
  .dash-stats { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-3); }
  .dash-stats .stat-card {
    flex-direction: row;
    align-items: center;
    gap: 8px;
    padding: 11px 10px;
    border-radius: var(--radius-md);
  }
  .dash-stats .stat-card.is-lead { grid-column: 1 / -1; padding: var(--space-4) var(--space-5); }
  .dash-stats .stat-card.is-lead .icon { width: 46px; height: 46px; font-size: 22px; border-radius: var(--radius-md); }
  .dash-stats .stat-card.is-lead .value { font-size: 32px; }
  .dash-stats .icon { width: 28px; height: 28px; font-size: 15px; border-radius: var(--radius-sm); }
  .dash-stats .value { font-size: 20px; letter-spacing: -0.4px; }
  .dash-stats .label { font-size: 11px; margin-top: 1px; }
  .dash-stats .hint { display: none; }
  .dash-stats .stat-arrow { display: none; }

  .quick-grid { grid-template-columns: minmax(0, 1fr); gap: var(--space-3); }
  .quick-item { padding: var(--space-3) var(--space-4); }
  .quick-icon { width: 40px; height: 40px; }
  .quick-mini-grid { gap: 6px; }
  .quick-mini { height: 32px; padding: 0 11px; font-size: var(--text-xs); }

  .dash-apps .app-grid { grid-template-columns: minmax(0, 1fr); }
}
</style>
