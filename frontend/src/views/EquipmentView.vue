<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '../api'

const emit = defineEmits(['notify'])

const FEATURES = [
  { key: 'temperature_c', label: '温度 ℃', threshold: 74, color: '#d97934' },
  { key: 'vibration_mm_s', label: '振动 mm/s', threshold: 3.1, color: '#cf5260' },
  { key: 'current_a', label: '电流 A', threshold: 6.2, color: '#4f6fd1' },
  { key: 'spindle_speed_rpm', label: '主轴转速 rpm', threshold: null, color: '#2b9a76' },
  { key: 'tool_wear', label: '刀具磨损', threshold: 0.78, color: '#8b5bc7' },
]
const STATE_LABELS = { normal: '正常', worn: '磨损', fault: '故障' }
const STATE_COLORS = { normal: '#2b9a76', worn: '#d2902e', fault: '#cf5260' }

const subTab = ref('diagnose')
const sourceKind = ref('dataset')
const scenario = ref('worn')
const equipmentCode = ref('CNC-01')
const workOrders = ref([])
const selectedWorkOrderId = ref('')
const file = ref(null)
const objectUrl = ref('')
const selectedFeature = ref('vibration_mm_s')
const result = ref(null)
const overview = ref({})
const records = ref([])
const running = ref(false)
const loadingRecords = ref(false)
const error = ref('')
// 磨损（worn）预警阈值：0.6 精确优先 / 0.1 高召回（宁可误报不漏报）
const wornThreshold = ref(0.6)
const WORN_PRESETS = [
  { value: 0.6, label: '0.6 精确优先（误报少）' },
  { value: 0.3, label: '0.3 平衡' },
  { value: 0.1, label: '0.1 高召回（宁可误报）' },
]
// 训练数据集对比（ai4i 46 条 worn vs NASA 铣削 760 条）
const datasetCompare = ref([])
const loadingCompare = ref(false)
const compareBest = ref('')

const feature = computed(
  () => FEATURES.find((item) => item.key === selectedFeature.value) || FEATURES[0],
)
const series = computed(() => result.value?.series || [])
const stateRows = computed(() => {
  const distribution = result.value?.state_distribution || {}
  return Object.entries(distribution).map(([key, value]) => ({
    key,
    label: value.label || STATE_LABELS[key] || key,
    count: value.count || 0,
    ratio: value.ratio || 0,
    color: STATE_COLORS[key] || '#89979d',
  }))
})

const wornWarning = computed(() => result.value?.worn_warning || null)
const wornScorePct = computed(() => Math.round((wornWarning.value?.worn_score || 0) * 100))
const anomalyInfo = computed(() => {
  const a = result.value?.anomaly
  if (!a || !a.available) return null
  return a
})
const anomalyHigh = computed(() => {
  const a = anomalyInfo.value
  if (!a) return false
  const score = Number(a.latest_score || 0)
  const thr = Number(a.threshold_q95 || Infinity)
  const flagged = Number(a.flagged || 0)
  // 与后端一致：有点被判异常，或最新分超过 95% 分位阈值
  return flagged > 0 || score >= thr
})

const lineChart = computed(() => {
  const width = 760
  const height = 250
  const padding = 36
  const values = series.value.map((row) => Number(row[selectedFeature.value]))
  if (values.length < 2) {
    return { points: '', width, height, min: 0, max: 1, ticks: [] }
  }

  const minimum = Math.min(...values)
  const maximum = Math.max(...values)
  const span = maximum - minimum || 1
  const chartMin = minimum - span * 0.1
  const chartMax = maximum + span * 0.1
  const pointList = values.map((value, index) => {
    const x = padding + (index / (values.length - 1)) * (width - padding * 2)
    const y =
      height -
      padding -
      ((value - chartMin) / (chartMax - chartMin)) * (height - padding * 2)
    return `${x.toFixed(2)},${y.toFixed(2)}`
  })
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => ({
    y: padding + ratio * (height - padding * 2),
    value: chartMax - ratio * (chartMax - chartMin),
  }))
  return {
    points: pointList.join(' '),
    width,
    height,
    min: chartMin,
    max: chartMax,
    ticks,
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
    overview.value = await api.equipmentOverview()
  } catch (err) {
    notify(`设备概览加载失败：${err.message}`, 'error')
  }
}

async function loadDatasetCompare() {
  loadingCompare.value = true
  try {
    const data = await api.equipmentDatasetCompare()
    datasetCompare.value = data.datasets || []
    compareBest.value = data.best_worn || ''
  } catch (err) {
    notify(`数据集对比加载失败：${err.message}`, 'error')
  } finally {
    loadingCompare.value = false
  }
}

