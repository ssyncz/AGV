<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../api'

const emit = defineEmits(['notify'])

const MODES = [
  { key: 'crack', label: '表面裂纹检测', groups: ['crack', 'free'] },
  { key: 'workpiece', label: '工件识别', groups: ['workpiece'] },
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
const records = ref([])
const recordFilter = ref('')

const running = ref(false)
const loadingRecords = ref(false)
const error = ref('')
const result = ref(null)

const crackParams = ref({ score_threshold: 0.54, vessel_threshold: 0.55, min_aspect: 2.5, mask_dilation: 2 })
const workpieceParams = ref({ min_area: 300, approx_epsilon: 0.02, morph_kernel: 5 })

const currentMode = computed(() => MODES.find((item) => item.key === mode.value) || MODES[0])
const groups = computed(() => currentMode.value.groups)
const activeSamples = computed(() => samples.value[sampleGroup.value] || [])
const activeParams = computed(() => (mode.value === 'crack' ? crackParams.value : workpieceParams.value))
const canRun = computed(() => (sourceKind.value === 'upload' ? !!file.value : !!sampleName.value))
const datasetCounts = computed(() => {
  const summary = datasetSummary.value || {}
  return `${summary.crack || 0} / ${summary.free || 0} / ${summary.workpiece || 0}`
})
const datasetNote = computed(() => {
  const summary = datasetSummary.value || {}
  return `数据集：MT_Crack ${summary.crack || 0} 张（含标注掩码）· MT_Free 无缺陷 ${summary.free || 0} 张 · 合成几何工件 ${summary.workpiece || 0} 张`
})
const previewUrl = computed(() => {
  if (sourceKind.value === 'upload') return objectUrl.value
  if (!sampleName.value) return ''
  return api.visionSampleImageUrl(sampleGroup.value, sampleName.value)
})
const objects = computed(() => result.value?.objects || [])

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
    } else {
      payload = { sample: `${sampleGroup.value}/${sampleName.value}`, params }
    }
    result.value = mode.value === 'crack'
      ? await api.visionCrack(payload)
      : await api.visionDetect(payload)
    notify(`检测完成，用时 ${result.value.elapsed_ms} ms`)
    await loadOverview()
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
        <div class="panel-desc">OpenCV 传统算法：任务 4 表面裂纹检测（MT 数据集）与任务 5 几何工件识别（合成数据集）</div>
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
                  <option v-for="item in MODES" :key="item.key" :value="item.key">{{ item.label }}</option>
                </select>
              </div>
              <div class="field">
                <label>图片来源</label>
                <select v-model="sourceKind" class="select">
                  <option value="dataset">内置数据集样例</option>
                  <option value="upload">本地上传图片</option>
                </select>
              </div>
              <template v-if="sourceKind === 'dataset'">
                <div class="field">
                  <label>样例分组</label>
                  <select v-model="sampleGroup" class="select">
                    <option v-for="group in groups" :key="group" :value="group">
                      {{ group === 'crack' ? 'MT_Crack 有裂纹' : group === 'free' ? 'MT_Free 无缺陷' : '合成工件' }}（{{ (samples[group] || []).length }}）
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
                  <label>判定阈值 score_threshold</label>
                  <input v-model.number="crackParams.score_threshold" class="input" type="number" step="0.02" min="0.05" max="1.5" />
                </div>
                <div class="field">
                  <label>黑脊响应阈值 vessel_threshold</label>
                  <input v-model.number="crackParams.vessel_threshold" class="input" type="number" step="0.05" min="0.05" max="0.95" />
                </div>
                <div class="field">
                  <label>细长比下限 min_aspect</label>
                  <input v-model.number="crackParams.min_aspect" class="input" type="number" step="0.1" min="1.2" max="8" />
                </div>
                <div class="field">
                  <label>掩码膨胀像素 mask_dilation</label>
                  <input v-model.number="crackParams.mask_dilation" class="input" type="number" step="1" min="0" max="5" />
                </div>
              </template>
              <template v-else>
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
            <span v-if="result" class="tag">{{ result.task_type === 'crack' ? '裂纹检测' : '工件识别' }}</span>
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
                <img v-if="result" class="vision-preview" :src="result.image_url" alt="检测结果" />
                <div v-else class="vision-placeholder">尚未检测</div>
              </figure>
            </div>

            <template v-if="result && result.task_type === 'crack'">
              <div class="notice mt-16" :class="result.result === 'crack' ? 'warning' : 'success'">
                <strong>{{ result.result === 'crack' ? '判定：检出裂纹' : '判定：未见裂纹' }}</strong>
                <span v-if="result.result === 'crack' && !result.localized">（置信分超过阈值但未定位到细长连通域，建议人工复核）</span>
              </div>
              <div class="grid metric-grid mt-16">
                <div class="optimization-metric"><span>判定结果</span><strong>{{ result.result === 'crack' ? 'crack' : 'normal' }}</strong></div>
                <div class="optimization-metric"><span>裂纹区域数</span><strong>{{ result.count }}</strong></div>
                <div class="optimization-metric"><span>置信分</span><strong>{{ result.score }}</strong></div>
                <div class="optimization-metric"><span>最大脊响应</span><strong>{{ result.max_response ?? '--' }}</strong></div>
                <div class="optimization-metric"><span>原图尺寸</span><strong>{{ result.width }}×{{ result.height }}</strong></div>
                <div class="optimization-metric"><span>耗时</span><strong>{{ result.elapsed_ms }} ms</strong></div>
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
              <tr><th>ID</th><th>类型</th><th>来源</th><th>输入</th><th>判定</th><th>数量</th><th>耗时</th><th>结果图</th><th>时间</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="record in records" :key="record.id">
                <td class="mono">{{ record.id }}</td>
                <td>{{ record.task_type_display }}</td>
                <td>{{ record.source_display }}</td>
                <td><span class="cell-main mono small">{{ record.input_name || '--' }}</span></td>
                <td>{{ record.verdict }}</td>
                <td>{{ record.object_count }}</td>
                <td>{{ record.elapsed_ms }} ms</td>
                <td><img v-if="record.result_image_url" class="vision-thumb" :src="record.result_image_url" alt="结果缩略图" /></td>
                <td class="small">{{ formatTime(record.created_at) }}</td>
                <td><button class="btn btn-sm btn-danger" @click="removeRecord(record)">删除</button></td>
              </tr>
              <tr v-if="!records.length"><td colspan="10"><div class="empty">暂无检测记录</div></td></tr>
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
  border: 1px solid var(--line-strong); background: rgba(0, 0, 0, 0.28);
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
</style>
