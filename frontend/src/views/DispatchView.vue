<script setup>
import { computed, nextTick, reactive, ref, watch } from 'vue'
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
const dispatchMode = ref('single')
const selectedTaskIds = ref([])
const singleAgvId = ref('')
const agvWeight = ref(30)
const strictDeadlines = ref(false)
const taskQuery = ref('')
const showCreateTask = ref(false)
const resultAnchor = ref(null)
const newTask = reactive({
  pickup_node: '', dropoff_node: '', cargo_name: '', cargo_weight: 30,
  priority: 2, release_at: '', due_at: '',
})
const busy = reactive({ single: false, batch: false, create: false })
const result = ref(null)
const resultMode = ref('')
const filteredPendingTasks = computed(() => {
  const keyword = taskQuery.value.trim().toLowerCase()
  if (!keyword) return pendingTasks.value
  return pendingTasks.value.filter((task) =>
    `${task.task_no} ${task.cargo_name} ${task.pickup_node_detail?.code || ''} ${task.dropoff_node_detail?.code || ''}`
      .toLowerCase()
      .includes(keyword),
  )
})
const scheduleScopeCount = computed(() =>
  selectedTaskIds.value.length || (dispatchMode.value === 'batch' ? pendingTasks.value.length : 0),
)
const scheduleScopeHint = computed(() =>
  dispatchMode.value === 'batch' && selectedTaskIds.value.length === 0
    ? '未单独选择时将处理全部待调度任务'
    : '执行后将保留最近一次优化结果',
)
watch(pendingTasks, (items) => {
  const ids = new Set(items.map((item) => item.id))
  selectedTaskIds.value = selectedTaskIds.value.filter((id) => ids.has(id))
}, { immediate: true })

function notify(message, type = 'success') {
  emit('notify', { message, type })
}

async function runSingle() {
  if (!selectedTaskIds.value.length) return notify('请至少选择一个任务', 'error')
  busy.single = true
  try {
    const data = await api.singleDispatch({
      task_ids: selectedTaskIds.value,
      agv_id: singleAgvId.value ? Number(singleAgvId.value) : null,
      strict_deadlines: strictDeadlines.value,
    })
    result.value = data
    resultMode.value = 'single'
    notify(data.message)
    emit('refresh')
    await nextTick()
    resultAnchor.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    busy.single = false
  }
}

async function runBatch() {
  if (!selectedTaskIds.value.length && !pendingTasks.value.length) return
  busy.batch = true
  try {
    const data = await api.batchDispatch({
      task_ids: selectedTaskIds.value.length ? selectedTaskIds.value : null,
      weights: { agv_weight: Number(agvWeight.value) },
      strict_deadlines: strictDeadlines.value,
    })
    result.value = data
    resultMode.value = 'batch'
    notify(data.message)
    emit('refresh')
    await nextTick()
    resultAnchor.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    busy.batch = false
  }
}

function toggleAllTasks() {
  const visibleIds = filteredPendingTasks.value.map((task) => task.id)
  const allSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedTaskIds.value.includes(id))
  if (allSelected) {
    selectedTaskIds.value = selectedTaskIds.value.filter((id) => !visibleIds.includes(id))
  } else {
    selectedTaskIds.value = [...new Set([...selectedTaskIds.value, ...visibleIds])]
  }
}

