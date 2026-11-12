<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '../api'
import ScheduleGantt from '../components/ScheduleGantt.vue'

const emit = defineEmits(['notify', 'refresh'])

const MODEL_LABELS = {
  auto: '自动选择',
  moving_average: '移动平均',
  holt_winters: 'Holt-Winters',
  arima: 'ARIMA',
  lightgbm: 'LightGBM（日历+滞后）',
}

const subTab = ref('predict')
const sourceKind = ref('dataset')
const model = ref('auto')
const horizon = ref(14)
const file = ref(null)
const objectUrl = ref('')
const result = ref(null)
const overview = ref({})
const runs = ref([])
const running = ref(false)
const loadingRuns = ref(false)
const error = ref('')
const nodes = ref([])
const planResult = ref(null)
const scheduleResult = ref(null)
const planning = ref(false)
const scheduling = ref(false)
const routeMode = ref('single')
const planRoutes = reactive([])

function isoLocalDate(offsetDays = 0) {
  const value = new Date()
  value.setDate(value.getDate() + offsetDays)
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

const planConfig = reactive({
  name: '',
  planning_start_date: isoLocalDate(1),
  tasks_per_order: 0.01,
  demand_buffer_percent: 10,
  release_lead_hours: 24,
  due_hour: 18,
  max_tasks: 500,
  pickup_node_id: '',
  dropoff_node_id: '',
  cargo_name: '预测订单货物',
  cargo_weight: 30,
  priority: 2,
  strict_deadlines: false,
})

const pickupNodes = computed(() => nodes.value.filter((item) => item.node_type === 'pickup'))
const dropoffNodes = computed(() => nodes.value.filter((item) => item.node_type === 'dropoff'))
const routeShareTotal = computed(
  () => planRoutes.reduce((total, route) => total + (Number(route.share) || 0), 0),
)
const scheduleRun = computed(() => scheduleResult.value?.run || {})
const scheduleEvaluation = computed(() => scheduleResult.value?.evaluation || {})

const selectedMetrics = computed(() => result.value?.metrics || {})
const candidates = computed(() => {
  const metrics = result.value?.candidate_metrics || {}
  return Object.entries(metrics).map(([key, value]) => ({
    key,
    label: MODEL_LABELS[key] || key,
    ...value,
  }))
})

const chart = computed(() => {
  const history = (result.value?.history || []).slice(-120)
  const forecast = result.value?.forecast || []
  if (!history.length || !forecast.length) {
    return { historyPoints: '', forecastPoints: '', width: 900, height: 280, ticks: [], historyEndX: 0 }
  }

  const width = 900
  const height = 280
  const padding = 42
  const allValues = [...history, ...forecast].map((item) => Number(item.order_count))
  const minimum = Math.min(...allValues)
  const maximum = Math.max(...allValues)
  const span = maximum - minimum || 1
  const chartMin = minimum - span * 0.12
  const chartMax = maximum + span * 0.12
  const total = history.length + forecast.length
  const xAt = (index) => padding + (index / (total - 1)) * (width - padding * 2)
  const yAt = (value) =>
    height - padding - ((value - chartMin) / (chartMax - chartMin)) * (height - padding * 2)

  const historyPoints = history
    .map((item, index) => `${xAt(index).toFixed(2)},${yAt(Number(item.order_count)).toFixed(2)}`)
    .join(' ')
  const forecastPoints = [
    `${xAt(history.length - 1).toFixed(2)},${yAt(Number(history.at(-1).order_count)).toFixed(2)}`,
    ...forecast.map((item, index) =>
      `${xAt(history.length + index).toFixed(2)},${yAt(Number(item.order_count)).toFixed(2)}`,
    ),
  ].join(' ')
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => ({
    y: padding + ratio * (height - padding * 2),
    value: chartMax - ratio * (chartMax - chartMin),
  }))

  return {
    historyPoints,
    forecastPoints,
    width,
    height,
    ticks,
    historyEndX: xAt(history.length - 1),
    startLabel: history[0]?.date,
    endLabel: forecast.at(-1)?.date,
  }
})

