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

// 主题：深色「森林夜色」/ 浅色「晨雾」，写在 <html data-theme> 上，样式层全量走 CSS 变量
const theme = ref(document.documentElement.dataset.theme === 'light' ? 'light' : 'dark')
const themeLabel = computed(() => (theme.value === 'dark' ? '森林夜色' : '晨雾浅色'))

function applyTheme(next) {
  theme.value = next
  document.documentElement.dataset.theme = next
  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta) meta.setAttribute('content', next === 'light' ? '#eef4e9' : '#04120b')
  // 手动切换后去掉 ?theme=，避免刷新时 URL 参数又把主题拉回去
  const url = new URL(window.location.href)
  if (url.searchParams.has('theme')) {
    url.searchParams.delete('theme')
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`)
  }
  try { localStorage.setItem('agv-theme', next) } catch { /* 隐私模式下忽略 */ }
}

function toggleTheme() {
  applyTheme(theme.value === 'dark' ? 'light' : 'dark')
}

const navigation = [
  {
    label: '运营',
    items: [
      { path: '/workbench', label: '工作台', icon: '◈' },
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
// 页头右侧那枚半透明外语词 / 眉题的后半段
const ROUTE_EN = {
  workbench: 'Workbench',
  dashboard: 'Production Overview',
  'work-orders': 'Work Orders',
  alerts: 'Alert Center',
  dispatch: 'Dispatch Center',
  tasks: 'Transport Tasks',
  map: 'Warehouse Map',
  plans: 'Production Plans',
  agvs: 'AGV Fleet',
  equipment: 'Equipment Health',
  vision: 'Vision QC',
  forecast: 'Demand Forecast',
  'master-data': 'Master Data',
}
const currentEn = computed(() => ROUTE_EN[route.name] || 'Operations')
const currentGroup = computed(() => {
  const hit = navigation.find((group) => group.items.some((item) => item.path === route.path))
  return hit ? hit.label : '运营'
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
  <div class="app-frame">
    <!-- macOS 风格标题栏：红绿灯 + 当前页 · 应用名 -->
    <div class="titlebar">
      <div class="traffic" aria-hidden="true">
        <i class="close"></i><i class="min"></i><i class="max"></i>
      </div>
      <div class="titlebar-title">{{ currentTitle }} — AGV 制造运营中心</div>
      <div class="titlebar-side">
        <button
          class="theme-toggle"
          type="button"
          :title="`当前：${themeLabel}（点击切换）`"
          :aria-label="`切换主题，当前 ${themeLabel}`"
          @click="toggleTheme"
        >
          <svg v-if="theme === 'dark'" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M21 12.8A8.6 8.6 0 1 1 11.1 3a6.9 6.9 0 0 0 9.9 9.8z" />
          </svg>
          <svg v-else viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="12" r="4.2" />
            <path d="M12 2.8v2.1M12 19.1v2.1M4.5 4.5l1.5 1.5M18 18l1.5 1.5M2.8 12h2.1M19.1 12h2.1M4.5 19.5 6 18M18 6l1.5-1.5" />
          </svg>
        </button>
        <span class="sync-chip" :class="{ offline: !online }">{{ online ? '运营服务已连接' : '后端未连接' }}</span>
      </div>
    </div>

    <div class="app-shell">
      <!-- 背景装饰：多语种淡字 + 几何图案（纯装饰，不可选中、不挡交互） -->
      <div class="decor-layer" aria-hidden="true">
        <span class="decor-word w1">工单</span>
        <span class="decor-word w2">DISPATCH</span>
        <span class="decor-word w3">ТРАНСПОРТ</span>
        <span class="decor-word w4">出荷</span>
        <span class="decor-word w5">QUALITY</span>
        <span class="decor-word w6">الشحن</span>
        <span class="decor-word w7">Versand</span>
        <span class="decor-ring"></span>
        <span class="decor-cross">✛</span>
        <span class="decor-dots"></span>
        <span class="decor-chevron">»</span>
      </div>

      <aside class="sidebar">
        <div class="brand">
          <img class="brand-logo" src="/logo-blg-b.svg" alt="BLG" />
          <div><div class="brand-title">制造运营中心</div><div class="brand-subtitle">Intelligent Operations</div></div>
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
          <div class="page-head">
            <div class="page-eyebrow">
              <span class="eyebrow-dot"></span>
              <span>{{ currentGroup }}</span>
              <span class="eyebrow-sep">/</span>
              <span class="eyebrow-en">{{ currentEn }}</span>
            </div>
            <div class="page-title-row">
              <h1 class="page-title">{{ currentTitle }}</h1>
              <span class="page-ghost" aria-hidden="true">{{ currentEn }}</span>
            </div>
            <div class="page-subtitle">{{ currentSubtitle }}</div>
          </div>
          <div class="top-actions">
            <span class="muted small">{{ refreshing ? '正在同步...' : '数据已同步' }}</span>
            <button class="btn" :disabled="refreshing" @click="loadAll()">刷新共享数据</button>
          </div>
        </header>

        <RouterView v-slot="{ Component }">
          <component :is="Component" v-bind="sharedProps" @refresh="loadAll(true)" @notify="handleNotify" />
        </RouterView>
      </main>
    </div>

    <div v-if="loading" class="loading-shade"><div class="spinner"></div></div>
    <div v-if="toast" class="toast" :class="toast.type">{{ toast.message }}</div>
  </div>
</template>
