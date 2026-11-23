<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { api } from '../api'
import StatusBadge from '../components/StatusBadge.vue'
import OrderDetailView from './OrderDetailView.vue'

const emit = defineEmits(['notify', 'refresh'])
const props = defineProps({
  initialStatus: { type: String, default: '' },
})

const orders = ref([])
const nodes = ref([])
const count = ref(0)
const page = ref(1)
const hasNext = ref(false)
const hasPrevious = ref(false)
const loading = ref(true)
const error = ref('')
const query = ref('')
const statusFilter = ref('')
const selectedId = ref(null)
const showCreate = ref(false)
const saving = ref(false)

const createForm = reactive({
  customer_name: '',
  customer_phone: '',
  cargo_name: '',
  cargo_weight: 1,
  pickup_node: null,
  dropoff_node: null,
  priority: 2,
  notes: '',
})

function formatTime(value) {
  if (!value) return '--'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function resetCreateForm() {
  Object.assign(createForm, {
    customer_name: '',
    customer_phone: '',
    cargo_name: '',
    cargo_weight: 1,
    pickup_node: nodes.value.find((item) => item.node_type === 'pickup')?.id || null,
    dropoff_node: nodes.value.find((item) => item.node_type === 'dropoff')?.id || null,
    priority: 2,
    notes: '',
  })
}

async function loadOrders(targetPage = page.value) {
  loading.value = true
  error.value = ''
  try {
    const data = await api.listOrders({
      search: query.value.trim(),
      status: statusFilter.value,
      page: targetPage,
    })
    orders.value = data?.results || []
    count.value = data?.count || 0
    page.value = targetPage
    hasNext.value = Boolean(data?.next)
    hasPrevious.value = Boolean(data?.previous)
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function loadNodes() {
  try {
    nodes.value = await api.nodes()
    if (!createForm.pickup_node) resetCreateForm()
  } catch (err) {
    emit('notify', { message: `无法加载取放货点：${err.message}`, type: 'error' })
  }
}

function applyFilters() {
  loadOrders(1)
}

function openCreate() {
  resetCreateForm()
  showCreate.value = true
  selectedId.value = null
}

async function submitOrder() {
  if (createForm.pickup_node === createForm.dropoff_node) {
    emit('notify', { message: '取货点和放货点不能相同', type: 'error' })
    return
  }
  saving.value = true
  try {
    const created = await api.createOrder({
      customer_name: createForm.customer_name,
      customer_phone: createForm.customer_phone,
      cargo_name: createForm.cargo_name,
      cargo_weight: Number(createForm.cargo_weight),
      pickup_node: Number(createForm.pickup_node),
      dropoff_node: Number(createForm.dropoff_node),
      priority: Number(createForm.priority),
      notes: createForm.notes,
    })
    showCreate.value = false
    selectedId.value = created.id
    emit('notify', { message: `订单 ${created.order_no} 已创建并生成运输任务` })
    emit('refresh')
    await loadOrders(1)
  } catch (err) {
    emit('notify', { message: err.message, type: 'error' })
  } finally {
    saving.value = false
  }
}

async function handleDetailUpdated() {
  emit('refresh')
  await loadOrders(page.value)
}

onMounted(() => {
  loadNodes()
  statusFilter.value = props.initialStatus || ''
  loadOrders(1)
})

watch(() => props.initialStatus, (status) => {
  statusFilter.value = status || ''
  selectedId.value = null
  loadOrders(1)
})
</script>

<template>
  <OrderDetailView
    v-if="selectedId"
    :order-id="selectedId"
    :nodes="nodes"
    @back="selectedId = null"
    @updated="handleDetailUpdated"
    @notify="emit('notify', $event)"
  />

  <template v-else>
    <section v-if="showCreate" class="panel create-panel">
      <div class="panel-head">
        <div><div class="panel-title">新建客户订单</div><div class="panel-desc">提交后将自动生成一条待调度运输任务</div></div>
        <button class="btn btn-sm" type="button" @click="showCreate = false">关闭</button>
      </div>
      <div class="panel-body">
        <form class="form-grid" @submit.prevent="submitOrder">
          <div class="field">
            <label>客户姓名</label>
            <input v-model.trim="createForm.customer_name" class="input" required maxlength="64" placeholder="例如：张伟" />
          </div>
          <div class="field">
            <label>客户手机号</label>
            <input v-model.trim="createForm.customer_phone" class="input" required maxlength="11" inputmode="tel" placeholder="11 位中国大陆手机号" />
          </div>
          <div class="field">
            <label>货物名称</label>
            <input v-model.trim="createForm.cargo_name" class="input" required maxlength="64" placeholder="例如：精密齿轮" />
          </div>
          <div class="field">
            <label>货物重量（kg）</label>
            <input v-model.number="createForm.cargo_weight" class="input" type="number" min="0.1" step="0.1" required />
          </div>
          <div class="field">
            <label>取货点</label>
            <select v-model.number="createForm.pickup_node" class="select" required>
              <option disabled :value="null">请选择取货工作站</option>
              <option v-for="node in nodes.filter((item) => item.node_type === 'pickup')" :key="node.id" :value="node.id">
                {{ node.code }} · {{ node.name }}
              </option>
            </select>
          </div>
          <div class="field">
            <label>放货点</label>
            <select v-model.number="createForm.dropoff_node" class="select" required>
              <option disabled :value="null">请选择放货工作站</option>
              <option v-for="node in nodes.filter((item) => item.node_type === 'dropoff')" :key="node.id" :value="node.id">
                {{ node.code }} · {{ node.name }}
              </option>
            </select>
          </div>
          <div class="field">
            <label>优先级</label>
            <select v-model.number="createForm.priority" class="select">
              <option :value="1">低</option><option :value="2">普通</option>
              <option :value="3">高</option><option :value="4">紧急</option>
            </select>
          </div>
          <div class="field">
            <label>备注</label>
            <input v-model.trim="createForm.notes" class="input" maxlength="255" placeholder="可选" />
          </div>
          <div class="field full order-submit-row">
            <button class="btn btn-primary" type="submit" :disabled="saving">{{ saving ? '正在提交...' : '提交订单并创建任务' }}</button>
          </div>
        </form>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <div><div class="panel-title">客户订单中心</div><div class="panel-desc">共 {{ count }} 个订单，执行状态由运输任务自动回写</div></div>
        <div class="toolbar-right">
          <form class="order-filter" @submit.prevent="applyFilters">
            <input v-model="query" class="input filter-input" placeholder="订单号、客户、货物或手机号" />
            <select v-model="statusFilter" class="select" style="width: 125px" @change="applyFilters">
              <option value="">全部状态</option>
              <option value="pending">待调度</option><option value="assigned">已分配</option>
              <option value="in_progress">执行中</option><option value="completed">已完成</option>
              <option value="failed">失败</option><option value="cancelled">已取消</option>
            </select>
            <button class="btn btn-sm" type="submit">查询</button>
          </form>
          <button class="btn btn-primary btn-sm" type="button" @click="openCreate">＋ 新建订单</button>
        </div>
      </div>
      <div class="panel-body">
        <div v-if="error" class="notice warning">{{ error }}</div>
        <div v-else-if="loading" class="empty">正在加载订单...</div>
        <div v-else class="table-wrap">
          <table>
            <thead><tr><th>订单</th><th>客户</th><th>货物</th><th>取放货点</th><th>优先级</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="order in orders" :key="order.id" @click="selectedId = order.id">
                <td><div class="cell-main mono">{{ order.order_no }}</div><div class="cell-sub">{{ order.transport_task?.task_no || '无关联任务' }}</div></td>
                <td>{{ order.customer.name }}<div class="cell-sub">{{ order.customer.masked_phone }}</div></td>
                <td>{{ order.cargo_name }}<div class="cell-sub">{{ order.cargo_weight }} kg</div></td>
                <td>{{ order.pickup_node_detail.code }}<div class="cell-sub">至 {{ order.dropoff_node_detail.code }}</div></td>
                <td :class="`priority-${order.priority}`">{{ order.priority_display }}</td>
                <td><StatusBadge :status="order.status" /></td>
                <td class="muted">{{ formatTime(order.created_at) }}</td>
                <td><button class="link-btn" type="button" @click.stop="selectedId = order.id">详情</button></td>
              </tr>
              <tr v-if="!orders.length"><td colspan="8"><div class="empty">没有匹配的订单</div></td></tr>
            </tbody>
          </table>
        </div>
        <div class="order-pagination">
          <span>第 {{ page }} 页 · {{ count }} 条记录</span>
          <div class="toolbar-right">
            <button class="btn btn-sm" :disabled="!hasPrevious || loading" @click="loadOrders(page - 1)">上一页</button>
            <button class="btn btn-sm" :disabled="!hasNext || loading" @click="loadOrders(page + 1)">下一页</button>
          </div>
        </div>
      </div>
    </section>
  </template>
</template>

<style scoped>
.create-panel { margin-bottom: 16px; }
.order-filter { display: flex; align-items: center; gap: 7px; }
.order-submit-row { align-items: flex-start; }
.order-pagination { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-top: 13px; color: #7a898f; font-size: 11px; }
tbody tr { cursor: pointer; }
@media (max-width: 900px) {
  .order-filter { width: 100%; flex-wrap: wrap; }
  .order-pagination { align-items: flex-start; flex-direction: column; }
}
</style>