function notify(message, type = 'success') {
  emit('notify', { message, type })
}

function formatTime(value) {
  if (!value) return '--'
  return String(value).replace('T', ' ').slice(0, 19)
}

function onFileChange(event) {
  const picked = event.target.files && event.target.files[0]
  if (objectUrl.value) URL.revokeObjectURL(objectUrl.value)
  file.value = picked || null
  objectUrl.value = picked ? URL.createObjectURL(picked) : ''
  result.value = null
  error.value = ''
}

async function loadOverview() {
  try {
    overview.value = await api.forecastOverview()
  } catch (err) {
    notify(`预测概览加载失败：${err.message}`, 'error')
  }
}

async function loadRuns() {
  loadingRuns.value = true
  try {
    runs.value = await api.forecastRuns()
  } catch (err) {
    notify(`预测记录加载失败：${err.message}`, 'error')
  } finally {
    loadingRuns.value = false
  }
}

function rebalanceRoutes() {
  if (!planRoutes.length) return
  const share = Number((100 / planRoutes.length).toFixed(2))
  planRoutes.forEach((route) => { route.share = share })
}

function nextAvailablePair() {
  const used = new Set(planRoutes.map((route) => `${route.pickup_node_id}|${route.dropoff_node_id}`))
  for (const pickup of pickupNodes.value) {
    for (const dropoff of dropoffNodes.value) {
      if (pickup.id === dropoff.id) continue
      const key = `${pickup.id}|${dropoff.id}`
      if (!used.has(key)) return { pickup, dropoff }
    }
  }
  return null
}

function newRoute(pair) {
  return {
    pickup_node_id: pair?.pickup?.id || '',
    dropoff_node_id: pair?.dropoff?.id || '',
    share: 0,
    cargo_name: planConfig.cargo_name || '预测订单货物',
    cargo_weight: Number(planConfig.cargo_weight || 30),
    priority: Number(planConfig.priority || 2),
  }
}

function initializeRoutes() {
  if (planRoutes.length) return
  const count = Math.min(4, pickupNodes.value.length, dropoffNodes.value.length)
  for (let index = 0; index < count; index += 1) {
    planRoutes.push(newRoute({
      pickup: pickupNodes.value[index],
      dropoff: dropoffNodes.value[index],
    }))
  }
  rebalanceRoutes()
}

function setRouteMode(mode) {
  routeMode.value = mode
  if (mode === 'multi') initializeRoutes()
}

function addPlanRoute() {
  const pair = nextAvailablePair()
  if (!pair) return notify('没有更多可用的取放货点组合', 'error')
  planRoutes.push(newRoute(pair))
  rebalanceRoutes()
}

function removePlanRoute(index) {
  if (planRoutes.length <= 2) return notify('多路线模式至少保留两条路线', 'error')
  planRoutes.splice(index, 1)
  rebalanceRoutes()
}

function validateMultiRoutes() {
  if (planRoutes.length < 2) return '多路线模式至少需要两条路线'
  const usedPairs = new Set()
  for (const [index, route] of planRoutes.entries()) {
    if (!route.pickup_node_id || !route.dropoff_node_id) return `路线 ${index + 1} 尚未选择取货点或放货点`
    if (String(route.pickup_node_id) === String(route.dropoff_node_id)) return `路线 ${index + 1} 的取货点和放货点不能相同`
    if (!route.cargo_name?.trim()) return `路线 ${index + 1} 缺少货物名称`
    if (Number(route.cargo_weight) <= 0) return `路线 ${index + 1} 的货物重量必须大于 0`
    if (Number(route.share) <= 0) return `路线 ${index + 1} 的任务份额必须大于 0`
    const key = `${route.pickup_node_id}|${route.dropoff_node_id}`
    if (usedPairs.has(key)) return `路线 ${index + 1} 与其他路线重复`
    usedPairs.add(key)
  }
  return ''
}

