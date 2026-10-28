# AGV 智能调度系统

基于 Django REST Framework、MySQL 和 Vue 3 的 AGV 调度平台。核心能力包括仓库地图建模、Dijkstra 最短路径规划、单台智能选车和多台 AGV 联合调度，并在此基础上扩展了**视觉检测（任务 4/5）**、**设备状态监测（任务 6）**和**订单需求预测（任务 7）**三个模块。

## 1. 已实现功能

### 单台 AGV 调度决策

- 支持选择一个或多个任务，由同一台 AGV 连续执行。
- 可自动选车，也可以指定某台 AGV。
- 综合评估 AGV 状态、空驶距离、剩余电量和载重裕量。
- 使用精确动态规划求解多任务执行顺序；超过 10 个任务时使用最近邻 + 2-opt。
- 使用 Dijkstra 算法计算每个任务的最优取放货路线。
- 保存规划路线、总里程、预计耗时、任务开始和结束时间。
- 自动将选中 AGV 状态更新为“执行任务”。

### 多台 AGV 调度

- 对多个待处理任务进行批量分配。
- 按任务优先级和创建顺序执行联合调度。
- 使用最优插入初始化，再通过变邻域搜索联合优化“任务到 AGV 分配”和“车辆内任务顺序”。
- 目标函数联合考虑 makespan、使用 AGV 数量、优先级加权完成时间、总行驶距离和避碰等待。
- 支持同一 AGV 连续执行多个任务。
- 使用节点时间窗预约检测多车冲突，冲突时自动加入避碰等待。
- 保存每条路线的节点序列、分段里程、预计到达时间和等待记录。
- 保存每次优化的 makespan、AGV 数量、迭代次数、基线结果和综合目标改进率。

### 任务与车辆管理

- AGV 状态、当前位置、电量、载重、速度管理。
- 运输任务创建、取消、开始和完成。
- 完成任务后自动更新 AGV 位置并扣减电量。
- 车辆状态分布、车队利用率、平均电量等统计。
- 调度记录追溯。
- Django Admin 后台管理。

### 路径规划地图

- 提供类似仓储平面图的障碍地图，包含黑色障碍区域、灰色可通行路网和 S1-S10 工作站。
- 支持选择任意起点、终点和执行 AGV，实时规划最短路径。
- 路径规划自动绕开障碍，并检查道路拓扑和 AGV 电量约束。
- 地图支持叠加多个当前执行中任务的彩色路线，以及手动规划的红色路线。
- 悬停节点显示“编号 · 名称”提示，贴边节点的提示会自动收进画布内。
- 返回路径节点序列、分段距离、预计耗时、预计耗电和约束检查结果。

### 视觉检测（任务 4 / 5）

由 `ManufacturingVision` 应用实现，全部为 OpenCV 传统图像处理，不使用深度学习。

- 表面裂纹检测：多尺度 Frangi 黑脊响应 + 连通域一致性筛选，输出判定结果与裂纹掩膜。
- 工件识别：Otsu 分割 + 多边形逼近，输出圆形 / 三角形 / 正方形 / 矩形 / 六边形分类与包围框。
- 支持上传图片或直接使用内置数据集样例，输入图与结果图落盘到 `media/`。
- 前端提供原图 / 结果图对比、工件明细表和检测记录回看。

### 设备状态监测（任务 6）

由 `EquipmentMonitoring` 应用实现。

- 输入温度、振动、电流、主轴转速和刀具磨损五个特征，输出正常 / 磨损 / 故障三分类。
- 使用 `StandardScaler + RandomForestClassifier`，返回置信度、特征重要性和模型指标。
- 叠加温度和振动等机理阈值规则告警，与模型判断互补。
- 支持上传 CSV、提交 JSON 记录或使用内置样例，结果落库并可在前端回看。

### 订单需求预测（任务 7）

由 `DemandForecast` 应用实现。

