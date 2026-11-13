<script setup>
import { computed, ref, watch } from 'vue'
import { api } from '../api'

const props = defineProps({ mapData: { type: Object, default: () => ({}) } })
const emit = defineEmits(['notify'])
const selectedRoute = ref(null)
const hoveredNode = ref(null)
const width = 920
const height = 880
const padding = 36
const colors = ['#2ec9b4', '#5f95ea', '#a383e0', '#e0a83a', '#46c07c', '#e2675e']

const nodes = computed(() => props.mapData.nodes || [])
const edges = computed(() => props.mapData.edges || [])
const agvs = computed(() => props.mapData.agvs || [])
const routes = computed(() => props.mapData.active_routes || [])
const executingRoutes = computed(() => routes.value.filter((item) => ['assigned', 'in_progress'].includes(item.status)))
const selectedWorkOrderId = ref('')
const routeGroups = computed(() => {
  const grouped = new Map()
  for (const route of executingRoutes.value) {
    const key = String(route.work_order_id || `unlinked-${route.production_plan_id || 'none'}`)
    if (!grouped.has(key)) {
      grouped.set(key, {
        id: key,
        work_order_id: route.work_order_id,
        work_order_no: route.work_order_no || '未关联工单',
        production_plan_no: route.production_plan_no || '',
        routes: [],
      })
    }
    grouped.get(key).routes.push(route)
  }
  return [...grouped.values()]
    .map((group) => ({ ...group, routes: group.routes.sort(compareRoutes) }))
    .sort((left, right) => left.work_order_no.localeCompare(right.work_order_no, 'zh-CN'))
})
const selectedRouteGroup = computed(
  () => routeGroups.value.find((group) => group.id === selectedWorkOrderId.value) || null,
)
const selectedRouteDetail = computed(
  () => executingRoutes.value.find((route) => route.task_id === selectedRoute.value) || null,
)
const visibleRoutes = computed(() => selectedRouteDetail.value ? [selectedRouteDetail.value] : [])
const obstacles = computed(() => props.mapData.obstacles || [])
const nodeMap = computed(() => Object.fromEntries(nodes.value.map((node) => [node.id, node])))
const extent = computed(() => {
  const nodeXs = nodes.value.map((node) => node.x)
  const nodeYs = nodes.value.map((node) => node.y)
  const obstacleXs = obstacles.value.map((item) => item.x + item.width)
  const obstacleYs = obstacles.value.map((item) => item.y + item.height)
  const rawMinX = Math.min(...nodeXs, ...obstacleXs, 0)
  const rawMaxX = Math.max(...nodeXs, ...obstacleXs, 1)
  const rawMinY = Math.min(...nodeYs, ...obstacleYs, 0)
  const rawMaxY = Math.max(...nodeYs, ...obstacleYs, 1)
  return {
    minX: rawMinX - 0.5,
    maxX: rawMaxX + 0.5,
    minY: rawMinY - 0.5,
    maxY: rawMaxY + 0.5,
  }
})

const gridXs = computed(() => {
  const count = Math.round(extent.value.maxX - extent.value.minX)
  return Array.from({ length: count + 1 }, (_, index) => extent.value.minX + index)
})
const gridYs = computed(() => {
  const count = Math.round(extent.value.maxY - extent.value.minY)
  return Array.from({ length: count + 1 }, (_, index) => extent.value.minY + index)
})

const hoverTooltip = computed(() => {
  const node = hoveredNode.value
  if (!node) return null
  const label = node.name ? `${node.code} · ${node.name}` : node.code
  // 11px 字号下全角字符约 11px、半角约 6.4px，再加左右内边距
  const fullWidth = /[\u2e80-\u9fff\uff00-\uffef]/
  const textWidth = [...label].reduce(
    (sum, char) => sum + (fullWidth.test(char) ? 11 : 6.4),
    0,
  )
  const boxWidth = Math.max(150, Math.round(textWidth) + 24)
  const anchor = point(node.id)
  return {
    label,
    width: boxWidth,
    // 贴边时向内收，避免 tooltip 被 viewBox 裁掉
    x: Math.min(Math.max(anchor.x + 12, padding), width - boxWidth - 4),
    y: Math.min(Math.max(anchor.y - 42, 4), height - 34),
  }
})