async function loadNodes() {
  try {
    nodes.value = await api.nodes()
    if (!planConfig.pickup_node_id && pickupNodes.value.length) {
      planConfig.pickup_node_id = pickupNodes.value[0].id
    }
    if (!planConfig.dropoff_node_id && dropoffNodes.value.length) {
      planConfig.dropoff_node_id = dropoffNodes.value[0].id
    }
    initializeRoutes()
  } catch (err) {
    notify(`地图节点加载失败：${err.message}`, 'error')
  }
}

async function runForecast() {
  running.value = true
  error.value = ''
  try {
    let payload
    if (sourceKind.value === 'upload') {
      if (!file.value) throw new Error('请先选择订单 CSV 文件')
      payload = new FormData()
      payload.append('file', file.value)
      payload.append('horizon', String(horizon.value))
      payload.append('model', model.value)
    } else {
      payload = { horizon: Number(horizon.value), model: model.value }
    }
    result.value = await api.forecastPredict(payload)
    planResult.value = null
    scheduleResult.value = null
    planConfig.name = `预测生产计划 #${result.value.record_id}`
    notify(`预测完成，采用 ${result.value.selected_model_label}`)
    await loadOverview()
    if (subTab.value === 'records') await loadRuns()
  } catch (err) {
    error.value = err.message
    notify(err.message, 'error')
  } finally {
    running.value = false
  }
}

async function generatePlan() {
  if (!result.value?.record_id) return notify('请先完成一次预测', 'error')
  let routePayload
  if (routeMode.value === 'multi') {
    const routeError = validateMultiRoutes()
    if (routeError) return notify(routeError, 'error')
    routePayload = {
      routes: planRoutes.map((route) => ({
        pickup_node_id: Number(route.pickup_node_id),
        dropoff_node_id: Number(route.dropoff_node_id),
        cargo_name: route.cargo_name,
        cargo_weight: Number(route.cargo_weight),
        priority: Number(route.priority),
        share: Number(route.share),
      })),
    }
  } else {
    if (!planConfig.pickup_node_id || !planConfig.dropoff_node_id) {
      return notify('请选择取货点和放货点', 'error')
    }
    if (planConfig.pickup_node_id === planConfig.dropoff_node_id) {
      return notify('取货点和放货点不能相同', 'error')
    }
    routePayload = {
      pickup_node_id: Number(planConfig.pickup_node_id),
      dropoff_node_id: Number(planConfig.dropoff_node_id),
      cargo_name: planConfig.cargo_name,
      cargo_weight: Number(planConfig.cargo_weight),
      priority: Number(planConfig.priority),
    }
  }
  planning.value = true
  try {
    const response = await api.generateProductionPlan({
      forecast_run_id: result.value.record_id,
      name: planConfig.name || `预测生产计划 #${result.value.record_id}`,
      planning_start_date: planConfig.planning_start_date,
      tasks_per_order: Number(planConfig.tasks_per_order),
      demand_buffer_percent: Number(planConfig.demand_buffer_percent),
      release_lead_hours: Number(planConfig.release_lead_hours),
      due_hour: Number(planConfig.due_hour),
      max_tasks: Number(planConfig.max_tasks),
      ...routePayload,
    })
    planResult.value = response.plan
    scheduleResult.value = null
    notify(response.message)
    emit('refresh')
  } catch (err) {
    notify(err.message, 'error')
  } finally {
    planning.value = false
  }
}

async function schedulePlan() {
  if (!planResult.value?.id) return notify('请先生成生产计划', 'error')
  scheduling.value = true
  try {
    const response = await api.scheduleProductionPlan(planResult.value.id, {
      strict_deadlines: Boolean(planConfig.strict_deadlines),
      weights: { agv_weight: 30 },
    })
    scheduleResult.value = response
    planResult.value = response.plan
    notify(response.message)
    emit('refresh')
  } catch (err) {
    notify(err.message, 'error')
  } finally {
    scheduling.value = false
  }
}

