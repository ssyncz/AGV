<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { api } from '../api'

const emit = defineEmits(['notify'])
const route = useRoute()

const MODES = [
  { key: 'crack', label: '表面裂纹检测', groups: ['crack', 'free'] },
  { key: 'defect', label: '缺陷检测（定位 + 分类）', groups: ['neu', 'crack', 'free', 'workpiece'], requires: 'detector' },
]
const SHAPE_LABELS = {
  circle: '圆形', triangle: '三角形', square: '正方形',
  rectangle: '矩形', hexagon: '六边形', unknown: '未识别',
}

const subTab = ref('detect')
const mode = ref('crack')
const sourceKind = ref('dataset')
const sampleGroup = ref('crack')
const sampleName = ref('')
const file = ref(null)
const objectUrl = ref('')

const samples = ref({ crack: [], free: [], workpiece: [] })
const datasetSummary = ref({})
const overview = ref({})
const algoStatus = ref(null)
const records = ref([])
const recordFilter = ref('')
const workOrders = ref([])
const selectedWorkOrderId = ref('')

const running = ref(false)
const loadingRecords = ref(false)
const error = ref('')
const result = ref(null)

const crackAlgorithm = ref('frangi')
const deepcrackParams = ref({ algorithm: 'deepcrack', threshold: 0.72, min_area: 8, min_coverage: 0.0002, max_side: 512 })
const frangiParams = ref({
  algorithm: 'frangi',
  score_threshold: 0.54,
  vessel_threshold: 0.55,
  min_aspect: 2.5,
  mask_threshold_ratio: 0.575,
  mask_close_kernel: 3,
  mask_skeleton: false,
  mask_dilation: 3,
})
const workpieceParams = ref({ min_area: 300, approx_epsilon: 0.02, morph_kernel: 5 })
// 缺陷检测（YOLOv8n）：一次给出外接框 + 类别 + 置信度
const detectorParams = ref({ conf: 0.25, iou: 0.45 })

const currentMode = computed(() => MODES.find((item) => item.key === mode.value) || MODES[0])
const detectorAvailable = computed(() => Boolean(algoStatus.value?.detector?.available))
const detectorModel = computed(() => algoStatus.value?.detector?.model || 'YOLOv8n')
const defectAvailable = computed(() => Boolean(algoStatus.value?.defect?.available))
const defectAccuracy = computed(() => algoStatus.value?.defect?.test_accuracy)
const defectAccuracyText = computed(() =>
  defectAccuracy.value ? `${(defectAccuracy.value * 100).toFixed(1)}%` : '未训练')
const deepcrackAvailable = computed(() => Boolean(algoStatus.value?.deepcrack?.weights_found))
const modeAvailable = (item) => !item.requires || Boolean(algoStatus.value?.[item.requires]?.available)
const currentModeReady = computed(() => {
  if (!modeAvailable(currentMode.value)) return false
  if (mode.value === 'crack' && crackAlgorithm.value === 'deepcrack') return deepcrackAvailable.value
  return true
})
const groups = computed(() => currentMode.value.groups)
const activeSamples = computed(() => samples.value[sampleGroup.value] || [])
const activeParams = computed(() => {
  if (mode.value === 'defect') return detectorParams.value
  if (mode.value === 'crack') {
    return crackAlgorithm.value === 'deepcrack' ? deepcrackParams.value : frangiParams.value
  }
  return workpieceParams.value
})
const canRun = computed(() => currentModeReady.value
  && (sourceKind.value === 'upload' ? !!file.value : !!sampleName.value))
const datasetCounts = computed(() => {
  const summary = datasetSummary.value || {}
  return `${summary.crack || 0} / ${summary.free || 0} / ${summary.workpiece || 0} / ${summary.neu || 0}`
})
const datasetNote = computed(() => {
  const summary = datasetSummary.value || {}
  return `数据集：MT_Crack ${summary.crack || 0} 张（含标注掩码）· MT_Free 无缺陷 ${summary.free || 0} 张 · 合成几何工件 ${summary.workpiece || 0} 张 · NEU 六类样例 ${summary.neu || 0} 张`
})
const previewUrl = computed(() => {
  if (sourceKind.value === 'upload') return objectUrl.value
  if (!sampleName.value) return ''
  return api.visionSampleImageUrl(sampleGroup.value, sampleName.value)
})
const objects = computed(() => result.value?.objects || [])
const linkableWorkOrders = computed(() => workOrders.value.filter((item) => !['completed', 'cancelled'].includes(item.status)))

