<template>
  <el-dialog
    v-model="open"
    class="workspace-command-dialog"
    title="快速搜索"
    width="min(580px, calc(100vw - 32px))"
    top="12vh"
    append-to-body
    @open="reset"
    @opened="field?.focus()"
  >
    <div class="command-body">
      <label class="command-field">
        <el-icon aria-hidden="true"><Search /></el-icon>
        <input
          ref="field"
          v-model="query"
          type="text"
          role="combobox"
          aria-label="搜索功能或内容"
          aria-autocomplete="list"
          :aria-expanded="Boolean(options.length)"
          :aria-controls="options.length ? 'workspace-command-results' : undefined"
          :aria-activedescendant="options.length ? optionId(selected) : undefined"
          placeholder="搜索功能或内容…"
          autocomplete="off"
          @keydown="onInputKey"
        />
      </label>
      <ul
        v-if="options.length"
        id="workspace-command-results"
        ref="results"
        class="command-results"
        role="listbox"
        aria-label="搜索结果"
      >
        <li v-for="(item, index) in options" :key="item.key" role="presentation">
          <RouterLink
            :id="optionId(index)"
            :to="item.to"
            class="command-option"
            :class="{ 'is-selected': selected === index }"
            role="option"
            :aria-selected="selected === index"
            @focus="selected = index"
            @click="open = false"
          >
            <el-icon aria-hidden="true"><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
            <el-icon v-if="selected === index" class="command-enter" aria-hidden="true"><Right /></el-icon>
          </RouterLink>
        </li>
      </ul>
      <p v-if="!matches.length" class="command-empty" role="status">{{ term ? '没有匹配的功能' : '暂无可访问的功能' }}</p>
      <div v-if="options.length" class="command-keys" aria-hidden="true">
        <span><kbd>↑</kbd> <kbd>↓</kbd> 选择</span>
        <span><kbd>↵</kbd> 打开</span>
        <span><kbd>Esc</kbd> 关闭</span>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { searchWorkspaceCommands } from '../../utils/workspaceNavigation'

const open = defineModel({ type: Boolean, required: true })
const props = defineProps({
  groups: { type: Array, required: true },
  primary: { type: Array, required: true },
  canSearch: Boolean,
})
const router = useRouter()
const query = ref('')
const selected = ref(0)
const field = ref(null)
const results = ref(null)
const term = computed(() => query.value.trim())
const matches = computed(() => term.value
  ? searchWorkspaceCommands(props.groups, term.value)
  : props.primary.length ? props.primary : searchWorkspaceCommands(props.groups, ''))
const options = computed(() => {
  const entries = matches.value.map(item => ({ ...item, key: item.path, to: item.path }))
  if (term.value && props.canSearch) {
    entries.unshift({
      key: 'content-search',
      to: { name: 'search', query: { kw: term.value } },
      icon: 'Search',
      label: `搜索内容“${term.value}”`,
    })
  }
  return entries
})

watch(options, () => { selected.value = 0 })

function optionId(index) {
  return `workspace-command-option-${index}`
}

function reset() {
  query.value = ''
  selected.value = 0
  if (results.value) results.value.scrollTop = 0
}

function onInputKey(event) {
  const count = options.value.length
  if (!count || event.isComposing || event.keyCode === 229) return
  if (event.key === 'Enter') {
    event.preventDefault()
    const item = options.value[selected.value]
    if (item) {
      open.value = false
      router.push(item.to)
    }
  } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    event.stopPropagation()
    const step = event.key === 'ArrowDown' ? 1 : -1
    selected.value = (selected.value + step + count) % count
    nextTick(() => document.getElementById(optionId(selected.value))?.scrollIntoView({ block: 'nearest' }))
  }
}
</script>

<style scoped>
.command-field {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 0 var(--space-4);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg);
  color: var(--text-tertiary);
}
.command-field:focus-within { border-color: var(--primary); }
.command-field input {
  flex: 1;
  width: 100%;
  min-height: 44px;
  padding: 0;
  border: 0;
  outline: none;
  background: transparent;
  color: var(--text-primary);
  font: inherit;
  font-size: var(--text-lg);
}
.command-field input::placeholder { color: var(--text-tertiary); }
.command-results {
  display: grid;
  gap: 3px;
  max-height: min(42vh, 320px);
  overflow: auto;
  list-style: none;
  margin: var(--space-3) 0 0;
  padding: 2px;
}
.command-option {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-height: 42px;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius);
  color: var(--text-secondary);
  text-decoration: none;
  overflow-wrap: anywhere;
}
.command-option.is-selected { background: var(--primary-bg-strong); color: var(--primary); }
.command-option:hover { background: var(--bg-subtle); }
.command-option .el-icon { flex: none; }
.command-enter { margin-left: auto; }
.command-empty { margin: var(--space-3) 0; color: var(--text-tertiary); }
.command-keys {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  margin-top: var(--space-4);
  padding-top: var(--space-3);
  border-top: 1px solid var(--border-light);
  color: var(--text-tertiary);
  font-size: var(--text-xs);
}
.command-keys kbd { font-family: var(--font-mono); }
@media (max-width: 768px) {
  .command-keys { display: none; }
  .command-results { max-height: none; }
}
</style>
