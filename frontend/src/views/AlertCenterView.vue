<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api } from '../api'

const emit = defineEmits(['notify'])
const route = useRoute()
const router = useRouter()
const alerts = ref([])
const loading = ref(false)
const busy = ref('')
const lastUpdated = ref('')
const filters = reactive({ status: '', severity: '', source_type: '' })
const openCount = computed(() => alerts.value.filter((item) => item.status !== 'resolved').length)
const criticalCount = computed(() => alerts.value.filter((item) => item.severity === 'critical' && item.status !== 'resolved').length)
const resolvedCount = computed(() => alerts.value.filter((item) => item.status === 'resolved').length)
const hasActiveFilters = computed(() => Object.values(filters).some(Boolean))
const healthyEmpty = computed(() => !loading.value && !hasActiveFilters.value && alerts.value.length === 0)
const selectedId = computed(() => Number(route.query.alert) || null)
const selectedAlert = computed(() => alerts.value.find((item) => item.id === selectedId.value) || null)

function formatTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '--'
}

function queryString() {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([key, value]) => {
    if (value) params.set(key, value)
  })
  const text = params.toString()
  return text ? `?${text}` : ''
}

async function load() {
  loading.value = true
  try {
    alerts.value = await api.alerts(queryString())
    lastUpdated.value = new Date().toISOString()
    if (
      window.matchMedia('(min-width: 981px)').matches
      && alerts.value.length
      && !alerts.value.some((item) => item.id === selectedId.value)
    ) {
      await router.replace({ path: '/alerts', query: { alert: alerts.value[0].id } })
    }
  } catch (error) {
    emit('notify', { message: `告警加载失败：${error.message}`, type: 'error' })
  } finally {
    loading.value = false
  }
}

async function handle(alert, action) {
  busy.value = `${alert.id}-${action}`
  try {
    await api.alertAction(alert.id, action)
    emit('notify', { message: action === 'resolve' ? '告警已解决' : '告警已确认' })
    await load()
  } catch (error) {
    emit('notify', { message: error.message, type: 'error' })
  } finally {
    busy.value = ''
  }
}

function backToQueue() {
  router.push({ path: '/alerts' })
}

onMounted(load)
</script>