const startNodeId = ref('')
const endNodeId = ref('')
const plannerAgvId = ref('')
const pathResult = ref(null)
const pathPlanning = ref(false)

watch([routeGroups, selectedWorkOrderId], ([groups, workOrderId]) => {
  if (!groups.length) {
    selectedWorkOrderId.value = ''
    selectedRoute.value = null
    return
  }
  if (!groups.some((group) => group.id === workOrderId)) {
    selectedWorkOrderId.value = groups[0].id
    return
  }
  const group = groups.find((item) => item.id === workOrderId)
  if (!group.routes.some((route) => route.task_id === selectedRoute.value)) {
    selectedRoute.value = group.routes[0]?.task_id || null
  }
}, { immediate: true })

watch(nodes, (items) => {
  if (!items.length) return
  if (!startNodeId.value) startNodeId.value = items.find((item) => item.code === 'S2')?.id || items[0].id
  if (!endNodeId.value) endNodeId.value = items.find((item) => item.code === 'S6')?.id || items[items.length - 1].id
}, { immediate: true })

function coordinatePoint(x, y) {
  const { minX, maxX, minY, maxY } = extent.value
  return {
    x: padding + ((x - minX) / Math.max(maxX - minX, 1)) * (width - padding * 2),
    y: height - padding - ((y - minY) / Math.max(maxY - minY, 1)) * (height - padding * 2),
  }
}

// 一条任务路线 = 空驶段（AGV 当前 → 取货点）+ 载货段（取货点 → 放货点）
// 拆分后地图上就能一眼看出哪段是空跑、哪段是拉货
function routeParts(route) {
  const nodes = route?.route?.nodes || []
  const legs = route?.route?.legs || []
  const pickup = route?.pickup_node ?? route?.route?.pickup_node
  const index = nodes.indexOf(pickup)
  const cut = index > 0 ? index : 0
  const sum = (from, to) => legs.slice(from, to).reduce((total, leg) => total + (Number(leg.distance) || 0), 0)
  return {
    deadheadNodes: cut > 0 ? nodes.slice(0, cut + 1) : [],
    loadedNodes: nodes.slice(cut),
    deadheadMeters: Math.round(sum(0, cut)),
    loadedMeters: Math.round(sum(cut, legs.length)),
    startNode: route?.route?.start_node ?? nodes[0],
    pickupNode: pickup,
    dropoffNode: route?.dropoff_node ?? route?.route?.dropoff_node,
  }
}

function point(nodeId) {
  const node = nodeMap.value[nodeId]
  if (!node) return { x: 0, y: 0 }
  return coordinatePoint(node.x, node.y)
}

function points(path) {
  return (path || []).map((id) => point(id)).map((item) => item.x + ',' + item.y).join(' ')
}

function obstacleRect(item) {
  const topLeft = coordinatePoint(item.x, item.y)
  const bottomRight = coordinatePoint(item.x + item.width, item.y + item.height)
  return {
    x: Math.min(topLeft.x, bottomRight.x) + 6,
    y: Math.min(topLeft.y, bottomRight.y) + 6,
    width: Math.max(Math.abs(bottomRight.x - topLeft.x) - 12, 8),
    height: Math.max(Math.abs(bottomRight.y - topLeft.y) - 12, 8),
  }
}

function nodeColor(type) {
  return { parking: '#7f9a8b', pickup: '#2f9e63', dropoff: '#c98f1c', charging: '#7a55c0', intersection: '#6d8a7c' }[type] || '#6d8a7c'
}

function routeColor(index) {
  return colors[index % colors.length]
}

