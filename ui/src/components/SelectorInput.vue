<template>
  <div class="selector-input-wrap" ref="wrapRef">
    <el-input
      v-bind="$attrs"
      :model-value="modelValue"
      @input="onInput"
      @keydown="onKeydown"
      @blur="onBlur"
      ref="inputRef"
    />
    <!-- 别名补全下拉 -->
    <div
      v-if="dropdownVisible && filteredAliases.length"
      class="alias-dropdown"
      @mousedown.prevent
    >
      <div
        v-for="(alias, i) in filteredAliases"
        :key="alias.id"
        class="alias-item"
        :class="{ 'alias-item--active': i === activeIndex }"
        @click="pickAlias(alias)"
      >
        <span class="alias-at">@</span>
        <span class="alias-name">{{ alias.name }}</span>
        <span class="alias-sels">{{ (alias.selectors || []).slice(0, 2).join(' / ') }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'

const props = defineProps({
  modelValue:  { type: String, default: '' },
  aliases:     { type: Array,  default: () => [] },   // 从父组件传入的别名列表
})
const emit = defineEmits(['update:modelValue', 'change'])

const inputRef        = ref(null)
const wrapRef         = ref(null)
const dropdownVisible = ref(false)
const activeIndex     = ref(0)
const atQuery         = ref('')    // @ 之后输入的关键词

// 判断当前输入是否处于 @xxx 触发态
function getAtQuery(val) {
  if (!val) return null
  // 整个值以 @ 开头，或光标前有 @
  const m = val.match(/@([^@]*)$/)
  return m ? m[1] : null
}

const filteredAliases = computed(() => {
  const q = atQuery.value.toLowerCase()
  return props.aliases.filter(a => a.name.toLowerCase().includes(q)).slice(0, 8)
})

function onInput(val) {
  emit('update:modelValue', val)
  const q = getAtQuery(val)
  if (q !== null) {
    atQuery.value = q
    dropdownVisible.value = true
    activeIndex.value = 0
  } else {
    dropdownVisible.value = false
  }
}

function onKeydown(e) {
  if (!dropdownVisible.value || !filteredAliases.value.length) return
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    activeIndex.value = (activeIndex.value + 1) % filteredAliases.value.length
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    activeIndex.value = (activeIndex.value - 1 + filteredAliases.value.length) % filteredAliases.value.length
  } else if (e.key === 'Enter' || e.key === 'Tab') {
    if (filteredAliases.value[activeIndex.value]) {
      e.preventDefault()
      pickAlias(filteredAliases.value[activeIndex.value])
    }
  } else if (e.key === 'Escape') {
    dropdownVisible.value = false
  }
}

function pickAlias(alias) {
  // 把 @xxx 替换为 @别名名称
  const cur = props.modelValue || ''
  const replaced = cur.replace(/@[^@]*$/, `@${alias.name}`)
  emit('update:modelValue', replaced)
  emit('change', replaced)
  dropdownVisible.value = false
}

function onBlur() {
  // 延迟关闭，让 mousedown.prevent 里的 pickAlias 能先执行
  setTimeout(() => { dropdownVisible.value = false }, 150)
  // 手动输入完成（失焦）时触发 change，与 el-input 原生行为保持一致
  emit('change', props.modelValue)
}
</script>

<style scoped>
.selector-input-wrap {
  position: relative;
  width: 100%;
}

.alias-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  z-index: 9999;
  min-width: 280px;
  max-width: 420px;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
  overflow: hidden;
}

.alias-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  cursor: pointer;
  font-size: 13px;
  transition: background .1s;
  overflow: hidden;
}

.alias-item:hover,
.alias-item--active {
  background: #ecf5ff;
}

.alias-at {
  flex-shrink: 0;
  color: #409eff;
  font-weight: 700;
  font-size: 13px;
}

.alias-name {
  flex-shrink: 0;
  color: #303133;
  font-weight: 600;
}

.alias-sels {
  flex: 1;
  color: #909399;
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