function openRuns() {
  subTab.value = 'records'
  loadRuns()
}

onMounted(() => {
  loadOverview()
  loadNodes()
})

onUnmounted(() => {
  if (objectUrl.value) URL.revokeObjectURL(objectUrl.value)
})
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <div>
        <div class="panel-title">订单需求预测</div>
        <div class="panel-desc">任务 7：比较移动平均、Holt-Winters 与 ARIMA，并预测未来订单量</div>
      </div>
      <div class="toolbar-right">
        <button class="btn btn-sm" :class="{ 'btn-primary': subTab === 'predict' }" @click="subTab = 'predict'">在线预测</button>
        <button class="btn btn-sm" :class="{ 'btn-primary': subTab === 'records' }" @click="openRuns">预测记录</button>
      </div>
    </div>

    <div class="panel-body">
      <div class="grid stats-grid">
        <div class="mini-stat panel"><span>累计预测</span><strong>{{ overview.total || 0 }}</strong></div>
        <div class="mini-stat panel"><span>平均 MAPE</span><strong>{{ overview.average_mape || 0 }}%</strong></div>
        <div class="mini-stat panel"><span>历史预测总量</span><strong>{{ Math.round(overview.predicted_total || 0) }}</strong></div>
        <div class="mini-stat panel"><span>候选模型</span><strong>3</strong></div>
      </div>

      <div v-if="subTab === 'predict'" class="grid forecast-grid mt-16">
        <section class="panel">
          <div class="panel-head"><div><div class="panel-title">预测配置</div><div class="panel-desc">使用内置订单序列，或上传 date/order_count（也支持 date/sales 多序列自动汇总）</div></div></div>
          <div class="panel-body">
            <div class="form-grid">
              <div class="field">
                <label>数据来源</label>
                <select v-model="sourceKind" class="select">
                  <option value="dataset">内置订单样例</option>
                  <option value="upload">上传 CSV</option>
                </select>
              </div>
              <div class="field">
                <label>预测算法</label>
                <select v-model="model" class="select">
                  <option value="auto">自动选择最优模型</option>
                  <option value="lightgbm">LightGBM（日历+滞后，综合最优）</option>
                  <option value="holt_winters">Holt-Winters（对照/季节外推）</option>
                </select>
              </div>
              <div class="field">
                <label>预测期数</label>
                <input v-model.number="horizon" class="input" type="number" min="1" max="120" />
              </div>
              <div v-if="sourceKind === 'upload'" class="field full">
                <label>订单 CSV</label>
                <input class="input" type="file" accept=".csv,text/csv" @change="onFileChange" />
              </div>
            </div>

            <div class="notice mt-12">
              必需列：<span class="mono">date + order_count</span>（或 date + sales，多序列自动汇总）
            </div>
            <div class="toolbar-row mt-16">
              <button class="btn btn-primary" :disabled="running" @click="runForecast">
                {{ running ? '正在预测...' : '开始预测' }}
              </button>
              <span class="muted small">自动模式会在 4 个候选模型（含移动平均 / ARIMA 对照）中按回测 RMSE 选最优</span>
            </div>
            <div v-if="error" class="notice warning mt-12">{{ error }}</div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div><div class="panel-title">预测结果</div><div class="panel-desc">历史订单与未来预测曲线</div></div>
            <span v-if="result" class="tag">{{ result.selected_model_label }}</span>
          </div>
          <div class="panel-body">
            <div v-if="result && result.aggregation && result.aggregation.aggregated" class="notice mt-12">
              数据来源：{{ result.aggregation.note }}（数值列：{{ result.aggregation.value_column }}），共 {{ result.history_count }} 天历史数据
            </div>
            <div v-if="result" class="grid metric-grid">
              <div class="optimization-metric"><span>预测模型</span><strong>{{ result.selected_model_label }}</strong></div>
              <div class="optimization-metric"><span>预测总量</span><strong>{{ Math.round(result.predicted_total) }}</strong></div>
              <div class="optimization-metric"><span>MAE</span><strong>{{ selectedMetrics.mae }}</strong></div>
              <div class="optimization-metric"><span>RMSE</span><strong>{{ selectedMetrics.rmse }}</strong></div>
              <div class="optimization-metric"><span>MAPE</span><strong>{{ selectedMetrics.mape }}%</strong></div>
              <div class="optimization-metric"><span>预测期数</span><strong>{{ result.horizon }}</strong></div>
            </div>
            <div v-else class="empty">请选择内置数据或上传 CSV 后开始预测</div>

            <template v-if="result">
              <svg class="forecast-chart" :viewBox="`0 0 ${chart.width} ${chart.height}`" role="img" aria-label="订单预测曲线">
                <line
                  v-for="tick in chart.ticks"
                  :key="tick.y"
                  x1="42"
                  :x2="chart.width - 42"
                  :y1="tick.y"
                  :y2="tick.y"
                  class="chart-grid"
                />
                <polyline :points="chart.historyPoints" fill="none" stroke="var(--cyan)" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" />
                <polyline :points="chart.forecastPoints" fill="none" stroke="var(--red)" stroke-width="4" stroke-dasharray="9 7" stroke-linecap="round" stroke-linejoin="round" />
                <line :x1="chart.historyEndX" :x2="chart.historyEndX" y1="34" :y2="chart.height - 34" class="forecast-divider" />
              </svg>
              <div class="forecast-axis">
                <span>{{ chart.startLabel }}</span>
                <span>未来预测</span>
                <span>{{ chart.endLabel }}</span>
              </div>

              <div class="table-wrap mt-16">
                <table>
                  <thead><tr><th>模型</th><th>MAE</th><th>RMSE</th><th>MAPE</th><th>状态</th></tr></thead>
                  <tbody>
                    <tr v-for="item in candidates" :key="item.key">
                      <td class="cell-main">{{ item.label }}</td>
                      <td>{{ item.mae ?? '--' }}</td>
                      <td>{{ item.rmse ?? '--' }}</td>
                      <td>{{ item.mape != null ? `${item.mape}%` : '--' }}</td>
                      <td>
                        <span v-if="item.key === result.selected_model" class="badge badge-completed">已采用</span>
                        <span v-else-if="item.error" class="badge badge-failed">失败</span>
                        <span v-else class="tag">对比模型</span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </template>
          </div>
        </section>
      </div>

      <div v-if="subTab === 'predict' && result" class="grid production-chain-grid mt-16">
        <section class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">预测转生产计划</div>
              <div class="panel-desc">把预测订单量转换为带释放时间、交期和取放货路线的运输任务</div>
            </div>
            <span class="tag">需求 → 任务</span>
          </div>
          <div class="panel-body">
            <div class="form-grid">
              <div class="field full">
                <label>计划名称</label>
                <input v-model="planConfig.name" class="input" placeholder="例如：11 月第 1 周生产补货计划" />
              </div>
              <div class="field">
                <label>计划开始日期</label>
                <input v-model="planConfig.planning_start_date" type="date" class="input" />
              </div>
              <div class="field">
                <label>任务/订单换算比例</label>
                <input v-model.number="planConfig.tasks_per_order" type="number" min="0.001" max="100" step="0.001" class="input" />
              </div>
              <div class="field">
                <label>需求缓冲 (%)</label>
                <input v-model.number="planConfig.demand_buffer_percent" type="number" min="0" max="200" step="1" class="input" />
              </div>
              <div class="field">
                <label>提前释放 (小时)</label>
                <input v-model.number="planConfig.release_lead_hours" type="number" min="0" max="720" step="1" class="input" />
              </div>
              <div class="field">
                <label>交期时刻</label>
                <input v-model.number="planConfig.due_hour" type="number" min="0" max="23" step="1" class="input" />
              </div>
              <div class="field">
                <label>最大生成任务数</label>
                <input v-model.number="planConfig.max_tasks" type="number" min="1" max="2000" step="1" class="input" />
              </div>

              <div class="field full">
                <label>运输路线模式</label>
                <div class="route-mode-switch">
                  <button type="button" :class="{ active: routeMode === 'single' }" @click="setRouteMode('single')">单一路线</button>
                  <button type="button" :class="{ active: routeMode === 'multi' }" @click="setRouteMode('multi')">多路线分配</button>
                </div>
              </div>

              <template v-if="routeMode === 'single'">
                <div class="field">
                  <label>取货点</label>
                  <select v-model="planConfig.pickup_node_id" class="select">
                    <option value="">请选择</option>
                    <option v-for="node in pickupNodes" :key="node.id" :value="node.id">{{ node.code }} · {{ node.name }}</option>
                  </select>
                </div>
                <div class="field">
                  <label>放货点</label>
                  <select v-model="planConfig.dropoff_node_id" class="select">
                    <option value="">请选择</option>
                    <option v-for="node in dropoffNodes" :key="node.id" :value="node.id">{{ node.code }} · {{ node.name }}</option>
                  </select>
                </div>
                <div class="field">
                  <label>货物名称</label>
                  <input v-model="planConfig.cargo_name" class="input" />
                </div>
                <div class="field">
                  <label>单任务重量 (kg)</label>
                  <input v-model.number="planConfig.cargo_weight" type="number" min="0.1" step="0.1" class="input" />
                </div>
                <div class="field">
                  <label>优先级</label>
                  <select v-model.number="planConfig.priority" class="select">
                    <option :value="1">低</option><option :value="2">普通</option><option :value="3">高</option><option :value="4">紧急</option>
                  </select>
                </div>
              </template>

              <div v-else class="field full route-editor-field">
                <div class="route-editor-head">
                  <div>
                    <label>多路线任务分配</label>
                    <div class="cell-sub">系统按份额归一化后分配任务，份额相同的路线会得到接近数量的任务。</div>
                  </div>
                  <div class="route-editor-actions">
                    <span class="tag">份额合计 {{ routeShareTotal.toFixed(2) }}</span>
                    <button type="button" class="btn btn-sm" @click="rebalanceRoutes">平均分配</button>
                    <button type="button" class="btn btn-sm btn-primary" @click="addPlanRoute">新增路线</button>
                  </div>
                </div>
                <div class="route-edit-list">
                  <article v-for="(route, index) in planRoutes" :key="index" class="route-edit-card">
                    <div class="route-edit-card-head">
                      <strong>路线 {{ index + 1 }}</strong>
                      <button type="button" class="link-btn danger" @click="removePlanRoute(index)">删除</button>
                    </div>
                    <div class="route-edit-grid">
                      <div class="field">
                        <label>取货点</label>
                        <select v-model="route.pickup_node_id" class="select">
                          <option v-for="node in pickupNodes" :key="node.id" :value="node.id">{{ node.code }} · {{ node.name }}</option>
                        </select>
                      </div>
                      <div class="field">
                        <label>放货点</label>
                        <select v-model="route.dropoff_node_id" class="select">
                          <option v-for="node in dropoffNodes" :key="node.id" :value="node.id">{{ node.code }} · {{ node.name }}</option>
                        </select>
                      </div>
                      <div class="field">
                        <label>任务份额</label>
                        <input v-model.number="route.share" type="number" min="0.01" step="1" class="input" />
                      </div>
                      <div class="field">
                        <label>货物名称</label>
                        <input v-model="route.cargo_name" class="input" />
                      </div>
                      <div class="field">
                        <label>单任务重量 (kg)</label>
                        <input v-model.number="route.cargo_weight" type="number" min="0.1" step="0.1" class="input" />
                      </div>
                      <div class="field">
                        <label>优先级</label>
                        <select v-model.number="route.priority" class="select">
                          <option :value="1">低</option><option :value="2">普通</option><option :value="3">高</option><option :value="4">紧急</option>
                        </select>
                      </div>
                    </div>
                  </article>
                </div>
              </div>
            </div>
            <div class="notice info mt-12">
              预测序列会按原周期间隔映射到计划开始日期；订单量先乘需求缓冲，再按累计取整生成任务，避免逐日舍入造成总量偏差。
            </div>
            <button class="btn btn-primary btn-block mt-16" :disabled="planning" @click="generatePlan">
              {{ planning ? '正在生成生产任务...' : '生成生产计划与运输任务' }}
            </button>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">生产排程</div>
              <div class="panel-desc">按释放时间、交期、优先级和 AGV 约束进行多车联合优化</div>
            </div>
            <span v-if="planResult" class="tag">{{ planResult.status_display }}</span>
          </div>
          <div class="panel-body">
            <template v-if="planResult">
              <div class="grid planner-metrics">
                <div><span>计划编号</span><strong class="mono">{{ planResult.plan_no }}</strong></div>
                <div><span>计划期</span><strong>{{ planResult.planning_start }} → {{ planResult.planning_end }}</strong></div>
                <div><span>生成任务</span><strong>{{ planResult.task_count }}</strong></div>
                <div><span>路线数量</span><strong>{{ planResult.route_count || 0 }} 条</strong></div>
                <div><span>预测订单</span><strong>{{ Math.round(planResult.forecast_order_total) }}</strong></div>
                <div><span>需求缓冲</span><strong>{{ planResult.demand_buffer_percent }}%</strong></div>
                <div><span>换算比例</span><strong>{{ planResult.tasks_per_order }} 任务/单</strong></div>
              </div>
              <RouterLink v-if="planResult.work_order" class="notice success mt-12" :to="{ path: '/work-orders', query: { work_order: planResult.work_order } }">
                已同步创建执行工单 <strong class="mono">{{ planResult.work_order_no }}</strong>，点击查看工单主线与质量/设备记录。
              </RouterLink>
              <label class="deadline-option mt-16">
                <input v-model="planConfig.strict_deadlines" type="checkbox" />
                <span><strong>硬交期模式</strong><small>任何任务预计拖期时拒绝生成排程；关闭时允许排程并报告准点率。</small></span>
              </label>
              <button class="btn btn-primary btn-block mt-16" :disabled="scheduling || planResult.status !== 'planned'" @click="schedulePlan">
                {{ scheduling ? '正在联合排程...' : planResult.status === 'planned' ? '执行生产排程' : '该计划已完成排程' }}
              </button>
            </template>
            <div v-else class="empty">完成预测并生成生产计划后，可在这里直接执行 AGV 排程</div>

            <template v-if="scheduleResult">
              <div class="notice success mt-16">
                已完成排程：{{ scheduleRun.agv_count }} 台 AGV、{{ scheduleRun.task_count }} 个任务；准点率 {{ scheduleRun.on_time_rate }}%。
              </div>
              <div v-if="scheduleRun.late_task_count" class="notice warning mt-12">
                {{ scheduleRun.late_task_count }} 个任务拖期，总拖期 {{ Number(scheduleRun.total_tardiness_seconds || 0).toFixed(1) }} 秒。请增加车辆、放宽交期或降低需求缓冲。
              </div>
              <div class="grid planner-metrics mt-16">
                <div><span>使用 AGV</span><strong>{{ scheduleRun.agv_count }} 台</strong></div>
                <div><span>计划跨度</span><strong>{{ Number(scheduleRun.makespan_seconds || 0).toFixed(1) }} s</strong></div>
                <div><span>准点率</span><strong>{{ scheduleRun.on_time_rate }}%</strong></div>
                <div><span>拖期任务</span><strong>{{ scheduleRun.late_task_count }}</strong></div>
                <div><span>总拖期</span><strong>{{ Number(scheduleRun.total_tardiness_seconds || 0).toFixed(1) }} s</strong></div>
                <div><span>总里程</span><strong>{{ Number(scheduleRun.total_distance || 0).toFixed(1) }} m</strong></div>
              </div>
            </template>
          </div>
        </section>
      </div>

      <ScheduleGantt v-if="subTab === 'predict' && scheduleResult" :result="scheduleResult" />

      <div v-if="subTab === 'records'" class="mt-16">
        <div class="section-toolbar">
          <span class="muted small">共 {{ runs.length }} 条预测记录</span>
          <button class="btn btn-sm" :disabled="loadingRuns" @click="loadRuns">{{ loadingRuns ? '加载中...' : '刷新记录' }}</button>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>ID</th><th>请求模型</th><th>采用模型</th><th>来源</th><th>历史量</th><th>预测期数</th><th>预测总量</th><th>MAPE</th><th>时间</th></tr></thead>
            <tbody>
              <tr v-for="run in runs" :key="run.id">
                <td class="mono">{{ run.id }}</td>
                <td>{{ run.model_display }}</td>
                <td class="cell-main">{{ MODEL_LABELS[run.selected_model] || run.selected_model }}</td>
                <td>{{ run.source_display }}</td>
                <td>{{ run.history_count }}</td>
                <td>{{ run.horizon }}</td>
                <td>{{ Math.round(run.predicted_total) }}</td>
                <td>{{ run.mape }}%</td>
                <td class="small">{{ formatTime(run.created_at) }}</td>
              </tr>
              <tr v-if="!runs.length"><td colspan="9"><div class="empty">暂无预测记录</div></td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.forecast-grid { grid-template-columns: minmax(340px, 0.78fr) minmax(0, 1.52fr); align-items: start; }