function routeText(route) {
  return (route.route?.nodes || []).map((id) => nodeMap.value[id]?.code || id).join(' -> ')
}

function compareRoutes(left, right) {
  const leftStart = left.scheduled_start ? new Date(left.scheduled_start).getTime() : Number.MAX_SAFE_INTEGER
  const rightStart = right.scheduled_start ? new Date(right.scheduled_start).getTime() : Number.MAX_SAFE_INTEGER
  return (
    leftStart - rightStart
    || (left.dispatch_order || Number.MAX_SAFE_INTEGER) - (right.dispatch_order || Number.MAX_SAFE_INTEGER)
    || (left.sequence_number || Number.MAX_SAFE_INTEGER) - (right.sequence_number || Number.MAX_SAFE_INTEGER)
    || left.task_id - right.task_id
  )
}

function selectRoute(route) {
  selectedRoute.value = route.task_id
  pathResult.value = null
}

async function planPath() {
  if (!startNodeId.value || !endNodeId.value) return
  pathPlanning.value = true
  try {
    pathResult.value = await api.planPath({
      start_node_id: Number(startNodeId.value),
      end_node_id: Number(endNodeId.value),
      agv_id: plannerAgvId.value ? Number(plannerAgvId.value) : null,
    })
    selectedRoute.value = null
  } catch (error) {
    emit('notify', { message: error.message, type: 'error' })
  } finally {
    pathPlanning.value = false
  }
}

function clearPath() {
  pathResult.value = null
}
</script>

