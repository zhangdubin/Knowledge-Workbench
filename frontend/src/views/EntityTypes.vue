<template>
  <div class="page">
    <PageTitle
      title="数据模型"
      subtitle="定义实体类型（表结构），承载结构化与非结构化数据"
      icon-key="Files"
    >
      <el-button @click="jsonNew">
        <el-icon><MagicStick /></el-icon>JSON 新建
      </el-button>
      <el-button type="primary" @click="$router.push('/types/new')">
        <el-icon><Plus /></el-icon>新建模型
      </el-button>
    </PageTitle>

    <el-tabs v-model="activeApp" class="app-tabs">
      <el-tab-pane label="全部" name="all" />
      <el-tab-pane
        v-for="app in apps"
        :key="app.key"
        :name="app.key"
      >
        <template #label>
          <span class="tab-label">
            <el-icon><component :is="appIcon(app.key)" /></el-icon>{{ app.name }}
          </span>
        </template>
      </el-tab-pane>
    </el-tabs>

    <div class="toolbar">
      <el-input
        v-model="search"
        placeholder="搜索模型名称、描述或标识…"
        clearable
        class="tb-search"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <div class="spacer"></div>
      <span class="toolbar-count">共 {{ filtered.length }} 个模型</span>
      <el-button @click="jsonNew">
        <el-icon><MagicStick /></el-icon>JSON 新建
      </el-button>
      <el-button type="primary" @click="$router.push('/types/new')">
        <el-icon><Plus /></el-icon>新建模型
      </el-button>
    </div>

    <div class="entity-grid">
      <div v-for="t in filtered" :key="t.id" class="entity-tile" @click="goRecords(t)">
        <div class="icon">
          <el-icon :size="22"><component :is="entityIcon(t.key)" /></el-icon>
        </div>
        <div class="info">
          <div class="name">{{ t.name }}</div>
          <div class="desc">
            <span>{{ t.description || t.key }}</span>
            <span class="app-label">{{ t.app }}</span>
          </div>
        </div>
        <div class="count-wrap">
          <span class="count">{{ t.record_count }}</span>
          <span class="count-label">记录</span>
        </div>
        <div class="tile-menu" @click.stop>
          <el-dropdown
            trigger="click"
            placement="bottom-end"
            @command="c => onTileCommand(c, t)"
          >
            <button type="button" class="tile-menu-btn" title="更多操作" @click.stop>
              <el-icon><MoreFilled /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="records">
                  <el-icon><Document /></el-icon>查看记录
                </el-dropdown-item>
                <el-dropdown-item command="edit">
                  <el-icon><EditPen /></el-icon>编辑模型
                </el-dropdown-item>
                <el-dropdown-item command="export">
                  <el-icon><Download /></el-icon>导出 JSON
                </el-dropdown-item>
                <el-dropdown-item command="delete" divided class="dd-danger">
                  <el-icon><Delete /></el-icon>删除模型
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
    </div>

    <div v-if="!filtered.length" class="empty-state">
      <div class="empty-icon"><el-icon :size="32"><Folder /></el-icon></div>
      <template v-if="search.trim()">
        <div class="empty-title">没有匹配「{{ search }}」的模型</div>
        <div class="empty-desc">换个关键词，或清空搜索查看全部模型。</div>
        <div class="empty-actions">
          <el-button @click="search = ''">清空搜索</el-button>
        </div>
      </template>
      <template v-else>
        <div class="empty-title">还没有数据模型</div>
        <div class="empty-desc">在应用下定义实体类型（表结构），即可承载结构化与非结构化数据。也可以直接粘贴一份 JSON 建模型。</div>
        <div class="empty-actions">
          <el-button type="primary" @click="$router.push('/types/new')">
            <el-icon><Plus /></el-icon>新建模型
          </el-button>
          <el-button @click="jsonNew">
            <el-icon><MagicStick /></el-icon>JSON 新建
          </el-button>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Plus, Search, Folder, MoreFilled, Document, EditPen, Download, Delete,
} from '@element-plus/icons-vue'
import { Api } from '../api'
import { entityIcon, appIcon } from '../utils/icons'
import { downloadText, safeFileName } from '../utils/download'
import { confirmAndDeleteModel } from '../utils/modelDelete'
import PageTitle from '../components/PageTitle.vue'

