<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { api, apiActivity } from './api'

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
const sidebarOpen = ref(false)
const sidebarCollapsed = ref(false)
let pollTimer = null
let toastTimer = null
const liveRoutes = new Set(['dispatch', 'tasks', 'map', 'agvs'])

try {
  sidebarCollapsed.value = window.localStorage.getItem('agv-sidebar-collapsed') === '1'
} catch {
  // Storage may be unavailable in privacy-restricted browser contexts.
}

const navigation = [
  {
    label: '运营',
    items: [
      { path: '/dashboard', label: '生产总览', icon: 'dashboard' },
      { path: '/work-orders', label: '生产工单', icon: 'orders' },
      { path: '/alerts', label: '告警中心', icon: 'alerts' },
    ],
  },
  {
    label: '生产执行',
    items: [
      { path: '/dispatch', label: '调度中心', icon: 'dispatch' },
      { path: '/tasks', label: '运输任务', icon: 'tasks' },
      { path: '/map', label: '地图监控', icon: 'map' },
      { path: '/plans', label: '生产计划', icon: 'plans' },
    ],
  },
  {
    label: '资源与质量',
    items: [
      { path: '/agvs', label: 'AGV 管理', icon: 'agvs' },
      { path: '/equipment', label: '设备监测', icon: 'equipment' },
      { path: '/vision', label: '视觉质检', icon: 'vision' },
    ],
  },
  {
    label: '计划与系统',
    items: [
      { path: '/forecast', label: '订单预测', icon: 'forecast' },
      { path: '/master-data', label: '主数据管理', icon: 'data' },
    ],
  },
]