.forecast-chart { width: 100%; min-height: 280px; margin-top: 4px; border-radius: 10px; background: var(--chart-bg); border: 1px solid var(--line); }
.chart-grid { stroke: var(--chart-grid); stroke-width: 1; }
.forecast-divider { stroke: var(--chart-divider); stroke-width: 1; stroke-dasharray: 4 5; }
.forecast-axis { display: flex; justify-content: space-between; padding: 6px 42px 0; color: var(--muted); font-size: 10px; }
.production-chain-grid { grid-template-columns: minmax(360px, 1.08fr) minmax(0, 0.92fr); align-items: start; }
.deadline-option { display: flex; gap: 10px; align-items: flex-start; padding: 12px 13px; border: 1px solid var(--line); border-radius: 10px; background: var(--fill-1); cursor: pointer; }
.deadline-option input { margin-top: 2px; accent-color: var(--cyan); }
.deadline-option span { display: flex; flex-direction: column; gap: 3px; }
.deadline-option small { color: var(--muted); font-size: 10px; line-height: 1.5; }
.route-mode-switch { display: inline-flex; width: fit-content; padding: 3px; border: 1px solid var(--line); border-radius: 9px; background: var(--track-bg-deep); }
.route-mode-switch button { padding: 7px 14px; border: 0; border-radius: 7px; background: transparent; color: var(--muted); font-size: 11px; font-weight: 650; }
.route-mode-switch button.active { color: var(--on-accent); background: var(--cyan); box-shadow: 0 3px 10px rgba(47,214,195,.28); font-weight: 700; }
.route-editor-field { gap: 10px; }
.route-editor-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.route-editor-head > div:first-child { display: grid; gap: 3px; }
.route-editor-actions { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; justify-content: flex-end; }
.route-edit-list { display: grid; gap: 10px; margin-top: 4px; }
.route-edit-card { padding: 13px; border: 1px solid var(--line); border-radius: 11px; background: var(--fill-1); }
.route-edit-card-head { display: flex; justify-content: space-between; margin-bottom: 9px; font-size: 11px; }
.route-edit-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 9px; }
.link-btn.danger { color: var(--red); }
@media (max-width: 980px) {
  .forecast-grid, .production-chain-grid { grid-template-columns: minmax(0, 1fr); }
  .route-edit-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .route-editor-head { flex-direction: column; }
  .route-editor-actions { justify-content: flex-start; }
}
@media (max-width: 620px) { .route-edit-grid { grid-template-columns: 1fr; } }
</style>