async function loadRecords() {
  loadingRecords.value = true
  try {
    records.value = await api.equipmentRecords()
  } catch (err) {
    notify(`诊断记录加载失败：${err.message}`, 'error')
  } finally {
    loadingRecords.value = false
  }
}

async function loadWorkOrders() {
  try {
    workOrders.value = await api.workOrders()
  } catch {
    workOrders.value = []
  }
}

async function runDiagnosis() {
  running.value = true
  error.value = ''
  try {
    let payload
    if (sourceKind.value === 'upload') {
      if (!file.value) throw new Error('请先选择传感器 CSV 文件')
      payload = new FormData()
      payload.append('file', file.value)
      payload.append('equipment_code', equipmentCode.value || 'CNC-01')
      payload.append('worn_threshold', String(wornThreshold.value))
      if (selectedWorkOrderId.value) payload.append('work_order_id', String(selectedWorkOrderId.value))
    } else {
      payload = {
        sample: scenario.value,
        equipment_code: equipmentCode.value || 'CNC-01',
        worn_threshold: wornThreshold.value,
        work_order_id: selectedWorkOrderId.value || null,
      }
    }
    result.value = await api.equipmentDiagnose(payload)
    notify(result.value.work_order_no
      ? `设备诊断完成并已关联工单 ${result.value.work_order_no}`
      : `设备诊断完成：${result.value.predicted_state_label}`)
    await loadOverview()
    await loadWorkOrders()
    if (subTab.value === 'records') await loadRecords()
  } catch (err) {
    error.value = err.message
    notify(err.message, 'error')
  } finally {
    running.value = false
  }
}

function openRecords() {
  subTab.value = 'records'
  loadRecords()
}

onMounted(() => {
  loadOverview()
  loadDatasetCompare()
  loadWorkOrders()
})

