<template>
  <div class="notes-page">
    <div class="notes-layout">
      <!-- 分组侧栏：窄屏变成抽屉 -->
      <NoteGroupSidebar
        v-if="groupsAvailable"
        :model-value="groupId"
        class="notes-groups"
        :all-count="allCount"
        :ungrouped-count="ungroupedCount"
        :open="drawerOpen"
        @update:model-value="setGroup"
        @changed="onGroupsChanged"
        @removed="onGroupRemoved"
        @navigate="drawerOpen = false"
      />
      <div
        v-if="drawerOpen"
        class="ng-backdrop"
        aria-hidden="true"
        @click="drawerOpen = false"
      ></div>

      <div class="notes-main">
        <!-- 页头 + 工具栏合成一块「头部卡片」：
             原来标题、搜索、视图切换是三条各自独立的带子，
             看着像三段不相干的东西拼在一起。 -->
        <div class="notes-header">
          <div class="notes-head">
            <div class="notes-head-main">
              <button
                class="notes-group-toggle"
                type="button"
                aria-label="打开分组栏"
                @click="drawerOpen = true"
              >
                <el-icon><FolderOpened /></el-icon>分组
              </button>
              <h2 class="notes-head-title">知识库</h2>
              <span class="notes-head-count">{{ filterHint || `共 ${data.total || 0} 条笔记` }}</span>
            </div>
            <div class="notes-head-actions">
              <span v-if="targetGroupName" class="notes-target">
                新建到 <b>{{ targetGroupName }}</b>
              </span>
              <el-button text size="small" @click="$router.push('/knowledge/graph')">
                <el-icon><DataAnalysis /></el-icon>知识图谱
              </el-button>
              <el-button type="primary" size="small" @click="openCreate">
                <el-icon><Plus /></el-icon>新建笔记
                <kbd class="notes-kbd">⌘N</kbd>
              </el-button>
            </div>
          </div>

          <!-- 工具栏：搜索 + 视图 -->
          <div class="notes-toolbar">
            <div class="notes-search">
              <el-icon class="notes-search-icon"><Search /></el-icon>
              <input
                ref="searchRef"
                v-model="keyword"
                class="notes-search-input"
                type="search"
                placeholder="搜索标题与正文…"
                aria-label="搜索笔记"
                @input="onSearchInput"
                @keydown.enter="load(1)"
                @keydown.down.prevent="moveCursor(1)"
                @keydown.up.prevent="moveCursor(-1)"
              />
              <kbd v-if="!keyword" class="notes-search-kbd">/</kbd>
            </div>
            <div class="notes-toolbar-right">
              <!-- 当前分组（窄屏没有侧栏时，这里是唯一的分组入口） -->
              <NoteGroupSelect
                v-if="groupsAvailable"
                :model-value="groupId === null ? 0 : groupId"
                class="notes-group-select"
                :groups="groups"
                aria-label="按分组筛选"
                @change="onGroupSelect"
              />
              <el-segmented
                v-model="viewMode"
                size="small"
                :options="[
                  { label: '列表', value: 'list' },
                  { label: '网格', value: 'grid' },
                ]"
              />
            </div>
          </div>

          <!-- 标签筛选：chips，点击即筛 -->
          <div v-if="allTags.length" class="notes-tagbar">
            <button
              class="notes-tagchip is-all"
              :class="{ 'is-on': !tagFilter }"
              type="button"
              @click="setTagFilter('')"
            >全部</button>
            <button
              v-for="t in allTags"
              :key="t"
              class="notes-tagchip"
              :class="{ 'is-on': tagFilter === t }"
              type="button"
              @click="setTagFilter(t)"
            >#{{ t }}</button>
          </div>
        </div>

        <!-- 内联快速新建：不是弹窗，标题栏直接能打字 -->
        <div v-if="creating" class="notes-composer-wrap">
          <div class="notes-composer-bar">
            <span class="notes-composer-label">归属分组</span>
            <NoteGroupSelect
              v-if="groupsAvailable"
              v-model="draftGroupId"
              :groups="groups"
              aria-label="新建笔记的归属分组"
            />
            <span class="notes-composer-hint">
              {{ draftGroupId ? `将建在「${groupNameOf(draftGroupId)}」` : '将建在「未分组」' }}
            </span>
          </div>
          <NoteEditor
            v-model="draft"
            mode="quick"
            class="notes-composer"
            :tag-suggestions="allTags"
            @save="createNote"
            @cancel="creating = false"
          />
        </div>

        <!-- 列表：主界面 -->
        <ul
          v-if="visibleItems.length"
          ref="listRef"
          class="notes-list"
          :class="{ 'is-grid': viewMode === 'grid' }"
          role="listbox"
          aria-label="笔记列表"
          tabindex="-1"
        >
          <li
            v-for="(n, idx) in visibleItems"
            :key="n.id"
            class="note-row"
            :class="{ 'is-active': idx === cursor }"
            role="option"
            :aria-selected="idx === cursor"
            tabindex="-1"
            @click="openNote(n.id)"
            @mouseenter="cursor = idx"
          >
            <span class="note-row-icon"><el-icon><Document /></el-icon></span>
            <div class="note-row-body">
              <div class="note-row-top">
                <span class="note-row-title">{{ titleOf(n) }}</span>
                <span v-if="!n.data?.content" class="note-row-empty">空</span>
                <span class="note-row-chips">
                  <button
                    v-for="t in (n.data?.tags || []).slice(0, 4)"
                    :key="t"
                    class="note-chip"
                    type="button"
                    :title="`按 #${t} 筛选`"
                    @click.stop="setTagFilter(t)"
                  >#{{ t }}</button>
                </span>
              </div>
              <div class="note-row-snippet">{{ snippetOf(n) }}</div>
            </div>
            <div class="note-row-meta">
              <!-- 正在按某个分组看的时候，每行都挂同一个分组标签是纯噪音。
                   但位置要留着（占位），不然时间的竖线会一列列地抖。 -->
              <span
                v-if="groupsAvailable"
                class="note-row-group-slot"
                :class="{ 'is-hidden': inFilteredGroup(n) }"
              >
                <NoteGroupBadge
                  v-if="!inFilteredGroup(n)"
                  :name="groupNameOf(groupIdOfNote(n))"
                  :color="groupColorOfNote(n)"
                  :muted="!groupIdOfNote(n)"
                />
              </span>
              <span class="note-row-time" :title="formatTime(n.updated_at)">
                {{ relativeOf(n) }}
              </span>
              <button
                class="note-row-del"
                type="button"
                :aria-label="`删除笔记 ${titleOf(n)}`"
                title="删除"
                @click.stop="confirmDelete(n)"
              >
                <el-icon><Delete /></el-icon>
              </button>
            </div>
          </li>
        </ul>

        <!-- 空状态 -->
        <div v-if="!visibleItems.length && !loading" class="notes-empty">
          <template v-if="isGroupEmpty">
            <div class="notes-empty-icon">
              <el-icon :size="26"><FolderOpened /></el-icon>
            </div>
            <div class="notes-empty-title">这个分组还是空的</div>
            <div class="notes-empty-desc">
              在「{{ targetGroupName || '未分组' }}」里新建第一篇笔记，
              之后按分组就能直接找到它。
            </div>
            <div class="notes-empty-actions">
              <el-button type="primary" size="small" @click="openCreate">
                <el-icon><Plus /></el-icon>新建第一篇
              </el-button>
            </div>
          </template>
          <template v-else>
            <div class="notes-empty-icon"><el-icon :size="26"><Document /></el-icon></div>
            <div class="notes-empty-title">
              {{ keyword || tagFilter ? '没有匹配的笔记' : '还没有笔记' }}
            </div>
            <div class="notes-empty-desc">
              {{ keyword || tagFilter
                ? '换个关键词，或清掉标签筛选再看看。'
                : '随手记一条：用 [[双链]] 把想法串起来，所有笔记都能被检索和图谱找到。' }}
            </div>
            <div v-if="!keyword && !tagFilter" class="notes-empty-actions">
              <el-button type="primary" size="small" @click="openCreate">
                <el-icon><Plus /></el-icon>新建笔记
              </el-button>
            </div>
          </template>
        </div>

        <!-- 分页：按标签筛选时是全量过滤，不再分页；
             分组筛选时如果后端已支持服务端过滤，分页照常（total 是该组的总数） -->
        <el-pagination
          v-if="visibleItems.length && !tagFilter && (groupId === null || serverFiltered)"
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="data.total || 0"
          layout="total, prev, pager, next, jumper"
          @current-change="load()"
          @size-change="load(1)"
          class="notes-pager"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  DataAnalysis, Delete, Document, FolderOpened, Plus, Search,
} from '@element-plus/icons-vue'
import { Api } from '../api'
import { formatTime } from '../utils/format'
import { firstLineTitle, noteSnippet, noteTitle, relativeTime } from '../utils/notes'
import NoteEditor from '../components/NoteEditor.vue'
import NoteGroupSidebar from '../components/note/NoteGroupSidebar.vue'
import NoteGroupSelect from '../components/note/NoteGroupSelect.vue'
import NoteGroupBadge from '../components/note/NoteGroupBadge.vue'
import { useNoteGroups } from '../components/note/useNoteGroups'

