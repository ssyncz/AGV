<script setup>
// 统一的「更多」动作菜单：把次要/危险操作收起来，每个状态只留一个主按钮
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({
  items: { type: Array, default: () => [] }, // [{ key, label, danger?, disabled?, hint? }]
  label: { type: String, default: '更多' },
  align: { type: String, default: 'right' },
})
const emit = defineEmits(['select'])
const open = ref(false)
const root = ref(null)

const visible = computed(() => props.items.filter((item) => item && !item.hidden))

function toggle() {
  if (!visible.value.length) return
  open.value = !open.value
}
function choose(item) {
  if (item.disabled) return
  open.value = false
  emit('select', item.key)
}
function onDocClick(event) {
  if (!open.value) return
  if (root.value && !root.value.contains(event.target)) open.value = false
}
function onKey(event) {
  if (event.key === 'Escape') open.value = false
}
onMounted(() => {
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <div ref="root" class="action-menu" :class="[`align-${align}`, { open }]">
    <button
      type="button"
      class="btn btn-sm action-menu-trigger"
      :disabled="!visible.length"
      :aria-expanded="open"
      @click="toggle"
    >
      {{ label }}<span class="action-menu-caret" aria-hidden="true">⌄</span>
    </button>
    <div v-if="open" class="action-menu-list" role="menu">
      <button
        v-for="item in visible"
        :key="item.key"
        type="button"
        class="action-menu-item"
        :class="{ danger: item.danger, disabled: item.disabled }"
        role="menuitem"
        :disabled="item.disabled"
        @click="choose(item)"
      >
        <span>{{ item.label }}</span>
        <small v-if="item.hint">{{ item.hint }}</small>
      </button>
    </div>
  </div>
</template>