onUnmounted(() => {
  if (objectUrl.value) URL.revokeObjectURL(objectUrl.value)
})
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <div>
        <div class="panel-title">设备状态监测</div>
        <div class="panel-desc">任务 6：对温度、振动、电流、转速和刀具磨损进行状态分类与规则告警</div>
      </div>
      <div class="toolbar-right">
        <button class="btn btn-sm" :class="{ 'btn-primary': subTab === 'diagnose' }" @click="subTab = 'diagnose'">在线诊断</button>
        <button class="btn btn-sm" :class="{ 'btn-primary': subTab === 'records' }" @click="openRecords">诊断记录</button>
      </div>
    </div>

    <div class="panel-body">
      <div class="grid stats-grid">
        <div class="mini-stat panel"><span>累计诊断</span><strong>{{ overview.total || 0 }}</strong></div>
        <div class="mini-stat panel"><span>平均置信度</span><strong>{{ ((overview.average_confidence || 0) * 100).toFixed(1) }}%</strong></div>
        <div class="mini-stat panel"><span>模型准确率</span><strong>{{ ((overview.model_metrics?.accuracy || 0) * 100).toFixed(1) }}%</strong></div>
        <div class="mini-stat panel"><span>状态类别</span><strong>3</strong></div>
      </div>

      <!-- 训练数据集对比：ai4i（46 条 worn）vs NASA 铣削（760 条 worn） -->
      <section class="panel mt-16">
        <div class="panel-head">
          <div>
            <div class="panel-title">训练数据集对比（worn 类效果）</div>
            <div class="panel-desc">
              同一套 LightGBM 流程，只更换训练数据：ai4i 仅 46 条 worn，NASA 铣削 760 条，Figshare 铣削 315 条
            </div>
          </div>
          <div class="toolbar-right">
            <span v-if="compareBest" class="tag">worn-F1 最优：{{ compareBest }}</span>
            <button class="btn btn-sm" :disabled="loadingCompare" @click="loadDatasetCompare">
              {{ loadingCompare ? '计算中...' : '重新对比' }}
            </button>
          </div>
        </div>
        <div class="panel-body">
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>数据集</th><th>样本数</th><th>worn 样本</th><th>特征数</th>
                  <th>准确率</th><th>macro-F1</th><th>worn-F1</th><th>fault F1</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in datasetCompare" :key="row.dataset">
                  <td class="cell-main">{{ row.dataset }}</td>
                  <td>{{ row.rows ?? '--' }}</td>
                  <td>{{ row.worn_count ?? '--' }}</td>
                  <td>{{ row.features ?? '--' }}</td>
                  <td>{{ row.accuracy != null ? (row.accuracy * 100).toFixed(1) + '%' : '--' }}</td>
                  <td>{{ row.macro_f1 ?? '--' }}</td>
                  <td>
                    <strong :style="{ color: row.dataset === compareBest ? '#2b9a76' : '#5f7179' }">
                      {{ row.worn_f1 ?? '--' }}
                    </strong>
                  </td>
                  <td>{{ row.fault_f1 ?? '--' }}</td>
                </tr>
                <tr v-if="!datasetCompare.length">
                  <td colspan="8"><div class="empty">暂无对比数据（可点右上角「重新对比」）</div></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="notice mt-12">
            说明：NASA 铣削数据没有温度/转速两列（用常数占位），因此作为**独立磨损数据集**验证方法有效性，
            不直接并入 ai4i 模型；worn-F1 由 5 折交叉验证的同分布评估得到。
          </div>
        </div>
      </section>

      <div v-if="subTab === 'diagnose'" class="grid equipment-grid mt-16">
        <section class="panel">
          <div class="panel-head"><div><div class="panel-title">数据配置</div><div class="panel-desc">使用内置样例或上传带传感器列的 CSV</div></div></div>
          <div class="panel-body">
            <div class="form-grid">
              <div class="field">
                <label>设备编号</label>
                <input v-model="equipmentCode" class="input" type="text" />
              </div>
              <div class="field">
                <label>关联生产工单（可选）</label>
                <select v-model="selectedWorkOrderId" class="select">
                  <option value="">不关联工单</option>
                  <option v-for="order in workOrders.filter(item => !['completed', 'cancelled'].includes(item.status))" :key="order.id" :value="order.id">{{ order.order_no }} · {{ order.title }} · {{ order.status_display }}</option>
                </select>
              </div>
              <div class="field">
                <label>数据来源</label>
                <select v-model="sourceKind" class="select">
                  <option value="dataset">内置样例</option>
                  <option value="upload">上传 CSV</option>
                </select>
              </div>
              <div v-if="sourceKind === 'dataset'" class="field">
                <label>设备场景</label>
                <select v-model="scenario" class="select">
                  <option value="normal">正常运行</option>
                  <option value="worn">刀具磨损</option>
                  <option value="fault">设备故障</option>
                </select>
              </div>
              <div class="field">
                <label>磨损灵敏度（worn 阈值）</label>
                <select v-model.number="wornThreshold" class="select">
                  <option v-for="item in WORN_PRESETS" :key="item.value" :value="item.value">{{ item.label }}</option>
                </select>
              </div>
              <div v-if="sourceKind === 'upload'" class="field full">
                <label>传感器 CSV（温度、振动、电流、转速、磨损列）</label>
                <input class="input" type="file" accept=".csv,text/csv" @change="onFileChange" />
              </div>
            </div>

            <div class="notice mt-12">
              必需列：<span class="mono">temperature_c, vibration_mm_s, current_a, spindle_speed_rpm, tool_wear</span>
            </div>
            <div class="toolbar-row mt-16">
              <button class="btn btn-primary" :disabled="running" @click="runDiagnosis">
                {{ running ? '正在诊断...' : '开始诊断' }}
              </button>
              <span class="muted small">模型：{{ result?.algorithm || 'LightGBM' }} + 规则告警 + 磨损检测头</span>
            </div>
            <div v-if="error" class="notice warning mt-12">{{ error }}</div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div><div class="panel-title">诊断结果</div><div class="panel-desc">当前状态、传感器趋势与规则告警</div></div>
            <span v-if="result" class="tag">{{ result.predicted_state_label }}</span>
          </div>
          <div class="panel-body">
            <div v-if="result" class="grid metric-grid">
              <div class="optimization-metric"><span>综合状态</span><strong :style="{ color: STATE_COLORS[result.predicted_state] }">{{ result.predicted_state_label }}</strong></div>
              <div class="optimization-metric"><span>样本数量</span><strong>{{ result.sample_count }}</strong></div>
              <div class="optimization-metric"><span>末样本置信度</span><strong>{{ (result.confidence * 100).toFixed(1) }}%</strong></div>
              <div class="optimization-metric"><span>规则告警</span><strong>{{ result.rule_alerts.length }}</strong></div>
            </div>
            <div v-else class="empty">请选择样例或上传 CSV 后开始诊断</div>

            <div v-if="wornWarning" class="worn-card mt-12" :class="{ alarm: wornWarning.worn_alert }">
              <div class="worn-head">
                <span class="worn-lamp" :class="{ on: wornWarning.worn_alert }"></span>
                <strong>刀具磨损预警</strong>
                <span class="worn-state" :class="{ on: wornWarning.worn_alert }">
                  {{ wornWarning.worn_alert ? '需要换刀' : '磨损正常' }}
                </span>
                <span class="muted small">检测头 AUROC {{ wornWarning.detector_metrics?.auroc ?? '--' }}</span>
              </div>
              <div class="worn-score-row">
                <span class="muted small">worn 概率</span>
                <div class="worn-track">
                  <div class="worn-fill" :style="{ width: `${wornScorePct}%` }"></div>
                  <div class="worn-threshold-mark" :style="{ left: `${(wornWarning.worn_threshold || 0.6) * 100}%` }"></div>
                </div>
                <strong>{{ wornScorePct }}%</strong>
              </div>
              <div class="worn-foot">
                <span class="muted small">阈值 {{ wornWarning.worn_threshold }}</span>
                <span v-if="wornWarning.error" class="small" style="color:#cf5260">{{ wornWarning.error }}</span>
                <span v-else class="muted small">概率超过阈值即亮红灯（阈值越低越灵敏）</span>
              </div>
            </div>

            <div v-if="anomalyInfo" class="anomaly-card mt-12" :class="{ alarm: anomalyHigh }">
              <div class="anomaly-head">
                <span class="anomaly-lamp" :class="{ on: anomalyHigh }"></span>
                <strong>无监督异常检测（{{ anomalyInfo.method || 'PyOD' }}）</strong>
                <span class="anomaly-state" :class="{ on: anomalyHigh }">
                  {{ anomalyHigh ? '偏离正常分布' : '接近正常分布' }}
                </span>
                <span class="muted small">无需标签 · 用于发现训练集里没有的异常</span>
              </div>
              <div class="anomaly-grid">
                <div><span class="muted small">最新异常分</span><strong>{{ anomalyInfo.latest_score ?? '--' }}</strong></div>
                <div><span class="muted small">异常阈值(正常样本99%分位)</span><strong>{{ anomalyInfo.threshold_q95 ?? '--' }}</strong></div>
                <div><span class="muted small">越线点数</span><strong>{{ anomalyInfo.flagged ?? 0 }} / {{ result?.sample_count ?? 0 }}</strong></div>
                <div><span class="muted small">越线占比</span><strong>{{ ((anomalyInfo.flagged_ratio || 0) * 100).toFixed(1) }}%</strong></div>
              </div>
              <div class="anomaly-foot muted small">
                基准：用同源 <b>{{ anomalyInfo.normal_samples ?? '--' }}</b> 条正常样本训练（{{ anomalyInfo.score_source || 'synthetic' }}）。
                分数越高越偏离正常；越线占比 0% 表示与正常分布一致，占比越高说明整段越漂移。
              </div>
            </div>

            <template v-if="result">
              <div class="section-toolbar mt-16">
                <select v-model="selectedFeature" class="select">
                  <option v-for="item in FEATURES" :key="item.key" :value="item.key">{{ item.label }}</option>
                </select>
                <span class="muted small">展示最近 {{ series.length }} 个采样点</span>
              </div>
              <svg class="equipment-chart" :viewBox="`0 0 ${lineChart.width} ${lineChart.height}`" role="img" aria-label="传感器趋势图">
                <line
                  v-for="tick in lineChart.ticks"
                  :key="tick.y"
                  x1="36"
                  :x2="lineChart.width - 36"
                  :y1="tick.y"
                  :y2="tick.y"
                  class="chart-grid"
                />
                <polyline :points="lineChart.points" fill="none" :stroke="feature.color" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" />
              </svg>

              <div class="state-bars mt-12">
                <div v-for="item in stateRows" :key="item.key" class="state-bar-row">
                  <span>{{ item.label }}</span>
                  <div class="progress-track"><div class="progress-bar" :style="{ width: `${item.ratio * 100}%`, background: item.color }"></div></div>
                  <strong>{{ item.count }}</strong>
                </div>
              </div>

              <div v-if="result.rule_alerts.length" class="notice warning mt-16">
                <strong>规则告警：</strong>
                <span>{{ result.rule_alerts.map((item) => item.message).join('；') }}</span>
              </div>
            </template>
          </div>
        </section>
      </div>

      <div v-else class="mt-16">
        <div class="section-toolbar">
          <span class="muted small">共 {{ records.length }} 条诊断记录</span>
          <button class="btn btn-sm" :disabled="loadingRecords" @click="loadRecords">{{ loadingRecords ? '加载中...' : '刷新记录' }}</button>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>ID</th><th>工单</th><th>设备</th><th>来源</th><th>样本数</th><th>状态</th><th>置信度</th><th>告警</th><th>时间</th></tr></thead>
            <tbody>
              <tr v-for="record in records" :key="record.id">
                <td class="mono">{{ record.id }}</td>
                <td><RouterLink v-if="record.work_order" class="link-btn" :to="{ path: '/work-orders', query: { work_order: record.work_order } }">{{ record.work_order_no }}</RouterLink><span v-else class="muted">--</span></td>
                <td class="cell-main">{{ record.equipment_code }}</td>
                <td>{{ record.source_display }}</td>
                <td>{{ record.sample_count }}</td>
                <td><span class="badge" :style="{ color: STATE_COLORS[record.predicted_state] }">{{ record.state_display }}</span></td>
                <td>{{ (record.confidence * 100).toFixed(1) }}%</td>
                <td>{{ record.rule_alerts.length }}</td>
                <td class="small">{{ formatTime(record.created_at) }}</td>
              </tr>
              <tr v-if="!records.length"><td colspan="9"><div class="empty">暂无诊断记录</div></td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.equipment-grid { grid-template-columns: minmax(340px, 0.85fr) minmax(0, 1.35fr); align-items: start; }