const router = useRouter()
const route = useRoute()
const noteTypeId = ref(null)
const data = ref({ items: [], total: 0 })
const keyword = ref('')
const tagFilter = ref('')
const allTags = ref([])
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const viewMode = ref('list')

// 分组：null = 全部笔记；0 = 未分组；>0 = 具体分组 id
const groupId = ref(null)
const allCount = ref(0)
// 是否已经拿到过「全体笔记数」（直接用带分组的链接进来时需要单独问一次）
const allCountKnown = ref(false)
const drawerOpen = ref(false)
// 后端是否已经按 group_id 服务端过滤（false = 前端兜底在筛）
const serverFiltered = ref(true)

// 内联快速新建
const creating = ref(false)
const draft = ref({ title: '', content: '', tags: [] })
const draftGroupId = ref(0)

// 键盘游标（选中项）
const cursor = ref(-1)
const listRef = ref(null)
const searchRef = ref(null)

let searchTimer = null

const { groups, available: groupsAvailable, load: loadGroups, groupOf } = useNoteGroups()

// 标签筛选是前端过滤（后端列表接口没有 tag 参数），
// 所以选中标签时一次性把笔记全部拉下来再筛，否则只会筛到当前页。
const filtered = computed(() => {
  let list = data.value.items || []
  if (tagFilter.value) {
    const key = tagFilter.value.toLowerCase()
    list = list.filter(n =>
      (n.data?.tags || []).some(t => String(t).toLowerCase() === key)
    )
  }
  // 分组筛选走服务端（?group_id=N）。只有「后端还没支持这个参数」时
  // 才由前端兜底筛一遍（见 load 里的兼容分支）。
  if (groupId.value !== null && !serverFiltered.value) {
    list = list.filter(n => groupIdOfNote(n) === groupId.value)
  }
  return list
})
const visibleItems = computed(() => filtered.value)