- 支持移动平均、Holt-Winters、ARIMA 和自动选择四种模式。
- 自动模式在回测集上比较三个模型，按 RMSE / MAPE 选优后再用完整历史预测未来。
- 支持上传包含 `date`、`order_count` 的 CSV，也支持提交序列或使用内置订单时间序列。
- 前端显示历史曲线、未来预测曲线、模型指标对比和预测记录。

## 2. 技术栈

| 层级 | 技术 |
| --- | --- |
| 后端 | Python 3.10+、Django 5.2、Django REST Framework |
| 数据库 | MySQL 8.0 |
| 前端 | Vue 3、Vite、原生 SVG 地图可视化 |
| 调度算法 | Dijkstra（含路径缓存）、综合成本选车、状态压缩动态规划（<=10 任务精确解）、最近邻 + 2-opt（大规模）、最优插入构造 + 变邻域下降（relocate/swap/or-opt/2-opt）、节点时间窗避碰 |
| 视觉检测 | OpenCV 4.11（Frangi 传统方法，默认）+ PyTorch 2.2（DeepCrack 监督分割，可选） |
| 设备监测 | scikit-learn（StandardScaler + RandomForestClassifier） |
| 需求预测 | statsmodels（Holt-Winters、SARIMA/ARIMA）、pandas、numpy |
| 接口 | RESTful JSON API |

## 3. 项目结构

```text
AGV/
├─ AGV/                                   # Django 项目配置
│  ├─ settings.py                         # MySQL、CORS、REST Framework 配置
│  ├─ urls.py                             # 根路由（挂载 5 个模块的 API 前缀）
│  ├─ asgi.py
│  └─ wsgi.py
├─ SchedulingDecision/                    # 调度业务应用
│  ├─ models.py                           # 地图节点/道路/障碍、AGV、任务、调度记录、调度运行
│  ├─ serializers.py
│  ├─ services.py                         # 路径规划与调度核心算法
│  ├─ views.py / urls.py / admin.py
│  ├─ tests.py                            # 调度流程与 API 测试
│  ├─ migrations/
│  └─ management/commands/seed_demo.py    # 演示数据初始化
├─ ManufacturingVision/                   # 视觉检测应用（任务 4 / 5）
│  ├─ datasets.py                         # 数据集访问层（样例列举、路径解析、标注读取）
│  ├─ services.py                         # 裂纹检测与工件识别算法
│  ├─ crack_detection.py                  # 命令行裂纹检测原型
│  ├─ models.py                           # VisionRecord 检测记录
│  ├─ tests.py                            # 算法 / 接口 / 管理命令测试
│  └─ management/commands/                # 合成数据集生成、批量评估
├─ EquipmentMonitoring/                   # 设备状态监测应用（任务 6）
│  ├─ models.py                           # EquipmentDiagnosisRecord 诊断记录
│  ├─ services.py                         # 特征工程 + 随机森林 + 规则告警
│  └─ views.py / serializers.py / urls.py / tests.py
├─ DemandForecast/                        # 订单需求预测应用（任务 7）
│  ├─ models.py                           # DemandForecastRun 预测记录
│  ├─ services.py                         # 移动平均 / Holt-Winters / ARIMA
│  └─ views.py / serializers.py / urls.py / tests.py
├─ datasets/vision/                       # 视觉数据集（详见该目录 README）
│  ├─ mt/crack/{images,masks}/            # MT_Crack 真实裂纹样本 + 同名二值掩码
│  ├─ mt/free/                            # MT_Free 无缺陷负样本（可复现抽样 100 张）
│  └─ workpiece/                          # 合成几何工件 120 张 + labels.json
├─ frontend/                              # Vue 3 + Vite 前端
│  ├─ src/App.vue                         # 布局、8 个菜单项、8 秒轮询
│  ├─ src/api.js                          # API 封装（含 FormData 上传分支）
│  ├─ src/components/                     # StatCard / StatusBadge / ScheduleGantt
│  ├─ src/views/                          # Dashboard/Dispatch/Map/Task/Agv/Vision/Equipment/Forecast
│  ├─ src/styles.css
│  ├─ vite.config.js                      # /api 与 /media 代理
│  └─ package.json
├─ .run/AGV Full Project.run.xml          # PyCharm 一键启动配置
├─ run_project.py                         # 同时拉起 Django + Vite 的启动脚本
├─ requirements.txt
├─ manage.py
└─ .env.example
```