watch(mode, () => {
  sampleGroup.value = groups.value[0]
  sampleName.value = (samples.value[sampleGroup.value] || [])[0] || ''
  result.value = null
  error.value = ''
})
watch(sampleGroup, (group) => {
  sampleName.value = (samples.value[group] || [])[0] || ''
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

function resetForm() {
  file.value = null
  if (objectUrl.value) URL.revokeObjectURL(objectUrl.value)
  objectUrl.value = ''
  result.value = null
  error.value = ''
}

async function loadSamples() {
  try {
    const data = await api.visionSamples()
    samples.value = data.samples || {}
    datasetSummary.value = data.summary || {}
    if (!activeSamples.value.length) {
      const first = groups.value.find((group) => (samples.value[group] || []).length)
      if (first) sampleGroup.value = first
    }
    if (!sampleName.value) sampleName.value = activeSamples.value[0] || ''
  } catch (err) {
    notify(`数据集样例加载失败：${err.message}`, 'error')
  }
}

async function loadOverview() {
  try {
    overview.value = await api.visionOverview()
  } catch (err) {
    notify(`视觉统计加载失败：${err.message}`, 'error')
  }
}

async function loadAlgoStatus() {
  try {
    algoStatus.value = await api.visionAlgoStatus()
  } catch {
    // 状态接口不可用时按“都未就绪”处理，避免误启用需要权重的任务。
    algoStatus.value = null
  }
}

async function loadRecords() {
  loadingRecords.value = true
  try {
    records.value = await api.visionRecords(recordFilter.value ? `?task_type=${recordFilter.value}` : '')
  } catch (err) {
    notify(`检测记录加载失败：${err.message}`, 'error')
  } finally {
    loadingRecords.value = false
  }
}

async function loadWorkOrders() {
  try {
    workOrders.value = await api.workOrders()
    const requestedWorkOrder = String(route.query.work_order || '')
    if (requestedWorkOrder && workOrders.value.some((item) => String(item.id) === requestedWorkOrder)) {
      selectedWorkOrderId.value = requestedWorkOrder
    }
  } catch {
    workOrders.value = []
  }
}

async function runDetect() {
  if (!canRun.value) return notify('请先选择或上传一张图片', 'error')
  running.value = true
  error.value = ''
  try {
    const params = { ...activeParams.value }
    let payload
    if (sourceKind.value === 'upload') {
      payload = new FormData()
      payload.append('image', file.value)
      payload.append('params', JSON.stringify(params))
      if (selectedWorkOrderId.value) payload.append('work_order_id', String(selectedWorkOrderId.value))
    } else {
      payload = {
        sample: `${sampleGroup.value}/${sampleName.value}`,
        params,
        work_order_id: selectedWorkOrderId.value || null,
      }
    }
    if (mode.value === 'defect') {
      result.value = await api.visionDetectDefect(payload)
    } else {
      result.value = mode.value === 'crack'
        ? await api.visionCrack(payload)
        : await api.visionDetect(payload)
    }
    notify(result.value.work_order_no
      ? `检测完成并已关联工单 ${result.value.work_order_no}`
      : `检测完成，用时 ${result.value.elapsed_ms} ms`)
    await loadOverview()
    await loadWorkOrders()
    if (records.value.length) await loadRecords()
  } catch (err) {
    error.value = err.message
    notify(err.message, 'error')
  } finally {
    running.value = false
  }
}

async function removeRecord(record) {
  if (!window.confirm(`确认删除记录 #${record.id}？对应图片文件也会一并删除。`)) return
  try {
    await api.deleteVisionRecord(record.id)
    notify(`记录 #${record.id} 已删除`)
    await loadRecords()
    await loadOverview()
  } catch (err) {
    notify(err.message, 'error')
  }
}

function openRecords() {
  subTab.value = 'records'
  loadRecords()
}

onMounted(() => {
  loadSamples()
  loadOverview()
  loadAlgoStatus()
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
        <div class="panel-title">视觉检测</div>
        <div class="panel-desc">Frangi / DeepCrack 裂纹分割 + YOLOv8n 缺陷检测（定位 + 分类）：MT 磁瓦裂纹与 NEU 六类表面缺陷，一次检测同时给出位置和类别</div>
      </div>
      <div class="toolbar-right">
        <button class="btn btn-sm" :class="{ 'btn-primary': subTab === 'detect' }" @click="subTab = 'detect'">在线检测</button>
        <button class="btn btn-sm" :class="{ 'btn-primary': subTab === 'records' }" @click="openRecords">检测记录</button>
      </div>
    </div>

    <div class="panel-body">
      <div class="grid stats-grid">
        <div class="mini-stat panel"><span>累计检测</span><strong>{{ overview.total || 0 }}</strong></div>
        <div class="mini-stat panel"><span>裂纹检出率</span><strong>{{ overview.crack_hit_rate || 0 }}%</strong></div>
        <div class="mini-stat panel"><span>平均耗时</span><strong>{{ overview.average_elapsed_ms || 0 }} ms</strong></div>
        <div class="mini-stat panel"><span>内置数据集</span><strong class="vision-mini-value">{{ datasetCounts }}</strong></div>
      </div>
      <div class="muted small mt-12">{{ datasetNote }}</div>

      <div v-if="subTab === 'detect'" class="grid vision-grid mt-16">
        <section class="panel">
          <div class="panel-head"><div><div class="panel-title">检测配置</div><div class="panel-desc">支持内置数据集样例或本地上传图片</div></div></div>
          <div class="panel-body">
            <div class="form-grid">
              <div class="field">
                <label>检测任务</label>
                <select v-model="mode" class="select">
                  <option v-for="item in MODES" :key="item.key" :value="item.key"
                          :disabled="!modeAvailable(item)">
                    {{ item.label }}{{ modeAvailable(item) ? '' : '（权重未就绪）' }}
                  </option>
                </select>
              </div>
              <div class="field">
                <label>图片来源</label>
                <select v-model="sourceKind" class="select">
                  <option value="dataset">内置数据集样例</option>
                  <option value="upload">本地上传图片</option>
                </select>
              </div>
              <div class="field full">
                <label>关联生产工单（可选）</label>
                <select v-model="selectedWorkOrderId" class="select">
                  <option value="">不关联工单，仅保存检测记录</option>
                  <option v-for="order in linkableWorkOrders" :key="order.id" :value="order.id">{{ order.order_no }} · {{ order.title }} · {{ order.status_display }}</option>
                </select>
              </div>
              <template v-if="sourceKind === 'dataset'">
                <div class="field">
                  <label>样例分组</label>
                  <select v-model="sampleGroup" class="select">
                    <option v-for="group in groups" :key="group" :value="group">
                      {{ group === 'crack' ? 'MT_Crack 有裂纹' : group === 'free' ? 'MT_Free 无缺陷' : group === 'neu' ? 'NEU 六类缺陷' : '合成工件' }}（{{ (samples[group] || []).length }}）
                    </option>
                  </select>
                </div>
                <div class="field">
                  <label>样例文件</label>
                  <select v-model="sampleName" class="select">
                    <option v-for="name in activeSamples" :key="name" :value="name">{{ name }}</option>
                  </select>
                </div>
              </template>
              <div v-else class="field full">
                <label>上传图片（jpg / png）</label>
                <input class="input" type="file" accept="image/*" @change="onFileChange" />
              </div>

              <template v-if="mode === 'crack'">
                <div class="field">
                  <label>裂纹算法</label>
                  <select v-model="crackAlgorithm" class="select">
                    <option value="frangi">Frangi 传统方法（推荐）</option>
                    <option value="deepcrack">DeepCrack 监督分割（实验：需域内微调权重）</option>
                  </select>
                </div>
              </template>
              <template v-if="mode === 'crack' && crackAlgorithm === 'deepcrack'">
                <div class="field">
                  <label>分割阈值 threshold</label>
                  <input v-model.number="deepcrackParams.threshold" class="input" type="number" step="0.05" min="0.05" max="0.95" />
                </div>
                <div class="field">
                  <label>最小裂纹面积 min_area</label>
                  <input v-model.number="deepcrackParams.min_area" class="input" type="number" step="1" min="0" max="200" />
                </div>
                <div class="field">
                  <label>判定覆盖率 min_coverage</label>
                  <input v-model.number="deepcrackParams.min_coverage" class="input" type="number" step="0.0002" min="0" max="0.01" />
                </div>
                <div class="field">
                  <label>推理长边上限 max_side</label>
                  <input v-model.number="deepcrackParams.max_side" class="input" type="number" step="64" min="128" max="2048" />
                </div>
              </template>
              <template v-if="mode === 'crack' && crackAlgorithm === 'frangi'">
                <div class="field">
                  <label>判定阈值 score_threshold</label>
                  <input v-model.number="frangiParams.score_threshold" class="input" type="number" step="0.02" min="0.05" max="1.5" />
                </div>
                <div class="field">
                  <label>黑脊响应阈值 vessel_threshold</label>
                  <input v-model.number="frangiParams.vessel_threshold" class="input" type="number" step="0.05" min="0.05" max="0.95" />
                </div>
                <div class="field">
                  <label>细长比下限 min_aspect</label>
                  <input v-model.number="frangiParams.min_aspect" class="input" type="number" step="0.1" min="1.2" max="8" />
                </div>
                <div class="field">
                  <label>掩码相对阈值 mask_threshold_ratio</label>
                  <input v-model.number="frangiParams.mask_threshold_ratio" class="input" type="number" step="0.025" min="0" max="1" />
                </div>
                <div class="field">
                  <label>掩码闭运算核 mask_close_kernel</label>
                  <input v-model.number="frangiParams.mask_close_kernel" class="input" type="number" step="2" min="1" max="15" />
                </div>
                <div class="field">
                  <label>中心线骨架化 mask_skeleton</label>
                  <select v-model="frangiParams.mask_skeleton" class="input">
                    <option :value="false">关闭（标定最优）</option>
                    <option :value="true">开启 Zhang-Suen</option>
                  </select>
                </div>
                <div class="field">
                  <label>掩码膨胀像素 mask_dilation</label>
                  <input v-model.number="frangiParams.mask_dilation" class="input" type="number" step="1" min="0" max="8" />
                </div>
              </template>
              <template v-if="mode === 'defect'">
                <div class="field full">
                  <div class="notice">
                    <span>
                      <b>{{ detectorModel }}</b> 缺陷检测器：一次给出<b>位置 + 类别 + 置信度</b>，
                      覆盖热轧带钢 6 类缺陷（龟裂 / 夹杂 / 斑块 / 麻点 / 氧化皮压入 / 划痕）。
                      置信度阈值越低越灵敏，可先按默认值跑。
                    </span>
                  </div>
                </div>
                <div class="field">
                  <label>置信度阈值 conf</label>
                  <input v-model.number="detectorParams.conf" class="input" type="number" step="0.05" min="0.05" max="0.95" />
                </div>
                <div class="field">
                  <label>重叠抑制 IoU</label>
                  <input v-model.number="detectorParams.iou" class="input" type="number" step="0.05" min="0.1" max="0.9" />
                </div>
              </template>
              <template v-if="mode === 'workpiece'">
                <div class="field">
                  <label>最小面积 min_area</label>
                  <input v-model.number="workpieceParams.min_area" class="input" type="number" step="50" min="20" max="5000" />
                </div>
                <div class="field">
                  <label>多边形逼近精度 approx_epsilon</label>
                  <input v-model.number="workpieceParams.approx_epsilon" class="input" type="number" step="0.005" min="0.005" max="0.1" />
                </div>
                <div class="field">
                  <label>形态学核尺寸 morph_kernel</label>
                  <input v-model.number="workpieceParams.morph_kernel" class="input" type="number" step="2" min="1" max="15" />
                </div>
              </template>
            </div>

            <div v-if="mode === 'defect' && !detectorAvailable" class="notice mt-12">
              缺陷检测权重未就绪（runs/neu_yolo_runs/train/weights/best.pt）。
              请先训练 YOLOv8n 检测器，或改选裂纹检测。
            </div>
            <div v-if="mode === 'crack' && crackAlgorithm === 'deepcrack' && !deepcrackAvailable"
                 class="notice mt-12">
              未找到 DeepCrack 权重（models/deepcrack.pth），本次请求将自动回退到 Frangi。
            </div>

            <div class="toolbar-row mt-16">
              <button class="btn btn-primary" :disabled="running || !canRun" @click="runDetect">
                {{ running ? '正在检测...' : '开始检测' }}
              </button>
              <button class="btn" :disabled="running" @click="resetForm">重置</button>
            </div>
            <div v-if="error" class="notice mt-12">{{ error }}</div>
            <div v-if="!activeSamples.length && sourceKind === 'dataset'" class="notice mt-12">
              未发现内置样例。请先运行 <span class="mono">python manage.py generate_workpiece_dataset</span>，或改用本地上传。
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div><div class="panel-title">检测结果</div><div class="panel-desc">左侧原图，右侧为算法标注后的结果图</div></div>
            <span v-if="result" class="tag">{{ result.task_type === 'crack' ? '裂纹检测' : result.task_type === 'defect' ? '缺陷检测' : '工件识别' }}</span>
          </div>
          <div class="panel-body">
            <div class="vision-compare">
              <figure class="vision-figure">
                <figcaption class="cell-sub">输入图像</figcaption>
                <img v-if="previewUrl" class="vision-preview" :src="previewUrl" alt="输入图像" />
                <div v-else class="vision-placeholder">未选择图片</div>
              </figure>
              <figure class="vision-figure">
                <figcaption class="cell-sub">结果图像</figcaption>
                <img v-if="result && result.image_url" class="vision-preview" :src="result.image_url" alt="检测结果" />
                <div v-else-if="result" class="vision-placeholder">该任务无标注结果图</div>
                <div v-else class="vision-placeholder">尚未检测</div>
              </figure>
            </div>

            <template v-if="result && result.task_type === 'crack'">
              <div class="notice mt-16" :class="result.result === 'crack' ? 'warning' : 'success'">
                <strong>{{ result.result === 'crack' ? '判定：检出裂纹' : '判定：未见裂纹' }}</strong>
                <span v-if="result.fallback">（DeepCrack 不可用，已回退到 Frangi 传统方法）</span>
                <span v-else-if="result.result === 'crack' && !result.localized">（置信分超过阈值但未定位到裂纹区域，建议人工复核）</span>
              </div>
              <div class="grid metric-grid mt-16">
                <div class="optimization-metric"><span>判定结果</span><strong>{{ result.result === 'crack' ? 'crack' : 'normal' }}</strong></div>
                <div class="optimization-metric"><span>算法</span><strong>{{ result.algorithm === 'deepcrack' ? 'DeepCrack' : 'Frangi' }}</strong></div>
                <div class="optimization-metric"><span>裂纹区域数</span><strong>{{ result.count }}</strong></div>
                <div class="optimization-metric"><span>置信分</span><strong>{{ result.score }}</strong></div>
                <div v-if="result.algorithm === 'deepcrack'" class="optimization-metric"><span>裂纹覆盖率</span><strong>{{ result.coverage ?? '--' }}</strong></div>
                <div v-if="result.algorithm === 'deepcrack'" class="optimization-metric"><span>最大概率</span><strong>{{ result.max_prob ?? '--' }}</strong></div>
                <div v-if="result.algorithm !== 'deepcrack'" class="optimization-metric"><span>最大脊响应</span><strong>{{ result.max_response ?? '--' }}</strong></div>
                <div class="optimization-metric"><span>原图尺寸</span><strong>{{ result.width }}×{{ result.height }}</strong></div>
                <div class="optimization-metric"><span>耗时</span><strong>{{ result.elapsed_ms }} ms</strong></div>
              </div>
            </template>

            <template v-else-if="result && result.task_type === 'defect'">
              <div class="notice mt-16" :class="result.count ? 'warning' : 'success'">
                <strong v-if="result.count">
                  判定：检出 {{ result.count }} 处缺陷（主类 {{ result.objects[0].label }}）
                </strong>
                <strong v-else>判定：未检出缺陷</strong>
                <span v-if="result.count">（最高置信度 {{ (result.objects[0].confidence * 100).toFixed(1) }}%）</span>
              </div>
              <div class="grid metric-grid mt-16">
                <div class="optimization-metric"><span>缺陷目标数</span><strong>{{ result.count }}</strong></div>
                <div class="optimization-metric"><span>缺陷类别数</span><strong>{{ Object.keys(result.class_counts || {}).length }}</strong></div>
                <div class="optimization-metric"><span>模型</span><strong>{{ result.model || 'YOLOv8n' }}</strong></div>
                <div class="optimization-metric"><span>原图尺寸</span><strong>{{ result.width }}×{{ result.height }}</strong></div>
                <div class="optimization-metric"><span>耗时</span><strong>{{ result.elapsed_ms }} ms</strong></div>
              </div>
              <div class="legend-list mt-16">
                <span v-for="(value, key) in result.class_counts || {}" :key="key" class="tag">
                  {{ (result.class_labels || {})[key] || key }} × {{ value }}
                </span>
                <span v-if="!result.count" class="cell-sub">未检出缺陷，可降低 conf 阈值重试</span>
              </div>
              <div class="table-wrap mt-16">
                <table>
                  <thead><tr><th>#</th><th>类别</th><th>置信度</th><th>外接框 (x,y,w,h)</th><th>面积</th></tr></thead>
                  <tbody>
                    <tr v-for="item in result.objects || []" :key="item.index">
                      <td class="mono">{{ item.index }}</td>
                      <td><span class="cell-main">{{ item.label }}</span><span class="cell-sub mono">{{ item.class }}</span></td>
                      <td>{{ (item.confidence * 100).toFixed(1) }}%</td>
                      <td class="mono">{{ (item.bbox || []).join(', ') }}</td>
                      <td>{{ Math.round(item.area || 0) }}</td>
                    </tr>
                    <tr v-if="!(result.objects || []).length"><td colspan="5"><div class="empty">未检出缺陷</div></td></tr>
                  </tbody>
                </table>
              </div>
            </template>

            <template v-else-if="result">
              <div class="grid metric-grid mt-16">
                <div class="optimization-metric"><span>识别工件数</span><strong>{{ result.count }}</strong></div>
                <div class="optimization-metric"><span>类别数</span><strong>{{ Object.keys(result.class_counts || {}).length }}</strong></div>
                <div class="optimization-metric"><span>原图尺寸</span><strong>{{ result.width }}×{{ result.height }}</strong></div>
                <div class="optimization-metric"><span>耗时</span><strong>{{ result.elapsed_ms }} ms</strong></div>
              </div>
              <div class="legend-list mt-16">
                <span v-for="(value, key) in result.class_counts || {}" :key="key" class="tag">
                  {{ SHAPE_LABELS[key] || key }} × {{ value }}
                </span>
                <span v-if="!Object.keys(result.class_counts || {}).length" class="cell-sub">未识别到工件</span>
              </div>
              <div class="table-wrap mt-16">
                <table>
                  <thead><tr><th>#</th><th>类别</th><th>置信分</th><th>外接框 (x,y,w,h)</th><th>面积</th><th>顶点数</th></tr></thead>
                  <tbody>
                    <tr v-for="(item, index) in objects" :key="index">
                      <td>{{ index + 1 }}</td>
                      <td><span class="cell-main">{{ SHAPE_LABELS[item.label] || item.label }}</span><span class="cell-sub mono">{{ item.label }}</span></td>
                      <td>{{ item.score }}</td>
                      <td class="mono">{{ item.box.join(', ') }}</td>
                      <td>{{ item.area }}</td>
                      <td>{{ item.vertices }}</td>
                    </tr>
                    <tr v-if="!objects.length"><td colspan="6"><div class="empty">未识别到工件</div></td></tr>
                  </tbody>
                </table>
              </div>
            </template>
            <div v-else class="empty mt-16">请在左侧选择图片后点击「开始检测」</div>
          </div>
        </section>
      </div>

      <div v-else class="mt-16">
        <div class="section-toolbar toolbar-row">
          <div class="toolbar-right">
            <select v-model="recordFilter" class="select" @change="loadRecords">
              <option value="">全部类型</option>
              <option value="crack">裂纹检测</option>
              <option value="defect">缺陷分类</option>
              <option value="workpiece">工件识别</option>
            </select>
            <button class="btn btn-sm" :disabled="loadingRecords" @click="loadRecords">
              {{ loadingRecords ? '加载中...' : '刷新记录' }}
            </button>
          </div>
          <span class="muted small">共 {{ records.length }} 条记录</span>
        </div>
        <div class="table-wrap mt-16">
          <table>
            <thead>
              <tr><th>ID</th><th>工单</th><th>类型</th><th>来源</th><th>输入</th><th>判定</th><th>质检</th><th>数量</th><th>耗时</th><th>结果图</th><th>时间</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="record in records" :key="record.id">
                <td class="mono">{{ record.id }}</td>
                <td><RouterLink v-if="record.work_order" class="link-btn" :to="{ path: '/work-orders', query: { work_order: record.work_order } }">{{ record.work_order_no }}</RouterLink><span v-else class="muted">--</span></td>
                <td>{{ record.task_type_display }}</td>
                <td>{{ record.source_display }}</td>
                <td><span class="cell-main mono small">{{ record.input_name || '--' }}</span></td>
                <td>{{ record.verdict }}</td>
                <td>{{ record.quality_result_display }}</td>
                <td>{{ record.object_count }}</td>
                <td>{{ record.elapsed_ms }} ms</td>
                <td><img v-if="record.result_image_url" class="vision-thumb" :src="record.result_image_url" alt="结果缩略图" /></td>
                <td class="small">{{ formatTime(record.created_at) }}</td>
                <td><button class="btn btn-sm btn-danger" @click="removeRecord(record)">删除</button></td>
              </tr>
              <tr v-if="!records.length"><td colspan="12"><div class="empty">暂无检测记录</div></td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.vision-grid { grid-template-columns: minmax(0, 420px) minmax(0, 1fr); align-items: start; }
.vision-compare { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.vision-figure { margin: 0; display: flex; flex-direction: column; gap: 6px; }
.vision-preview {
  width: 100%; height: 240px; object-fit: contain; border-radius: 10px;
  border: 1px solid var(--line-strong); background: var(--track-bg-deep);
}
.vision-placeholder {
  height: 240px; display: flex; align-items: center; justify-content: center;
  border: 1px dashed var(--line-strong); border-radius: 10px;
  color: var(--muted); font-size: 12px;
}
.vision-thumb {
  width: 66px; height: 44px; object-fit: cover; border-radius: 6px;
  border: 1px solid var(--line-strong);
}
.legend-list { display: flex; flex-wrap: wrap; gap: 8px; }
.mini-stat span { white-space: nowrap; }
.vision-mini-value { font-size: 19px; white-space: nowrap; }
.btn { white-space: nowrap; }

/* ---- 缺陷识别 top-3 概率条 ---- */
.defect-bar-row { display: grid; grid-template-columns: 96px minmax(0, 1fr) 56px; gap: 10px; align-items: center; font-size: 12px; margin-bottom: 7px; }
.defect-bar-label { color: var(--text-soft); }
</style>
