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
const resultTab = ref('diagnosis')
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
const recentRecords = computed(() => records.value.slice(0, 8))
const modelMetrics = computed(() => overview.value.model_metrics || {})

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
    resultTab.value = 'diagnosis'
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
  loadRecords()
})

onUnmounted(() => {
  if (objectUrl.value) URL.revokeObjectURL(objectUrl.value)
})
</script>

<template>
  <div class="equipment-page">
    <section class="panel equipment-command">
      <div class="equipment-command-copy">
        <span class="equipment-command-mark">◈</span>
        <div><strong>设备状态监测</strong><small>温度、振动、电流、转速和刀具磨损的状态分类与规则告警</small></div>
      </div>
      <div class="toolbar-right">
        <button class="btn btn-sm" :class="{ 'btn-primary': subTab === 'diagnose' }" @click="subTab = 'diagnose'">在线诊断</button>
        <button class="btn btn-sm" :class="{ 'btn-primary': subTab === 'records' }" @click="openRecords">诊断记录</button>
      </div>
    </section>

    <div class="grid stats-grid equipment-stats">
      <div class="mini-stat panel"><span>累计诊断</span><strong>{{ overview.total || 0 }}</strong></div>
      <div class="mini-stat panel"><span>平均置信度</span><strong>{{ ((overview.average_confidence || 0) * 100).toFixed(1) }}%</strong></div>
      <div class="mini-stat panel"><span>模型准确率</span><strong>{{ ((modelMetrics.accuracy || 0) * 100).toFixed(1) }}%</strong></div>
      <div class="mini-stat panel"><span>状态类别</span><strong>3</strong></div>
    </div>

    <div v-if="subTab === 'diagnose'" class="equipment-workspace">
      <aside class="panel equipment-config-panel">
        <div class="panel-head"><div><div class="panel-title">诊断配置</div><div class="panel-desc">样例或 CSV 输入</div></div></div>
        <div class="panel-body">
          <div class="equipment-form-stack">
            <div class="field"><label>设备编号</label><input v-model="equipmentCode" class="input" type="text" /></div>
            <div class="field"><label>关联生产工单（可选）</label><select v-model="selectedWorkOrderId" class="select"><option value="">不关联工单</option><option v-for="order in workOrders.filter(item => !['completed', 'cancelled'].includes(item.status))" :key="order.id" :value="order.id">{{ order.order_no }} · {{ order.title }}</option></select></div>
            <div class="field"><label>数据来源</label><select v-model="sourceKind" class="select"><option value="dataset">内置样例</option><option value="upload">上传 CSV</option></select></div>
            <div v-if="sourceKind === 'dataset'" class="field"><label>设备场景</label><select v-model="scenario" class="select"><option value="normal">正常运行</option><option value="worn">刀具磨损</option><option value="fault">设备故障</option></select></div>
            <div class="field"><label>磨损灵敏度</label><select v-model.number="wornThreshold" class="select"><option v-for="item in WORN_PRESETS" :key="item.value" :value="item.value">{{ item.label }}</option></select></div>
            <div v-if="sourceKind === 'upload'" class="field"><label>传感器 CSV</label><input class="input" type="file" accept=".csv,text/csv" @change="onFileChange" /></div>
          </div>
          <div class="feature-requirements">
            <span>必要字段</span>
            <code>temperature_c · vibration_mm_s · current_a · spindle_speed_rpm · tool_wear</code>
          </div>
          <div v-if="error" class="notice warning mt-12">{{ error }}</div>
          <div class="equipment-run-block">
            <button class="btn btn-primary btn-block" :disabled="running" @click="runDiagnosis">{{ running ? '正在诊断...' : '开始设备诊断' }}</button>
            <span>模型：{{ result?.algorithm || 'LightGBM' }} + 规则告警</span>
          </div>
        </div>
      </aside>

      <main class="panel equipment-result-panel">
        <div class="panel-head equipment-result-head">
          <div><div class="panel-title">诊断工作区</div><div class="panel-desc">结果、数据集对比与模型配置</div></div>
          <div class="result-tabs">
            <button :class="{ active: resultTab === 'diagnosis' }" @click="resultTab = 'diagnosis'">诊断结果</button>
            <button :class="{ active: resultTab === 'dataset' }" @click="resultTab = 'dataset'">数据集对比</button>
            <button :class="{ active: resultTab === 'model' }" @click="resultTab = 'model'">模型信息</button>
          </div>
        </div>
        <div class="panel-body equipment-result-body">
          <template v-if="resultTab === 'diagnosis'">
            <div v-if="result" class="grid metric-grid result-metrics">
              <div class="optimization-metric"><span>综合状态</span><strong :style="{ color: STATE_COLORS[result.predicted_state] }">{{ result.predicted_state_label }}</strong></div>
              <div class="optimization-metric"><span>样本数量</span><strong>{{ result.sample_count }}</strong></div>
              <div class="optimization-metric"><span>末样本置信度</span><strong>{{ (result.confidence * 100).toFixed(1) }}%</strong></div>
              <div class="optimization-metric"><span>规则告警</span><strong>{{ result.rule_alerts.length }}</strong></div>
            </div>
            <div v-else class="equipment-result-empty"><span>◈</span><strong>等待设备诊断</strong><p>在左侧选择样例或上传 CSV，然后点击“开始设备诊断”。</p></div>

            <div v-if="wornWarning" class="worn-card mt-12" :class="{ alarm: wornWarning.worn_alert }">
              <div class="worn-head"><span class="worn-lamp" :class="{ on: wornWarning.worn_alert }"></span><strong>刀具磨损预警</strong><span class="worn-state" :class="{ on: wornWarning.worn_alert }">{{ wornWarning.worn_alert ? '需要换刀' : '磨损正常' }}</span><span class="muted small">AUROC {{ wornWarning.detector_metrics?.auroc ?? '--' }}</span></div>
              <div class="worn-score-row"><span class="muted small">worn 概率</span><div class="worn-track"><div class="worn-fill" :style="{ width: `${wornScorePct}%` }"></div><div class="worn-threshold-mark" :style="{ left: `${(wornWarning.worn_threshold || 0.6) * 100}%` }"></div></div><strong>{{ wornScorePct }}%</strong></div>
              <div class="worn-foot"><span class="muted small">阈值 {{ wornWarning.worn_threshold }}</span><span v-if="wornWarning.error" class="small" style="color:#cf5260">{{ wornWarning.error }}</span><span v-else class="muted small">概率超过阈值即触发换刀提醒</span></div>
            </div>

            <div v-if="anomalyInfo" class="anomaly-card mt-12" :class="{ alarm: anomalyHigh }">
              <div class="anomaly-head"><span class="anomaly-lamp" :class="{ on: anomalyHigh }"></span><strong>无监督异常检测 · {{ anomalyInfo.method || 'PyOD' }}</strong><span class="anomaly-state" :class="{ on: anomalyHigh }">{{ anomalyHigh ? '偏离正常分布' : '接近正常分布' }}</span></div>
              <div class="anomaly-grid"><div><span>最新异常分</span><strong>{{ anomalyInfo.latest_score ?? '--' }}</strong></div><div><span>异常阈值</span><strong>{{ anomalyInfo.threshold_q95 ?? '--' }}</strong></div><div><span>越线点数</span><strong>{{ anomalyInfo.flagged ?? 0 }} / {{ result?.sample_count ?? 0 }}</strong></div><div><span>越线占比</span><strong>{{ ((anomalyInfo.flagged_ratio || 0) * 100).toFixed(1) }}%</strong></div></div>
            </div>

            <template v-if="result">
              <div class="section-toolbar mt-16"><select v-model="selectedFeature" class="select"><option v-for="item in FEATURES" :key="item.key" :value="item.key">{{ item.label }}</option></select><span class="muted small">最近 {{ series.length }} 个采样点</span></div>
              <svg class="equipment-chart" :viewBox="`0 0 ${lineChart.width} ${lineChart.height}`" role="img" aria-label="传感器趋势图"><line v-for="tick in lineChart.ticks" :key="tick.y" x1="36" :x2="lineChart.width - 36" :y1="tick.y" :y2="tick.y" class="chart-grid" /><polyline :points="lineChart.points" fill="none" :stroke="feature.color" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" /></svg>
              <div class="state-bars mt-12"><div v-for="item in stateRows" :key="item.key" class="state-bar-row"><span>{{ item.label }}</span><div class="progress-track"><div class="progress-bar" :style="{ width: `${item.ratio * 100}%`, background: item.color }"></div></div><strong>{{ item.count }}</strong></div></div>
              <div v-if="result.rule_alerts.length" class="notice warning mt-16"><strong>规则告警：</strong><span>{{ result.rule_alerts.map((item) => item.message).join('；') }}</span></div>
            </template>
          </template>

          <template v-else-if="resultTab === 'dataset'">
            <div class="result-tab-toolbar"><div><div class="panel-title">训练数据集对比</div><div class="panel-desc">同一套 LightGBM 流程，比较不同训练数据下的 worn 类效果</div></div><div class="toolbar-right"><span v-if="compareBest" class="tag">worn-F1 最优：{{ compareBest }}</span><button class="btn btn-sm" :disabled="loadingCompare" @click="loadDatasetCompare">{{ loadingCompare ? '计算中...' : '重新对比' }}</button></div></div>
            <div class="table-wrap mt-12"><table><thead><tr><th>数据集</th><th>样本数</th><th>worn 样本</th><th>特征数</th><th>准确率</th><th>macro-F1</th><th>worn-F1</th><th>fault F1</th></tr></thead><tbody><tr v-for="row in datasetCompare" :key="row.dataset"><td class="cell-main">{{ row.dataset }}</td><td>{{ row.rows ?? '--' }}</td><td>{{ row.worn_count ?? '--' }}</td><td>{{ row.features ?? '--' }}</td><td>{{ row.accuracy != null ? (row.accuracy * 100).toFixed(1) + '%' : '--' }}</td><td>{{ row.macro_f1 ?? '--' }}</td><td><strong :style="{ color: row.dataset === compareBest ? '#2b9a76' : '#5f7179' }">{{ row.worn_f1 ?? '--' }}</strong></td><td>{{ row.fault_f1 ?? '--' }}</td></tr><tr v-if="!datasetCompare.length"><td colspan="8"><div class="empty">暂无对比数据</div></td></tr></tbody></table></div>
            <div class="notice mt-12"><strong>说明：</strong>NASA 与 Figshare 铣削数据用于验证独立磨损检测方法，不直接并入 ai4i 模型；worn-F1 来自同分布交叉验证。</div>
          </template>

          <template v-else>
            <div class="model-info-grid">
              <div><span>主模型</span><strong>{{ result?.algorithm || 'LightGBM' }}</strong></div>
              <div><span>模型准确率</span><strong>{{ ((modelMetrics.accuracy || 0) * 100).toFixed(1) }}%</strong></div>
              <div><span>状态类别</span><strong>正常 / 磨损 / 故障</strong></div>
              <div><span>累计诊断</span><strong>{{ overview.total || 0 }}</strong></div>
            </div>
            <div class="model-feature-list">
              <div class="subpanel-title">模型输入特征</div>
              <div v-for="item in FEATURES" :key="item.key" class="model-feature-row"><span class="feature-dot" :style="{ background: item.color }"></span><strong>{{ item.label }}</strong><code>{{ item.key }}</code><small>{{ item.threshold == null ? '无固定规则阈值' : `规则阈值 ${item.threshold}` }}</small></div>
            </div>
            <div class="notice info mt-16"><strong>组合策略：</strong>LightGBM 负责状态分类，规则引擎用于阈值告警，磨损检测头和无监督异常检测提供额外风险提示。</div>
          </template>
        </div>
      </main>

      <aside class="panel equipment-history-panel">
        <div class="panel-head"><div><div class="panel-title">最近诊断记录</div><div class="panel-desc">共 {{ records.length }} 条</div></div><button class="btn btn-sm" :disabled="loadingRecords" @click="loadRecords">刷新</button></div>
        <div class="panel-body">
          <div class="equipment-history-list">
            <article v-for="record in recentRecords" :key="record.id" class="equipment-history-item">
              <div class="history-item-head"><span class="history-state" :style="{ color: STATE_COLORS[record.predicted_state] }">{{ record.state_display }}</span><span class="history-time">{{ formatTime(record.created_at) }}</span></div>
              <strong>{{ record.equipment_code }}</strong>
              <div class="history-meta">{{ record.source_display }} · {{ record.sample_count }} 样本 · {{ (record.confidence * 100).toFixed(1) }}%</div>
              <RouterLink v-if="record.work_order" :to="{ path: '/work-orders', query: { work_order: record.work_order } }">关联工单 {{ record.work_order_no }} →</RouterLink>
            </article>
            <div v-if="!recentRecords.length" class="empty">暂无诊断记录</div>
          </div>
        </div>
      </aside>
    </div>

    <section v-else class="panel records-panel">
      <div class="panel-head"><div><div class="panel-title">诊断记录</div><div class="panel-desc">全部设备诊断结果与关联工单</div></div><button class="btn btn-sm" :disabled="loadingRecords" @click="loadRecords">{{ loadingRecords ? '加载中...' : '刷新记录' }}</button></div>
      <div class="panel-body">
        <div class="table-wrap"><table><thead><tr><th>ID</th><th>工单</th><th>设备</th><th>来源</th><th>样本数</th><th>状态</th><th>置信度</th><th>告警</th><th>时间</th></tr></thead><tbody><tr v-for="record in records" :key="record.id"><td class="mono">{{ record.id }}</td><td><RouterLink v-if="record.work_order" class="link-btn" :to="{ path: '/work-orders', query: { work_order: record.work_order } }">{{ record.work_order_no }}</RouterLink><span v-else class="muted">--</span></td><td class="cell-main">{{ record.equipment_code }}</td><td>{{ record.source_display }}</td><td>{{ record.sample_count }}</td><td><span class="badge" :style="{ color: STATE_COLORS[record.predicted_state] }">{{ record.state_display }}</span></td><td>{{ (record.confidence * 100).toFixed(1) }}%</td><td>{{ record.rule_alerts.length }}</td><td class="small">{{ formatTime(record.created_at) }}</td></tr><tr v-if="!records.length"><td colspan="9"><div class="empty">暂无诊断记录</div></td></tr></tbody></table></div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.equipment-page { display: grid; gap: 16px; }
