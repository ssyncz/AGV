<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { api } from './api'

const route = useRoute()
const loading = ref(true)
const refreshing = ref(false)
const online = ref(false)
const overview = ref({})
const mapData = ref({ nodes: [], edges: [], agvs: [], active_routes: [] })
const agvs = ref([])
const tasks = ref([])
const dispatches = ref([])
const toast = ref(null)
let pollTimer = null
let toastTimer = null
const liveRoutes = new Set(['dispatch', 'tasks', 'map', 'agvs'])

const navigation = [
  {
    label: '运营',
    items: [
      { path: '/dashboard', label: '生产总览', icon: '⌂' },
      { path: '/work-orders', label: '生产工单', icon: '▤' },
      { path: '/alerts', label: '告警中心', icon: '◉' },
    ],
  },
  {
    label: '生产执行',
    items: [
      { path: '/dispatch', label: '调度中心', icon: '⌁' },
      { path: '/tasks', label: '运输任务', icon: '◇' },
      { path: '/map', label: '地图监控', icon: '◎' },
      { path: '/plans', label: '生产计划', icon: '▥' },
    ],
  },
  {
    label: '资源与质量',
    items: [
      { path: '/agvs', label: 'AGV 管理', icon: '▣' },
      { path: '/equipment', label: '设备监测', icon: '◈' },
      { path: '/vision', label: '视觉质检', icon: '◍' },
    ],
  },
  {
    label: '计划与系统',
    items: [
      { path: '/forecast', label: '订单预测', icon: '◒' },
      { path: '/master-data', label: '主数据管理', icon: '▦' },
    ],
  },
]

const currentTitle = computed(() => route.meta.title || '运营平台')
const currentSubtitle = computed(() => route.meta.subtitle || '')
const sharedProps = computed(() => {
  if (route.name === 'dispatch') return { tasks: tasks.value, agvs: agvs.value, nodes: mapData.value.nodes || [] }
  if (route.name === 'map') return { mapData: mapData.value }
  if (route.name === 'tasks') return { tasks: tasks.value, nodes: mapData.value.nodes || [] }
  if (route.name === 'agvs') return { agvs: agvs.value }
  return {}
})

function showToast(message, type = 'success') {
  toast.value = { message, type }
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = null }, 4200)
}

async function loadAll(silent = false) {
  if (!silent) refreshing.value = true
  try {
    const [summary, fleet, taskList, dispatchList, graph] = await Promise.all([
      api.overview(), api.agvs(), api.tasks(), api.dispatches(), api.map(),
    ])
    overview.value = summary
    agvs.value = fleet
    tasks.value = taskList
    dispatches.value = dispatchList
    mapData.value = graph
    online.value = true
  } catch (error) {
    online.value = false
    if (!silent) showToast(`无法连接后端：${error.message}`, 'error')
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

function handleNotify(payload) {
  showToast(payload.message, payload.type || 'success')
}

function configurePolling() {
  clearInterval(pollTimer)
  pollTimer = null
  if (!liveRoutes.has(route.name)) return
  pollTimer = setInterval(() => loadAll(true), 8000)
}

onMounted(() => {
  loadAll()
  configurePolling()
})

watch(() => route.name, configurePolling)

onUnmounted(() => {
  clearInterval(pollTimer)
  clearTimeout(toastTimer)
})
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">AGV</div>
        <div><div class="brand-title">制造运营中心</div><div class="brand-subtitle">Intelligent Operations Platform</div></div>
      </div>
      <nav class="sidebar-nav">
        <div v-for="group in navigation" :key="group.label" class="nav-group">
          <div class="nav-label">{{ group.label }}</div>
          <RouterLink v-for="item in group.items" :key="item.path" :to="item.path" class="nav-item">
            <span class="nav-icon">{{ item.icon }}</span><span>{{ item.label }}</span>
          </RouterLink>
        </div>
      </nav>
      <div class="sidebar-foot">
        <strong><span class="connection-dot" :class="{ error: !online }"></span> {{ online ? '运营服务在线' : '后端连接异常' }}</strong>
        <span>统一业务事件 · 请求追踪<br>Django REST API · Vue Router</span>
      </div>
    </aside>

    <main class="main-area">
      <header class="topbar">
        <div><div class="page-title">{{ currentTitle }}</div><div class="page-subtitle">{{ currentSubtitle }}</div></div>
        <div class="top-actions">
          <span class="muted small">{{ refreshing ? '正在同步...' : '数据已同步' }}</span>
          <button class="btn" :disabled="refreshing" @click="loadAll()">刷新共享数据</button>
        </div>
      </header>

      <RouterView v-slot="{ Component }">
        <component :is="Component" v-bind="sharedProps" @refresh="loadAll(true)" @notify="handleNotify" />
      </RouterView>
    </main>

    <div v-if="loading" class="loading-shade"><div class="spinner"></div></div>
    <div v-if="toast" class="toast" :class="toast.type">{{ toast.message }}</div>
  </div>
</template>
