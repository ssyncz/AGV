<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'

const emit = defineEmits(['notify'])
const data = ref({ sites: [], products: [], equipment: [], work_calendars: [] })
const busy = ref('')
const siteForm = reactive({ code: '', name: '', location: '' })
const productForm = reactive({ code: '', name: '', specification: '', unit: '件' })
const equipmentForm = reactive({ code: '', name: '', equipment_type: '', site: '' })
const calendarForm = reactive({
  site: '', name: '默认白班', weekdays: [1, 2, 3, 4, 5],
  shift_start: '08:00', shift_end: '18:00',
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

async function create(kind) {
  busy.value = kind
  try {
    if (kind === 'site') {
      await api.createSite(siteForm)
      Object.assign(siteForm, { code: '', name: '', location: '' })
    } else if (kind === 'product') {
      await api.createProduct(productForm)
      Object.assign(productForm, { code: '', name: '', specification: '', unit: '件' })
    } else if (kind === 'equipment') {
      await api.createEquipment({ ...equipmentForm, site: equipmentForm.site || null })
      Object.assign(equipmentForm, { code: '', name: '', equipment_type: '', site: data.value.sites?.[0]?.id || '' })
    } else {
      await api.createWorkCalendar(calendarForm)
      Object.assign(calendarForm, {
        site: data.value.sites?.[0]?.id || '', name: '默认白班',
        weekdays: [1, 2, 3, 4, 5], shift_start: '08:00', shift_end: '18:00',
      })
    }
    emit('notify', { message: '主数据已新增' })
    await load()
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

onMounted(load)
</script>

<template>
  <div class="master-grid">
    <section class="panel">
      <div class="panel-head"><div><div class="panel-title">业务站点</div><div class="panel-desc">工厂、车间或仓库的统一编码</div></div></div>
      <div class="panel-body">
        <div class="form-grid compact"><div class="field"><label>编码</label><input v-model="siteForm.code" class="input" /></div><div class="field"><label>名称</label><input v-model="siteForm.name" class="input" /></div><div class="field full"><label>位置</label><input v-model="siteForm.location" class="input" /></div></div>
        <button class="btn btn-primary btn-block mt-12" :disabled="busy === 'site'" @click="create('site')">新增站点</button>
        <div class="table-wrap mt-16"><table><thead><tr><th>编码</th><th>名称</th><th>位置</th></tr></thead><tbody><tr v-for="item in data.sites" :key="item.id"><td class="mono">{{ item.code }}</td><td>{{ item.name }}</td><td>{{ item.location || '--' }}</td></tr><tr v-if="!data.sites.length"><td colspan="3"><div class="empty">暂无站点</div></td></tr></tbody></table></div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head"><div><div class="panel-title">产品主数据</div><div class="panel-desc">工单和质检追溯使用的产品档案</div></div></div>
      <div class="panel-body">
        <div class="form-grid compact"><div class="field"><label>编码</label><input v-model="productForm.code" class="input" /></div><div class="field"><label>名称</label><input v-model="productForm.name" class="input" /></div><div class="field"><label>规格</label><input v-model="productForm.specification" class="input" /></div><div class="field"><label>单位</label><input v-model="productForm.unit" class="input" /></div></div>
        <button class="btn btn-primary btn-block mt-12" :disabled="busy === 'product'" @click="create('product')">新增产品</button>
        <div class="table-wrap mt-16"><table><thead><tr><th>编码</th><th>名称</th><th>规格</th><th>单位</th></tr></thead><tbody><tr v-for="item in data.products" :key="item.id"><td class="mono">{{ item.code }}</td><td>{{ item.name }}</td><td>{{ item.specification || '--' }}</td><td>{{ item.unit }}</td></tr><tr v-if="!data.products.length"><td colspan="4"><div class="empty">暂无产品</div></td></tr></tbody></table></div>
      </div>
    </section>

    <section class="panel master-wide">
      <div class="panel-head"><div><div class="panel-title">设备主数据</div><div class="panel-desc">设备诊断和异常告警统一关联设备档案</div></div></div>
      <div class="panel-body">
        <div class="form-grid"><div class="field"><label>设备编号</label><input v-model="equipmentForm.code" class="input" /></div><div class="field"><label>设备名称</label><input v-model="equipmentForm.name" class="input" /></div><div class="field"><label>设备类型</label><input v-model="equipmentForm.equipment_type" class="input" /></div><div class="field"><label>所属站点</label><select v-model="equipmentForm.site" class="select"><option v-for="site in data.sites" :key="site.id" :value="site.id">{{ site.name }}</option></select></div></div>
        <button class="btn btn-primary mt-12" :disabled="busy === 'equipment'" @click="create('equipment')">新增设备</button>
        <div class="table-wrap mt-16"><table><thead><tr><th>设备编号</th><th>名称</th><th>类型</th><th>站点</th><th>状态</th><th>最后诊断</th></tr></thead><tbody><tr v-for="item in data.equipment" :key="item.id"><td class="mono">{{ item.code }}</td><td>{{ item.name || '--' }}</td><td>{{ item.equipment_type || '--' }}</td><td>{{ item.site_detail?.name || '--' }}</td><td><span class="tag">{{ item.status_display }}</span></td><td class="small">{{ item.last_seen_at ? new Date(item.last_seen_at).toLocaleString('zh-CN', { hour12: false }) : '--' }}</td></tr><tr v-if="!data.equipment.length"><td colspan="6"><div class="empty">暂无设备</div></td></tr></tbody></table></div>
      </div>
    </section>

    <section class="panel master-wide">
      <div class="panel-head"><div><div class="panel-title">班次日历</div><div class="panel-desc">工序计划时间使用站点班次窗口，支持选择工作日和起止时间</div></div></div>
      <div class="panel-body">
        <div class="form-grid">
          <div class="field"><label>所属站点</label><select v-model="calendarForm.site" class="select"><option v-for="site in data.sites" :key="site.id" :value="site.id">{{ site.name }}</option></select></div>
          <div class="field"><label>日历名称</label><input v-model="calendarForm.name" class="input" /></div>
          <div class="field"><label>班次开始</label><input v-model="calendarForm.shift_start" type="time" class="input" /></div>
          <div class="field"><label>班次结束</label><input v-model="calendarForm.shift_end" type="time" class="input" /></div>
          <div class="field full">
            <label>工作日</label>
            <div class="weekday-picker">
              <button v-for="day in [{value:1,label:'周一'},{value:2,label:'周二'},{value:3,label:'周三'},{value:4,label:'周四'},{value:5,label:'周五'},{value:6,label:'周六'},{value:7,label:'周日'}]" :key="day.value" type="button" :class="{ active: calendarForm.weekdays.includes(day.value) }" @click="toggleWeekday(day.value)">{{ day.label }}</button>
            </div>
          </div>
        </div>
        <button class="btn btn-primary mt-12" :disabled="busy === 'calendar'" @click="create('calendar')">新增班次日历</button>
        <div class="table-wrap mt-16"><table><thead><tr><th>站点</th><th>名称</th><th>工作日</th><th>班次</th></tr></thead><tbody><tr v-for="item in data.work_calendars" :key="item.id"><td>{{ item.site_detail?.name || '--' }}</td><td>{{ item.name }}</td><td>{{ item.weekdays.join(', ') }}</td><td>{{ item.shift_start }} - {{ item.shift_end }}</td></tr><tr v-if="!data.work_calendars?.length"><td colspan="4"><div class="empty">暂无班次日历</div></td></tr></tbody></table></div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.master-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; align-items: start; }
.master-wide { grid-column: 1 / -1; }
.form-grid.compact { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.weekday-picker { display: flex; gap: 6px; flex-wrap: wrap; }
.weekday-picker button { padding: 6px 10px; border: 1px solid var(--line); border-radius: 8px; background: #fff; color: var(--muted); font-size: 10px; }
.weekday-picker button.active { border-color: var(--cyan); background: #eaf7f5; color: var(--cyan); font-weight: 700; }
@media (max-width: 900px) { .master-grid, .form-grid.compact { grid-template-columns: 1fr; } .master-wide { grid-column: auto; } }
</style>