## 4. 环境要求

- Python 3.10 或更高版本
- MySQL 8.0 或更高版本
- Node.js 18 或更高版本
- npm 9 或更高版本

建议**为项目单独准备虚拟环境**再安装 `requirements.txt`。该文件锁定了 `numpy==1.26.4` 与 `PyMySQL==1.1.1`，如果直接装进已有其他项目的环境，可能把环境中较新的 numpy 降级，进而影响 numba、faiss 等依赖。

## 5. MySQL 准备

创建数据库：

```sql
CREATE DATABASE agv CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

默认连接参数见 `.env.example`，也可以在启动后端前通过环境变量覆盖：

```powershell
$env:DB_NAME = "agv"
$env:DB_USER = "root"
$env:DB_PASSWORD = "123456"
$env:DB_HOST = "127.0.0.1"
$env:DB_PORT = "3306"
```

当前 `AGV/settings.py` 使用兼容性较好的 `PyMySQL`，无需额外编译 `mysqlclient`。

## 6. 一键启动

`run_project.py` 会同时拉起 Django 与 Vite，并自动跳过已在运行的服务：

```powershell
cd D:\python\AGV
python run_project.py
```

- Django：http://127.0.0.1:8000
- Vite：http://127.0.0.1:5173
- 8000 / 5173 已被占用时跳过启动，Ctrl+C 只停止由本脚本创建的服务。
- 需要 Node.js 已安装且 `npm` 在 PATH 中。

在 PyCharm 中也可以直接运行 `.run/AGV Full Project.run.xml`（运行配置名为 AGV Full Project）。该配置的解释器为 `pmp`，与手动启动使用的环境一致；如果 PyCharm 里换成了别的解释器，会出现依赖缺失或 `Couldn't import Django` 之类的报错。

## 7. 手动启动后端

在项目根目录执行：

```powershell
# 下文用 $PY 代指本机解释器路径，请按实际情况替换
$PY = "C:\Users\ssync\miniconda3\envs\pmp\python.exe"

& $PY -m pip install -r requirements.txt
& $PY manage.py migrate
& $PY manage.py seed_demo --reset
& $PY manage.py runserver 127.0.0.1:8000
```

做 20 条任务的调度演示时，可直接用：

```powershell
# 清空全部业务数据并重新生成 20 个待调度任务
& $PY manage.py seed_demo --reset --task-count 20

# 或只清空调度任务、调度记录和优化记录，保留地图与 AGV 位置/电量
& $PY manage.py seed_demo --reset-tasks --task-count 20
```

如果 `python` 已加入 PATH 并指向正确的环境，也可以直接使用 `python manage.py ...`。

`migrate` 会为全部 5 个应用建表（含 `SchedulingDecision`、`ManufacturingVision`、`EquipmentMonitoring`、`DemandForecast`）。

`seed_demo --reset` 会清空业务数据后重新初始化：

- 76 个仓库地图节点（12×8 网格扣除 20 个障碍格，其中充电区 1 个、停车区 3 个、取货点 5 个、放货点 5 个、路口 62 个）
- 103 条可通行道路
- 10 个障碍区域
- 4 台 AGV
- 默认 6 个待调度演示任务；使用 `--task-count 20` 可生成 20 个
- Django 管理员账号：`admin` / `Admin123!`

后端地址：

- API 根地址：http://127.0.0.1:8000/api/
- Django Admin：http://127.0.0.1:8000/admin/

## 8. 启动前端

另开一个终端：

```powershell
cd D:\python\AGV\frontend
npm install
npm run dev
```

浏览器访问：http://127.0.0.1:5173

