<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { api } from '../api'
import ScheduleGantt from '../components/ScheduleGantt.vue'

const props = defineProps({
  tasks: { type: Array, default: () => [] },
  agvs: { type: Array, default: () => [] },
  nodes: { type: Array, default: () => [] },
})
const emit = defineEmits(['refresh', 'notify'])

const pendingTasks = computed(() => props.tasks.filter((item) => item.status === 'pending'))
const idleAgvs = computed(() => props.agvs.filter((item) => item.status === 'idle'))
const pickupNodes = computed(() => props.nodes.filter((item) => ['pickup', 'intersection'].includes(item.node_type)))
const dropoffNodes = computed(() => props.nodes.filter((item) => ['dropoff', 'intersection'].includes(item.node_type)))
const singleSelection = ref([])
const batchSelection = ref([])
const singleAgvId = ref('')
const agvWeight = ref(30)
const strictDeadlines = ref(false)
const newTask = reactive({
  pickup_node: '', dropoff_node: '', cargo_name: '', cargo_weight: 30,
  priority: 2, release_at: '', due_at: '',
})
const busy = reactive({ single: false, batch: false, create: false })
const result = ref(null)
const resultMode = ref('')
watch(pendingTasks, (items) => {
  const ids = new Set(items.map((item) => item.id))
  singleSelection.value = singleSelection.value.filter((id) => ids.has(id))
  batchSelection.value = batchSelection.value.filter((id) => ids.has(id))
}, { immediate: true })

function notify(message, type = 'success') {
  emit('notify', { message, type })
}

async function runSingle() {
  if (!singleSelection.value.length) return notify('请至少选择一个任务', 'error')
  busy.single = true
  try {
    const data = await api.singleDispatch({
      task_ids: singleSelection.value,
      agv_id: singleAgvId.value ? Number(singleAgvId.value) : null,
      strict_deadlines: strictDeadlines.value,
    })
    result.value = data
    resultMode.value = 'single'
    notify(data.message)
    emit('refresh')
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    busy.single = false
  }
}

async function runBatch() {
  if (!batchSelection.value.length && !pendingTasks.value.length) return
  busy.batch = true
  try {
    const data = await api.batchDispatch({
      task_ids: batchSelection.value.length ? batchSelection.value : null,
      weights: { agv_weight: Number(agvWeight.value) },
      strict_deadlines: strictDeadlines.value,
    })
    result.value = data
    resultMode.value = 'batch'
    notify(data.message)
    emit('refresh')
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    busy.batch = false
  }
}

async function createTask() {
  if (!newTask.pickup_node || !newTask.dropoff_node || !newTask.cargo_name) {
    return notify('请完整填写任务信息', 'error')
  }
  if (newTask.pickup_node === newTask.dropoff_node) return notify('取货点和放货点不能相同', 'error')
  if (newTask.release_at && newTask.due_at && new Date(newTask.release_at) >= new Date(newTask.due_at)) {
    return notify('要求完成时间必须晚于最早释放时间', 'error')
  }
  busy.create = true
  try {
    await api.createTask({
      ...newTask,
      release_at: newTask.release_at ? new Date(newTask.release_at).toISOString() : null,
      due_at: newTask.due_at ? new Date(newTask.due_at).toISOString() : null,
      cargo_weight: Number(newTask.cargo_weight),
      priority: Number(newTask.priority),
      pickup_node: Number(newTask.pickup_node),
      dropoff_node: Number(newTask.dropoff_node),
    })
    notify('任务创建成功')
    Object.assign(newTask, {
      pickup_node: '', dropoff_node: '', cargo_name: '', cargo_weight: 30,
      priority: 2, release_at: '', due_at: '',
    })
    emit('refresh')
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    busy.create = false
  }
}
</script>