function clearSelection() {
  selectedTaskIds.value = []
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
  <div class="dispatch-page">
    <section class="panel dispatch-mode-bar">
      <div class="mode-copy">
        <span class="mode-mark">⌁</span>
        <div><strong>AGV 调度工作台</strong><small>选择任务与优化模式，执行后结果会保留在工作台中</small></div>
      </div>
      <div class="dispatch-mode-tabs">
        <button type="button" :class="{ active: dispatchMode === 'single' }" @click="dispatchMode = 'single'">单台顺序优化</button>
        <button type="button" :class="{ active: dispatchMode === 'batch' }" @click="dispatchMode = 'batch'">多台联合优化</button>
      </div>
    </section>

    <div class="grid dispatch-grid dispatch-workspace">
      <section class="panel task-selection-panel">
        <div class="panel-head">
          <div><div class="panel-title">选择待调度任务</div><div class="panel-desc">任务选择会在单台和多台模式之间保留</div></div>
          <span class="selection-count">{{ selectedTaskIds.length }} / {{ pendingTasks.length }}</span>
        </div>
        <div class="panel-body">
          <div class="task-list-toolbar">
            <input v-model="taskQuery" class="input" placeholder="搜索任务、货物或站点..." />
            <button class="btn btn-sm" @click="toggleAllTasks">{{ filteredPendingTasks.length && filteredPendingTasks.every(task => selectedTaskIds.includes(task.id)) ? '取消全选' : '全选当前' }}</button>
            <button v-if="selectedTaskIds.length" class="btn btn-sm" @click="clearSelection">清除</button>
          </div>
          <div class="task-select-list compact-list dispatch-task-list">
            <label v-for="task in filteredPendingTasks" :key="task.id" class="task-select-row" :class="{ selected: selectedTaskIds.includes(task.id) }">
              <input v-model="selectedTaskIds" type="checkbox" :value="task.id" />
              <span class="select-main"><span class="mono strong">{{ task.task_no }}</span><span class="cell-sub">{{ task.cargo_name }} · {{ task.cargo_weight }}kg</span><span v-if="task.due_at" class="cell-sub">交期 {{ new Date(task.due_at).toLocaleString('zh-CN', { hour12: false }) }}</span></span>
              <span class="tag">{{ task.pickup_node_detail?.code }} → {{ task.dropoff_node_detail?.code }}</span>
              <span :class="`priority-${task.priority}`">P{{ task.priority }}</span>
            </label>
            <div v-if="!filteredPendingTasks.length" class="empty">没有符合条件的待调度任务</div>
          </div>
        </div>
      </section>

      <section class="panel optimization-settings-panel">
        <div class="panel-head">
          <div>
            <div class="panel-title">{{ dispatchMode === 'single' ? '单台 AGV 多任务顺序优化' : '多台 AGV 联合优化' }}</div>
            <div class="panel-desc">{{ dispatchMode === 'single' ? '系统自动选择一台 AGV，并用动态规划优化执行顺序' : '统一优化任务分配、车辆内顺序和避碰时间窗' }}</div>
          </div>
          <span class="tag">{{ dispatchMode === 'single' ? 'DP / 2-opt' : 'VNS 多目标' }}</span>
        </div>
        <div class="panel-body">
          <div v-if="dispatchMode === 'single'" class="settings-stack">
            <div class="field">
              <label>指定 AGV（可选，留空自动择优）</label>
              <select v-model="singleAgvId" class="select">
                <option value="">系统自动选择单台 AGV</option>
                <option v-for="agv in idleAgvs" :key="agv.id" :value="agv.id">{{ agv.code }} · 电量 {{ agv.battery_percent }}% · 载重 {{ agv.payload_capacity }}kg</option>
              </select>
            </div>
            <label class="check-inline"><input v-model="strictDeadlines" type="checkbox" /> 硬交期模式：不接受任何拖期</label>
            <div class="algorithm-note">
              <strong>执行方式</strong>
              <span>选中的 {{ selectedTaskIds.length }} 个任务将连续分配给同一台 AGV，系统自动比较执行顺序。</span>
            </div>
          </div>
          <div v-else class="settings-stack">
            <div class="field">
              <label>AGV 数量权重</label>
              <input v-model.number="agvWeight" type="number" min="0" max="200" class="input" />
            </div>
            <label class="check-inline"><input v-model="strictDeadlines" type="checkbox" /> 硬交期模式：不接受任何拖期</label>
            <div class="algorithm-note">
              <strong>权重说明</strong>
              <span>数值越高，优化越倾向减少使用车辆；当前已选择 {{ selectedTaskIds.length }} 个任务。</span>
            </div>
          </div>
          <div class="optimization-action-row">
            <div class="selected-summary"><span>本次调度任务</span><strong>{{ scheduleScopeCount }}</strong><small>{{ scheduleScopeHint }}</small></div>
            <button v-if="dispatchMode === 'single'" class="btn btn-primary optimization-run-btn" :disabled="busy.single || !selectedTaskIds.length" @click="runSingle">{{ busy.single ? '正在优化...' : '开始单台顺序优化' }}</button>
            <button v-else class="btn btn-primary optimization-run-btn" :disabled="busy.batch || !pendingTasks.length || !idleAgvs.length" @click="runBatch">{{ busy.batch ? '正在执行...' : '执行多台联合调度' }}</button>
          </div>
        </div>
      </section>
    </div>

    <div ref="resultAnchor" class="dispatch-result-anchor">
      <ScheduleGantt v-if="result" :result="result" />
      <section v-else class="panel dispatch-result-empty">
        <div class="result-empty-visual">
          <span>⌁</span>
          <strong>调度结果将在这里持续显示</strong>
          <p>选择任务并执行优化后，指标、甘特图和 AGV 分配会保留在当前位置，不需重新查找。</p>
        </div>
      </section>
    </div>

    <section class="panel create-task-panel">
      <div class="panel-head create-task-head">
        <div><div class="panel-title">新建运输任务</div><div class="panel-desc">创建后可参与当前调度流程</div></div>
        <button class="btn btn-sm" @click="showCreateTask = !showCreateTask">{{ showCreateTask ? '收起表单' : '展开表单' }}</button>
      </div>
      <div v-if="showCreateTask" class="panel-body">
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
</template>

<style scoped>
.dispatch-page { display: grid; gap: 16px; }
.dispatch-mode-bar {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  overflow: hidden;
  padding: 14px 16px;
  background:
    radial-gradient(circle at 86% 15%, rgba(14, 135, 146, 0.075), transparent 27%),
    linear-gradient(135deg, #ffffff, #f7fbf9);
}
.dispatch-mode-bar::before {
  content: "";
  position: absolute;
  inset: 0 0 auto;
  height: 2px;
  background: linear-gradient(90deg, #4b83e4, #1b9c9c, transparent 72%);
}
.mode-copy { display: flex; align-items: center; gap: 11px; min-width: 0; }
.mode-mark {
  width: 37px;
  height: 37px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  border: 1px solid rgba(14, 135, 146, 0.16);
  border-radius: 10px;
  color: var(--cyan);
  background: #edf8f5;
  font-size: 18px;
}
.mode-copy > div { display: grid; gap: 3px; }
.mode-copy strong { color: #17333b; font-size: 13px; font-weight: 800; }
.mode-copy small { color: var(--muted); font-size: 9.5px; }
.dispatch-mode-tabs {
  display: flex;
  gap: 4px;
  padding: 4px;
  border: 1px solid #dbe5e0;
  border-radius: 11px;
  background: #edf4f1;
}
.dispatch-mode-tabs button {
  min-height: 33px;
  padding: 6px 13px;
  border: 0;
  border-radius: 8px;
  color: #687b74;
  background: transparent;
  font-size: 10.5px;
  font-weight: 680;
}
.dispatch-mode-tabs button:hover { color: #244e4b; background: rgba(255, 255, 255, 0.55); }
.dispatch-mode-tabs button.active {
  color: #153e40;
  background: #ffffff;
  box-shadow: 0 2px 8px rgba(20, 45, 54, 0.08);
}
.dispatch-grid {
  gap: 18px;
}
.dispatch-workspace {
  grid-template-columns: minmax(0, 1.15fr) minmax(350px, 0.85fr);
  align-items: stretch;
}
.dispatch-workspace > .panel:last-child { grid-column: auto; }
.task-selection-panel,
.optimization-settings-panel { display: flex; flex-direction: column; }
.task-selection-panel .panel-body,
.optimization-settings-panel .panel-body { flex: 1; min-height: 0; }
.selection-count {
  min-width: 50px;
  height: 26px;
  display: grid;
  place-items: center;
  border: 1px solid #d2e5de;
  border-radius: 8px;
  color: #28796e;
  background: #f1f8f5;
  font-family: "Cascadia Mono", Consolas, monospace;
  font-size: 9px;
  font-weight: 800;
}
.task-list-toolbar { display: flex; gap: 7px; align-items: center; }
.task-list-toolbar .input { min-height: 38px; flex: 1; }
.task-list-toolbar .btn { white-space: nowrap; }
.dispatch-task-list.compact-list {
  max-height: 430px;
  margin-top: 10px;
}
.settings-stack { display: grid; gap: 13px; }
.algorithm-note {
  display: grid;
  gap: 4px;
  padding: 12px 13px;
  border: 1px solid #dce7e2;
  border-radius: 10px;
  background: #f7faf8;
}
.algorithm-note strong { color: #405a55; font-size: 10px; }
.algorithm-note span { color: #7c8b86; font-size: 9.5px; line-height: 1.55; }
.optimization-action-row {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 14px;
  margin-top: auto;
  padding-top: 18px;
  border-top: 1px solid #e5ece9;
}
.selected-summary { display: grid; gap: 1px; min-width: 0; }
.selected-summary span { color: #83918d; font-size: 8.5px; }
.selected-summary strong { color: #17363d; font-size: 25px; line-height: 1.05; }
.selected-summary small { color: #81908b; font-size: 8.5px; line-height: 1.4; }
.optimization-run-btn { min-width: 190px; min-height: 44px; }
.dispatch-result-anchor { scroll-margin-top: 18px; }
.dispatch-result-empty {
  min-height: 280px;
  display: grid;
  place-items: center;
  background:
    radial-gradient(circle at center, rgba(14, 135, 146, 0.055), transparent 38%),
    #ffffff;
}
.result-empty-visual { max-width: 390px; display: grid; justify-items: center; gap: 8px; padding: 28px; text-align: center; }
.result-empty-visual > span {
  width: 52px;
  height: 52px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(14, 135, 146, 0.16);
  border-radius: 15px;
  color: var(--cyan);
  background: #eef8f5;
  font-size: 23px;
}
.result-empty-visual strong { color: #28454b; font-size: 14px; }
.result-empty-visual p { margin: 0; color: var(--muted); font-size: 10px; line-height: 1.65; }
.create-task-panel { position: relative; overflow: hidden; }
.create-task-panel::before {
  content: "";
  position: absolute;
  inset: 0 0 auto;
  height: 2px;
  background: linear-gradient(90deg, #7863c9, rgba(120, 99, 201, 0.12));
}
.create-task-head { min-height: 66px; }
.create-task-head .btn {
  min-height: 34px;
  padding: 7px 13px;
  border-color: #cbdcd6;
  border-radius: 9px;
  color: #365b56;
  background: #ffffff;
  font-size: 12px;
  font-weight: 720;
}
.create-task-head .btn:hover { border-color: #9fc5bc; color: #174d49; background: #f8fcfa; }
.dispatch-grid > .panel {
  position: relative;
  isolation: isolate;
  overflow: hidden;
  background:
    radial-gradient(circle at 100% 0%, rgba(47, 111, 218, 0.055), transparent 25%),
    linear-gradient(155deg, #ffffff 0%, #fbfdfc 100%);
}
.dispatch-grid > .panel::before {
  content: "";
  position: absolute;
  inset: 0 0 auto;
  z-index: 2;
  height: 3px;
  background: linear-gradient(90deg, #4b83e4, rgba(75, 131, 228, 0.18));
}
.dispatch-grid > .panel:nth-child(2)::before {
  background: linear-gradient(90deg, #1b9c9c, rgba(27, 156, 156, 0.16));
}
.dispatch-grid > .panel:nth-child(3)::before {
  background: linear-gradient(90deg, #6c65bc, rgba(108, 101, 188, 0.16));
}
.dispatch-grid > .panel::after {
  content: "";
  position: absolute;
  z-index: 0;
  top: -78px;
  right: -58px;
  width: 180px;
  height: 180px;
  border: 1px solid rgba(53, 113, 129, 0.075);
  border-radius: 50%;
  box-shadow: 0 0 0 18px rgba(53, 113, 129, 0.018);
  pointer-events: none;
}
.dispatch-grid > .panel > .panel-head,
.dispatch-grid > .panel > .panel-body {
  position: relative;
  z-index: 1;
}
.dispatch-grid > .panel > .panel-head {
  min-height: 82px;
  padding: 18px 21px 16px;
  background:
    linear-gradient(rgba(39, 91, 89, 0.02) 1px, transparent 1px),
    linear-gradient(90deg, rgba(39, 91, 89, 0.02) 1px, transparent 1px),
    linear-gradient(180deg, rgba(249, 252, 251, 0.96), rgba(255, 255, 255, 0.78));
  background-size: 24px 24px, 24px 24px, auto;
}
.dispatch-grid > .panel > .panel-head .tag {
  padding: 6px 9px;
  border-color: rgba(69, 124, 139, 0.16);
  border-radius: 8px;
  background: rgba(245, 250, 250, 0.9);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.8);
  font-size: 9px;
  letter-spacing: 0.04em;
}
.dispatch-grid > .panel > .panel-body {
  padding: 18px 20px 20px;
}
.dispatch-grid .task-select-list.compact-list {
  gap: 9px;
  max-height: 310px;
  padding: 3px 7px 3px 2px;
  scrollbar-width: thin;
  scrollbar-color: rgba(90, 142, 137, 0.28) transparent;
}
.dispatch-grid .task-select-row {
  grid-template-columns: 25px minmax(0, 1fr) auto 30px;
  gap: 11px;
  min-height: 68px;
  padding: 11px 12px;
  border-color: #d7e3de;
  border-radius: 11px;
  background: linear-gradient(145deg, #ffffff, #f8fbf9);
  box-shadow: 0 1px 2px rgba(18, 42, 50, 0.025), 0 5px 14px rgba(18, 42, 50, 0.025);
  transition: transform 160ms ease, border-color 160ms ease, box-shadow 160ms ease, background 160ms ease;
}
.dispatch-grid .task-select-row:hover {
  border-color: #b9cfc7;
  background: #ffffff;
  box-shadow: 0 3px 8px rgba(18, 42, 50, 0.045), 0 10px 24px rgba(18, 42, 50, 0.06);
  transform: translateY(-1px);
}
.dispatch-grid .task-select-row.selected {
  border-color: rgba(20, 151, 151, 0.36);
  background:
    linear-gradient(90deg, rgba(20, 151, 151, 0.075), rgba(20, 151, 151, 0.018)),
    #ffffff;
  box-shadow: inset 3px 0 0 #159797, 0 5px 16px rgba(20, 120, 120, 0.07);
}
.dispatch-grid .task-select-row input[type="checkbox"] {
  appearance: none;
  width: 19px;
  height: 19px;
  display: grid;
  place-items: center;
  margin: 0;
  border: 1px solid #bdcbc6;
  border-radius: 6px;
  background: #ffffff;
  box-shadow: inset 0 1px 1px rgba(18, 42, 50, 0.04);
  cursor: pointer;
  transition: border-color 150ms ease, background 150ms ease, box-shadow 150ms ease;
}
.dispatch-grid .task-select-row input[type="checkbox"]::after {
  content: "";
  width: 8px;
  height: 4px;
  border-left: 2px solid #ffffff;
  border-bottom: 2px solid #ffffff;
  opacity: 0;
  transform: translateY(-1px) rotate(-45deg) scale(0.7);
  transition: opacity 120ms ease, transform 120ms ease;
}
.dispatch-grid .task-select-row input[type="checkbox"]:checked {
  border-color: #129393;
  background: linear-gradient(145deg, #1aa4a0, #0e7d83);
  box-shadow: 0 3px 8px rgba(14, 125, 131, 0.2);
}
.dispatch-grid .task-select-row input[type="checkbox"]:checked::after {
  opacity: 1;
  transform: translateY(-1px) rotate(-45deg) scale(1);
}
.dispatch-grid .select-main {
  min-width: 0;
  gap: 4px;
}
.dispatch-grid .select-main > .strong {
  overflow: hidden;
  color: #20353d;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dispatch-grid .task-select-row > .tag {
  padding: 5px 8px;
  border-color: #d5e5e4;
  border-radius: 7px;
  background: rgba(247, 251, 250, 0.96);
  color: #346c70;
  font-family: "Cascadia Mono", Consolas, monospace;
  letter-spacing: 0.02em;
}
.dispatch-grid .task-select-row > [class^="priority-"] {
  min-width: 30px;
  padding: 4px 5px;
  border: 1px solid currentColor;
  border-radius: 7px;
  text-align: center;
  font-size: 9px;
  font-weight: 800;
  opacity: 0.84;
}
.dispatch-grid .field {
  gap: 8px;
}
.dispatch-grid .field > label:first-child {
  color: #4e625d;
  font-size: 10.5px;
  font-weight: 720;
}
.dispatch-grid .input,
.dispatch-grid .select {
  min-height: 43px;
  border-color: #cddbd5;
  background: linear-gradient(180deg, #ffffff, #fbfdfc);
  box-shadow: inset 0 1px 1px rgba(18, 42, 50, 0.025), 0 2px 8px rgba(18, 42, 50, 0.018);
}
.dispatch-grid .check-inline {
  padding: 8px 11px;
  border: 1px solid #d6e2dd;
  border-radius: 10px;
  background: #f8fbfa;
  min-height: 43px;
  cursor: pointer;
}
.dispatch-grid .form-grid {
  gap: 14px;
}
.dispatch-grid .toolbar-row {
  align-items: flex-end;
  padding-top: 14px;
  border-top: 1px solid #e5ece9;
}
.dispatch-grid .toolbar-row > .muted {
  max-width: 55%;
  line-height: 1.55;
}
.dispatch-grid .btn-primary {
  position: relative;
  overflow: hidden;
  min-height: 43px;
  border-radius: 11px;
  box-shadow: 0 5px 12px rgba(14, 126, 133, 0.18), 0 12px 26px rgba(14, 126, 133, 0.1), inset 0 1px 0 rgba(255, 255, 255, 0.22);
  transition: transform 150ms ease, box-shadow 150ms ease, filter 150ms ease;
}
.dispatch-grid .btn-primary::after {
  content: "";
  position: absolute;
  top: -45%;
  left: -35%;
  width: 28%;
  height: 190%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.2), transparent);
  transform: rotate(18deg);
  transition: left 320ms ease;
  pointer-events: none;
}
.dispatch-grid .btn-primary:hover:not(:disabled) {
  filter: saturate(1.04);
  transform: translateY(-2px);
  box-shadow: 0 7px 16px rgba(14, 126, 133, 0.22), 0 17px 34px rgba(14, 126, 133, 0.14), inset 0 1px 0 rgba(255, 255, 255, 0.24);
}
.dispatch-grid .btn-primary:hover:not(:disabled)::after {
  left: 118%;
}
.dispatch-grid .btn-primary:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: 0 3px 8px rgba(14, 126, 133, 0.18), inset 0 1px 2px rgba(4, 55, 59, 0.12);
}
@media (max-width: 980px) {
  .dispatch-workspace { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 720px) {
  .dispatch-mode-bar { align-items: stretch; flex-direction: column; gap: 11px; }
  .dispatch-mode-tabs { align-self: stretch; }
  .dispatch-mode-tabs button { flex: 1; }
  .optimization-action-row { align-items: stretch; flex-direction: column; }
  .optimization-run-btn { width: 100%; }
  .task-list-toolbar { align-items: stretch; flex-wrap: wrap; }
  .task-list-toolbar .input { flex-basis: 100%; }
  .dispatch-grid .task-select-row {
    grid-template-columns: 22px minmax(0, 1fr) auto;
  }
  .dispatch-grid .task-select-row > [class^="priority-"] {
    display: none;
  }
  .dispatch-grid .toolbar-row {
    align-items: stretch;
    flex-direction: column;
  }
  .dispatch-grid .toolbar-row > .muted {
    max-width: none;
  }
}
</style>
