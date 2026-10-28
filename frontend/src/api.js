const API_BASE = import.meta.env.VITE_API_BASE || '/api'

async function request(path, options = {}) {
  const { headers: extraHeaders, ...rest } = options
  const isFormData = typeof FormData !== 'undefined' && rest.body instanceof FormData
  const headers = { ...(extraHeaders || {}) }
  if (!isFormData) {
    headers['Content-Type'] = 'application/json'
  }
  let response
  try {
    response = await fetch(`${API_BASE}${path}`, { headers, ...rest })
  } catch (err) {
    throw new Error(`无法连接后端服务：${err.message}`)
  }
  const text = await response.text()
  let data = null
  let nonJson = false
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      // 后端 500 在 DEBUG 下会返回整页 HTML；只在控制台保留原文，不要把源码塞进提示条。
      nonJson = true
      console.error(`[api] ${path} 返回了非 JSON 内容（HTTP ${response.status}）:`,
        text.slice(0, 2000))
    }
  }
  if (!response.ok) {
    const fallback = response.status >= 500
      ? `服务器内部错误（HTTP ${response.status}），详情见浏览器控制台与后端日志`
      : `请求失败（HTTP ${response.status}）`
    throw new Error(detailOf(data) || fallback)
  }
  if (nonJson) {
    throw new Error('后端返回的不是 JSON，请检查接口地址与后端日志')
  }
  return data
}

function unwrap(data) {
  return Array.isArray(data) ? data : (data?.results || [])
}

// DRF 的 detail 有时是字符串，有时是字段校验对象或数组，统一转成可读文本。
function detailOf(data) {
  const detail = data?.detail ?? data?.message
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((item) => String(item)).join('；')
  if (detail && typeof detail === 'object') return JSON.stringify(detail)
  return ''
}

function postVision(path, payload) {
  if (typeof FormData !== 'undefined' && payload instanceof FormData) {
    return request(path, { method: 'POST', body: payload })
  }
  return request(path, { method: 'POST', body: JSON.stringify(payload) })
}

export const api = {
  overview: () => request('/overview/'),
  map: () => request('/map/'),
  nodes: () => request('/nodes/').then(unwrap),
  edges: () => request('/edges/').then(unwrap),
  agvs: () => request('/agvs/').then(unwrap),
  tasks: () => request('/tasks/').then(unwrap),
  dispatches: () => request('/dispatches/').then(unwrap),
  scheduleRuns: () => request('/schedule-runs/').then(unwrap),
  createTask: (payload) => request('/tasks/', { method: 'POST', body: JSON.stringify(payload) }),
  updateTask: (id, payload) => request(`/tasks/${id}/`, { method: 'PATCH', body: JSON.stringify(payload) }),
  updateAgv: (id, payload) => request(`/agvs/${id}/`, { method: 'PATCH', body: JSON.stringify(payload) }),
  singleDispatch: (payload) => request('/schedules/single/', { method: 'POST', body: JSON.stringify(payload) }),
  batchDispatch: (payload) => request('/schedules/batch/', { method: 'POST', body: JSON.stringify(payload) }),
  planPath: (payload) => request('/path-planning/', { method: 'POST', body: JSON.stringify(payload) }),
  taskAction: (id, action) => request(`/tasks/${id}/${action}/`, { method: 'POST', body: '{}' }),

  // --- 视觉检测（ManufacturingVision，任务 4/5）---
  visionOverview: () => request('/vision/overview/'),
  visionAlgoStatus: () => request('/vision/algo/status/'),
  visionSamples: () => request('/vision/samples/'),
  visionCrack: (payload) => postVision('/vision/crack/', payload),
  visionDefect: (payload) => postVision('/vision/algo/defect/', payload),
  visionDetect: (payload) => postVision('/vision/detect/', payload),
  visionRecords: (query = '') => request(`/vision/records/${query}`).then(unwrap),
  deleteVisionRecord: (id) => request(`/vision/records/${id}/`, { method: 'DELETE' }),
  visionSampleImageUrl: (group, name) =>
    `${API_BASE}/vision/samples/${encodeURIComponent(group)}/${encodeURIComponent(name)}/`,

  // --- 设备状态监测（任务 6）---
  equipmentOverview: () => request('/equipment/overview/'),
  equipmentSample: (scenario = 'worn') =>
    request(`/equipment/sample/?scenario=${encodeURIComponent(scenario)}`),
  equipmentModel: () => request('/equipment/model/'),
  equipmentDatasetCompare: () => request('/equipment/algo/dataset-compare/'),
  equipmentDiagnose: (payload) => postVision('/equipment/diagnose/', payload),
  equipmentRecords: (query = '') => request(`/equipment/records/${query}`).then(unwrap),
  deleteEquipmentRecord: (id) =>
    request(`/equipment/records/${id}/`, { method: 'DELETE' }),

  // --- 订单需求预测（任务 7）---
  forecastOverview: () => request('/forecast/overview/'),
  forecastSample: (days = 240) => request(`/forecast/sample/?days=${days}`),
  forecastPredict: (payload) => postVision('/forecast/predict/', payload),
  forecastRuns: (query = '') => request(`/forecast/runs/${query}`).then(unwrap),
  deleteForecastRun: (id) => request(`/forecast/runs/${id}/`, { method: 'DELETE' }),
}