const filterHint = computed(() => {
  const bits = []
  if (groupId.value !== null) bits.push(`分组「${targetGroupName.value}」`)
  if (tagFilter.value) bits.push(`#${tagFilter.value}`)
  if (!bits.length) return ''
  const n = serverFiltered.value ? (data.value.total || 0) : filtered.value.length
  return `${bits.join(' · ')} · ${n} 篇`
})

// 当前分组的显示名（未分组 / 全部）
const targetGroupName = computed(() => {
  if (groupId.value === null) return ''
  if (groupId.value === 0) return '未分组'
  return groupNameOf(groupId.value)
})

/**
 * 未分组笔记数 = 全部笔记数 − Σ 各分组 count
 * ---------------------------------------------------------------------------
 * 分组数直接用接口给的 count（后端已经按「记录形态的笔记」算），
 * 全部笔记数用列表接口的 total —— 两个口径都是「记录」，对得上。
 * 注意：total 只在「没按分组筛选」时取（筛过分组时 total 是那一组的数）。
 */
const ungroupedCount = computed(() => {
  const inGroups = groups.value.reduce((sum, g) => sum + (g.count || 0), 0)
  return Math.max(0, allCount.value - inGroups)
})
// 某个分组是不是空的（空状态要区别「空分组」和「筛选无果」）
const isGroupEmpty = computed(() =>
  groupId.value !== null && !keyword.value && !tagFilter.value)

function titleOf(n) {
  return noteTitle(n, n?.id)
}

function snippetOf(n) {
  return noteSnippet(n?.data?.content || '', 160) || '（空笔记）'
}

function relativeOf(n) {
  return relativeTime(n?.updated_at)
}

/** 笔记的分组 id（0 = 未分组） */
function groupIdOfNote(n) {
  return Number(n?.data?.group_id || 0)
}