Vite 已将 `/api` 和 `/media` 代理到 `http://127.0.0.1:8000`。如需修改后端地址，可复制 `frontend/.env.example` 为 `frontend/.env` 并调整 `VITE_API_BASE`。

生产构建：

```powershell
npm run build
```

构建产物位于 `frontend/dist/`。

## 9. 主要 API

接口前缀为 `/api/`（视觉为 `/api/vision/`，设备为 `/api/equipment/`，预测为 `/api/forecast/`）。当前所有接口默认开放匿名访问（`AllowAny`），列表接口统一分页，每页 100 条，可用 `?page=` 翻页。

> 注意：`?字段=值` 形式的字段筛选目前只在视觉记录、设备记录和预测记录这类在 `get_queryset` 中手动读取查询参数的接口上生效。调度类接口（节点、道路、障碍、AGV、任务、调度记录）虽然声明了 `filterset_fields`，但项目未安装 `django-filter`，`DEFAULT_FILTER_BACKENDS` 中也没有 `DjangoFilterBackend`，因此这些参数不会过滤结果；需要筛选时请使用 `?search=`（任务）或 `?ordering=`。

### 9.1 调度与地图

| 方法 | 地址 | 说明 |
| --- | --- | --- |
| GET | `/api/overview/` | 仪表盘统计（车队利用率、任务分布、最近调度记录） |
| GET | `/api/map/` | 地图节点、道路、障碍、AGV 和活动路线 |
| POST | `/api/path-planning/` | 根据起点、终点和 AGV 规划最短路径 |
| GET/POST/PUT/PATCH/DELETE | `/api/nodes/` | 地图节点增删改查 |
| GET/POST/PUT/PATCH/DELETE | `/api/edges/` | 道路增删改查 |
| GET/POST/PUT/PATCH/DELETE | `/api/obstacles/` | 障碍区域增删改查 |
| GET/POST/PUT/PATCH/DELETE | `/api/agvs/` | AGV 增删改查（支持 `?ordering=`） |
| GET | `/api/agvs/summary/` | 车辆状态分布与平均电量 |
| GET/POST/PUT/PATCH/DELETE | `/api/tasks/` | 运输任务增删改查（支持 `?search=`，按 `task_no` / `cargo_name` 检索） |
| POST | `/api/tasks/{id}/start/` | 开始任务 |
| POST | `/api/tasks/{id}/complete/` | 完成任务 |
| POST | `/api/tasks/{id}/cancel/` | 取消任务 |
| GET | `/api/dispatches/` | 调度记录（只读） |
| GET | `/api/schedule-runs/` | 调度优化记录与指标（只读） |
| POST | `/api/schedules/single/` | 单台 AGV 多任务顺序优化 |
| POST | `/api/schedules/batch/` | 多台 AGV 批量调度 |

### 9.2 视觉检测

| 方法 | 地址 | 说明 |
| --- | --- | --- |
| POST | `/api/vision/crack/` | 表面裂纹检测（上传图片或使用内置样例） |
| POST | `/api/vision/detect/` | 几何工件识别（形状分类与定位） |
| GET | `/api/vision/samples/` | 内置数据集样例列表 |
| GET | `/api/vision/samples/{分组}/{文件名}/` | 返回内置样例原图（前端预览用） |
| GET | `/api/vision/records/` | 检测记录（支持 `?task_type=`、`?source=`、`?verdict=`） |
| DELETE | `/api/vision/records/{id}/` | 删除记录，同时清理其输入图与结果图 |
| GET | `/api/vision/overview/` | 检测次数、判定分布与最近记录 |

### 9.3 设备状态监测

| 方法 | 地址 | 说明 |
| --- | --- | --- |
| GET | `/api/equipment/overview/` | 诊断统计与模型指标 |
| GET | `/api/equipment/sample/` | 内置传感器样例（`?scenario=normal/worn/fault`） |
| GET | `/api/equipment/model/` | 模型指标与特征重要性 |
| POST | `/api/equipment/diagnose/` | 状态分类与规则告警（上传 CSV 或提交 `records`） |
| GET/DELETE | `/api/equipment/records/` | 诊断记录（支持 `?equipment_code=`、`?predicted_state=`、`?source=`） |

