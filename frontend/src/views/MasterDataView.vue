<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api'

const emit = defineEmits(['notify'])
const data = ref({ sites: [], products: [], equipment: [], work_calendars: [] })
const busy = ref('')
const activeTab = ref('site')
const keyword = ref('')
const drawerOpen = ref(false)
const drawerKind = ref('site')
const editingId = ref(null)
const siteForm = reactive({ code: '', name: '', location: '' })
const productForm = reactive({ code: '', name: '', specification: '', unit: '件' })
const equipmentForm = reactive({ code: '', name: '', equipment_type: '', site: '' })
const calendarForm = reactive({
  site: '', name: '默认白班', weekdays: [1, 2, 3, 4, 5],
  shift_start: '08:00', shift_end: '18:00',
})

const tabConfig = {
  site: { label: '业务站点', dataKey: 'sites', singular: '站点', icon: '⌂' },
  product: { label: '产品档案', dataKey: 'products', singular: '产品', icon: '▤' },
  equipment: { label: '设备档案', dataKey: 'equipment', singular: '设备', icon: '◈' },
  calendar: { label: '班次日历', dataKey: 'work_calendars', singular: '班次日历', icon: '▥' },
}
const weekdayLabels = { 1: '一', 2: '二', 3: '三', 4: '四', 5: '五', 6: '六', 7: '日' }

const tabs = computed(() => Object.entries(tabConfig).map(([key, item]) => ({
  key,
  ...item,
  count: data.value[item.dataKey]?.length || 0,
})))
const activeConfig = computed(() => tabConfig[activeTab.value])
const activeItems = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  const items = data.value[activeConfig.value.dataKey] || []
  if (!text) return items
  return items.filter((item) => JSON.stringify(item).toLowerCase().includes(text))
})

async function load() {
  try {
    data.value = await api.masterData()
    if (!equipmentForm.site && data.value.sites?.length) equipmentForm.site = data.value.sites[0].id
    if (!calendarForm.site && data.value.sites?.length) calendarForm.site = data.value.sites[0].id
  } catch (error) {
    emit('notify', { message: `主数据加载失败：${error.message}`, type: 'error' })
  }
}

function resetForm(kind) {
  if (kind === 'site') Object.assign(siteForm, { code: '', name: '', location: '' })
  if (kind === 'product') Object.assign(productForm, { code: '', name: '', specification: '', unit: '件' })
  if (kind === 'equipment') Object.assign(equipmentForm, { code: '', name: '', equipment_type: '', site: data.value.sites?.[0]?.id || '' })
  if (kind === 'calendar') Object.assign(calendarForm, {
    site: data.value.sites?.[0]?.id || '', name: '默认白班',
    weekdays: [1, 2, 3, 4, 5], shift_start: '08:00', shift_end: '18:00',
  })
}

function openCreate(kind = activeTab.value) {
  drawerKind.value = kind
  editingId.value = null
  resetForm(kind)
  drawerOpen.value = true
}

function openEdit(kind, item) {
  drawerKind.value = kind
  editingId.value = item.id
  if (kind === 'site') Object.assign(siteForm, { code: item.code || '', name: item.name || '', location: item.location || '' })
  if (kind === 'product') Object.assign(productForm, { code: item.code || '', name: item.name || '', specification: item.specification || '', unit: item.unit || '件' })
  if (kind === 'equipment') Object.assign(equipmentForm, { code: item.code || '', name: item.name || '', equipment_type: item.equipment_type || '', site: item.site || data.value.sites?.[0]?.id || '' })
  if (kind === 'calendar') Object.assign(calendarForm, {
    site: item.site || data.value.sites?.[0]?.id || '', name: item.name || '',
    weekdays: [...(item.weekdays || [])], shift_start: item.shift_start || '08:00', shift_end: item.shift_end || '18:00',
  })
  drawerOpen.value = true
}

function closeDrawer() {
  drawerOpen.value = false
  editingId.value = null
  busy.value = ''
}

