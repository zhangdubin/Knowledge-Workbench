<template>
  <!--
    标签 chips 输入器（Obsidian 的 Properties → Tags）
    ---------------------------------------------------------------------------
    交互约定：
      - 输入 #  → 弹出已有标签候选
      - 输入文字 → 按包含匹配候选
      - 回车 / 逗号 / 中文逗号 → 确认当前输入
      - 退格（输入框为空时）→ 删掉最后一个标签
      - × → 删除对应标签
      - 点击候选 / 点击已有标签 → 直接复用
    之所以自己写而不用 el-select / el-tag 的组合：
    那些控件一次只能编辑一个值，做不到「输入 # 触发候选」这种随手记的节奏。
  -->
  <div ref="rootRef" class="tag-input" :class="{ 'is-focused': focused, 'is-empty': !modelValue.length }">
    <span
      v-for="t in modelValue"
      :key="t"
      class="tag-chip"
    >
      <button
        type="button"
        class="tag-chip-name"
        :title="`复用标签 #${t}`"
        @click="emit('tag-click', t)"
      >#{{ t }}</button>
      <button
        type="button"
        class="tag-chip-x"
        :aria-label="`移除标签 ${t}`"
        @click="remove(t)"
      >×</button>
    </span>

    <input
      ref="inputRef"
      v-model="text"
      class="tag-field"
      type="text"
      :placeholder="placeholder"
      :aria-label="ariaLabel"
      role="combobox"
      aria-autocomplete="list"
      :aria-expanded="showSuggestions"
      @focus="focused = true"
      @blur="onBlur"
      @input="onInput"
      @keydown="onKeydown"
    />

    <ul v-if="showSuggestions" class="tag-suggest" role="listbox" :aria-label="ariaLabel">
      <li
        v-for="(s, i) in suggestions"
        :key="s"
        class="tag-suggest-item"
        :class="{ 'is-active': i === activeIndex }"
        role="option"
        :aria-selected="i === activeIndex"
        @mousedown.prevent="pick(s)"
        @mouseenter="activeIndex = i"
      >
        <span class="tag-suggest-name">#{{ s }}</span>
        <span v-if="s.toLowerCase() === queryText.toLowerCase()" class="tag-suggest-new">新建</span>
      </li>
      <li v-if="!suggestions.length" class="tag-suggest-empty">
        回车新建标签「{{ queryText }}」
      </li>
    </ul>
  </div>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { matchTags, normalizeTags } from '../utils/notes'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  // 已有标签（用来给候选）
  suggestions: { type: Array, default: () => [] },
  placeholder: { type: String, default: '添加标签（输入 # 或 , 确认）' },
  ariaLabel: { type: String, default: '笔记标签' },
})
const emit = defineEmits(['update:modelValue', 'tag-click'])

const text = ref('')
const focused = ref(false)
const activeIndex = ref(0)
const inputRef = ref(null)
const rootRef = ref(null)

// 候选用纯函数算：输入 # 时给出全部，输入文字时按包含匹配
const queryText = computed(() => text.value.replace(/^#+/, '').trim())
const suggestions = computed(() => {
  // 已经在标签里的不再重复出现
  const used = new Set(props.modelValue.map(t => t.toLowerCase()))
  return matchTags(queryText.value, props.suggestions, 8).filter(t => !used.has(t.toLowerCase()))
})
const showSuggestions = computed(() => focused.value && (text.value.length > 0 || props.suggestions.length > 0))

function addTag(raw) {
  const t = String(raw ?? '').trim().replace(/^#+/, '').trim()
  if (!t) return
  const next = normalizeTags([...props.modelValue, t])
  if (next.length !== props.modelValue.length) {
    emit('update:modelValue', next)
  }
  text.value = ''
  activeIndex.value = 0
}

function remove(t) {
  emit('update:modelValue', props.modelValue.filter(x => x !== t))
}

function pick(s) {
  addTag(s)
  nextTick(() => inputRef.value?.focus())
}

function onInput() {
  activeIndex.value = 0
}

function onKeydown(e) {
  // 回车：优先吃掉候选，否则确认当前输入
  if (e.key === 'Enter') {
    e.preventDefault()
    const s = suggestions.value[activeIndex.value]
    if (s) pick(s)
    else addTag(text.value)
    return
  }
  // 逗号（半角/全角）确认
  if (e.key === ',' || e.key === '，') {
    e.preventDefault()
    addTag(text.value)
    return
  }
  if (e.key === 'Backspace' && !text.value && props.modelValue.length) {
    remove(props.modelValue[props.modelValue.length - 1])
    return
  }
  if (e.key === 'Escape') {
    if (text.value) text.value = ''
    else inputRef.value?.blur()
    return
  }
  if (e.key === 'ArrowDown' && suggestions.value.length) {
    e.preventDefault()
    activeIndex.value = (activeIndex.value + 1) % suggestions.value.length
    return
  }
  if (e.key === 'ArrowUp' && suggestions.value.length) {
    e.preventDefault()
    activeIndex.value = (activeIndex.value - 1 + suggestions.value.length) % suggestions.value.length
  }
}

// 失焦时收起候选；mousedown.prevent 已经先完成了「点候选」的添加
function onBlur() {
  focused.value = false
}
</script>

<style scoped>
.tag-input {
  position: relative;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  min-height: 30px;
  padding: 3px 6px;
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  transition: border-color var(--duration-fast) var(--ease-out), background var(--duration-fast);
}
.tag-input.is-focused {
  border-color: var(--primary-ring);
  background: var(--bg-subtle);
}
.tag-input.is-empty { padding-left: 2px; }

.tag-chip {
  display: inline-flex;
  align-items: center;
  gap: 1px;
  height: 21px;
  padding: 0 2px 0 7px;
  border-radius: var(--radius-xs);
  background: var(--primary-bg);
  color: var(--primary-dark);
  font-size: var(--text-xs);
  line-height: 1;
  max-width: 200px;
}
html.dark .tag-chip { color: var(--primary-light); }

.tag-chip-name {
  border: none;
  background: none;
  padding: 0;
  font: inherit;
  color: inherit;
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tag-chip-name:hover { text-decoration: underline; }

.tag-chip-x {
  border: none;
  background: none;
  padding: 0 3px;
  font: inherit;
  font-size: 13px;
  line-height: 1;
  color: var(--text-tertiary);
  cursor: pointer;
  border-radius: 3px;
}
.tag-chip-x:hover { color: var(--danger); background: var(--danger-bg); }

.tag-field {
  flex: 1;
  min-width: 90px;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text-primary);
  font-size: var(--text-sm);
  padding: 2px 4px;
}
.tag-field::placeholder { color: var(--text-disabled); }

.tag-suggest {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  z-index: 20;
  margin: 0;
  padding: 4px;
  list-style: none;
  min-width: 160px;
  max-width: 280px;
  max-height: 220px;
  overflow-y: auto;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow-lg);
}
.tag-suggest-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 5px 8px;
  border-radius: var(--radius-xs);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  cursor: pointer;
}
.tag-suggest-item.is-active,
.tag-suggest-item:hover {
  background: var(--primary-bg);
  color: var(--primary-dark);
}
html.dark .tag-suggest-item.is-active,
html.dark .tag-suggest-item:hover { color: var(--primary-light); }
.tag-suggest-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tag-suggest-new {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  flex-shrink: 0;
}
.tag-suggest-empty {
  padding: 6px 8px;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
</style>
