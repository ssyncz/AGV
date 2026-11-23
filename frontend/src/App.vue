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
const sidebarCollapsed = ref(false)
let pollTimer = null
let toastTimer = null
const liveRoutes = new Set(['dispatch', 'tasks', 'map', 'agvs'])

try {
  sidebarCollapsed.value = window.localStorage.getItem('agv-sidebar-collapsed') === '1'
} catch {
  // Local storage may be unavailable in privacy-restricted browser contexts.
}

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
  { path: '/workbench', label: '工作台', icon: '◈' },
  { path: '/dashboard', label: '生产总览', icon: '⌂' },
  {
    path: '/forecast',
    label: '预测与计划',
    icon: '◒',
    tabs: [
      { path: '/forecast', label: '订单预测' },
      { path: '/plans', label: '生产计划' },
    ],
  },
  { path: '/work-orders', label: '生产工单', icon: '▤' },
  {
    path: '/dispatch',
    label: '调度执行',
    icon: '⌁',
    tabs: [
      { path: '/dispatch', label: 'AGV 调度' },
      { path: '/tasks', label: '运输任务' },
      { path: '/map', label: '地图监控' },
      { path: '/agvs', label: 'AGV 管理' },
    ],
  },
  {
    path: '/equipment',
    label: '质量与设备',
    icon: '◍',
    tabs: [
      { path: '/equipment', label: '设备监测' },
      { path: '/vision', label: '视觉质检' },
    ],
  },
  { path: '/alerts', label: '异常中心', icon: '◉' },
  { path: '/master-data', label: '基础数据', icon: '▦' },
]

const currentTitle = computed(() => route.meta.title || '运营平台')
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
const currentNavItem = computed(() =>
  navigation.find((item) => item.path === route.path || item.tabs?.some((tab) => tab.path === route.path)))
const currentSectionTab = computed(() =>
  currentNavItem.value?.tabs?.find((tab) => tab.path === route.path))
const currentGroup = computed(() => currentNavItem.value?.label || '业务中心')

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
}

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

watch(sidebarCollapsed, (collapsed) => {
  try {
    window.localStorage.setItem('agv-sidebar-collapsed', collapsed ? '1' : '0')
  } catch {
    // Keep the current session state even if persistence is unavailable.
  }
})

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

    <div class="app-shell" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
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
          <img class="brand-logo" src="/logo-agv.svg" alt="AGV" />
          <div class="brand-copy">
            <div class="brand-title">制造运营中心</div>
            <div class="brand-subtitle">Intelligent Operations</div>
          </div>
          <button
            class="sidebar-toggle"
            type="button"
            :title="sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'"
            :aria-label="sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'"
            :aria-expanded="!sidebarCollapsed"
            @click="toggleSidebar"
          >
            <span aria-hidden="true">{{ sidebarCollapsed ? '›' : '‹' }}</span>
          </button>
        </div>
        <nav class="sidebar-nav">
          <RouterLink
            v-for="item in navigation"
            :key="item.path"
            :to="item.path"
            class="nav-item"
            :class="{ active: currentNavItem?.path === item.path }"
            :title="item.label"
            :aria-label="item.label"
          >
            <span class="nav-icon">{{ item.icon }}</span><span class="nav-text">{{ item.label }}</span>
          </RouterLink>
        </nav>
        <div class="sidebar-foot">
          <strong>
            <span class="connection-dot" :class="{ error: !online }"></span>
            <span class="sidebar-status-text">{{ online ? '运营服务在线' : '后端连接异常' }}</span>
          </strong>
        </div>
      </aside>

      <main class="main-area">
        <div class="main-head">
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
            </div>
            <div class="top-actions">
              <span class="muted small">{{ refreshing ? '正在同步...' : '数据已同步' }}</span>
              <button class="btn" :disabled="refreshing" @click="loadAll()">刷新共享数据</button>
            </div>
          </header>

          <nav v-if="currentNavItem?.tabs?.length" class="section-tabs" aria-label="当前业务模块">
            <RouterLink
              v-for="tab in currentNavItem.tabs"
              :key="tab.path"
              :to="tab.path"
              class="section-tab"
              :class="{ active: currentSectionTab?.path === tab.path }"
            >
              {{ tab.label }}
            </RouterLink>
          </nav>
        </div>

        <RouterView v-slot="{ Component }">
          <component :is="Component" v-bind="sharedProps" @refresh="loadAll(true)" @notify="handleNotify" />
        </RouterView>
      </main>
    </div>

    <div v-if="loading" class="loading-shade"><div class="spinner"></div></div>
    <div v-if="toast" class="toast" :class="toast.type">{{ toast.message }}</div>
  </div>