function groupNameOf(id) {
  if (!id) return '未分组'
  return groupOf(id)?.name || '未分组'
}

function groupColorOfNote(n) {
  const gid = groupIdOfNote(n)
  return gid ? (groupOf(gid)?.color || '') : ''
}

/** 这篇笔记是不是正在看的那个分组里的？
 *  是的话就别在每行重复挂同一个分组标签了 —— 一屏 20 行全是「未分组」，
 *  看着像故障，其实只是没用的重复。 */
function inFilteredGroup(n) {
  if (groupId.value === null) return false
  return groupIdOfNote(n) === groupId.value
}

async function load(p) {
  if (!noteTypeId.value) return
  if (p) page.value = p
  loading.value = true
  try {
    const tagFiltering = !!tagFilter.value
    const groupFiltering = groupId.value !== null
    // 标签筛选是前端做的（列表接口没有 tag 参数），所以标签筛选时一次性拉全量
    const params = {
      page: tagFiltering ? 1 : page.value,
      page_size: tagFiltering ? 500 : pageSize.value,
      keyword: keyword.value,
    }
    // 分组筛选走服务端：?group_id=N（0 = 未分组，不传 = 不过滤）
    if (groupFiltering) params.group_id = groupId.value
    let res = await Api.listRecords(noteTypeId.value, params)
    // 兼容分支：后端还没支持 group_id 过滤时，响应里会混着别的分组的笔记。
    // 这时退回「全量拉 + 本地筛」，免得整个知识库都显示在一个分组下。
    // 后端一旦支持了，这个分支自动不再触发（响应里全是本组的笔记）。
    if (groupFiltering && !tagFiltering && looksUnfiltered(res.items)) {
      res = await Api.listRecords(noteTypeId.value, {
        page: 1, page_size: 500, keyword: params.keyword,
      })
      serverFiltered.value = false
    } else {
      serverFiltered.value = true
    }
    data.value = res
    const tags = new Set()
    for (const n of (data.value.items || [])) {
      for (const t of (n.data?.tags || [])) {
        if (t) tags.add(t)
      }
    }
    allTags.value = [...tags].sort((a, b) => a.localeCompare(b, 'zh'))
    // 全部笔记数：列表的 total 在「按分组筛选」时是「那一组」的数，
    // 侧栏的「全部笔记 / 未分组」要的是全体 —— 这时单独问一次（只取 1 条，只要 total）
    if (groupId.value === null) {
      allCount.value = data.value.total || 0
      allCountKnown.value = true
    } else if (!allCountKnown.value) {
      try {
        const all = await Api.listRecords(noteTypeId.value, { page: 1, page_size: 1 })
        allCount.value = all.total || 0
        allCountKnown.value = true
      } catch (e) {
        // 拿不到就算了：侧栏显示 0，也不至于报错
      }
    }
    // 游标保持在合法范围内
    if (cursor.value >= visibleItems.value.length) cursor.value = visibleItems.value.length - 1
  } finally {
    loading.value = false
  }
}

/** 响应里是不是混着别的分组的笔记（= 后端没按 group_id 过滤） */
function looksUnfiltered(items) {
  if (!items || !items.length) return false
  return items.some(n => groupIdOfNote(n) !== groupId.value)
}

function onSearchInput() {
  // 搜索框与列表联动：输入即筛（防抖，别每敲一个字都打后端）
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => load(1), 250)
}

function setTagFilter(t) {
  tagFilter.value = tagFilter.value === t ? '' : t
  cursor.value = -1
  load(1)
}

/** 切换分组：保留搜索词，重置到第 1 页，地址栏带上分组参数 */
function setGroup(id) {
  const next = id === null ? null : Number(id)
  if (next === groupId.value) return
  groupId.value = next
  cursor.value = -1
  page.value = 1
  syncUrl()
  load(1)
}

// 侧栏选中 / 工具栏下拉选中
function onGroupSelect(id) {
  setGroup(id)
}

/** 地址栏同步：#/notes?group=3 —— 刷新后还在原分组 */
function syncUrl() {
  const next = groupId.value === null ? undefined : String(groupId.value)
  const cur = route.query.group
  const curStr = cur == null ? undefined : String(Array.isArray(cur) ? cur[0] : cur)
  if (curStr === next) return
  router.replace({
    path: '/notes',
    query: groupId.value === null ? {} : { group: next },
  }).catch(() => {})
}