<template>
  <div class="grid dispatch-grid">
    <section class="panel">
      <div class="panel-head">
        <div><div class="panel-title">单台 AGV 多任务顺序优化</div><div class="panel-desc">选择多个任务，系统自动选择一台 AGV 并用动态规划优化执行顺序</div></div>
        <span class="tag">精确 DP / 2-opt</span>
      </div>
      <div class="panel-body">
        <div class="task-select-list compact-list">
          <label v-for="task in pendingTasks" :key="task.id" class="task-select-row" :class="{ selected: singleSelection.includes(task.id) }">
            <input v-model="singleSelection" type="checkbox" :value="task.id" />
            <span class="select-main"><span class="mono strong">{{ task.task_no }}</span><span class="cell-sub">{{ task.cargo_name }} · {{ task.cargo_weight }}kg</span><span v-if="task.due_at" class="cell-sub">交期 {{ new Date(task.due_at).toLocaleString('zh-CN', { hour12: false }) }}</span></span>
            <span class="tag">{{ task.pickup_node_detail?.code }} → {{ task.dropoff_node_detail?.code }}</span>
            <span :class="`priority-${task.priority}`">P{{ task.priority }}</span>
          </label>
          <div v-if="!pendingTasks.length" class="empty">暂无待调度任务</div>
        </div>
        <div class="field mt-16">
          <label>指定 AGV（可选，留空自动择优）</label>
          <select v-model="singleAgvId" class="select">
            <option value="">系统自动选择单台 AGV</option>
            <option v-for="agv in idleAgvs" :key="agv.id" :value="agv.id">{{ agv.code }} · 电量 {{ agv.battery_percent }}% · 载重 {{ agv.payload_capacity }}kg</option>
          </select>
        </div>
        <button class="btn btn-primary btn-block mt-16" :disabled="busy.single || !singleSelection.length" @click="runSingle">
          {{ busy.single ? '正在优化任务顺序...' : `优化单台 AGV 的 ${singleSelection.length} 个任务顺序` }}
        </button>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <div><div class="panel-title">多台 AGV 联合优化</div><div class="panel-desc">最优插入初始化 + 变邻域搜索，统一优化任务分配、车辆内顺序和避碰时间窗</div></div>
        <span class="tag">VNS 多目标优化</span>
      </div>
      <div class="panel-body">
        <div class="task-select-list compact-list">
          <label v-for="task in pendingTasks" :key="task.id" class="task-select-row" :class="{ selected: batchSelection.includes(task.id) }">
            <input v-model="batchSelection" type="checkbox" :value="task.id" />
            <span class="select-main"><span class="mono strong">{{ task.task_no }}</span><span class="cell-sub">{{ task.cargo_name }} · {{ task.cargo_weight }}kg</span><span v-if="task.due_at" class="cell-sub">交期 {{ new Date(task.due_at).toLocaleString('zh-CN', { hour12: false }) }}</span></span>
            <span class="tag">{{ task.pickup_node_detail?.code }} → {{ task.dropoff_node_detail?.code }}</span>
            <span :class="`priority-${task.priority}`">P{{ task.priority }}</span>
          </label>
          <div v-if="!pendingTasks.length" class="empty">暂无待调度任务</div>
        </div>
        <div class="form-grid mt-16">
          <div class="field"><label>AGV 数量权重</label><input v-model.number="agvWeight" type="number" min="0" max="200" class="input" /></div>
          <div class="field"><label>交期约束</label><label class="check-inline"><input v-model="strictDeadlines" type="checkbox" /> 硬交期模式：不接受任何拖期</label></div>
        </div>
        <div class="toolbar-row mt-16">
          <span class="muted small">已选择 {{ batchSelection.length }} 个任务 · 权重越高越倾向减少使用车辆</span>
          <button class="btn btn-primary" :disabled="busy.batch || !pendingTasks.length || !idleAgvs.length" @click="runBatch">{{ busy.batch ? '正在执行联合优化...' : '执行多台 AGV 联合调度' }}</button>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head"><div><div class="panel-title">新建运输任务</div><div class="panel-desc">创建后可参与单台顺序优化或多台联合调度</div></div></div>
      <div class="panel-body">
        <div class="form-grid">
          <div class="field full"><label>货物名称</label><input v-model="newTask.cargo_name" class="input" placeholder="例如：电子元件箱" /></div>
          <div class="field"><label>取货点</label><select v-model="newTask.pickup_node" class="select"><option value="">请选择</option><option v-for="node in pickupNodes" :key="node.id" :value="node.id">{{ node.code }} · {{ node.name }}</option></select></div>
          <div class="field"><label>放货点</label><select v-model="newTask.dropoff_node" class="select"><option value="">请选择</option><option v-for="node in dropoffNodes" :key="node.id" :value="node.id">{{ node.code }} · {{ node.name }}</option></select></div>
          <div class="field"><label>重量 (kg)</label><input v-model.number="newTask.cargo_weight" type="number" min="0.1" step="0.1" class="input" /></div>
          <div class="field"><label>优先级</label><select v-model.number="newTask.priority" class="select"><option :value="1">低</option><option :value="2">普通</option><option :value="3">高</option><option :value="4">紧急</option></select></div>
          <div class="field"><label>最早释放时间（可选）</label><input v-model="newTask.release_at" type="datetime-local" class="input" /></div>
          <div class="field"><label>要求完成时间（可选）</label><input v-model="newTask.due_at" type="datetime-local" class="input" /></div>
        </div>
        <button class="btn btn-block mt-16" :disabled="busy.create" @click="createTask">{{ busy.create ? '创建中...' : '创建运输任务' }}</button>
      </div>
    </section>
  </div>

  <ScheduleGantt :result="result" />
</template>
