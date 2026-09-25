<template>
  <div class="page">
    <!-- 欢迎区 -->
    <div class="hero">
      <div class="hero-content">
        <h1>欢迎回来</h1>
        <p>统一管理结构化与非结构化数据，跨实体关联分析，承载多种业务应用</p>
      </div>
      <div class="hero-actions">
        <el-button size="large" @click="$router.push('/notes')">
          <el-icon><EditPen /></el-icon>新建笔记
        </el-button>
        <el-button size="large" @click="$router.push('/library')">
          <el-icon><Upload /></el-icon>上传文件
        </el-button>
      </div>
    </div>

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
          @click="!s.done && $router.push(s.to)"
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

    <!-- 统计 -->
    <div class="stat-grid">
      <div class="stat-card" @click="$router.push('/types')">
        <div class="icon"><el-icon><Files /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ stats.type_count || 0 }}</div>
          <div class="label">数据模型</div>
        </div>
      </div>
      <div class="stat-card success" @click="$router.push('/types')">
        <div class="icon"><el-icon><Document /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ stats.record_count || 0 }}</div>
          <div class="label">数据记录</div>
        </div>
      </div>
      <div class="stat-card warning" @click="$router.push('/graph')">
        <div class="icon"><el-icon><Share /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ stats.relation_count || 0 }}</div>
          <div class="label">关联关系</div>
        </div>
      </div>
      <div class="stat-card info" @click="$router.push('/library')">
        <div class="icon"><el-icon><Coin /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ fileCount }}</div>
          <div class="label">附件文件</div>
        </div>
      </div>
    </div>

    <!-- 快捷入口 -->
    <div class="card">
      <div class="card-title">
        <span class="card-title-text">
          <el-icon class="title-ico"><Lightning /></el-icon>快捷入口
        </span>
      </div>
      <div class="quick-grid">
        <div
          v-for="q in quickLinks"
          :key="q.path"
          class="quick-item"
          @click="$router.push(q.path)"
        >
          <div class="quick-icon" :style="{ background: q.bg, color: q.color }">
            <el-icon :size="22"><component :is="q.icon" /></el-icon>
          </div>
          <div class="quick-name">{{ q.name }}</div>
          <div class="quick-desc">{{ q.desc }}</div>
        </div>
      </div>
    </div>

    <div class="dashboard-row">
      <!-- 应用卡片 -->
      <div class="card">
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
            @click="$router.push(`/apps/${app.key}`)"
          >
            <div class="app-card-header">
              <div class="app-icon">
                <el-icon :size="22"><component :is="appIcon(app.key)" /></el-icon>
              </div>
            </div>
            <div class="app-name">{{ app.name }}</div>
            <div class="app-desc">{{ app.description }}</div>
            <div class="app-meta">
              <span><el-icon><Files /></el-icon>{{ app.entity_count }} 模型</span>
              <span><el-icon><Document /></el-icon>{{ app.record_count }} 记录</span>
            </div>
          </div>
        </div>

        <div v-else class="empty-state">
          <div class="empty-icon"><el-icon :size="32"><Grid /></el-icon></div>
          <div class="empty-title">还没有应用</div>
          <div class="empty-desc">应用是一组数据模型的容器，创建后即可在应用下管理数据。</div>
          <div class="empty-actions">
            <el-button type="primary" @click="$router.push('/apps')">
              <el-icon><Plus /></el-icon>前往应用中心
            </el-button>
          </div>
        </div>
      </div>

      <!-- 最近活动 -->
      <div class="card">
        <div class="card-title">
          <span class="card-title-text">
            <el-icon class="title-ico"><Clock /></el-icon>最近活动
          </span>
        </div>

        <div v-if="stats.recent?.length" class="recent-list">
          <div
            v-for="r in stats.recent.slice(0, 8)"
            :key="`${r.entity_type_key}-${r.record_id}`"
            class="recent-item"
            @click="$router.push(`/records/${r.entity_type_id}?id=${r.record_id}`)"
          >
            <div class="recent-icon">
              <el-icon :size="16"><component :is="entityIcon(r.entity_type_key)" /></el-icon>
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

        <div v-else class="empty-state" style="border:none;background:transparent;padding:48px 20px">
          <div class="empty-icon"><el-icon :size="32"><Clock /></el-icon></div>
          <div class="empty-title">还没有数据</div>
          <div class="empty-desc">开始你的第一条记录，这里会显示最近的活动</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { Api } from '../api'
import { formatTime } from '../utils/format'
import { entityIcon, appIcon } from '../utils/icons'

const stats = ref({})
const apps = ref([])
const fileCount = ref(0)
const onboardDismissed = ref(localStorage.getItem('kb_onboard_dismissed') === '1')