/** 从地址栏解析分组参数（刷新 / 直接贴链接进来） */
function parseGroupParam(v) {
  if (v == null || v === '' || v === 'all') return null
  const n = Number(Array.isArray(v) ? v[0] : v)
  if (!Number.isFinite(n) || n < 0) return null
  return n
}

function onGroupsChanged() {
  // 分组变了（新建/改名/删除）→ 刷新列表里的分组信息
  load()
}

/**
 * 分组被删了：把记录侧的归属也改掉
 * ---------------------------------------------------------------------------
 * 新契约里后端删分组会顺手清掉记录上的 data.group_id；
 * 但后端还在切换期时它可能只清了 document 侧（或者还没上线）。
 * 所以前端这里做一次兜底：把「还在指着一个已删分组」的笔记改成未分组。
 *
 * 要按全量找，不能只看当前列表 —— 被删的分组可能不是当前选中的那个，
 * 它的笔记此刻根本不在页面上。
 */
async function onGroupRemoved({ group, moveTo }) {
  const next = moveTo || null
  let affected = (data.value.items || []).filter(n => groupIdOfNote(n) === group.id)
  if (!affected.length) {
    // 当前列表里没有 → 按全量找一次
    try {
      const all = await Api.listRecords(noteTypeId.value, { page: 1, page_size: 500 })
      affected = (all.items || []).filter(n => groupIdOfNote(n) === group.id)
    } catch (e) {
      affected = []
    }
  }
  if (!affected.length) {
    load()
    return
  }
  let failed = 0
  for (const n of affected) {
    try {
      await Api.updateRecord(n.id, { ...(n.data || {}), group_id: next })
    } catch (e) {
      failed++
    }
  }
  if (failed) {
    ElMessage.warning(`有 ${failed} 篇笔记没能改归属，刷新后再试一次`)
  }
  load()
}

function openNote(id) {
  router.push(`/notes/${id}`)
}

function openCreate() {
  draft.value = { title: '', content: '', tags: [] }
  // 当前选中的是某个分组 → 笔记直接建到该分组
  draftGroupId.value = groupId.value === null ? 0 : groupId.value
  creating.value = true
}

async function createNote() {
  const content = draft.value.content || ''
  // Obsidian 行为：没起标题就用正文首行当标题；都空了就先建空笔记（先建后填）
  const title = (draft.value.title || '').trim() || firstLineTitle(content)
  try {
    const r = await Api.createRecord(noteTypeId.value, {
      title,
      content,
      tags: draft.value.tags,
      // 分组归属存在 data.group_id：null = 未分组
      group_id: draftGroupId.value || null,
    })
    if (content) {
      await Api.syncNoteLinks(r.id, content)
    }
    ElMessage.success('已创建')
    creating.value = false
    // 新建完直接进详情页继续写（Obsidian 的「新建文件 → 光标已在正文里」）
    router.push(`/notes/${r.id}`)
  } catch (e) {
    ElMessage.error('创建失败：' + (e?.message || e))
  }
}

async function confirmDelete(note) {
  try {
    await ElMessageBox.confirm(
      `确定删除笔记「${titleOf(note)}」？反向链接和正链都会被解除。`,
      '删除笔记',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
    await Api.deleteRecord(note.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    if (e === 'cancel' || e?.code === 'cancel' || e?.message === 'cancel') return
    ElMessage.error('删除失败：' + (e?.message || e))
  }
}

// ============ 键盘优先（Obsidian 的手感）============
function moveCursor(delta) {
  const total = visibleItems.value.length
  if (!total) return
  let next = cursor.value + delta
  if (cursor.value < 0) next = delta > 0 ? 0 : total - 1
  cursor.value = Math.min(Math.max(next, 0), total - 1)
  // 选中项滚进视野
  nextTick(() => {
    const el = listRef.value?.querySelector('.note-row.is-active')
    el?.scrollIntoView({ block: 'nearest' })
  })
}

function onKeydown(e) {
  const el = e.target
  const tag = el?.tagName
  const typing = tag === 'INPUT' || tag === 'TEXTAREA' || el?.isContentEditable
  const inSearch = el === searchRef.value
  const inComposer = !!el?.closest?.('.notes-composer')

  // ⌘/Ctrl + N —— 新建笔记
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'n') {
    e.preventDefault()
    openCreate()
    return
  }
  // 快速新建开着时，Esc 一律取消（焦点在编辑器内由编辑器自己处理，这里是兜底）
  if (e.key === 'Escape' && creating.value) {
    // 有弹窗（删除确认等）时不抢 Esc
    if (document.querySelector('.el-overlay, .el-message-box__wrapper')) return
    e.preventDefault()
    creating.value = false
    return
  }
  // 编辑器内部的按键不参与列表导航
  if (inComposer) return
  // / —— 聚焦搜索（Obsidian 的老习惯）
  if (e.key === '/' && !typing) {
    e.preventDefault()
    searchRef.value?.focus()
    return
  }
  if (typing && !inSearch) return

  if (e.key === 'ArrowDown') {
    e.preventDefault()
    moveCursor(1)
    return
  }
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    moveCursor(-1)
    return
  }
  // 回车打开选中的笔记 —— 但焦点在按钮上时让按钮自己处理
  // （否则侧栏项上按回车会「切分组」的同时又「打开笔记」）
  const onButton = el?.closest?.('button, a, [role="button"]')
  if (e.key === 'Enter' && !onButton && cursor.value >= 0 && visibleItems.value[cursor.value]) {
    e.preventDefault()
    openNote(visibleItems.value[cursor.value].id)
  }
}

onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  groupId.value = parseGroupParam(route.query.group)
  const et = await Api.getEntityTypeByKey('note')
  noteTypeId.value = et.id
  // 分组接口可能还没上线：不可用时安静降级（隐藏侧栏），不弹错误。
  // force=true：每次进页面都重新拉一次 —— 计数会随「笔记挪进/挪出分组」变，
  // 缓存住旧数会让侧栏显示「组里 0 篇」而列表里明明有。
  await loadGroups(true)
  await load(1)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  clearTimeout(searchTimer)
})

// 地址栏里的分组参数变了（用户改了 hash / 前进后退）→ 跟着切
watch(() => route.query.group, (v) => {
  const next = parseGroupParam(v)
  if (next === groupId.value) return
  groupId.value = next
  cursor.value = -1
  page.value = 1
  load(1)
})
</script>

<style scoped>
.notes-page {
  padding: var(--space-5) var(--space-6) var(--space-6);
  /* 铺满可用宽度：知识库是主工作区，不该缩在中间一小条。
     （原来 max-width:1320px + 内部 grid 236px+1fr，
       在宽屏上内容只占中间 1000px，两侧一大片空白） */
  width: 100%;
  max-width: 1560px;
  margin: 0 auto;
  /* 撑满视口高度：列表区自己滚动，分页钉在底部。
     不这样的话，笔记少的时候下面就是一大片空白 */
  min-height: 100%;
  display: flex;
  flex-direction: column;
}

/* 两栏：分组侧栏 + 笔记主区 */
.notes-layout {
  display: grid;
  grid-template-columns: 232px minmax(0, 1fr);
  gap: var(--space-5);
  align-items: start;
  flex: 1;
  min-height: 0;
}
.notes-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
}

/* 页头 + 工具栏 + 标签条：合成一块头部卡片 */
.notes-header {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  padding: 14px 16px 12px;
  margin-bottom: var(--space-4);
}

/* 页头 */
.notes-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-3);
  flex-wrap: wrap;
}
.notes-head-main {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  min-width: 0;
}
.notes-head-title {
  margin: 0;
  font-size: var(--text-2xl);
  font-weight: 650;
  letter-spacing: -0.5px;
  font-family: var(--font-display);
  color: var(--text-primary);
}
.notes-head-count {
  font-size: var(--text-sm);
  color: var(--text-tertiary);
}
.notes-head-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.notes-target {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  background: var(--primary-bg);
  color: var(--primary-dark);
  border-radius: var(--radius-full);
  padding: 2px 10px;
}
html.dark .notes-target { color: var(--primary-light); }
.notes-kbd {
  font-family: var(--font-mono);
  font-size: 10px;
  line-height: 15px;
  padding: 0 4px;
  margin-left: 6px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-subtle);
  color: var(--text-secondary);
}

/* 窄屏的分组抽屉开关 */
.notes-group-toggle {
  display: none;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-card);
  color: var(--text-secondary);
  font-size: var(--text-sm);
  cursor: pointer;
}
.notes-group-toggle:hover { background: var(--bg-subtle); color: var(--text-primary); }