</template>

<style scoped>
.main-head {
  position: sticky;
  top: 0;
  z-index: 20;
  margin: 0 0 16px;
  background: var(--topbar-bg);
  backdrop-filter: blur(22px) saturate(1.2);
  -webkit-backdrop-filter: blur(22px) saturate(1.2);
}

.main-head .topbar {
  position: static;
  z-index: auto;
  margin-bottom: 0;
}

.section-tabs {
  width: fit-content;
  max-width: 100%;
  display: flex;
  align-items: center;
  gap: 4px;
  margin: 0 0 12px;
  padding: 4px;
  overflow-x: auto;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: var(--glass);
  scrollbar-width: none;
}

.section-tabs::-webkit-scrollbar {
  display: none;
}

.section-tab {
  min-height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 7px 14px;
  border: 1px solid transparent;
  border-radius: 8px;
  color: var(--muted);
  font-size: 11px;
  font-weight: 650;
  white-space: nowrap;
  text-decoration: none;
  transition: color 150ms ease, border-color 150ms ease, background 150ms ease, box-shadow 150ms ease;
}

.section-tab:hover {
  color: var(--text);
  background: var(--nav-hover-bg);
}

.section-tab.active {
  color: var(--nav-active-fg);
  border-color: var(--line);
  background: var(--nav-active-bg);
  box-shadow: var(--nav-active-shadow);
}

.sidebar-nav {
  gap: 5px;
  padding-top: 3px;
}

.sidebar-nav .nav-item {
  min-height: 42px;
  padding: 8px 10px;
}

.sidebar-nav .nav-icon {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--fill-1);
  font-size: 14px;
}

.sidebar-nav .nav-item.active .nav-icon,
.sidebar-nav .nav-item.router-link-active .nav-icon {
  border-color: var(--nav-active-line);
  background: var(--nav-active-bg);
}

.sidebar-toggle {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  margin-left: auto;
  padding: 0;
  border: 1px solid var(--line);
  border-radius: 9px;
  color: var(--muted);
  background: var(--btn-bg);
  box-shadow: var(--btn-shadow);
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
  transition: color 150ms ease, border-color 150ms ease, background 150ms ease, transform 150ms ease;
}

.sidebar-toggle:hover {
  color: var(--nav-active-fg);
  border-color: var(--nav-active-line);
  background: var(--nav-hover-bg);
}

.sidebar-toggle:active {
  transform: scale(0.95);
}

.sidebar {
  transition: flex-basis 180ms ease, width 180ms ease, padding 180ms ease;
}

@media (min-width: 821px) {
  .app-shell.sidebar-collapsed .sidebar {
    flex-basis: 78px;
    width: 78px;
    padding-inline: 10px;
  }

  .app-shell.sidebar-collapsed .brand {
    flex-direction: column;
    gap: 10px;
    padding-inline: 0;
  }

  .app-shell.sidebar-collapsed .brand-copy,
  .app-shell.sidebar-collapsed .nav-text,
  .app-shell.sidebar-collapsed .sidebar-status-text {
    display: none;
  }

  .app-shell.sidebar-collapsed .sidebar-toggle {
    margin-left: 0;
  }

  .app-shell.sidebar-collapsed .sidebar-nav .nav-item {
    justify-content: center;
    padding-inline: 0;
  }

  .app-shell.sidebar-collapsed .sidebar-nav .nav-icon {
    width: 32px;
    height: 32px;
  }

  .app-shell.sidebar-collapsed .nav-item.active::before,
  .app-shell.sidebar-collapsed .nav-item.router-link-active::before {
    left: -10px;
  }

  .app-shell.sidebar-collapsed .sidebar-foot {
    display: grid;
    place-items: center;
    padding: 8px 4px;
    border-color: transparent;
    background: transparent;
  }

  .app-shell.sidebar-collapsed .sidebar-foot strong {
    justify-content: center;
    margin: 0;
  }
}

@media (max-width: 820px) {
  .sidebar-toggle {
    display: none;
  }
}

@media (max-width: 720px) {
  .main-head {
    margin-bottom: 12px;
  }

  .section-tabs {
    width: 100%;
    margin-top: 0;
  }

  .section-tab {
    flex: 1 0 auto;
  }
}
</style>