const quickLinks = [
  { path: '/notes', name: '知识库', desc: 'Obsidian 风格笔记 · 双链', icon: 'Notebook', bg: 'var(--primary-bg)', color: 'var(--primary)' },
  { path: '/library', name: '数据中心', desc: '统一文件管理 · 在线预览', icon: 'Coin', bg: 'var(--warning-bg)', color: 'var(--warning)' },
  { path: '/apps', name: '应用中心', desc: '模板一键建应用', icon: 'Grid', bg: 'var(--success-bg)', color: 'var(--success)' },
  { path: '/types', name: '数据模型', desc: '自定义实体类型与字段', icon: 'Files', bg: 'var(--danger-bg)', color: 'var(--danger)' },
  { path: '/relations', name: '关联定义', desc: '配置模型之间的关系', icon: 'Connection', bg: 'rgba(122,106,208,.10)', color: '#7a6ad0' },
  { path: '/knowledge/graph', name: '知识图谱', desc: '所有笔记的可视化网络', icon: 'DataAnalysis', bg: 'rgba(187,90,134,.10)', color: '#bb5a86' },
  { path: '/graph', name: '关联图谱', desc: '业务实体的关联分析', icon: 'Share', bg: 'rgba(15,155,142,.10)', color: '#0f9b8e' },
  { path: '/search', name: '全局搜索', desc: '跨实体的全文检索', icon: 'Search', bg: 'rgba(74,127,181,.10)', color: '#4a7fb5' },
  { path: '/guide', name: '使用指南', desc: '五步跑通一个业务', icon: 'Compass', bg: 'var(--primary-bg)', color: 'var(--primary)' },
  { path: '/ai-settings', name: 'AI 助手', desc: '配置模型 · 智能摘要问答', icon: 'MagicStick', bg: 'rgba(180,128,30,.11)', color: '#b4801e' },
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
.hero {
  background:
    radial-gradient(120% 165% at 88% -22%, rgba(124, 128, 216, 0.34) 0%, rgba(124, 128, 216, 0) 58%),
    linear-gradient(135deg, #1f2131 0%, #14161f 58%, #191b2b 100%);
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: var(--radius-lg);
  padding: 32px 36px;
  color: #fff;
  margin-bottom: var(--space-5);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-5);
  box-shadow: var(--shadow-lg);
  position: relative;
  overflow: hidden;
}
.hero::after {
  content: '';
  position: absolute;
  right: -50px;
  top: -90px;
  width: 320px;
  height: 320px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(131, 135, 222, 0.18), transparent 66%);
  pointer-events: none;
}
.hero-content { position: relative; z-index: 1; }
.hero h1 {
  margin: 0 0 9px;
  font-size: var(--text-3xl);
  font-weight: 650;
  letter-spacing: -1px;
  font-family: var(--font-display);
}
.hero p {
  margin: 0;
  color: rgba(255, 255, 255, 0.72);
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
  background: rgba(255, 255, 255, 0.10) !important;
  color: #fff !important;
  border: 1px solid rgba(255, 255, 255, 0.18) !important;
  font-weight: 550;
  backdrop-filter: blur(6px);
}
.hero-actions .el-button:hover {
  background: rgba(255, 255, 255, 0.18) !important;
  border-color: rgba(255, 255, 255, 0.28) !important;
}

.stat-card { cursor: pointer; }

/* 上手清单 */
.onboard-card {
  background: linear-gradient(135deg, var(--primary-50), var(--bg-card) 55%);
  border: 1px solid var(--primary-light);
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

/* 快捷入口 */
.quick-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: var(--space-3);
}
.quick-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 18px 12px;
  background: var(--bg);
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  cursor: pointer;
  transition: all var(--duration) var(--ease-out);
  text-align: center;
}
.quick-item:hover {
  background: var(--bg-card);
  transform: translateY(-2px);
  box-shadow: var(--shadow);
  border-color: var(--primary-light);
}
.quick-icon {
  width: 46px;
  height: 46px;
  border-radius: var(--radius);
  display: flex;
  align-items: center;
  justify-content: center;
}
.quick-name { font-weight: 600; font-size: var(--text-base); }
.quick-desc { font-size: var(--text-xs); color: var(--text-tertiary); line-height: 1.4; }

/* 双栏布局 */
.dashboard-row {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: var(--space-4);
}
.dashboard-row > .card { margin-bottom: 0; }

@media (max-width: 1100px) {
  .dashboard-row { grid-template-columns: 1fr; }
  .hero { flex-direction: column; align-items: flex-start; }
}

/* 手机端：hero 收紧、快捷入口变 3 列紧凑小卡（竖排罗列不实用） */
@media (max-width: 768px) {
  .hero {
    padding: 20px 18px;
  }
  .hero h1 { font-size: var(--text-2xl); margin-bottom: 6px; }
  .hero p { font-size: var(--text-sm); }
  .hero-actions {
    width: 100%;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .hero-actions .el-button { flex: 1 1 auto; }

  .quick-grid {
    grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
    gap: var(--space-2);
  }
  .quick-item { padding: 12px 6px; gap: 5px; }
  .quick-icon { width: 38px; height: 38px; }
  .quick-name { font-size: var(--text-sm); }
  .quick-desc { display: none; }   /* 手机上信息密度优先，描述让位 */
}

/* 最近活动 */
.recent-list { display: flex; flex-direction: column; gap: 2px; }
.recent-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
}
.recent-item:hover { background: var(--bg-subtle); }
.recent-icon {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  background: var(--primary-bg);
  color: var(--primary);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.recent-info { flex: 1; min-width: 0; }
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
</style>