.equipment-command {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 14px 16px;
  background:
    radial-gradient(circle at 86% 18%, rgba(14, 135, 146, 0.07), transparent 28%),
    linear-gradient(135deg, #ffffff, #f8fbf9);
}
.equipment-command-copy { display: flex; align-items: center; gap: 11px; min-width: 0; }
.equipment-command-mark {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  border: 1px solid rgba(14, 135, 146, 0.16);
  border-radius: 11px;
  color: var(--cyan);
  background: #edf8f5;
  font-size: 17px;
}
.equipment-command-copy > div { display: grid; gap: 3px; }
.equipment-command-copy strong { color: #18353d; font-size: 13px; font-weight: 800; }
.equipment-command-copy small { color: var(--muted); font-size: 9.5px; }
.equipment-stats { margin: 0; }
.equipment-workspace {
  display: grid;
  grid-template-columns: minmax(290px, 330px) minmax(0, 1fr) minmax(250px, 292px);
  gap: 14px;
  align-items: start;
}
.equipment-config-panel,
.equipment-history-panel { position: sticky; top: 18px; }
.equipment-config-panel .panel-body { padding: 15px; }
.equipment-form-stack { display: grid; gap: 11px; }
.feature-requirements {
  display: grid;
  gap: 5px;
  margin-top: 12px;
  padding: 11px 12px;
  border: 1px solid #dfe8e4;
  border-radius: 10px;
  background: #f7faf8;
}
.feature-requirements span { color: #70817b; font-size: 9px; font-weight: 720; }
.feature-requirements code { color: #4c6963; font-size: 8.5px; line-height: 1.65; white-space: normal; word-break: break-word; }
.equipment-run-block { display: grid; gap: 7px; margin-top: 14px; padding-top: 14px; border-top: 1px solid #e5ece9; }
.equipment-run-block .btn { min-height: 42px; }
.equipment-run-block span { color: #84928d; font-size: 8.5px; text-align: center; }
.equipment-result-panel { min-width: 0; }
.equipment-result-head { min-height: 72px; }
.result-tabs {
  display: flex;
  gap: 3px;
  padding: 3px;
  border: 1px solid #dce6e1;
  border-radius: 10px;
  background: #f2f6f4;
}
.result-tabs button {
  min-height: 29px;
  padding: 5px 9px;
  border: 0;
  border-radius: 7px;
  color: #6d7f79;
  background: transparent;
  font-size: 9px;
  font-weight: 680;
  white-space: nowrap;
}
.result-tabs button.active { color: #174a48; background: #fff; box-shadow: 0 2px 6px rgba(20, 45, 54, 0.07); }
.equipment-result-body { min-height: 620px; padding: 17px; }
.result-metrics { margin-bottom: 0; }
.equipment-result-empty {
  min-height: 430px;
  display: grid;
  place-content: center;
  justify-items: center;
  gap: 8px;
  border-radius: 12px;
  background: radial-gradient(circle at center, rgba(14, 135, 146, 0.055), transparent 38%), #fbfcfc;
  text-align: center;
}
.equipment-result-empty > span {
  width: 50px;
  height: 50px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(14, 135, 146, 0.15);
  border-radius: 15px;
  color: var(--cyan);
  background: #eef8f5;
  font-size: 21px;
}
.equipment-result-empty strong { color: #29454b; font-size: 13px; }
.equipment-result-empty p { max-width: 300px; margin: 0; color: var(--muted); font-size: 9.5px; line-height: 1.6; }
.result-tab-toolbar { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.equipment-history-panel { display: flex; flex-direction: column; max-height: calc(100vh - 36px); overflow: hidden; }
.equipment-history-panel .panel-head { min-height: 68px; padding: 14px 14px 12px; }
.equipment-history-panel .panel-body { flex: 1; min-height: 0; padding: 11px; overflow-y: auto; scrollbar-width: thin; }
.equipment-history-list { display: grid; gap: 7px; }
.equipment-history-item {
  display: grid;
  gap: 5px;
  padding: 10px;
  border: 1px solid #dfe8e4;
  border-radius: 9px;
  background: linear-gradient(145deg, #fff, #f9fbfa);
}
.history-item-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.history-state { font-size: 9px; font-weight: 760; }
.history-time { color: #96a19d; font-size: 7.5px; }
.equipment-history-item > strong { color: #294249; font-size: 10.5px; }
.history-meta { color: #7f8e89; font-size: 8px; line-height: 1.45; }
.equipment-history-item a { color: var(--cyan); font-size: 8.5px; text-decoration: none; }
.equipment-history-item a:hover { text-decoration: underline; text-underline-offset: 2px; }
.model-info-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 9px; }
.model-info-grid > div { display: grid; gap: 4px; padding: 13px; border: 1px solid #dfe8e4; border-radius: 10px; background: #f8faf9; }
.model-info-grid span { color: #7c8b86; font-size: 8.5px; }
.model-info-grid strong { color: #29444a; font-size: 12px; }
.model-feature-list { display: grid; gap: 6px; margin-top: 14px; padding: 14px; border: 1px solid #dfe8e4; border-radius: 11px; background: #fbfcfb; }
.model-feature-list .subpanel-title { margin-bottom: 4px; }
.model-feature-row { display: grid; grid-template-columns: 8px 110px minmax(0, 1fr) auto; gap: 8px; align-items: center; padding: 7px 0; border-bottom: 1px solid #edf1ef; }
.model-feature-row:last-child { border-bottom: 0; }
.feature-dot { width: 7px; height: 7px; border-radius: 50%; }
.model-feature-row strong { color: #344d53; font-size: 9.5px; }
.model-feature-row code { color: #71817c; font-size: 8.5px; }
.model-feature-row small { color: #8c9894; font-size: 8px; }
.records-panel .panel-body { padding-top: 14px; }
@media (max-width: 1300px) {
  .equipment-workspace { grid-template-columns: minmax(290px, 330px) minmax(0, 1fr); }
  .equipment-history-panel { position: static; grid-column: 1 / -1; max-height: none; }
  .equipment-history-list { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 980px) {
  .equipment-workspace { grid-template-columns: minmax(0, 1fr); }
  .equipment-config-panel { position: static; }
  .equipment-history-list { grid-template-columns: minmax(0, 1fr); }
  .result-tab-toolbar { flex-direction: column; }
  .model-info-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 760px) {
  .equipment-command { align-items: stretch; flex-direction: column; gap: 11px; }
  .equipment-command .toolbar-right { width: 100%; }
  .equipment-command .toolbar-right .btn { flex: 1; }
  .result-tabs { width: 100%; }
  .result-tabs button { flex: 1; }
  .model-feature-row { grid-template-columns: 8px minmax(0, 1fr) auto; }
  .model-feature-row code { grid-column: 2 / -1; }
  .model-feature-row small { display: none; }
}
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
