import { createRouter, createWebHashHistory } from 'vue-router'
import AgvView from './views/AgvView.vue'
import AlertCenterView from './views/AlertCenterView.vue'
import CommandCenterView from './views/CommandCenterView.vue'
import WorkbenchView from './views/WorkbenchView.vue'
import PortalView from './views/PortalView.vue'
import DispatchView from './views/DispatchView.vue'
import EquipmentView from './views/EquipmentView.vue'
import ForecastView from './views/ForecastView.vue'
import MapView from './views/MapView.vue'
import MasterDataView from './views/MasterDataView.vue'
import ProductionPlanView from './views/ProductionPlanView.vue'
import TaskView from './views/TaskView.vue'
import VisionView from './views/VisionView.vue'
import WorkOrderView from './views/WorkOrderView.vue'

const routes = [
  { path: '/', redirect: '/workbench' },
  { path: '/workbench', name: 'workbench', component: PortalView, meta: { title: '工作台' } },
  { path: '/dashboard', name: 'dashboard', component: CommandCenterView, meta: { title: '生产总览' } },
  { path: '/work-orders', name: 'work-orders', component: WorkOrderView, meta: { title: '生产工单' } },
  { path: '/alerts', name: 'alerts', component: AlertCenterView, meta: { title: '告警中心' } },
  { path: '/dispatch', name: 'dispatch', component: DispatchView, meta: { title: '调度中心' } },
  { path: '/tasks', name: 'tasks', component: TaskView, meta: { title: '运输任务' } },
  { path: '/map', name: 'map', component: MapView, meta: { title: '地图监控' } },
  { path: '/plans', name: 'plans', component: ProductionPlanView, meta: { title: '生产计划' } },
  { path: '/agvs', name: 'agvs', component: AgvView, meta: { title: 'AGV 管理' } },
  { path: '/equipment', name: 'equipment', component: EquipmentView, meta: { title: '设备监测' } },
  { path: '/vision', name: 'vision', component: VisionView, meta: { title: '视觉质检' } },
  { path: '/forecast', name: 'forecast', component: ForecastView, meta: { title: '订单预测' } },
  { path: '/master-data', name: 'master-data', component: MasterDataView, meta: { title: '主数据管理' } },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.afterEach((to) => {
  document.title = `${to.meta.title || '运营平台'} · AGV 制造运营系统`
})

export default router