<template>
  <div class="alert-workspace" :class="{ 'has-selection': selectedAlert, 'healthy-empty': healthyEmpty }">
    <aside class="panel alert-queue-panel">
      <div class="panel-head">
        <div>
          <div class="panel-title">运营异常队列</div>
          <div class="panel-desc">优先处理影响生产和交付的异常</div>
        </div>
        <button class="btn btn-sm" :disabled="loading" @click="load">{{ loading ? '加载中' : '刷新' }}</button>
      </div>
      <div class="panel-body">
        <div class="alert-queue-stats">
          <span><strong>{{ openCount }}</strong> 未解决</span>
          <span class="critical"><strong>{{ criticalCount }}</strong> 严重</span>
        </div>
        <div class="alert-filters">
          <select v-model="filters.status" class="select" @change="load"><option value="">全部状态</option><option value="open">待处理</option><option value="acknowledged">已确认</option><option value="resolved">已解决</option></select>
          <select v-model="filters.severity" class="select" @change="load"><option value="">全部级别</option><option value="critical">严重</option><option value="warning">警告</option><option value="info">提示</option></select>
          <select v-model="filters.source_type" class="select" @change="load"><option value="">全部来源</option><option value="equipment">设备</option><option value="quality">质量</option><option value="agv">AGV</option><option value="deadline">交期</option><option value="system">系统</option></select>
        </div>
        <div class="alert-queue">
          <RouterLink
            v-for="alert in alerts"
            :key="alert.id"
            class="alert-queue-item"
            :class="[`severity-${alert.severity}`, { active: selectedId === alert.id }]"
            :to="{ path: '/alerts', query: { alert: alert.id } }"
          >
            <div class="alert-item-head">
              <span class="severity-pill" :class="`severity-${alert.severity}`">{{ alert.severity_display }}</span>
              <span class="alert-item-source">{{ alert.source_type_display }}</span>
              <span class="alert-item-time">{{ formatTime(alert.created_at) }}</span>
            </div>
            <strong>{{ alert.title }}</strong>
            <p>{{ alert.message }}</p>
            <div class="alert-item-foot">
              <span>{{ alert.status_display }}</span>
              <span v-if="alert.work_order_no">{{ alert.work_order_no }}</span>
              <span v-if="alert.equipment_code">{{ alert.equipment_code }}</span>
            </div>
          </RouterLink>
          <div v-if="!alerts.length" class="empty">没有符合筛选条件的告警</div>
        </div>
      </div>
    </aside>

    <section v-if="selectedAlert" class="panel alert-detail-panel" :class="`detail-${selectedAlert.severity}`">
      <div class="panel-head">
        <div class="alert-detail-title">
          <span class="severity-pill" :class="`severity-${selectedAlert.severity}`">{{ selectedAlert.severity_display }}</span>
          <div><div class="panel-title">{{ selectedAlert.title }}</div><div class="panel-desc">{{ selectedAlert.source_type_display }} · {{ selectedAlert.status_display }}</div></div>
        </div>
        <div class="toolbar-right">
          <button class="btn btn-sm alert-mobile-back" @click="backToQueue">← 返回队列</button>
          <button v-if="selectedAlert.status === 'open'" class="btn btn-sm" :disabled="busy === `${selectedAlert.id}-acknowledge`" @click="handle(selectedAlert, 'acknowledge')">确认告警</button>
          <button v-if="selectedAlert.status !== 'resolved'" class="btn btn-sm btn-primary" :disabled="busy === `${selectedAlert.id}-resolve`" @click="handle(selectedAlert, 'resolve')">标记解决</button>
          <span v-else class="muted small">此告警已关闭</span>
        </div>
      </div>
      <div class="panel-body">
        <div class="alert-message-card">
          <span class="alert-message-label">异常说明</span>
          <p>{{ selectedAlert.message }}</p>
        </div>
        <div class="alert-detail-grid">
          <div><span>告警级别</span><strong>{{ selectedAlert.severity_display }}</strong></div>
          <div><span>告警来源</span><strong>{{ selectedAlert.source_type_display }}</strong></div>
          <div><span>当前状态</span><strong>{{ selectedAlert.status_display }}</strong></div>
          <div><span>产生时间</span><strong>{{ formatTime(selectedAlert.created_at) }}</strong></div>
        </div>
        <section class="alert-linkage-panel">
          <div class="subpanel-title">关联业务对象</div>
          <div class="alert-linkage-list">
            <RouterLink v-if="selectedAlert.work_order" :to="{ path: '/work-orders', query: { work_order: selectedAlert.work_order } }">
              <span>生产工单</span><strong>{{ selectedAlert.work_order_no }}</strong><small>打开工单详情 →</small>
            </RouterLink>
            <div v-if="selectedAlert.equipment_code">
              <span>设备对象</span><strong>{{ selectedAlert.equipment_code }}</strong><small>设备诊断关联对象</small>
            </div>
            <div v-if="selectedAlert.resolved_by">
              <span>处理记录</span><strong>{{ selectedAlert.resolved_by }}</strong><small>告警已由该用户关闭</small>
            </div>
            <div v-if="!selectedAlert.work_order && !selectedAlert.equipment_code && !selectedAlert.resolved_by" class="empty">暂无关联业务对象</div>
          </div>
        </section>
        <div class="notice warning mt-16">
          <strong>处置建议</strong>
          <span v-if="selectedAlert.severity === 'critical'">严重告警可能影响生产连续性，建议优先检查关联设备、工单和当前运输任务。</span>
          <span v-else>确认异常影响范围后处理关联工单或设备，再将该告警标记为已解决。</span>
        </div>
      </div>
    </section>

    <section v-else-if="healthyEmpty" class="panel alert-health-panel">
      <div class="health-hero">
        <div class="health-orbit"><span>✓</span></div>
        <div class="health-copy">
          <div class="health-eyebrow">ALL CLEAR · 运行正常</div>
          <h2>当前没有待处理告警</h2>
          <p>设备、质量、AGV 和交期监测暂未发现需要人工处置的异常。</p>
        </div>
        <button class="btn btn-sm" :disabled="loading" @click="load">重新检查</button>
      </div>
      <div class="health-metrics">
        <div><span>未解决</span><strong>{{ openCount }}</strong><small>需要处理的告警</small></div>
        <div><span>严重告警</span><strong>{{ criticalCount }}</strong><small>高优先级异常</small></div>
        <div><span>已解决</span><strong>{{ resolvedCount }}</strong><small>已关闭的处理记录</small></div>
        <div><span>最近同步</span><strong>{{ formatTime(lastUpdated) }}</strong><small>系统持续监测中</small></div>
      </div>
      <div class="health-content-grid">
        <section class="health-monitor-panel">
          <div class="health-section-title">持续监测范围</div>
          <div class="health-monitor-links">
            <RouterLink to="/work-orders"><span>▤</span><div><strong>生产工单</strong><small>交期、工序与阻塞状态</small></div><em>查看 →</em></RouterLink>
            <RouterLink to="/equipment"><span>◈</span><div><strong>设备监测</strong><small>磨损、故障与传感器预警</small></div><em>查看 →</em></RouterLink>
            <RouterLink to="/vision"><span>◉</span><div><strong>视觉质检</strong><small>缺陷识别与质量异常</small></div><em>查看 →</em></RouterLink>
          </div>
        </section>
        <section class="health-guide-panel">
          <div class="health-section-title">告警处置流程</div>
          <ol class="health-flow">
            <li><span>01</span><div><strong>异常触发</strong><small>设备、质量或交期规则自动生成告警</small></div></li>
            <li><span>02</span><div><strong>确认影响</strong><small>检查关联工单、设备和生产任务</small></div></li>
            <li><span>03</span><div><strong>闭环处理</strong><small>解决异常并关闭告警记录</small></div></li>
          </ol>
        </section>
      </div>
    </section>
    <section v-else class="panel alert-detail-empty">
      <div class="alert-empty-visual">
        <span>◉</span>
        <strong>选择一条告警查看详情</strong>
        <p>左侧队列会展示告警级别、来源、状态与关联对象，在右侧完成确认和解决。</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.alert-workspace {
  display: grid;
  grid-template-columns: minmax(300px, 350px) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}
