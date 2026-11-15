import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class MapNode(models.Model):
    """仓库地图节点。"""

    class NodeType(models.TextChoices):
        PARKING = "parking", "停车点"
        PICKUP = "pickup", "取货点"
        DROPOFF = "dropoff", "放货点"
        CHARGING = "charging", "充电点"
        INTERSECTION = "intersection", "路径节点"

    code = models.CharField("节点编码", max_length=32, unique=True)
    name = models.CharField("节点名称", max_length=64)
    node_type = models.CharField(
        "节点类型", max_length=20, choices=NodeType.choices, default=NodeType.INTERSECTION
    )
    x = models.FloatField("X 坐标")
    y = models.FloatField("Y 坐标")
    is_active = models.BooleanField("启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "地图节点"
        verbose_name_plural = "地图节点"

    def __str__(self):
        return f"{self.code} - {self.name}"


class MapEdge(models.Model):
    """地图中两个节点之间的可通行道路。"""

    start_node = models.ForeignKey(
        MapNode, on_delete=models.CASCADE, related_name="outgoing_edges", verbose_name="起点"
    )
    end_node = models.ForeignKey(
        MapNode, on_delete=models.CASCADE, related_name="incoming_edges", verbose_name="终点"
    )
    distance = models.FloatField("距离(米)", validators=[MinValueValidator(0.1)])
    speed_limit = models.FloatField(
        "限速(米/秒)", default=1.2, validators=[MinValueValidator(0.1)]
    )
    bidirectional = models.BooleanField("双向通行", default=True)
    is_active = models.BooleanField("启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        ordering = ["start_node__code", "end_node__code"]
        constraints = [
            models.UniqueConstraint(fields=["start_node", "end_node"], name="uniq_edge_pair")
        ]
        verbose_name = "地图道路"
        verbose_name_plural = "地图道路"

    def __str__(self):
        return f"{self.start_node.code} -> {self.end_node.code} ({self.distance}m)"

class MapObstacle(models.Model):
    """地图中的不可通行障碍区域。"""

    code = models.CharField("障碍物编码", max_length=32, unique=True)
    name = models.CharField("障碍物名称", max_length=64, blank=True)
    x = models.FloatField("X 坐标")
    y = models.FloatField("Y 坐标")
    width = models.FloatField("宽度", default=1)
    height = models.FloatField("高度", default=1)
    is_active = models.BooleanField("启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "地图障碍物"
        verbose_name_plural = "地图障碍物"

    def __str__(self):
        return f"{self.code} ({self.x}, {self.y})"

class AGV(models.Model):
    class Status(models.TextChoices):
        IDLE = "idle", "空闲"
        BUSY = "busy", "执行任务"
        CHARGING = "charging", "充电中"
        OFFLINE = "offline", "离线"
        ERROR = "error", "故障"

    code = models.CharField("AGV 编号", max_length=32, unique=True)
    name = models.CharField("名称", max_length=64)
    model_name = models.CharField("型号", max_length=64, blank=True)
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.IDLE)
    current_node = models.ForeignKey(
        MapNode,
        on_delete=models.PROTECT,
        related_name="agvs",
        verbose_name="当前位置",
    )
    battery_percent = models.FloatField(
        "电量(%)", default=100, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    payload_capacity = models.FloatField(
        "额定载重(kg)", default=100, validators=[MinValueValidator(0.1)]
    )
    speed = models.FloatField("速度(米/秒)", default=1.0, validators=[MinValueValidator(0.1)])
    last_heartbeat = models.DateTimeField("最后心跳", auto_now=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "AGV"
        verbose_name_plural = "AGV"

    def __str__(self):
        return f"{self.code} - {self.name}"


class ProductionPlan(models.Model):
    """由需求预测生成的一批生产运输计划。

    计划把预测期的订单量转成运输任务，并保存转换参数和假设，保证调度结果可追溯。
    """

    class Status(models.TextChoices):
        PLANNED = "planned", "已生成"
        SCHEDULED = "scheduled", "已排程"
        COMPLETED = "completed", "已完成"
        CANCELLED = "cancelled", "已取消"

    plan_no = models.CharField("计划编号", max_length=32, unique=True)
    name = models.CharField("计划名称", max_length=128)
    forecast_run = models.ForeignKey(
        "DemandForecast.DemandForecastRun",
        on_delete=models.PROTECT,
        related_name="production_plans",
        verbose_name="预测记录",
    )
    work_order = models.ForeignKey(
        "Operations.WorkOrder",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="production_plans",
        verbose_name="执行工单",
    )
    status = models.CharField(
        "状态", max_length=16, choices=Status.choices, default=Status.PLANNED
    )
    planning_start = models.DateField("计划开始日期")
    planning_end = models.DateField("计划结束日期")
    tasks_per_order = models.DecimalField(
        "每单任务数", max_digits=8, decimal_places=3, default=1
    )
    demand_buffer_percent = models.DecimalField(
        "需求缓冲(%)", max_digits=6, decimal_places=2, default=10
    )
    release_lead_hours = models.FloatField("提前释放小时数", default=24)
    due_hour = models.PositiveSmallIntegerField(
        "交期时刻", default=18, validators=[MaxValueValidator(23)]
    )
    forecast_order_total = models.FloatField("预测订单总量", default=0)
    task_count = models.PositiveIntegerField("生成任务数", default=0)
    assumptions = models.JSONField("转换假设", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "planning_start"]),
            models.Index(fields=["forecast_run", "created_at"]),
        ]
        verbose_name = "生产计划"
        verbose_name_plural = "生产计划"

    def __str__(self):
        return f"{self.plan_no} - {self.name}"


class ScheduleRun(models.Model):
    """一次调度优化的可追溯结果。"""

    class Algorithm(models.TextChoices):
        SINGLE_SEQUENCE = "single_sequence", "单台多任务顺序优化"
        MULTI_VNS = "multi_vns", "多台变邻域优化"

    batch_id = models.UUIDField("调度批次", default=uuid.uuid4, unique=True, editable=False)
    production_plan = models.ForeignKey(
        ProductionPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="schedule_runs",
        verbose_name="生产计划",
    )
    algorithm = models.CharField("优化算法", max_length=32, choices=Algorithm.choices)
    objective_name = models.CharField("目标函数", max_length=128)
    task_count = models.PositiveIntegerField("任务数", default=0)
    agv_count = models.PositiveIntegerField("使用 AGV 数", default=0)
    makespan_seconds = models.FloatField("完工时间(秒)", default=0)
    total_distance = models.FloatField("总里程(米)", default=0)
    total_wait_seconds = models.FloatField("总等待时间(秒)", default=0)
    total_tardiness_seconds = models.FloatField("总拖期(秒)", default=0)
    late_task_count = models.PositiveIntegerField("拖期任务数", default=0)
    on_time_rate = models.FloatField("准点率(%)", default=100)
    iteration_count = models.PositiveIntegerField("搜索迭代次数", default=0)
    baseline_makespan_seconds = models.FloatField("基线完工时间(秒)", default=0)
    improvement_percent = models.FloatField("改进率(%)", default=0)
    assignments = models.JSONField("AGV 分配与顺序", default=dict, blank=True)
    metrics = models.JSONField("优化指标", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "调度优化记录"
        verbose_name_plural = "调度优化记录"

    def __str__(self):
        return f"{self.get_algorithm_display()} - {self.task_count}任务/{self.agv_count}车"


class TransportTask(models.Model):
    class Priority(models.IntegerChoices):
        LOW = 1, "低"
        NORMAL = 2, "普通"
        HIGH = 3, "高"
        URGENT = 4, "紧急"

    class BizType(models.TextChoices):
        TRANSPORT = "transport", "普通运输"
        TOOL_CHANGE = "tool_change", "换刀配送"
        TOOL_RETURN = "tool_return", "旧刀回收"

    class Status(models.TextChoices):
        PENDING = "pending", "待调度"
        ASSIGNED = "assigned", "已分配"
        IN_PROGRESS = "in_progress", "执行中"
        COMPLETED = "completed", "已完成"
        FAILED = "failed", "失败"
        CANCELLED = "cancelled", "已取消"

    task_no = models.CharField("任务编号", max_length=32, unique=True)
    biz_type = models.CharField(
        "业务类型", max_length=16, choices=BizType.choices, default=BizType.TRANSPORT
    )
    work_order = models.ForeignKey(
        "Operations.WorkOrder",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transport_tasks",
        verbose_name="关联工单",
    )
    operation_step = models.ForeignKey(
        "Operations.OperationStep",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transport_tasks",
        verbose_name="关联工序",
    )
    production_plan = models.ForeignKey(
        ProductionPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
        verbose_name="生产计划",
    )
    forecast_order_count = models.FloatField("对应预测订单数", null=True, blank=True)
    demand_date = models.DateField("需求日期", null=True, blank=True)
    release_at = models.DateTimeField("最早释放时间", null=True, blank=True)
    due_at = models.DateTimeField("要求完成时间", null=True, blank=True)
    pickup_node = models.ForeignKey(
        MapNode, on_delete=models.PROTECT, related_name="pickup_tasks", verbose_name="取货点"
    )
    dropoff_node = models.ForeignKey(
        MapNode, on_delete=models.PROTECT, related_name="dropoff_tasks", verbose_name="放货点"
    )
    cargo_name = models.CharField("货物名称", max_length=64)
    cargo_weight = models.FloatField("货物重量(kg)", validators=[MinValueValidator(0.1)])
    priority = models.PositiveSmallIntegerField(
        "优先级", choices=Priority.choices, default=Priority.NORMAL
    )
    status = models.CharField("状态", max_length=20, choices=Status.choices, default=Status.PENDING)
    assigned_agv = models.ForeignKey(
        AGV, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="tasks", verbose_name="执行 AGV",
    )
    schedule_run = models.ForeignKey(
        ScheduleRun, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="tasks", verbose_name="调度优化记录",
    )
    sequence_number = models.PositiveIntegerField("执行顺序", default=0)
    dispatch_order = models.PositiveIntegerField("全局调度顺序", default=0)
    planned_wait_seconds = models.FloatField("计划避碰等待(秒)", default=0)
    optimization_details = models.JSONField("优化详情", default=dict, blank=True)
    route = models.JSONField("规划路线", default=dict, blank=True)
    total_distance = models.FloatField("总里程(米)", default=0)
    estimated_duration = models.FloatField("单任务耗时(秒)", default=0)
    scheduled_start = models.DateTimeField("计划开始", null=True, blank=True)
    scheduled_end = models.DateTimeField("计划完成", null=True, blank=True)
    started_at = models.DateTimeField("实际开始", null=True, blank=True)
    completed_at = models.DateTimeField("实际完成", null=True, blank=True)
    notes = models.CharField("备注", max_length=255, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "priority", "created_at"]),
            models.Index(fields=["assigned_agv", "status"]),
            models.Index(fields=["schedule_run", "sequence_number"]),
            models.Index(fields=["work_order", "status"]),
            models.Index(fields=["operation_step", "status"]),
            models.Index(fields=["production_plan", "status"]),
            models.Index(fields=["due_at", "status"]),
        ]
        verbose_name = "运输任务"
        verbose_name_plural = "运输任务"

    def __str__(self):
        return f"{self.task_no} ({self.cargo_name})"

class DispatchRecord(models.Model):
    class Algorithm(models.TextChoices):
        SINGLE = "single", "单台调度"
        BATCH = "batch", "多台调度"

    task = models.ForeignKey(
        TransportTask, on_delete=models.CASCADE, related_name="dispatch_records", verbose_name="任务"
    )
    agv = models.ForeignKey(
        AGV, on_delete=models.SET_NULL, null=True,
        related_name="dispatch_records", verbose_name="AGV",
    )
    algorithm = models.CharField("调度算法", max_length=16, choices=Algorithm.choices)
    success = models.BooleanField("成功", default=True)
    message = models.CharField("调度说明", max_length=255, blank=True)
    route = models.JSONField("调度路线", default=dict, blank=True)
    distance = models.FloatField("调度里程(米)", default=0)
    estimated_duration = models.FloatField("预计耗时(秒)", default=0)
    created_at = models.DateTimeField("调度时间", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "调度记录"
        verbose_name_plural = "调度记录"

    def __str__(self):
        return f"{self.task.task_no} -> {self.agv.code if self.agv else '未分配'}"