const iconPaths = {
  dashboard: ['M3 10.5 12 3l9 7.5V21H3z', 'M9 21v-7h6v7'],
  orders: ['M8 4H6a2 2 0 0 0-2 2v14h16V6a2 2 0 0 0-2-2h-2', 'M9 2h6v4H9z', 'M8 12h8', 'M8 16h5'],
  alerts: ['M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9', 'M10 21h4'],
  dispatch: ['M3 19h18', 'M5 16l4-4 3 3 6-7', 'M15 8h3v3'],
  tasks: ['M9 6h11', 'M9 12h11', 'M9 18h11', 'm3.5 6 1.2 1.2L7 5', 'm3.5 12 1.2 1.2L7 11', 'm3.5 18 1.2 1.2L7 17'],
  map: ['m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3z', 'M9 3v15', 'M15 6v15'],
  plans: ['M5 4h14v17H5z', 'M8 2v4', 'M16 2v4', 'M5 9h14', 'M9 13h2', 'M14 13h2', 'M9 17h2'],
  agvs: ['M4 8h12v9H4z', 'M16 11h3l2 3v3h-5', 'M7 20a2 2 0 1 0 0-4 2 2 0 0 0 0 4z', 'M17 20a2 2 0 1 0 0-4 2 2 0 0 0 0 4z', 'M8 11h4'],
  equipment: ['M4 18a8 8 0 1 1 16 0', 'M12 18l4-5', 'M6 18h12'],
  vision: ['M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6z', 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z'],
  forecast: ['M4 19V5', 'M4 19h16', 'm7 15 3-4 3 2 5-6', 'M15 7h3v3'],
  data: ['M4 6c0 2 3.6 3 8 3s8-1 8-3-3.6-3-8-3-8 1-8 3z', 'M4 6v6c0 2 3.6 3 8 3s8-1 8-3V6', 'M4 12v6c0 2 3.6 3 8 3s8-1 8-3v-6'],
}

const currentTitle = computed(() => route.meta.title || '运营平台')
const currentSubtitle = computed(() => route.meta.subtitle || '')
const syncing = computed(() => refreshing.value || apiActivity.pending > 0)
const currentPageIndex = computed(() => {
  const pages = navigation.flatMap((group) => group.items)
  const index = pages.findIndex((item) => item.path === route.path)
  return String((index >= 0 ? index : 0) + 1).padStart(2, '0')
})
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
    const results = await Promise.allSettled([
      api.overview(), api.agvs(), api.tasks(), api.dispatches(), api.map(),
    ])
    const values = results.map((result) => result.status === 'fulfilled' ? result.value : null)
    if (values[0]) overview.value = values[0]
    if (values[1]) agvs.value = values[1]
    if (values[2]) tasks.value = values[2]
    if (values[3]) dispatches.value = values[3]
    if (values[4]) mapData.value = values[4]

    const failed = results.filter((result) => result.status === 'rejected')
    online.value = failed.length < results.length
    if (failed.length && !silent) {
      const message = failed.length === results.length
        ? `无法连接后端：${failed[0].reason?.message || '未知错误'}`
        : `部分共享数据加载失败（${failed.length}/${results.length}），其他模块仍可正常使用`
      showToast(message, 'error')
    }
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

function handleNotify(payload) {
  showToast(payload.message, payload.type || 'success')
}

function toggleNavigation() {
  if (window.matchMedia('(max-width: 720px)').matches) {
    sidebarOpen.value = !sidebarOpen.value
    return
  }
  sidebarCollapsed.value = !sidebarCollapsed.value
}

function configurePolling(reloadNow = true) {
  clearInterval(pollTimer)
  pollTimer = null
  if (!liveRoutes.has(route.name)) return
  if (reloadNow) loadAll(true)
  pollTimer = setInterval(() => loadAll(true), 8000)
}

onMounted(() => {
  loadAll()
  configurePolling(false)
  window.addEventListener('keydown', handleKeydown)
})

watch(() => route.name, () => {
  sidebarOpen.value = false
  configurePolling(true)
})

watch(sidebarCollapsed, (collapsed) => {
  try {
    window.localStorage.setItem('agv-sidebar-collapsed', collapsed ? '1' : '0')
  } catch {
    // Keep the current session state even if persistence is unavailable.
  }
})

function handleKeydown(event) {
  if (event.key === 'Escape') sidebarOpen.value = false
}

onUnmounted(() => {
  clearInterval(pollTimer)
  clearTimeout(toastTimer)
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <div class="app-shell" :class="{ 'sidebar-open': sidebarOpen, 'sidebar-collapsed': sidebarCollapsed }">
    <aside id="primary-navigation" class="sidebar">
      <div class="brand">
        <div class="brand-mark">AGV</div>
        <div class="brand-copy">
          <div class="brand-eyebrow">Operations OS</div>
          <div class="brand-title">制造运营中心</div>
          <div class="brand-subtitle">Intelligent Operations Platform</div>
        </div>
      </div>
      <button class="mobile-nav-close" type="button" aria-label="关闭导航" @click="sidebarOpen = false">×</button>
      <nav class="sidebar-nav">
        <div
          v-for="(group, groupIndex) in navigation"
          :key="group.label"
          class="nav-group"
          :class="{ 'nav-group-active': group.items.some((item) => item.path === route.path) }"
        >
          <div class="nav-label">
            <span>{{ group.label }}</span>
            <span class="nav-group-index">{{ String(groupIndex + 1).padStart(2, '0') }}</span>
          </div>
          <RouterLink v-for="item in group.items" :key="item.path" :to="item.path" class="nav-item" :title="item.label">
            <span class="nav-icon">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path v-for="path in iconPaths[item.icon]" :key="path" :d="path" />
              </svg>
            </span>
            <span class="nav-text">{{ item.label }}</span>
            <span class="nav-chevron">›</span>
          </RouterLink>
        </div>
      </nav>
      <div class="sidebar-foot">
        <div class="service-state">
          <span class="connection-dot" :class="{ error: !online }"></span>
          <div>
            <strong>{{ online ? '运营服务在线' : '后端连接异常' }}</strong>
            <small>{{ online ? 'All systems operational' : 'Connection unavailable' }}</small>
          </div>
        </div>
      </div>
    </aside>
    <div v-if="sidebarOpen" class="sidebar-scrim" @click="sidebarOpen = false"></div>

    <main class="main-area">
      <div class="route-progress" :class="{ active: syncing }" aria-hidden="true"><span></span></div>
      <header class="topbar">
        <button
          class="shell-nav-toggle"
          type="button"
          :aria-expanded="sidebarOpen || !sidebarCollapsed"
          aria-controls="primary-navigation"
          aria-label="展开或收起导航"
          @click="toggleNavigation"
        >
          <span></span><span></span><span></span>
        </button>
        <div class="topbar-decoration" aria-hidden="true">
          <span class="topbar-line"></span>
          <span class="topbar-node node-one"></span>
          <span class="topbar-node node-two"></span>
          <span class="topbar-node node-three"></span>
        </div>
        <div class="page-heading">
          <div class="page-eyebrow">
            <span class="page-index">{{ currentPageIndex }}</span>
            <span class="eyebrow-rule"></span>
            Operations workspace
          </div>
          <div class="page-title-row">
            <div class="page-title">{{ currentTitle }}</div>
            <span class="page-live"><i></i>LIVE</span>
          </div>
          <div class="page-subtitle">{{ currentSubtitle }}</div>
        </div>
        <div class="top-actions">
          <div class="sync-state" :class="{ syncing }">
            <span class="sync-pulse"></span>
            <div><small>{{ syncing ? '正在同步' : '实时数据' }}</small><strong>{{ syncing ? '请稍候' : '已同步' }}</strong></div>
          </div>
          <button class="btn btn-refresh" :disabled="syncing" @click="loadAll()">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11a8 8 0 1 0-2.34 5.66" /><path d="M20 4v7h-7" /></svg>
            <span>刷新共享数据</span>
          </button>
        </div>
      </header>

      <RouterView v-slot="{ Component }">
        <component v-if="Component" :is="Component" v-bind="sharedProps" @refresh="loadAll(true)" @notify="handleNotify" />
      </RouterView>
    </main>

    <div v-if="loading" class="loading-shade"><div class="spinner"></div></div>
    <div v-if="toast" class="toast" :class="toast.type">{{ toast.message }}</div>
  </div>
</template>
