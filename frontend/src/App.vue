<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from './api'
import DashboardView from './views/DashboardView.vue'
import DispatchView from './views/DispatchView.vue'
import AgvView from './views/AgvView.vue'
import TaskView from './views/TaskView.vue'
import MapView from './views/MapView.vue'
import VisionView from './views/VisionView.vue'

const activeTab = ref('dashboard')
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

const tabs = [
  { key: 'dashboard', label: '调度总览', icon: '◫', subtitle: '运行指标、车队状态与最近调度记录' },
  { key: 'dispatch', label: '调度中心', icon: '⌁', subtitle: '单台智能调度与多台 AGV 协同调度' },
  { key: 'map', label: '地图监控', icon: '◎', subtitle: '仓库拓扑、AGV 位置与实时规划路线' },
  { key: 'tasks', label: '运输任务', icon: '◇', subtitle: '任务全生命周期与执行状态管理' },
  { key: 'agvs', label: 'AGV 管理', icon: '▣', subtitle: '车辆状态、电量、载重和位置管理' },
  { key: 'vision', label: '视觉检测', icon: '◍', subtitle: '表面裂纹检测与工件识别（OpenCV 传统算法）' },
]

const currentTab = computed(() => tabs.find((item) => item.key === activeTab.value) || tabs[0])
const currentTitle = computed(() => currentTab.value.label)
const currentSubtitle = computed(() => currentTab.value.subtitle)

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

onMounted(() => {
  loadAll()
  pollTimer = setInterval(() => loadAll(true), 8000)
})

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
        <div><div class="brand-title">智能调度中心</div><div class="brand-subtitle">Fleet Orchestration Platform</div></div>
      </div>
      <div class="nav-label">工作台</div>
      <button v-for="tab in tabs" :key="tab.key" class="nav-item" :class="{ active: activeTab === tab.key }" @click="activeTab = tab.key">
        <span class="nav-icon">{{ tab.icon }}</span><span>{{ tab.label }}</span>
      </button>
      <div class="sidebar-foot">
        <strong><span class="connection-dot" :class="{ error: !online }"></span> {{ online ? '调度服务在线' : '后端连接异常' }}</strong>
        <span>每 8 秒自动同步<br>Django REST API · MySQL</span>
      </div>
    </aside>

    <main class="main-area">
      <header class="topbar">
        <div><div class="page-title">{{ currentTitle }}</div><div class="page-subtitle">{{ currentSubtitle }}</div></div>
        <div class="top-actions">
          <span class="muted small">{{ refreshing ? '正在同步...' : '数据已同步' }}</span>
          <button class="btn" :disabled="refreshing" @click="loadAll()">刷新数据</button>
        </div>
      </header>

      <DashboardView v-if="activeTab === 'dashboard'" :overview="overview" :agvs="agvs" :tasks="tasks" :dispatches="dispatches" />
      <DispatchView v-else-if="activeTab === 'dispatch'" :tasks="tasks" :agvs="agvs" :nodes="mapData.nodes || []" @refresh="loadAll(true)" @notify="handleNotify" />
      <MapView v-else-if="activeTab === 'map'" :map-data="mapData" @notify="handleNotify" />
      <TaskView v-else-if="activeTab === 'tasks'" :tasks="tasks" :nodes="mapData.nodes || []" @refresh="loadAll(true)" @notify="handleNotify" />
      <AgvView v-else-if="activeTab === 'agvs'" :agvs="agvs" @refresh="loadAll(true)" @notify="handleNotify" />
      <VisionView v-else @notify="handleNotify" />
    </main>

    <div v-if="loading" class="loading-shade"><div class="spinner"></div></div>
    <div v-if="toast" class="toast" :class="toast.type">{{ toast.message }}</div>
  </div>
</template>
