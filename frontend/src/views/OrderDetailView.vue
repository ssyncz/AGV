<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { api } from '../api'
import OrderTimeline from '../components/OrderTimeline.vue'
import StatusBadge from '../components/StatusBadge.vue'

const props = defineProps({
  orderId: { type: Number, required: true },
  nodes: { type: Array, default: () => [] },
})
const emit = defineEmits(['back', 'updated', 'notify'])

const order = ref(null)
const loading = ref(false)
const error = ref('')
const editing = ref(false)
const busy = ref(false)
const form = reactive({
  cargo_name: '',
  cargo_weight: 1,
  pickup_node: null,
  dropoff_node: null,
  priority: 2,
  notes: '',
})

const canEdit = computed(() => order.value?.status === 'pending')
const canCancel = computed(() => ['pending', 'assigned'].includes(order.value?.status))

function formatTime(value) {
  if (!value) return '--'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function syncForm() {
  if (!order.value) return
  Object.assign(form, {
    cargo_name: order.value.cargo_name,
    cargo_weight: order.value.cargo_weight,
    pickup_node: order.value.pickup_node,
    dropoff_node: order.value.dropoff_node,
    priority: order.value.priority,
    notes: order.value.notes || '',
  })
}

async function loadOrder() {
  loading.value = true
  error.value = ''
  try {
    order.value = await api.getOrder(props.orderId)
    syncForm()
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function saveOrder() {
  if (!form.pickup_node || !form.dropoff_node) {
    emit('notify', { message: '请选择取货点和放货点', type: 'error' })
    return
  }
  if (form.pickup_node === form.dropoff_node) {
    emit('notify', { message: '取货点和放货点不能相同', type: 'error' })
    return
  }
  busy.value = true
  try {
    order.value = await api.updateOrder(props.orderId, {
      cargo_name: form.cargo_name,
      cargo_weight: Number(form.cargo_weight),
      pickup_node: Number(form.pickup_node),
      dropoff_node: Number(form.dropoff_node),
      priority: Number(form.priority),
      notes: form.notes,
    })
    editing.value = false
    syncForm()
    emit('notify', { message: '待调度订单已更新' })
    emit('updated')
  } catch (err) {
    emit('notify', { message: err.message, type: 'error' })
  } finally {
    busy.value = false
  }
}

async function cancelOrder() {
  if (!window.confirm('确认取消该订单及其运输任务？')) return
  busy.value = true
  try {
    order.value = await api.cancelOrder(props.orderId)
    editing.value = false
    emit('notify', { message: '订单已取消' })
    emit('updated')
  } catch (err) {
    emit('notify', { message: err.message, type: 'error' })
  } finally {
    busy.value = false
  }
}

watch(() => props.orderId, loadOrder, { immediate: true })
</script>

<template>
  <section class="panel order-detail-panel">
    <div class="panel-head">
      <div class="detail-heading">
        <button class="back-btn" type="button" @click="emit('back')">← 返回订单列表</button>
        <div v-if="order">
          <div class="panel-title mono">{{ order.order_no }}</div>
          <div class="panel-desc">{{ order.cargo_name }} · 下单于 {{ formatTime(order.created_at) }}</div>
        </div>
        <div v-else class="panel-title">订单详情</div>
      </div>
      <div v-if="order" class="toolbar-right">
        <StatusBadge :status="order.status" />
        <button v-if="canEdit && !editing" class="btn btn-sm" @click="editing = true">编辑订单</button>
        <button v-if="canCancel" class="btn btn-sm btn-danger" :disabled="busy" @click="cancelOrder">取消订单</button>
      </div>
    </div>

    <div class="panel-body">
      <div v-if="loading" class="empty">正在加载订单详情...</div>
      <div v-else-if="error" class="notice warning">{{ error }}</div>
      <template v-else-if="order">
        <form v-if="editing" class="form-grid detail-form" @submit.prevent="saveOrder">
          <div class="field">
            <label>货物名称</label>
            <input v-model.trim="form.cargo_name" class="input" required maxlength="64" />
          </div>
          <div class="field">
            <label>货物重量（kg）</label>
            <input v-model.number="form.cargo_weight" class="input" type="number" min="0.1" step="0.1" required />
          </div>
          <div class="field">
            <label>取货点</label>
            <select v-model.number="form.pickup_node" class="select" required>
              <option disabled :value="null">请选择</option>
              <option v-for="node in nodes.filter((item) => item.node_type === 'pickup')" :key="node.id" :value="node.id">
                {{ node.code }} · {{ node.name }}
              </option>
            </select>
          </div>
          <div class="field">
            <label>放货点</label>
            <select v-model.number="form.dropoff_node" class="select" required>
              <option disabled :value="null">请选择</option>
              <option v-for="node in nodes.filter((item) => item.node_type === 'dropoff')" :key="node.id" :value="node.id">
                {{ node.code }} · {{ node.name }}
              </option>
            </select>
          </div>
          <div class="field">
            <label>优先级</label>
            <select v-model.number="form.priority" class="select">
              <option :value="1">低</option><option :value="2">普通</option>
              <option :value="3">高</option><option :value="4">紧急</option>
            </select>
          </div>
          <div class="field">
            <label>备注</label>
            <input v-model.trim="form.notes" class="input" maxlength="255" />
          </div>
          <div class="field full edit-actions">
            <button class="btn btn-primary" type="submit" :disabled="busy">保存修改</button>
            <button class="btn" type="button" :disabled="busy" @click="editing = false; syncForm()">放弃</button>
          </div>
        </form>

        <div v-else class="detail-grid">
          <section class="detail-card">
            <h3>订单信息</h3>
            <dl>
              <div><dt>客户</dt><dd>{{ order.customer.name }} · {{ order.customer.masked_phone }}</dd></div>
              <div><dt>货物</dt><dd>{{ order.cargo_name }} · {{ order.cargo_weight }} kg</dd></div>
              <div><dt>运输路线</dt><dd>{{ order.pickup_node_detail.code }} {{ order.pickup_node_detail.name }} → {{ order.dropoff_node_detail.code }} {{ order.dropoff_node_detail.name }}</dd></div>
              <div><dt>优先级</dt><dd :class="`priority-${order.priority}`">{{ order.priority_display }}</dd></div>
              <div><dt>备注</dt><dd>{{ order.notes || '无' }}</dd></div>
            </dl>
          </section>

          <section class="detail-card">
            <h3>运输任务</h3>
            <dl v-if="order.transport_task">
              <div><dt>任务编号</dt><dd class="mono">{{ order.transport_task.task_no }}</dd></div>
              <div><dt>执行车辆</dt><dd>{{ order.transport_task.assigned_agv_code || '等待分配' }}</dd></div>
              <div><dt>计划窗口</dt><dd>{{ formatTime(order.transport_task.scheduled_start) }}<br>{{ formatTime(order.transport_task.scheduled_end) }}</dd></div>
              <div><dt>里程 / 耗时</dt><dd>{{ order.transport_task.total_distance || 0 }} m / {{ order.transport_task.estimated_duration || 0 }} s</dd></div>
            </dl>
            <div v-else class="empty small-empty">该订单暂无关联运输任务</div>
          </section>
        </div>

        <section class="timeline-section">
          <div class="section-title">
            <div>
              <div class="panel-title">订单时间轴</div>
              <div class="panel-desc">状态随运输任务自动回写</div>
            </div>
          </div>
          <OrderTimeline :events="order.events" />
        </section>
      </template>
    </div>
  </section>
</template>

<style scoped>
.order-detail-panel { overflow: hidden; }
.detail-heading { display: flex; align-items: center; gap: 16px; }
.back-btn {
  padding: 7px 10px;
  border: 1px solid #d7e1dd;
  border-radius: 8px;
  color: #526870;
  background: #f8fbfa;
  font-size: 11px;
}
.detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.detail-card {
  padding: 16px;
  border: 1px solid #e0e8e4;
  border-radius: 11px;
  background: #f9fbfa;
}
.detail-card h3 { margin: 0 0 13px; color: #1c353d; font-size: 13px; }
dl { display: grid; gap: 11px; margin: 0; }
dl > div { display: grid; grid-template-columns: 90px minmax(0, 1fr); gap: 12px; }
dt { color: #7b898e; font-size: 11px; }
dd { margin: 0; color: #2d454d; font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }
.detail-form { padding: 3px; }
.edit-actions { flex-direction: row; }
.timeline-section { margin-top: 17px; padding: 16px; border: 1px solid #e0e8e4; border-radius: 11px; }
.section-title { margin-bottom: 15px; }
@media (max-width: 760px) {
  .detail-grid { grid-template-columns: 1fr; }
  .detail-heading { align-items: flex-start; flex-direction: column; }
}
</style>