async function create(kind) {
  busy.value = kind
  try {
    if (kind === 'site') {
      editingId.value ? await api.updateSite(editingId.value, siteForm) : await api.createSite(siteForm)
      resetForm(kind)
    } else if (kind === 'product') {
      editingId.value ? await api.updateProduct(editingId.value, productForm) : await api.createProduct(productForm)
      resetForm(kind)
    } else if (kind === 'equipment') {
      const payload = { ...equipmentForm, site: equipmentForm.site || null }
      editingId.value ? await api.updateEquipment(editingId.value, payload) : await api.createEquipment(payload)
      resetForm(kind)
    } else {
      editingId.value ? await api.updateWorkCalendar(editingId.value, calendarForm) : await api.createWorkCalendar(calendarForm)
      resetForm(kind)
    }
    emit('notify', { message: editingId.value ? '主数据已更新' : '主数据已新增' })
    await load()
    closeDrawer()
  } catch (error) {
    emit('notify', { message: error.message, type: 'error' })
  } finally {
    busy.value = ''
  }
}

function toggleWeekday(day) {
  if (calendarForm.weekdays.includes(day)) {
    calendarForm.weekdays = calendarForm.weekdays.filter((item) => item !== day)
  } else {
    calendarForm.weekdays = [...calendarForm.weekdays, day].sort()
  }
}

function weekdaysText(days = []) {
  return days.map((day) => `周${weekdayLabels[day] || day}`).join('、')
}

function formatDateTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '--'
}

onMounted(load)
</script>