<template>
  <div class="map-layout map-layout-wide">
    <section class="panel">
      <div class="panel-head">
        <div><div class="panel-title">仓库障碍地图与路径规划</div><div class="panel-desc">青色路网、深色障碍块、S1-S10 工作站以及 AGV 彩色路线</div></div>
        <div class="toolbar-right">
          <span v-if="selectedRouteGroup" class="tag">{{ selectedRouteGroup.work_order_no }}</span>
          <span v-if="selectedRouteDetail" class="tag">调度顺序 #{{ selectedRouteDetail.dispatch_order || selectedRouteGroup.routes.indexOf(selectedRouteDetail) + 1 }}</span>
          <span class="tag">节点 {{ nodes.length }}</span><span class="tag">道路 {{ edges.length }}</span><span class="tag">障碍 {{ obstacles.length }}</span>
        </div>
      </div>
      <div class="panel-body">
        <div class="map-canvas warehouse-map">
          <svg :viewBox="`0 0 ${width} ${height}`" preserveAspectRatio="xMidYMid meet" role="img" aria-label="AGV 路径规划地图">
            <line v-for="x in gridXs" :key="`v-${x}`" class="map-grid-line" :x1="coordinatePoint(x, extent.minY).x" :y1="coordinatePoint(x, extent.minY).y" :x2="coordinatePoint(x, extent.maxY).x" :y2="coordinatePoint(x, extent.maxY).y" />
            <line v-for="y in gridYs" :key="`h-${y}`" class="map-grid-line" :x1="coordinatePoint(extent.minX, y).x" :y1="coordinatePoint(extent.minX, y).y" :x2="coordinatePoint(extent.maxX, y).x" :y2="coordinatePoint(extent.maxX, y).y" />
            <line v-for="edge in edges" :key="edge.id" class="map-edge" :x1="point(edge.start_node).x" :y1="point(edge.start_node).y" :x2="point(edge.end_node).x" :y2="point(edge.end_node).y" />
            <rect v-for="item in obstacles" :key="item.id" class="map-obstacle" v-bind="obstacleRect(item)" rx="3" />
            <g v-for="(route, index) in visibleRoutes" :key="route.task_id" class="route-group">
              <!-- 空驶段：AGV 当前位置 → 取货点（虚线） -->
              <polyline
                v-if="routeParts(route).deadheadNodes.length"
                class="map-route-deadhead"
                :points="points(routeParts(route).deadheadNodes)"
                :style="{ stroke: routeColor(index) }"
              />
              <!-- 载货段：取货点 → 放货点（实线 + 流动） -->
              <polyline
                class="map-route route-selected"
                :points="points(routeParts(route).loadedNodes)"
                :style="{ stroke: routeColor(index), color: routeColor(index) }"
              />
              <!-- 关键点标注 -->
              <g v-if="routeParts(route).startNode" class="route-mark">
                <circle :cx="point(routeParts(route).startNode).x" :cy="point(routeParts(route).startNode).y" r="7"
                        fill="none" :stroke="routeColor(index)" stroke-width="2.5" />
                <text :x="point(routeParts(route).startNode).x" :y="point(routeParts(route).startNode).y - 13"
                      text-anchor="middle" class="map-node-label">出发</text>
              </g>
              <g v-if="routeParts(route).pickupNode" class="route-mark">
                <rect :x="point(routeParts(route).pickupNode).x - 6" :y="point(routeParts(route).pickupNode).y - 6"
                      width="12" height="12" rx="3" fill="#55e08c" stroke="#04150c" stroke-width="2" />
                <text :x="point(routeParts(route).pickupNode).x" :y="point(routeParts(route).pickupNode).y + 20"
                      text-anchor="middle" class="map-node-label">取货</text>
              </g>
              <g v-if="routeParts(route).dropoffNode" class="route-mark">
                <rect :x="point(routeParts(route).dropoffNode).x - 6" :y="point(routeParts(route).dropoffNode).y - 6"
                      width="12" height="12" rx="3" fill="#f3c04b" stroke="#04150c" stroke-width="2" />
                <text :x="point(routeParts(route).dropoffNode).x" :y="point(routeParts(route).dropoffNode).y + 20"
                      text-anchor="middle" class="map-node-label">放货</text>
              </g>
            </g>
            <polyline v-if="pathResult" class="map-route manual-route" :points="points(pathResult.route.nodes)" />
            <g v-for="node in nodes" :key="node.id" class="map-node-group" @mouseenter="hoveredNode = node" @mouseleave="hoveredNode = null">
              <circle class="map-node-hit" :cx="point(node.id).x" :cy="point(node.id).y" r="11" />
              <circle class="map-node" :cx="point(node.id).x" :cy="point(node.id).y" :r="node.node_type === 'intersection' ? 3 : 10" :fill="nodeColor(node.node_type)" />
              <text v-if="node.node_type !== 'intersection'" class="map-node-label" :x="point(node.id).x" :y="point(node.id).y + 23" text-anchor="middle">{{ node.code }}</text>
            </g>
            <g v-if="pathResult" class="planner-endpoints">
              <circle :cx="point(pathResult.route.nodes[0]).x" :cy="point(pathResult.route.nodes[0]).y" r="15" fill="none" stroke="var(--green)" stroke-width="4" />
              <circle :cx="point(pathResult.route.nodes[pathResult.route.nodes.length - 1]).x" :cy="point(pathResult.route.nodes[pathResult.route.nodes.length - 1]).y" r="15" fill="none" stroke="var(--red)" stroke-width="4" />
            </g>
            <g v-for="(agv, index) in agvs" :key="agv.id" class="map-agv">
              <circle :cx="point(agv.current_node).x + (index % 2) * 10 - 5" :cy="point(agv.current_node).y - 10 - Math.floor(index / 2) * 10" r="12" fill="var(--cyan)" opacity="0.2" />
              <circle :cx="point(agv.current_node).x + (index % 2) * 10 - 5" :cy="point(agv.current_node).y - 10 - Math.floor(index / 2) * 10" r="6" fill="var(--cyan)" :style="{ stroke: 'var(--map-node-stroke)' }" stroke-width="2" />
              <text :x="point(agv.current_node).x + (index % 2) * 10 - 5" :y="point(agv.current_node).y - 28 - Math.floor(index / 2) * 10" text-anchor="middle" :style="{ fill: 'var(--map-label)' }" font-size="10">{{ agv.code }}</text>
            </g>
            <g v-if="hoverTooltip" class="map-node-tooltip" pointer-events="none">
              <rect :x="hoverTooltip.x" :y="hoverTooltip.y" :width="hoverTooltip.width" height="30" rx="6" />
              <text :x="hoverTooltip.x + 10" :y="hoverTooltip.y + 19">{{ hoverTooltip.label }}</text>
            </g>
          </svg>
        </div>
      </div>
    </section>

    <aside class="panel">
      <div class="panel-head"><div><div class="panel-title">起点到终点路径规划</div><div class="panel-desc">自动绕开障碍并满足道路、电池约束</div></div></div>
      <div class="panel-body">
        <div class="path-planner">
          <div class="field"><label>起点</label><select v-model="startNodeId" class="select"><option v-for="node in nodes" :key="node.id" :value="node.id">{{ node.code }} · {{ node.name }}</option></select></div>
          <div class="field"><label>终点</label><select v-model="endNodeId" class="select"><option v-for="node in nodes" :key="node.id" :value="node.id">{{ node.code }} · {{ node.name }}</option></select></div>
          <div class="field"><label>执行 AGV（可选）</label><select v-model="plannerAgvId" class="select"><option value="">通用 AGV</option><option v-for="agv in agvs" :key="agv.id" :value="agv.id">{{ agv.code }} · 电量 {{ agv.battery_percent }}%</option></select></div>
          <div class="toolbar-row"><button class="btn btn-primary" :disabled="pathPlanning" @click="planPath">{{ pathPlanning ? '规划中...' : '规划最短路径' }}</button><button class="btn" @click="clearPath">清除</button></div>
        </div>
        <div v-if="pathResult" class="planner-result mt-16">
          <div class="planner-metrics"><div><span>距离</span><strong>{{ pathResult.distance }} m</strong></div><div><span>预计耗时</span><strong>{{ pathResult.estimated_duration }} s</strong></div><div><span>节点数</span><strong>{{ pathResult.route.nodes.length }}</strong></div></div>
          <div class="route-path mt-12">{{ routeText(pathResult) }}</div>
          <div v-if="pathResult.agv" class="notice mt-12" :class="pathResult.agv.battery_ok ? 'success' : 'warning'">预计耗电 {{ pathResult.agv.battery_required }}%，{{ pathResult.agv.battery_ok ? '电量满足约束' : '电量不足' }}</div>
        </div>
        <div class="legend-list mt-16">
          <div class="legend-row"><span class="legend-name"><span class="legend-dot" style="--dot: #7fa394"></span>障碍区域</span></div>
          <div class="legend-row"><span class="legend-name"><span class="legend-dot" style="--dot: #55e08c"></span>取货点</span></div>
          <div class="legend-row"><span class="legend-name"><span class="legend-dot" style="--dot: #f3c04b"></span>放货点</span></div>
          <div class="legend-row"><span class="legend-name"><span class="legend-dot" style="--dot: #ff7a72"></span>载货段（实线）</span></div>
          <div class="legend-row"><span class="legend-name"><span class="legend-dot" style="--dot: #7fa394"></span>空驶段（虚线）</span></div>
        </div>
        <div class="executing-routes mt-16">
          <div class="route-section-head"><strong>工单调度路线</strong><span>{{ routeGroups.length }} 个工单 · {{ executingRoutes.length }} 条路线</span></div>
          <div v-if="routeGroups.length" class="route-navigation">
            <div class="field">
              <label>选择工单</label>
              <select v-model="selectedWorkOrderId" class="select">
                <option v-for="group in routeGroups" :key="group.id" :value="group.id">{{ group.work_order_no }} · {{ group.routes.length }} 个路线</option>
              </select>
            </div>
            <div class="route-order-buttons">
              <button
                v-for="(route, index) in selectedRouteGroup?.routes || []"
                :key="route.task_id"
                class="route-order-button"
                :class="{ active: selectedRoute === route.task_id }"
                @click="selectRoute(route)"
              >
                <span class="route-order-index">{{ route.dispatch_order || index + 1 }}</span>
                <span class="route-order-main">
                  <strong class="mono">{{ route.task_no }}</strong>
                  <small>{{ route.agv_code || '未分配' }} · {{ nodeMap[route.pickup_node]?.code }}→{{ nodeMap[route.dropoff_node]?.code }} · 排期 #{{ route.schedule_run_id || '-' }}</small>
                </span>
              </button>
            </div>
            <div v-if="selectedRouteDetail" class="route-card route-current">
              <div class="route-card-top">
                <div><span class="strong mono">{{ selectedRouteDetail.task_no }}</span><span class="tag" style="margin-left: 7px">{{ selectedRouteDetail.agv_code || '未分配' }}</span></div>
                <span class="badge" :class="selectedRouteDetail.status === 'in_progress' ? 'badge-in_progress' : 'badge-assigned'">{{ selectedRouteDetail.status === 'in_progress' ? '执行中' : '已分配' }}</span>
              </div>
              <div class="route-path">{{ nodeMap[selectedRouteDetail.pickup_node]?.code || '--' }} → {{ nodeMap[selectedRouteDetail.dropoff_node]?.code || '--' }} · 全局第 {{ selectedRouteDetail.dispatch_order || '-' }} 项 · 车内第 {{ selectedRouteDetail.sequence_number || '-' }} 项</div>
              <div class="route-path">{{ selectedRouteDetail.total_distance || 0 }} m · {{ selectedRouteDetail.estimated_duration || 0 }} s</div>
              <div class="route-full-path">
                <span>完整路径（出发 → 取货 → 放货）</span>
                <code>{{ routeText(selectedRouteDetail) || '暂无路径' }}</code>
                <span v-if="selectedRouteDetail">空驶 {{ routeParts(selectedRouteDetail).deadheadMeters }} m · 载货 {{ routeParts(selectedRouteDetail).loadedMeters }} m</span>
              </div>
            </div>
          </div>
          <div v-else class="empty small-empty">暂无正在执行的任务路线</div>
        </div>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.map-route-deadhead {
  fill: none;
  stroke-width: 3;
  stroke-dasharray: 7 6;
  stroke-linecap: round;
  opacity: 0.55;
}
.route-mark text { font-size: 10px; font-weight: 650; paint-order: stroke; stroke: rgba(4, 21, 12, 0.55); stroke-width: 3px; }
<style scoped>
.route-navigation { display: grid; gap: 12px; }
.route-order-buttons { display: grid; gap: 7px; max-height: 245px; overflow-y: auto; padding-right: 3px; }
.route-order-button { display: grid; grid-template-columns: 28px minmax(0, 1fr); gap: 9px; align-items: center; width: 100%; padding: 8px 9px; border: 1px solid var(--line); border-radius: 9px; background: var(--fill-1); color: inherit; text-align: left; transition: background 150ms ease, border-color 150ms ease; }
.route-order-button:hover { background: var(--fill-2); }
.route-order-button.active { border-color: var(--accent-line); background: var(--accent-tint-weak); box-shadow: inset 3px 0 0 var(--cyan); }
.route-order-index { width: 25px; height: 25px; display: grid; place-items: center; border-radius: 50%; background: var(--fill-3); color: var(--text-soft); font-size: 10px; font-weight: 800; }
.route-order-button.active .route-order-index { background: var(--cyan); color: var(--on-accent); }
.route-order-main { min-width: 0; display: grid; gap: 2px; }
.route-order-main strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 10px; }
.route-order-main small { color: var(--muted); font-size: 9px; }
.route-current { border: 1px solid var(--line); border-radius: 10px; background: var(--fill-1); }
</style>