const router = useRouter()
const activeApp = ref('all')
const types = ref([])
const apps = ref([])
const relDefs = ref([])
const search = ref('')
const page = ref(1)

const filtered = computed(() => {
  let arr = types.value
  if (activeApp.value !== 'all') {
    arr = arr.filter(t => t.app === activeApp.value)
  }
  if (search.value.trim()) {
    const kw = search.value.trim().toLowerCase()
    arr = arr.filter(t =>
      t.name.toLowerCase().includes(kw) ||
      (t.description || '').toLowerCase().includes(kw) ||
      (t.key || '').toLowerCase().includes(kw)
    )
  }
  return arr
})

async function load() {
  types.value = await Api.listEntityTypes()
  if (!apps.value.length) {
    apps.value = await Api.listApps()
  }
  // 关联定义的失败不影响主列表，单独兜住
  try {
    relDefs.value = await Api.listRelationDefs()
  } catch (e) {
    relDefs.value = []
  }
}

onMounted(load)

function goRecords(t) {
  router.push(`/records/${t.id}`)
}

/** 该模型参与的关联定义条数：删除会一起带走，得先告诉用户 */
function relationCount(typeId) {
  return relDefs.value.filter(
    d => d.source_type_id === typeId || d.target_type_id === typeId
  ).length
}

function onTileCommand(cmd, t) {
  if (cmd === 'records') return goRecords(t)
  if (cmd === 'edit') return router.push(`/types/${t.id}/edit`)
  if (cmd === 'export') return exportModel(t)
  if (cmd === 'delete') return removeModel(t)
}

/** 导出模型定义（不含记录）——删除前的「留个底」 */
async function exportModel(t) {
  try {
    const r = await Api.exportEntityType(t.id)
    downloadText(`${safeFileName(t.key)}.model.json`,
      r.json || JSON.stringify(r.model, null, 2))
    ElMessage.success(`已导出「${t.name}」的模型定义`)
  } catch (e) {
    // 拦截器已提示
  }
}

async function removeModel(t) {
  const ok = await confirmAndDeleteModel({ ...t, relation_count: relationCount(t.id) })
  if (ok) await load()
}

/** 从 JSON 起草模型：进编辑器并预填一份能直接跑的样例 */
function jsonNew() {
  router.push({ path: '/types/new', query: { mode: 'json' } })
}
</script>

<style scoped>
.app-tabs :deep(.el-tabs__header) { margin-bottom: var(--space-4); }
.app-tabs :deep(.el-tabs__item) { font-weight: 600; }
.tab-label { display: inline-flex; align-items: center; gap: 6px; }

.tb-search { width: 320px; }
.toolbar-count {
  font-size: var(--text-sm);
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
}

.entity-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: var(--space-3);
}
.entity-tile {
  position: relative;
  padding: 18px;
  display: flex;
  align-items: center;
  gap: 14px;
}
.entity-tile .info {
  flex: 1;
  min-width: 0;
}
.entity-tile .name {
  font-weight: 700;
  font-size: var(--text-md);
  margin-bottom: 6px;
  letter-spacing: -0.2px;
}
.entity-tile .desc {
  color: var(--text-tertiary);
  font-size: var(--text-sm);
  line-height: 1.5;
  display: flex;
  align-items: center;
  gap: 6px;
}
.entity-tile .desc span:first-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 160px;
}
.entity-tile .app-label {
  flex-shrink: 0;
  background: var(--bg-subtle);
  color: var(--text-secondary);
  padding: 1px 8px;
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: 500;
}
.entity-tile .count-wrap {
  text-align: right;
  flex-shrink: 0;
  min-width: 44px;
}
.entity-tile .count {
  display: block;
  font-size: var(--text-2xl);
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.1;
}
.entity-tile .count-label {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
.entity-tile .tile-menu {
  flex-shrink: 0;
  opacity: 0;
  transition: opacity var(--duration-fast) var(--ease-out);
}
.entity-tile:hover .tile-menu,
.entity-tile:focus-within .tile-menu {
  opacity: 1;
}
/* 触屏没有 hover：菜单必须常显，否则等于没有入口 */
@media (hover: none) {
  .entity-tile .tile-menu { opacity: 1; }
}
.tile-menu-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
  border-radius: var(--radius);
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}
.tile-menu-btn:hover {
  background: var(--bg-subtle);
  color: var(--text-primary);
}
</style>
