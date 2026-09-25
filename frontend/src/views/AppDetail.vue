<template>
  <div class="page">
    <el-button text class="back-btn" @click="$router.push('/apps')">
      <el-icon><ArrowLeft /></el-icon>返回应用中心
    </el-button>

    <PageTitle
      v-if="app"
      :title="app.name"
      :subtitle="app.description"
      icon-key="Grid"
    >
      <el-button @click="$router.push('/apps')">
        <el-icon><Setting /></el-icon>管理应用
      </el-button>
      <el-button type="primary" @click="$router.push({ path: '/types/new', query: { app: appKey }})">
        <el-icon><Plus /></el-icon>新建模型
      </el-button>
    </PageTitle>

    <!-- 应用概览 -->
    <div v-if="app" class="stat-grid">
      <div class="stat-card">
        <div class="icon"><el-icon><Files /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ types.length }}</div>
          <div class="label">数据模型</div>
        </div>
      </div>
      <div class="stat-card success">
        <div class="icon"><el-icon><Document /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ totalRecords }}</div>
          <div class="label">数据记录</div>
        </div>
      </div>
      <div class="stat-card warning">
        <div class="icon"><el-icon><Histogram /></el-icon></div>
        <div class="value-block">
          <div class="value">{{ totalFields }}</div>
          <div class="label">总字段数</div>
        </div>
      </div>
    </div>

    <!-- 数据模型 -->
    <div class="card">
      <div class="card-title">
        <span class="card-title-text">
          <el-icon class="title-ico"><Files /></el-icon>数据模型
          <span class="badge badge-ghost">{{ types.length }}</span>
        </span>
        <el-button type="primary" size="small" @click="$router.push({ path: '/types/new', query: { app: appKey }})">
          <el-icon><Plus /></el-icon>新建模型
        </el-button>
      </div>

      <div v-if="types.length" class="entity-grid">
        <div
          v-for="t in types"
          :key="t.id"
          class="entity-tile"
          @click="$router.push(`/records/${t.id}`)"
        >
          <div class="icon">
            <el-icon :size="22"><component :is="entityIcon(t.key)" /></el-icon>
          </div>
          <div class="info">
            <div class="name">{{ t.name }}</div>
            <div class="desc">{{ t.description || t.key }}</div>
          </div>
          <div class="entity-meta">
            <span class="count">{{ t.record_count }}</span>
            <span class="count-label">记录</span>
          </div>
          <el-tooltip content="编辑模型" placement="top" :show-after="400">
            <el-button
              size="small"
              text
              class="edit-btn"
              @click.stop="$router.push(`/types/${t.id}/edit`)"
            >
              <el-icon><Setting /></el-icon>
            </el-button>
          </el-tooltip>
        </div>
      </div>

      <div v-else class="empty-state">
        <div class="empty-icon"><el-icon :size="32"><Files /></el-icon></div>
        <div class="empty-title">该应用下还没有数据模型</div>
        <div class="empty-desc">数据模型定义了这张「表」有哪些字段，创建后即可录入与管理数据。</div>
        <div class="empty-actions">
          <el-button type="primary" @click="$router.push({ path: '/types/new', query: { app: appKey }})">
            <el-icon><Plus /></el-icon>新建模型
          </el-button>
        </div>
      </div>
    </div>

    <!-- 最近活动 -->
    <div v-if="recent.length" class="card">
      <div class="card-title">
        <span class="card-title-text">
          <el-icon class="title-ico"><Clock /></el-icon>最近活动
        </span>
      </div>
      <el-timeline>
        <el-timeline-item
          v-for="r in recent"
          :key="`app-${r.record_id}`"
          :timestamp="formatTime(r.updated_at)"
          placement="top"
          type="primary"
          hollow
        >
          <div class="recent-row">
            <span class="recent-type-tag">
              <el-icon :size="12"><component :is="entityIcon(r.entity_type_key)" /></el-icon>
              {{ r.entity_type_name }}
            </span>
            <a class="recent-link" @click="$router.push(`/records/${r.entity_type_id}?id=${r.record_id}`)">
              {{ r.data?.name || r.data?.title || r.data?.code || `#${r.record_id}` }}
            </a>
          </div>
        </el-timeline-item>
      </el-timeline>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Api } from '../api'
import { formatTime } from '../utils/format'
import { entityIcon } from '../utils/icons'
import PageTitle from '../components/PageTitle.vue'

const route = useRoute()
const appKey = computed(() => route.params.appKey)

const app = ref(null)
const types = ref([])
const recent = ref([])

const totalRecords = computed(() => types.value.reduce((s, t) => s + (t.record_count || 0), 0))
const totalFields = computed(() => types.value.reduce((s, t) => s + (t.field_count || 0), 0))

async function load() {
  const [a, t] = await Promise.all([
    Api.listApps(),
    Api.listEntityTypes(appKey.value),
  ])
  app.value = a.find(x => x.key === appKey.value)
  types.value = t

  const allRecent = []
  for (const et of t) {
    try {
      const r = await Api.listRecords(et.id, { page_size: 5 })
      for (const rec of (r.items || [])) {
        allRecent.push({
          record_id: rec.id,
          entity_type_id: et.id,
          entity_type_key: et.key,
          entity_type_name: et.name,
          data: rec.data || {},
          updated_at: rec.updated_at,
        })
      }
    } catch {}
  }
  allRecent.sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at))
  recent.value = allRecent.slice(0, 8)
}

onMounted(load)
watch(appKey, load)
</script>

<style scoped>
.back-btn { margin-bottom: var(--space-2); }
.card-title-text { display: inline-flex; align-items: center; gap: 8px; }
.title-ico { color: var(--primary); font-size: 18px; }

.entity-grid {
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
}
.entity-tile {
  position: relative;
  padding: 18px;
}
.entity-tile .info { flex: 1; min-width: 0; }
.entity-tile .name { font-weight: 700; font-size: var(--text-md); margin-bottom: 6px; }
.entity-tile .desc {
  color: var(--text-tertiary);
  font-size: var(--text-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.entity-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  flex-shrink: 0;
}
.entity-meta .count {
  font-size: var(--text-2xl);
  font-weight: 700;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}
.entity-meta .count-label { font-size: var(--text-xs); color: var(--text-tertiary); }
.edit-btn {
  position: absolute;
  top: 10px;
  right: 10px;
  opacity: 0;
  transition: opacity var(--duration-fast);
}
.entity-tile:hover .edit-btn { opacity: 1; }

.recent-row { display: flex; align-items: center; gap: var(--space-3); }
.recent-type-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-xs);
  color: var(--text-secondary);
  background: var(--bg-subtle);
  padding: 2px 8px;
  border-radius: var(--radius-full);
  font-weight: 600;
}
.recent-link { color: var(--primary); font-weight: 600; cursor: pointer; }
.recent-link:hover { text-decoration: underline; }
</style>