### 9.4 订单需求预测

| 方法 | 地址 | 说明 |
| --- | --- | --- |
| GET | `/api/forecast/overview/` | 预测统计、可用模型与最近记录 |
| GET | `/api/forecast/sample/` | 内置订单序列（`?days=`） |
| POST | `/api/forecast/predict/` | 多模型时间序列预测（上传 CSV 或提交 `history`） |
| GET/DELETE | `/api/forecast/runs/` | 预测记录（支持 `?selected_model=`） |

### 9.5 调度请求示例

单台 AGV 多任务顺序优化：

```json
POST /api/schedules/single/
{
  "task_ids": [1, 2, 3, 4],
  "agv_id": null
}
```

- `agv_id` 为空时自动选择综合成本最低的一台 AGV。
- 接口返回优化后的执行顺序、makespan、总里程、基线结果和改进率。

多台 AGV 联合优化：

```json
POST /api/schedules/batch/
{
  "task_ids": [1, 2, 3, 4, 5, 6],
  "limit": 30,
  "weights": {
    "agv_weight": 30
  }
}
```

- `task_ids` 传 `null` 或省略时，调度全部待处理任务。
- `agv_weight` 越大，优化结果越倾向于减少 AGV 使用数量。

设备诊断与订单预测的请求体示例见各自模块的 README。

## 10. 调度算法说明

### 10.1 单台 AGV 多任务顺序优化

单台模式解决的问题是：

```text
给定一台 AGV 和多个待搬运任务，确定任务执行顺序，使整个搬运过程总用时最短。
```

计算过程：

1. 使用 Dijkstra 预计算任意起点到任务取货点、取货点到放货点的最短距离。
2. 对每个候选 AGV，计算“当前位置 → 首个取货点 → 首个放货点”的初始成本。
3. 计算任务之间的转移成本：前一个任务放货点 → 下一个任务取货点 → 下一个任务放货点。
4. 对不超过 10 个任务使用状态压缩动态规划精确求解最优顺序。
5. 对更大规模使用最近邻构造初始解，再使用 2-opt 优化。
6. 将规划结果同时考虑卸货、装货、安全间隔和电池消耗。

### 10.2 多台 AGV 联合优化

多台模式统一优化两个决策变量：

```text
1. 每个任务分配给哪台 AGV
2. 每台 AGV 内部任务的执行顺序
```

算法流程：

1. 使用基准算法生成初始对比结果。
2. 使用“最优插入”生成初始可行解，对每个任务尝试所有 AGV 和所有插入位置。
3. 使用变邻域搜索迁移任务位置，同时改变任务所属 AGV 和车辆内顺序。
4. 每轮完整评估 makespan、优先级加权完成时间、总距离、等待时间和 AGV 数量。
5. 在路线节点上建立时间窗预约，遇到冲突时自动加入安全间隔等待。
6. 输出相对基准算法的综合目标改进率。

默认综合目标：

```text
objective = makespan
          + agv_weight * 使用 AGV 数
          + wait_weight * 避碰等待
          + distance_weight * 总里程
          + priority_weight * 优先级加权完成时间
```

路线 JSON 示例：

```json
{
  "nodes": [1, 5, 9, 14],
  "legs": [
    { "from_node": 1, "to_node": 5, "distance": 4, "seconds": 3.33 }
  ],
  "timeline": [
    { "node_id": 1, "arrival_seconds": 0, "departure_seconds": 2, "wait_seconds": 0 }
  ],
  "waits": [
    { "node_id": 9, "seconds": 2.6, "reason": "避碰等待" }
  ]
}
```

### 10.3 障碍地图路径规划