.equipment-chart { width: 100%; min-height: 250px; margin-top: 4px; border-radius: 10px; background: #f8faf9; border: 1px solid #e1e8e5; }
.chart-grid { stroke: #e2e9e6; stroke-width: 1; }
.state-bars { display: grid; gap: 9px; }
.state-bar-row { display: grid; grid-template-columns: 56px minmax(0, 1fr) 40px; gap: 10px; align-items: center; color: #5f7179; font-size: 11px; }
@media (max-width: 980px) { .equipment-grid { grid-template-columns: minmax(0, 1fr); } }

/* ---- 磨损（worn）预警卡片 ---- */
.worn-card { border: 1px solid #e1e8e5; border-radius: 10px; padding: 12px 14px; background: #f8faf9; display: grid; gap: 9px; }
.worn-card.alarm { border-color: #f0b4bb; background: #fdf3f4; }
.worn-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12px; }
.worn-lamp { width: 11px; height: 11px; border-radius: 50%; background: #2b9a76; box-shadow: 0 0 0 3px rgba(43,154,118,.15); }
.worn-lamp.on { background: #cf5260; box-shadow: 0 0 0 3px rgba(207,82,96,.2); animation: worn-blink 1.2s infinite; }
.worn-state { font-size: 11px; color: #2b9a76; }
.worn-state.on { color: #cf5260; font-weight: 600; }
.worn-score-row { display: grid; grid-template-columns: 60px minmax(0,1fr) 48px; gap: 10px; align-items: center; font-size: 12px; }
.worn-track { position: relative; height: 10px; border-radius: 6px; background: #e8efec; overflow: hidden; }
.worn-fill { height: 100%; border-radius: 6px; background: linear-gradient(90deg, #2b9a76, #d2902e 60%, #cf5260); transition: width .3s ease; }
.worn-threshold-mark { position: absolute; top: -2px; bottom: -2px; width: 2px; background: #34495e; opacity: .55; }
.worn-foot { display: flex; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
@keyframes worn-blink { 0%,100% { opacity: 1 } 50% { opacity: .45 } }

/* ---- 无监督异常（PyOD ECOD）卡片 ---- */
.anomaly-card { border: 1px solid #e1e8e5; border-radius: 10px; padding: 12px 14px; background: #f7f9fb; display: grid; gap: 9px; }
.anomaly-card.alarm { border-color: #f2d3a8; background: #fdf8f1; }
.anomaly-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12px; }
.anomaly-lamp { width: 11px; height: 11px; border-radius: 50%; background: #2b9a76; box-shadow: 0 0 0 3px rgba(43,154,118,.15); }
.anomaly-lamp.on { background: #d2902e; box-shadow: 0 0 0 3px rgba(210,144,46,.2); }
.anomaly-state { font-size: 11px; color: #2b9a76; }
.anomaly-state.on { color: #b8791f; font-weight: 600; }
.anomaly-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.anomaly-grid > div { display: grid; gap: 2px; font-size: 12px; }
.anomaly-grid strong { font-size: 15px; color: #2f3d44; }
.anomaly-foot { line-height: 1.5; }
@media (max-width: 980px) { .anomaly-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