<template>
  <div class="master-page">
    <section class="panel master-tab-panel">
      <div v-for="tab in tabs" :key="tab.key" class="master-tab" :class="{ active: activeTab === tab.key }" @click="activeTab = tab.key; keyword = ''">
        <span class="master-tab-icon">{{ tab.icon }}</span>
        <div><strong>{{ tab.label }}</strong><small>{{ tab.count }} 条记录</small></div>
      </div>
    </section>

    <section class="panel master-list-panel">
      <div class="panel-head">
        <div><div class="panel-title">{{ activeConfig.label }}</div><div class="panel-desc">统一维护编码、状态及业务关联信息</div></div>
        <div class="master-toolbar">
          <input v-model="keyword" class="input" placeholder="搜索当前分类..." />
          <button class="btn btn-primary" @click="openCreate(activeTab)">＋ 新增{{ activeConfig.singular }}</button>
        </div>
      </div>
      <div class="panel-body">
        <div class="master-list-summary"><span>当前分类 <strong>{{ activeItems.length }}</strong> 条</span><span>数据更新后自动同步</span></div>

        <div v-if="activeTab === 'site'" class="table-wrap">
          <table><thead><tr><th>编码</th><th>名称</th><th>位置</th><th>创建时间</th><th>操作</th></tr></thead><tbody><tr v-for="item in activeItems" :key="item.id"><td class="mono cell-main">{{ item.code }}</td><td>{{ item.name }}</td><td>{{ item.location || '--' }}</td><td class="small">{{ formatDateTime(item.created_at) }}</td><td><button class="btn btn-sm" @click="openEdit('site', item)">编辑</button></td></tr><tr v-if="!activeItems.length"><td colspan="5"><div class="empty">暂无站点</div></td></tr></tbody></table>
        </div>

        <div v-else-if="activeTab === 'product'" class="table-wrap">
          <table><thead><tr><th>编码</th><th>名称</th><th>规格</th><th>单位</th><th>创建时间</th><th>操作</th></tr></thead><tbody><tr v-for="item in activeItems" :key="item.id"><td class="mono cell-main">{{ item.code }}</td><td>{{ item.name }}</td><td>{{ item.specification || '--' }}</td><td>{{ item.unit }}</td><td class="small">{{ formatDateTime(item.created_at) }}</td><td><button class="btn btn-sm" @click="openEdit('product', item)">编辑</button></td></tr><tr v-if="!activeItems.length"><td colspan="6"><div class="empty">暂无产品</div></td></tr></tbody></table>
        </div>

        <div v-else-if="activeTab === 'equipment'" class="table-wrap">
          <table><thead><tr><th>设备编号</th><th>名称</th><th>类型</th><th>所属站点</th><th>状态</th><th>最后诊断</th><th>操作</th></tr></thead><tbody><tr v-for="item in activeItems" :key="item.id"><td class="mono cell-main">{{ item.code }}</td><td>{{ item.name || '--' }}</td><td>{{ item.equipment_type || '--' }}</td><td>{{ item.site_detail?.name || '--' }}</td><td><span class="tag">{{ item.status_display }}</span></td><td class="small">{{ formatDateTime(item.last_seen_at) }}</td><td><button class="btn btn-sm" @click="openEdit('equipment', item)">编辑</button></td></tr><tr v-if="!activeItems.length"><td colspan="7"><div class="empty">暂无设备</div></td></tr></tbody></table>
        </div>

        <div v-else class="table-wrap">
          <table><thead><tr><th>所属站点</th><th>名称</th><th>工作日</th><th>班次</th><th>状态</th><th>操作</th></tr></thead><tbody><tr v-for="item in activeItems" :key="item.id"><td>{{ item.site_detail?.name || '--' }}</td><td class="cell-main">{{ item.name }}</td><td>{{ weekdaysText(item.weekdays) }}</td><td class="mono">{{ item.shift_start }} - {{ item.shift_end }}</td><td><span class="tag">{{ item.is_active ? '启用' : '停用' }}</span></td><td><button class="btn btn-sm" @click="openEdit('calendar', item)">编辑</button></td></tr><tr v-if="!activeItems.length"><td colspan="6"><div class="empty">暂无班次日历</div></td></tr></tbody></table>
        </div>
      </div>
    </section>

    <div v-if="drawerOpen" class="master-drawer-scrim" @click="closeDrawer"></div>
    <aside v-if="drawerOpen" class="panel master-drawer">
      <div class="panel-head">
        <div><div class="panel-title">{{ editingId ? '编辑' : '新增' }}{{ tabConfig[drawerKind].singular }}</div><div class="panel-desc">保存后会立即刷新主数据列表</div></div>
        <button class="master-drawer-close" aria-label="关闭" @click="closeDrawer">×</button>
      </div>
      <div class="panel-body">
        <div v-if="drawerKind === 'site'" class="drawer-form">
          <div class="field"><label>站点编码</label><input v-model="siteForm.code" class="input" placeholder="例如 SITE-01" /></div>
          <div class="field"><label>站点名称</label><input v-model="siteForm.name" class="input" placeholder="例如 一号制造车间" /></div>
          <div class="field"><label>位置</label><input v-model="siteForm.location" class="input" /></div>
        </div>
        <div v-else-if="drawerKind === 'product'" class="drawer-form">
          <div class="field"><label>产品编码</label><input v-model="productForm.code" class="input" /></div>
          <div class="field"><label>产品名称</label><input v-model="productForm.name" class="input" /></div>
          <div class="field"><label>规格</label><input v-model="productForm.specification" class="input" /></div>
          <div class="field"><label>单位</label><input v-model="productForm.unit" class="input" /></div>
        </div>
        <div v-else-if="drawerKind === 'equipment'" class="drawer-form">
          <div class="field"><label>设备编号</label><input v-model="equipmentForm.code" class="input" /></div>
          <div class="field"><label>设备名称</label><input v-model="equipmentForm.name" class="input" /></div>
          <div class="field"><label>设备类型</label><input v-model="equipmentForm.equipment_type" class="input" /></div>
          <div class="field"><label>所属站点</label><select v-model="equipmentForm.site" class="select"><option v-for="site in data.sites" :key="site.id" :value="site.id">{{ site.name }}</option></select></div>
        </div>
        <div v-else class="drawer-form">
          <div class="field"><label>所属站点</label><select v-model="calendarForm.site" class="select"><option v-for="site in data.sites" :key="site.id" :value="site.id">{{ site.name }}</option></select></div>
          <div class="field"><label>日历名称</label><input v-model="calendarForm.name" class="input" /></div>
          <div class="drawer-time-grid"><div class="field"><label>班次开始</label><input v-model="calendarForm.shift_start" type="time" class="input" /></div><div class="field"><label>班次结束</label><input v-model="calendarForm.shift_end" type="time" class="input" /></div></div>
          <div class="field"><label>工作日</label><div class="weekday-picker"><button v-for="day in [{value:1,label:'周一'},{value:2,label:'周二'},{value:3,label:'周三'},{value:4,label:'周四'},{value:5,label:'周五'},{value:6,label:'周六'},{value:7,label:'周日'}]" :key="day.value" type="button" :class="{ active: calendarForm.weekdays.includes(day.value) }" @click="toggleWeekday(day.value)">{{ day.label }}</button></div></div>
        </div>
      </div>
      <div class="master-drawer-foot">
        <button class="btn" @click="closeDrawer">取消</button>
        <button class="btn btn-primary" :disabled="busy" @click="create(drawerKind)">{{ busy ? '保存中...' : editingId ? '保存修改' : '新增记录' }}</button>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.master-page { display: grid; gap: 15px; }