/* 工具栏 */
.notes-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}
/* 标签条是头部的最后一块，贴着卡片底 */
.notes-header .notes-tagbar { margin-bottom: 0; }
.notes-search {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  max-width: 420px;
  height: 32px;
  padding: 0 10px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--bg-card);
  transition: border-color var(--duration-fast) var(--ease-out), box-shadow var(--duration-fast);
}
.notes-search:focus-within {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-ring);
}
.notes-search-icon { color: var(--text-tertiary); }
.notes-search-input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text-primary);
  font-size: var(--text-sm);
}
.notes-search-input::-webkit-search-cancel-button { cursor: pointer; }
.notes-search-kbd {
  font-family: var(--font-mono);
  font-size: 10px;
  line-height: 16px;
  padding: 0 5px;
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text-tertiary);
  background: var(--bg-subtle);
}
.notes-toolbar-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

/* 标签筛选条 */
.notes-tagbar {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: var(--space-3);
}
.notes-tagchip {
  border: 1px solid var(--border-light);
  background: var(--bg-subtle);
  color: var(--text-secondary);
  border-radius: var(--radius-full);
  padding: 2px 10px;
  font-size: var(--text-xs);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}
.notes-tagchip:hover {
  border-color: var(--primary-light);
  color: var(--primary-dark);
}
html.dark .notes-tagchip:hover { color: var(--primary-light); }
.notes-tagchip.is-on {
  background: var(--primary-bg);
  border-color: var(--primary-light);
  color: var(--primary-dark);
  font-weight: 600;
}
html.dark .notes-tagchip.is-on { color: var(--primary-light); }
.notes-tagchip.is-all { color: var(--text-tertiary); }

/* 快速新建 */
.notes-composer-wrap { margin-bottom: var(--space-3); }
.notes-composer-bar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: 6px;
}
.notes-composer-label {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
.notes-composer-hint {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
.notes-composer { margin-bottom: 0; }

/* 列表 */
.notes-list {
  list-style: none;
  margin: 0;
  padding: 0;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  background: var(--bg-card);
  overflow: hidden;
  /* 列表占满剩余高度（笔记少时不会在下面留一大片空白） */
  flex: 1;
  min-height: 0;
  align-content: start;
}
.notes-list:focus { outline: none; }

.note-row {
  position: relative;
  display: grid;
  /* 图标 | 正文 | 右侧信息列
     右侧一列固定宽度 —— 归属/时间/删除按钮上下对齐成一条竖线，
     不会因为标题长短而东倒西歪 */
  grid-template-columns: 18px minmax(0, 1fr) auto;
  align-items: center;
  column-gap: 12px;
  padding: 11px 14px 12px;
  border-bottom: 1px solid var(--border-light);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
}
.note-row:last-child { border-bottom: none; }
.note-row:hover { background: var(--bg-subtle); }
.note-row.is-active { background: var(--primary-bg); }
.note-row.is-active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 2px;
  background: var(--primary);
}

.note-row-icon {
  color: var(--text-tertiary);
  margin-top: 2px;
  flex-shrink: 0;
  transition: color var(--duration-fast);
}
.note-row:hover .note-row-icon,
.note-row.is-active .note-row-icon { color: var(--primary); }

.note-row-body {
  min-width: 0;
}
.note-row-top {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}
.note-row-title {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  /* 标题不再卡在 60% —— 右边那一列宽度固定，正文列自然就宽了 */
  max-width: none;
  min-width: 0;
}
.note-row-empty {
  flex-shrink: 0;
  font-size: 10px;
  color: var(--text-disabled);
  border: 1px solid var(--border-light);
  border-radius: 3px;
  padding: 0 4px;
}
.note-row-chips {
  display: flex;
  align-items: center;
  gap: 4px;
  overflow: hidden;
}
.note-chip {
  border: none;
  background: var(--primary-bg);
  color: var(--primary-dark);
  border-radius: var(--radius-xs);
  padding: 1px 6px;
  font-size: var(--text-xs);
  line-height: 1.5;
  cursor: pointer;
  white-space: nowrap;
}
html.dark .note-chip { color: var(--primary-light); }
.note-chip:hover { background: var(--primary-bg-strong); }

.note-row-snippet {
  margin-top: 2px;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  line-height: 1.6;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.note-row-meta {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-shrink: 0;
  /* 固定一列宽度：归属标签、时间、删除按钮成一条竖线对齐。
     宽度给得松一点，标签出现/消失时右边不会跟着跳 */
  min-width: 150px;
}
/* 分组标签的位置给它留出来（没有标签时留白），
   这样「有没有分组」不会把时间列推来推去 */
.note-row-group-slot {
  display: inline-flex;
  align-items: center;
  max-width: 110px;
  flex: 0 0 auto;
}
.note-row-group-slot.is-hidden { visibility: hidden; }
.note-row-time {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  min-width: 62px;
  text-align: right;
}
.note-row-del {
  border: none;
  background: transparent;
  color: var(--text-disabled);
  cursor: pointer;
  padding: 2px;
  border-radius: 4px;
  opacity: 0;
  transition: opacity var(--duration-fast), color var(--duration-fast);
}
.note-row:hover .note-row-del,
.note-row.is-active .note-row-del { opacity: 1; }
.note-row-del:hover { color: var(--danger); background: var(--danger-bg); }

/* 网格视图 */
.notes-list.is-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(258px, 1fr));
  gap: 1px;
  background: var(--border-light);
}
.notes-list.is-grid .note-row {
  /* 网格视图改成单列堆叠（.note-row 已经是 grid 了，
     这里把三列摊平成一列） */
  grid-template-columns: minmax(0, 1fr);
  grid-template-areas:
    'icon'
    'body'
    'meta';
  gap: 6px;
  padding: 12px 14px;
  background: var(--bg-card);
  border-bottom: none;
}
.notes-list.is-grid .note-row-icon { grid-area: icon; }
.notes-list.is-grid .note-row-body { grid-area: body; }
.notes-list.is-grid .note-row-meta {
  grid-area: meta;
  width: 100%;
  justify-content: space-between;
  min-width: 0;
}
.notes-list.is-grid .note-row.is-active { background: var(--primary-bg); }
.notes-list.is-grid .note-row-top { flex-wrap: wrap; gap: 4px 8px; }
.notes-list.is-grid .note-row-title { max-width: 100%; white-space: normal; }
.notes-list.is-grid .note-row-snippet {
  white-space: normal;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  min-height: 3em;
}