.alert-queue-panel {
  position: sticky;
  top: 18px;
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 36px);
  overflow: hidden;
}
.alert-queue-panel .panel-head { min-height: 68px; padding: 14px 15px 12px; }
.alert-queue-panel .panel-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 12px;
}
.alert-queue-stats {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 9px 11px;
  border: 1px solid #dfe8e4;
  border-radius: 10px;
  color: #72827d;
  background: #f8faf9;
  font-size: 9px;
}
.alert-queue-stats strong { color: #1e383f; font-size: 15px; margin-right: 3px; }
.alert-queue-stats .critical strong { color: var(--red); }
.alert-filters {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
  margin-top: 9px;
}
.alert-filters .select { min-height: 35px; font-size: 9.5px; }
.alert-filters .select:last-child { grid-column: 1 / -1; }
.alert-queue {
  flex: 1;
  min-height: 0;
  display: grid;
  align-content: start;
  gap: 7px;
  margin-top: 9px;
  overflow-y: auto;
  padding: 1px 3px 1px 1px;
  scrollbar-width: thin;
  scrollbar-color: rgba(92, 143, 136, 0.25) transparent;
}
.alert-queue-item {
  position: relative;
  display: grid;
  gap: 5px;
  overflow: hidden;
  padding: 10px 11px;
  border: 1px solid #dce6e1;
  border-radius: 11px;
  color: inherit;
  background: linear-gradient(145deg, #ffffff, #f9fbfa);
  text-decoration: none;
  transition: border-color 150ms ease, background 150ms ease, transform 150ms ease, box-shadow 150ms ease;
}
.alert-queue-item::before {
  content: "";
  position: absolute;
  inset: 8px auto 8px 0;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: transparent;
}
.alert-queue-item:hover {
  border-color: #b9cec7;
  background: #fff;
  box-shadow: 0 7px 18px rgba(20, 45, 54, 0.055);
  transform: translateY(-1px);
}
.alert-queue-item.active {
  border-color: rgba(14, 135, 146, 0.34);
  background: linear-gradient(90deg, rgba(14, 135, 146, 0.075), rgba(255, 255, 255, 0.82));
  box-shadow: 0 7px 18px rgba(14, 94, 95, 0.07);
}
.alert-queue-item.active::before { background: var(--cyan); }
.alert-queue-item.severity-critical::before { background: var(--red); }
.alert-queue-item.severity-warning::before { background: var(--amber); }
.alert-queue-item.severity-info::before { background: var(--blue); }
.alert-item-head,
.alert-item-foot { display: flex; align-items: center; gap: 7px; }
.alert-item-head { justify-content: flex-start; }
.alert-item-source { color: #637771; font-size: 8.5px; }
.alert-item-time { margin-left: auto; color: #94a09c; font-size: 8px; }
.alert-queue-item > strong { overflow: hidden; color: #20363e; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.alert-queue-item p {
  display: -webkit-box;
  overflow: hidden;
  margin: 0;
  color: #7b8984;
  font-size: 9px;
  line-height: 1.45;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
.alert-item-foot { color: #7a8984; font-size: 8.5px; }
.alert-item-foot span + span::before { content: "·"; margin-right: 7px; color: #c1cbc7; }
.severity-pill {
  display: inline-flex;
  align-items: center;
  padding: 3px 7px;
  border: 1px solid transparent;
  border-radius: 999px;
  font-size: 8.5px;
  font-weight: 720;
  background: #eef2f0;
  color: var(--muted);
  white-space: nowrap;
}
.severity-pill.severity-critical { color: var(--red); background: #fdeef0; border-color: #f2ccd1; }
.severity-pill.severity-warning { color: var(--amber); background: #fdf5e6; border-color: #eddbb2; }
.severity-pill.severity-info { color: var(--blue); background: #edf3ff; border-color: #d3e0f7; }
.alert-detail-panel {
  position: relative;
  min-width: 0;
  overflow: hidden;
}
.alert-detail-panel::before {
  content: "";
  position: absolute;
  inset: 0 0 auto;
  height: 3px;
  background: var(--cyan);
}
.alert-detail-panel.detail-critical::before { background: var(--red); }
.alert-detail-panel.detail-warning::before { background: var(--amber); }
.alert-detail-panel.detail-info::before { background: var(--blue); }
.alert-detail-title { display: flex; align-items: center; gap: 11px; min-width: 0; }
.toolbar-right { display: flex; gap: 7px; flex-wrap: wrap; align-items: center; }
.alert-message-card {
  padding: 16px 17px;
  border: 1px solid #dce7e2;
  border-radius: 13px;
  background:
    linear-gradient(rgba(55, 101, 96, 0.024) 1px, transparent 1px),
    linear-gradient(90deg, rgba(55, 101, 96, 0.024) 1px, transparent 1px),
    #f9fbfa;
  background-size: 24px 24px, 24px 24px, auto;
}
.alert-message-label { color: #7e8e88; font-size: 9px; font-weight: 750; letter-spacing: 0.08em; }
.alert-message-card p { margin: 8px 0 0; color: #344c53; font-size: 13px; line-height: 1.65; }
.alert-detail-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 9px;
  margin-top: 14px;
}
.alert-detail-grid > div {
  display: grid;
  gap: 4px;
  padding: 12px;
  border: 1px solid #dfe8e4;
  border-radius: 10px;
  background: #f8faf9;
}
.alert-detail-grid span { color: #7d8d87; font-size: 9px; }
.alert-detail-grid strong { color: #263e46; font-size: 11px; line-height: 1.4; }
.alert-linkage-panel {
  margin-top: 14px;
  padding: 15px;
  border: 1px solid #dfe8e4;
  border-radius: 12px;
  background: #fbfcfb;
}
.subpanel-title { color: var(--text); font-size: 12px; font-weight: 750; }
.alert-linkage-list { display: grid; gap: 7px; margin-top: 10px; }
.alert-linkage-list > a,
.alert-linkage-list > div:not(.empty) {
  display: grid;
  grid-template-columns: 100px minmax(0, 1fr) auto;
  gap: 9px;
  align-items: center;
  padding: 10px 11px;
  border: 1px solid #e0e8e4;
  border-radius: 9px;
  color: inherit;
  background: #fff;
  text-decoration: none;
}
.alert-linkage-list span { color: #7b8b86; font-size: 9px; }
.alert-linkage-list strong { color: #24434a; font-size: 10.5px; }
.alert-linkage-list small { color: var(--cyan); font-size: 8.5px; }
.alert-linkage-list > a:hover { border-color: #a9cbc4; background: #f6fbf9; }
.alert-workspace.healthy-empty { grid-template-columns: minmax(0, 1fr); }
.alert-workspace.healthy-empty .alert-queue-panel { display: none; }
.alert-health-panel {
  position: relative;
  min-height: 520px;
  overflow: hidden;
  padding: 26px;
  background:
    linear-gradient(rgba(46, 106, 98, 0.024) 1px, transparent 1px),
    linear-gradient(90deg, rgba(46, 106, 98, 0.024) 1px, transparent 1px),
    radial-gradient(circle at 78% 8%, rgba(49, 180, 159, 0.1), transparent 30%),
    linear-gradient(145deg, #ffffff, #f7fbf9);
  background-size: 28px 28px, 28px 28px, auto, auto;
}
.alert-health-panel::after {
  content: "";
  position: absolute;
  top: -130px;
  right: -80px;
  width: 340px;
  height: 340px;
  border: 1px solid rgba(35, 155, 141, 0.1);
  border-radius: 50%;
  box-shadow: 0 0 0 28px rgba(35, 155, 141, 0.018), 0 0 0 62px rgba(35, 155, 141, 0.012);
  pointer-events: none;
}
.health-hero {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: 66px minmax(0, 1fr) auto;
  gap: 17px;
  align-items: center;
  padding: 18px 20px;
  border: 1px solid #d8e7e1;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.76);
  box-shadow: 0 10px 30px rgba(20, 45, 54, 0.045);
  backdrop-filter: blur(8px);
}
.health-orbit {
  position: relative;
  width: 62px;
  height: 62px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(45, 174, 144, 0.2);
  border-radius: 50%;
  background: radial-gradient(circle, #effaf5 40%, #e4f6ef 100%);
  box-shadow: 0 0 0 8px rgba(46, 174, 144, 0.045);
}
.health-orbit::before {
  content: "";
  position: absolute;
  inset: 7px;
  border: 1px dashed rgba(45, 174, 144, 0.25);
  border-radius: 50%;
  animation: health-spin 9s linear infinite;
}
.health-orbit span {
  width: 31px;
  height: 31px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  color: #ffffff;
  background: linear-gradient(145deg, #44c699, #219878);
  box-shadow: 0 5px 12px rgba(33, 152, 120, 0.23);
  font-size: 15px;
  font-weight: 850;
}
@keyframes health-spin { to { transform: rotate(360deg); } }
.health-copy { min-width: 0; }
.health-eyebrow { color: #2c967b; font-size: 8px; font-weight: 800; letter-spacing: 0.14em; }
.health-copy h2 { margin: 5px 0 5px; color: #17343b; font-size: 19px; letter-spacing: -0.025em; }
.health-copy p { margin: 0; color: #788884; font-size: 10px; line-height: 1.6; }
.health-metrics {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}
.health-metrics > div {
  display: grid;
  gap: 4px;
  padding: 14px 15px;
  border: 1px solid #dde7e3;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.82);
}
.health-metrics span { color: #7b8b86; font-size: 9px; }
.health-metrics strong { color: #203a41; font-size: 16px; line-height: 1.25; }
.health-metrics small { color: #96a19d; font-size: 8px; }
.health-content-grid {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(260px, 0.75fr);
  gap: 12px;
  margin-top: 14px;
}
.health-monitor-panel,
.health-guide-panel {
  padding: 16px;
  border: 1px solid #dde7e3;
  border-radius: 13px;
  background: rgba(255, 255, 255, 0.78);
}
.health-section-title { color: #314a50; font-size: 11px; font-weight: 780; }
.health-monitor-links { display: grid; gap: 7px; margin-top: 11px; }
.health-monitor-links a {
  display: grid;
  grid-template-columns: 31px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 10px 11px;
  border: 1px solid #e1e9e5;
  border-radius: 9px;
  color: inherit;
  background: rgba(248, 251, 249, 0.86);
  text-decoration: none;
  transition: border-color 150ms ease, background 150ms ease, transform 150ms ease;
}
.health-monitor-links a:hover { border-color: #afd0c7; background: #fff; transform: translateX(2px); }
.health-monitor-links > a > span {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  color: var(--cyan);
  background: #eaf6f2;
  font-size: 13px;
}
.health-monitor-links div { display: grid; gap: 2px; }
.health-monitor-links strong { color: #28444a; font-size: 10.5px; }
.health-monitor-links small { color: #899691; font-size: 8.5px; }
.health-monitor-links em { color: #4b7c78; font-size: 8.5px; font-style: normal; }
.health-flow { display: grid; gap: 9px; margin: 11px 0 0; padding: 0; list-style: none; }
.health-flow li { display: grid; grid-template-columns: 28px minmax(0, 1fr); gap: 9px; align-items: start; }
.health-flow li > span {
  width: 27px;
  height: 27px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  color: #2d8170;
  background: #e9f6f1;
  font-family: "Cascadia Mono", Consolas, monospace;
  font-size: 8px;
  font-weight: 800;
}
.health-flow div { display: grid; gap: 2px; }
.health-flow strong { color: #30494f; font-size: 10px; }
.health-flow small { color: #8a9793; font-size: 8.5px; line-height: 1.45; }
.alert-detail-empty {
  min-height: 440px;
  display: grid;
  place-items: center;
  background: radial-gradient(circle at center, rgba(14, 135, 146, 0.055), transparent 38%), #fff;
}
.alert-empty-visual { max-width: 330px; display: grid; justify-items: center; gap: 9px; padding: 28px; text-align: center; }
.alert-empty-visual > span {
  width: 54px;
  height: 54px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(14, 135, 146, 0.15);
  border-radius: 16px;
  color: var(--cyan);
  background: #f1f8f6;
  font-size: 24px;
}
.alert-empty-visual strong { color: #244049; font-size: 14px; }
.alert-empty-visual p { margin: 0; color: var(--muted); font-size: 10px; line-height: 1.65; }
.alert-mobile-back { display: none; }
.notice { display: flex; align-items: flex-start; gap: 9px; padding: 11px 13px; border: 1px solid #eddbb2; border-radius: 10px; color: #765b24; background: #fff9ec; font-size: 10px; line-height: 1.55; }
.notice strong { color: #5f4819; white-space: nowrap; }
@media (max-width: 980px) {
  .alert-workspace { grid-template-columns: minmax(0, 1fr); }
  .alert-queue-panel { position: static; max-height: none; }
  .alert-queue { max-height: 440px; }
  .alert-workspace.has-selection .alert-queue-panel { display: none; }
  .alert-mobile-back { display: inline-flex; }
  .health-content-grid { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 760px) {
  .alert-detail-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .alert-detail-panel > .panel-head { align-items: flex-start; flex-direction: column; }
  .alert-detail-panel > .panel-head .toolbar-right { width: 100%; justify-content: flex-start; }
  .alert-linkage-list > a,
  .alert-linkage-list > div:not(.empty) { grid-template-columns: 82px minmax(0, 1fr); }
  .alert-linkage-list small { grid-column: 1 / -1; }
  .alert-health-panel { min-height: 0; padding: 16px; }
  .health-hero { grid-template-columns: 52px minmax(0, 1fr); padding: 15px; }
  .health-orbit { width: 50px; height: 50px; }
  .health-hero > .btn { grid-column: 1 / -1; }
  .health-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .health-copy h2 { font-size: 17px; }
}
</style>