.master-tab-panel { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; padding: 10px; }
.master-tab {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 13px;
  border: 1px solid transparent;
  border-radius: 11px;
  color: #60736d;
  cursor: pointer;
  transition: border-color 150ms ease, background 150ms ease, box-shadow 150ms ease;
}
.master-tab:hover { background: #f6faf8; }
.master-tab.active {
  border-color: rgba(14, 135, 146, 0.2);
  color: #1c5653;
  background: linear-gradient(145deg, #f1faf7, #ffffff);
  box-shadow: 0 4px 13px rgba(20, 45, 54, 0.06);
}
.master-tab-icon {
  width: 33px;
  height: 33px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  border-radius: 9px;
  color: var(--cyan);
  background: #eaf6f2;
  font-size: 14px;
}
.master-tab > div { display: grid; gap: 2px; min-width: 0; }
.master-tab strong { color: inherit; font-size: 11px; }
.master-tab small { color: #8a9893; font-size: 8.5px; }
.master-toolbar { display: flex; align-items: center; gap: 8px; }
.master-toolbar .input { width: 220px; }
.master-list-summary { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; color: #7d8c87; font-size: 9px; }
.master-list-summary strong { color: #29474c; }
.master-drawer-scrim { position: fixed; inset: 0; z-index: 110; background: rgba(5, 22, 29, 0.42); backdrop-filter: blur(2px); }
.master-drawer {
  position: fixed;
  z-index: 120;
  top: 12px;
  right: 12px;
  bottom: 12px;
  width: min(390px, calc(100vw - 24px));
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 24px 70px rgba(5, 25, 31, 0.25);
  animation: drawer-in 180ms ease-out;
}
@keyframes drawer-in { from { opacity: 0; transform: translateX(18px); } }
.master-drawer > .panel-head { min-height: 72px; flex: 0 0 auto; padding-right: 48px; }
.master-drawer > .panel-body { flex: 1; min-height: 0; overflow-y: auto; }
.master-drawer-close {
  position: absolute;
  top: 15px;
  right: 15px;
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  padding: 0;
  border: 1px solid #d8e2de;
  border-radius: 8px;
  color: #667a73;
  background: #fff;
  font-size: 18px;
}
.drawer-form { display: grid; gap: 13px; }
.drawer-time-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.master-drawer-foot {
  flex: 0 0 auto;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 13px 17px;
  border-top: 1px solid #e2e9e6;
  background: #fbfcfb;
}
.master-drawer-foot .btn-primary { min-width: 105px; }
.weekday-picker { display: flex; gap: 6px; flex-wrap: wrap; }
.weekday-picker button { padding: 7px 10px; border: 1px solid var(--line); border-radius: 8px; background: #fff; color: var(--muted); font-size: 10px; }
.weekday-picker button.active { border-color: var(--cyan); background: #eaf7f5; color: var(--cyan); font-weight: 700; }
@media (max-width: 1080px) {
  .master-tab-panel { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 760px) {
  .master-list-panel > .panel-head { align-items: stretch; flex-direction: column; }
  .master-toolbar { width: 100%; align-items: stretch; flex-direction: column; }
  .master-toolbar .input { width: 100%; }
  .master-drawer { top: 8px; right: 8px; bottom: 8px; width: calc(100vw - 16px); }
  .drawer-time-grid { grid-template-columns: minmax(0, 1fr); }
}
</style>