1. 地图由 12×8 网格构成，被障碍覆盖的格子不生成节点，因此最终得到 76 个节点、103 条道路。
2. 相邻可通行网格之间建立双向道路边，单格边长 4.0 m。
3. 使用 Dijkstra 算法从起点搜索到终点，因此不会穿过障碍区域。
4. 根据 AGV 速度计算行驶时间，根据路径长度计算预计电量消耗。
5. 若指定 AGV 执行且安全电量不足，则拒绝该规划结果。
6. 地图前端同时渲染障碍块、道路、工作站、AGV 和多条彩色路线。

## 11. 视觉模块（任务 4 裂纹检测 / 任务 5 工件识别）

由 `ManufacturingVision` 应用实现，全部为 OpenCV 传统算法（无深度学习）。算法原理、调参记录、接口契约与 AI 使用记录详见 [`ManufacturingVision/README.md`](ManufacturingVision/README.md)；数据集来源与抽样规则详见 [`datasets/vision/README.md`](datasets/vision/README.md)。

```powershell
# 安装依赖（新增 opencv-python / numpy）
& $PY -m pip install -r requirements.txt

# 建表（新增 ManufacturingVision_visionrecord）
& $PY manage.py migrate

# 生成合成工件数据集（任务 5，固定 seed 可复现）
& $PY manage.py generate_workpiece_dataset --count 120 --size 400 --seed 42

# 批量评估，输出 reports/crack_metrics.json 与 reports/workpiece_metrics.json
& $PY manage.py evaluate_vision --task all --out ManufacturingVision/reports

# 本模块测试（需要 MySQL）
& $PY manage.py test ManufacturingVision -v 2
```

实测指标：裂纹检测准确率 **0.8662**、F1 **0.8235**；工件检测 F1 **0.9901**、形状分类准确率 **0.9767**。

已知限制：裂纹平均像素 IoU 为 0.2723，定位后处理显著改善了宽度召回，但仍存在漏定位；参数是在 157 张图上标定的，留出集 F1 为 0.7692。工件识别基于合成数据，真实产线图像需要重新标注验证。

## 12. 设备状态监测（任务 6）

由 `EquipmentMonitoring` 应用实现：

- 支持内置正常、磨损、故障样例（`?scenario=normal/worn/fault`）。
- 支持上传包含温度、振动、电流、主轴转速和刀具磨损列的 CSV。
- 使用 `StandardScaler + RandomForestClassifier` 进行分类，并返回置信度和特征重要性。
- 叠加温度、振动、电流、转速和磨损阈值规则，输出报警信息。
- 前端显示状态分布、传感器趋势、规则告警和历史诊断记录。

```powershell
# 建表（新增 EquipmentMonitoring_equipmentdiagnosisrecord）
& $PY manage.py migrate

# 本模块测试
& $PY manage.py test EquipmentMonitoring -v 2
```

详细说明见 [`EquipmentMonitoring/README.md`](EquipmentMonitoring/README.md)。

## 13. 订单需求预测（任务 7）

由 `DemandForecast` 应用实现：

- 支持移动平均、Holt-Winters、ARIMA 和自动选择模式。
- 自动模式使用回测集比较 MAE、RMSE 和 MAPE，选择表现最好的模型。
- 支持上传包含 `date`、`order_count` 的 CSV，也支持内置订单时间序列。
- 前端显示历史曲线、未来预测曲线、模型对比和预测记录。

```powershell
# 建表（新增 DemandForecast_demandforecastrun）
& $PY manage.py migrate

# 本模块测试
& $PY manage.py test DemandForecast -v 2
```

详细说明见 [`DemandForecast/README.md`](DemandForecast/README.md)。

## 14. 测试

测试需要可用的 MySQL（Django 会自动创建并销毁 `test_agv` 库）：

```powershell
# 全部测试
& $PY manage.py test -v 2

# 或按模块运行
& $PY manage.py test SchedulingDecision -v 2
& $PY manage.py test ManufacturingVision -v 2
& $PY manage.py test EquipmentMonitoring -v 2
& $PY manage.py test DemandForecast -v 2
```

覆盖内容：