/* 空状态 */
.notes-empty {
  padding: 48px 20px;
  text-align: center;
  border: 1px dashed var(--border);
  border-radius: var(--radius-md);
}
.notes-empty-icon {
  color: var(--text-disabled);
  margin-bottom: 10px;
}
.notes-empty-title {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 6px;
}
.notes-empty-desc {
  font-size: var(--text-sm);
  color: var(--text-tertiary);
  line-height: 1.7;
  max-width: 420px;
  margin: 0 auto;
}
.notes-empty-actions { margin-top: 14px; }

.notes-pager {
  margin-top: var(--space-4);
  justify-content: flex-end;
  flex-shrink: 0;
}

/* ============ 窄屏：侧栏变抽屉 ============ */
.ng-backdrop {
  position: fixed;
  inset: 0;
  z-index: 190;
  background: rgba(10, 11, 15, 0.42);
}

@media (max-width: 959px) {
  .notes-page { padding: var(--space-4); }
  .notes-layout { grid-template-columns: minmax(0, 1fr); }
  .notes-group-toggle { display: inline-flex; }
  /* 侧栏变成左侧抽屉：默认滑出屏幕，选中分组后自动收起 */
  .notes-layout .ng-sidebar {
    position: fixed;
    left: 0;
    top: 0;
    bottom: 0;
    z-index: 200;
    width: 258px;
    max-height: none;
    border-radius: 0;
    border-left: none;
    border-top: none;
    border-bottom: none;
    transform: translateX(-100%);
    transition: transform var(--duration) var(--ease-out);
    overflow-y: auto;
  }
  .notes-layout .ng-sidebar.is-open { transform: none; }
  .notes-toolbar { flex-wrap: wrap; }
  .notes-search { max-width: none; }
  .notes-toolbar-right { margin-left: 0; width: 100%; justify-content: space-between; }

  /* 窄屏：右侧信息列别占那么宽 —— 标题正文才是主角 */
  .note-row-meta { min-width: 0; gap: 8px; }
  .note-row-group-slot { max-width: 90px; }
  .note-row-time { min-width: 0; }
  .notes-page { padding: var(--space-4) var(--space-4) var(--space-5); }
}
</style>
