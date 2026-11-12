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
  { path: '/workbench', name: 'workbench', component: PortalView, meta: { title: '工作台', subtitle: '按功能快速进入各模块' } },
  { path: '/dashboard', name: 'dashboard', component: CommandCenterView, meta: { title: '生产总览', subtitle: '工单、车队、质量与设备异常的运营总览' } },
  { path: '/work-orders', name: 'work-orders', component: WorkOrderView, meta: { title: '生产工单', subtitle: '计划、运输、质检和设备异常的统一业务主线' } },
  { path: '/alerts', name: 'alerts', component: AlertCenterView, meta: { title: '告警中心', subtitle: '统一确认与处置设备、质量和交期异常' } },
  { path: '/dispatch', name: 'dispatch', component: DispatchView, meta: { title: '调度中心', subtitle: '单台智能调度与多台 AGV 协同调度' } },
  { path: '/tasks', name: 'tasks', component: TaskView, meta: { title: '运输任务', subtitle: '运输任务生命周期、路线与执行状态管理' } },
  { path: '/map', name: 'map', component: MapView, meta: { title: '地图监控', subtitle: '仓库拓扑、AGV 位置与实时规划路线' } },
  { path: '/plans', name: 'plans', component: ProductionPlanView, meta: { title: '生产计划', subtitle: '预测驱动的计划、排程与执行工单追踪' } },
  { path: '/agvs', name: 'agvs', component: AgvView, meta: { title: 'AGV 管理', subtitle: '车辆状态、电量、载重和位置管理' } },
  { path: '/equipment', name: 'equipment', component: EquipmentView, meta: { title: '设备监测', subtitle: '多变量传感器状态分类、磨损识别与规则告警' } },
  { path: '/vision', name: 'vision', component: VisionView, meta: { title: '视觉质检', subtitle: '裂纹检测、缺陷定位与分类，并关联生产工单' } },
  { path: '/forecast', name: 'forecast', component: ForecastView, meta: { title: '订单预测', subtitle: '需求预测、模型回测与生产计划生成' } },
  { path: '/master-data', name: 'master-data', component: MasterDataView, meta: { title: '主数据管理', subtitle: '站点、产品和设备的统一编码档案' } },
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