- Dijkstra 路线生成
- 单台 AGV 自动选车
- 多台 AGV 批量分配
- 多车路线与避碰等待
- 任务开始、完成、车辆位置和电量更新
- Dashboard、地图与调度 API
- 裂纹检测算法与工件识别算法
- 视觉数据集访问、批量评估与数据集生成命令
- 设备诊断服务与接口
- 预测服务与接口

前端检查：

```powershell
cd frontend
npm run build
```

## 15. 部署注意事项

- 生产环境必须修改 `DJANGO_SECRET_KEY`、数据库密码并设置 `DJANGO_DEBUG=False`。
- 当前 API 默认开放匿名访问，便于课程设计和演示；生产环境建议接入 JWT 或 Session 权限。
- 开发时使用 Vite，生产时可将 `frontend/dist` 部署到 Nginx，并将 `/api` 反向代理到 Django。
- 视觉模块的输入图与结果图写入 `media/`，已在 `.gitignore` 中忽略；仅在 DEBUG 下由 Django 托管静态访问。
- `ManufacturingVision/reports/` 是 `evaluate_vision` 的产物目录，可重新生成，不属于运行必需文件。
- 若部署到无图形库的服务器，把 `opencv-python` 换成 `opencv-python-headless` 即可（服务端代码不使用 OpenCV 的 GUI 函数）。
- 可进一步接入 WebSocket，用于真实 AGV 遥测数据和实时任务进度推送。

## 16. 公开数据集接入（任务 6 / 任务 7）

除内置合成演示数据外，项目支持接入**公开真实数据集**，数据文件统一放在 `datasets/` 下，
转换脚本为 [`tools/build_public_datasets.py`](tools/build_public_datasets.py)（可复现，不依赖 Django）。

| 数据集 | 用途 | 规模 | 性质 |
| --- | --- | --- | --- |
| `datasets/equipment/ai4i_equipment.csv` | 设备状态监测（任务 6） | 10,000 行 x 5 特征 + label | 公开基准数据集（基于真实工业过程模型生成） |
| `datasets/forecast/online_retail_daily.csv` | 订单需求预测（任务 7） | 374 天日订单量 | 真实交易数据（541,909 条交易按天聚合） |
| `datasets/m3/*.csv` | 制造业订单横截面 | 6 张表、2,880 条记录 | 真实官方统计（仅最近 3 个月，不能做时间序列） |

重新生成数据：

```powershell
python tools/build_public_datasets.py `
  --ai4i   "E:\下载文件\ai4i+2020+predictive+maintenance+dataset.zip" `
  --retail "E:\下载文件\online+retail.zip" `
  --m3     "E:\下载文件\数据.zip"
```

新增接口：

| 方法 | 地址 | 说明 |
| --- | --- | --- |
| GET | `/api/equipment/datasets/` | 列出设备数据集（来源、行数、标签分布） |
| GET | `/api/equipment/model/?data_source=ai4i_equipment` | 用真实数据集训练并返回指标与特征重要性 |
| POST | `/api/equipment/diagnose/` | 支持 `dataset` 与 `data_source` 参数，直接用真实数据诊断 |
| GET | `/api/forecast/series/` | 列出可用真实订单序列 |
| POST | `/api/forecast/predict/` | 支持 `series` 参数（如 `online_retail_daily`） |

实测指标（真实数据集，本机复现）：

- 设备监测（AI4I，真实标签）：accuracy **0.8984**、F1-macro **0.5042**；`worn` 类仅 46 条样本、F1 仅 0.106
  —— 真实数据的类别不平衡会显著拉低指标，报告中需如实说明。
- 订单预测（Online Retail 日订单量，374 天）：移动平均 MAPE 35.30%、**Holt-Winters 24.32%**、ARIMA 32.71%，
  `auto` 模式自动选中 Holt-Winters。

数据来源、许可、字段映射、派生公式与诚实提示详见 `datasets/equipment/README.md`、
`datasets/forecast/README.md`、`datasets/m3/README.md`。
