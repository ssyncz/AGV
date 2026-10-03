# AGV 智能调度系统

基于 Django REST Framework、MySQL 和 Vue 3 的 AGV 调度平台，支持单台 AGV 智能选车，以及多台 AGV 批量任务分配。系统内置仓库地图建模、Dijkstra 最短路径规划、综合成本评分和多车节点时间窗避碰。

## 1. 已实现功能

### 单台 AGV 调度决策

- 支持选择一个或多个任务，由同一台 AGV 连续执行。
- 可自动选车，也可以指定某台 AGV。
- 综合评估 AGV 状态、空驶距离、剩余电量和载重裕量。
- 使用精确动态规划求解多任务执行顺序；超过 10 个任务时使用最近邻 + 2-opt。\n- 使用 Dijkstra 算法计算每个任务的最优取放货路线。
- 保存规划路线、总里程、预计耗时、任务开始和结束时间。
- 自动将选中 AGV 状态更新为“执行任务”。

### 多台 AGV 调度

- 对多个待处理任务进行批量分配。
- 按任务优先级和创建顺序执行联合调度。
- 使用最优插入初始化，再通过变邻域搜索联合优化“任务到 AGV 分配”和“车辆内任务顺序”。\n- 目标函数联合考虑 makespan、使用 AGV 数量、优先级加权完成时间、总行驶距离和避碰等待。
- 支持同一 AGV 连续执行多个任务。
- 使用节点时间窗预约检测多车冲突，冲突时自动加入避碰等待。
- 保存每条路线的节点序列、分段里程、预计到达时间和等待记录。\n- 保存每次优化的 makespan、AGV 数量、迭代次数、基线结果和综合目标改进率。

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
- 返回路径节点序列、分段距离、预计耗时、预计耗电和约束检查结果。

## 2. 技术栈

| 层级 | 技术 |
| --- | --- |
| 后端 | Python 3.10+、Django 5.2、Django REST Framework |
| 数据库 | MySQL 8.0 |
| 前端 | Vue 3、Vite、原生 SVG 地图可视化 |
| 调度算法 | Dijkstra、综合成本选车、贪心多任务分配、节点时间窗避碰 |
| 接口 | RESTful JSON API |

## 3. 项目结构

```text
AGV/
├─ AGV/                              # Django 项目配置
│  ├─ settings.py                    # MySQL、CORS、REST Framework 配置
│  ├─ urls.py                        # 根路由
│  ├─ asgi.py
│  └─ wsgi.py
├─ SchedulingDecision/               # AGV 调度业务应用
│  ├─ models.py                      # 地图、AGV、任务、调度记录模型
│  ├─ serializers.py                 # API 序列化器
│  ├─ services.py                    # 路径规划与调度核心算法
│  ├─ views.py                       # REST API 视图
│  ├─ urls.py                        # API 路由
│  ├─ admin.py                       # Django Admin 配置
│  ├─ tests.py                       # 调度与 API 自动化测试
│  ├─ migrations/                    # 数据库迁移
│  └─ management/commands/seed_demo.py
├─ frontend/                         # Vue 3 + Vite 前端
│  ├─ src/App.vue
│  ├─ src/api.js
│  ├─ src/components/
│  ├─ src/views/
│  ├─ package.json
│  └─ vite.config.js
├─ ManufacturingVision/              # 视觉检测业务应用（任务 4 裂纹检测 / 任务 5 工件识别）
│  ├─ services.py                    # OpenCV 裂纹检测与工件识别算法
│  ├─ views.py                       # 视觉 REST 接口
│  └─ management/commands/           # 合成工件数据集生成、批量评估
├─ datasets/vision/                  # 视觉数据集（MT 裂纹/无缺陷 + 合成工件）
├─ requirements.txt
├─ manage.py
└─ .env.example
```

## 4. 环境要求

- Python 3.10 或更高版本
- MySQL 8.0 或更高版本
- Node.js 18 或更高版本
- npm 9 或更高版本

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

## 6. 启动后端

在项目根目录执行：

```powershell
C:\Users\ssync\miniconda3\envs\pmp\python.exe -m pip install -r requirements.txt
C:\Users\ssync\miniconda3\envs\pmp\python.exe manage.py migrate
C:\Users\ssync\miniconda3\envs\pmp\python.exe manage.py seed_demo --reset
C:\Users\ssync\miniconda3\envs\pmp\python.exe manage.py runserver 127.0.0.1:8000
```

如果 `python` 已加入 PATH，可直接使用 `python manage.py ...`。

`seed_demo --reset` 会初始化：

- 20 个仓库地图节点
- 31 条可通行道路
- 4 台 AGV
- 6 个待调度演示任务
- Django 管理员账号：`admin` / `Admin123!`

后端地址：

- API 根地址：http://127.0.0.1:8000/api/
- Django Admin：http://127.0.0.1:8000/admin/

## 7. 启动前端

另开一个终端：

```powershell
cd D:\python\AGV\frontend
npm install
npm run dev
```

浏览器访问：http://127.0.0.1:5173

Vite 已将 `/api` 代理到 `http://127.0.0.1:8000`。如需修改后端地址，可复制 `frontend/.env.example` 为 `frontend/.env` 并调整 `VITE_API_BASE`。

生产构建：

```powershell
npm run build
```

构建产物位于 `frontend/dist/`。

## 8. 主要 API

| 方法 | 地址 | 说明 |
| --- | --- | --- |
| GET | `/api/overview/` | 仪表盘统计 |
| GET | `/api/map/` | 地图节点、道路、障碍、AGV 和活动路线 |
| POST | `/api/path-planning/` | 根据起点、终点和 AGV 规划最短路径 |
| GET/POST | `/api/nodes/` | 地图节点查询和创建 |
| GET/POST | `/api/edges/` | 道路查询和创建 |
| GET/POST/PATCH | `/api/agvs/` | AGV 查询、创建和更新 |
| GET/POST/PATCH | `/api/tasks/` | 运输任务管理与查询 |
| POST | `/api/schedules/single/` | 单台 AGV 多任务顺序优化 |
| POST | `/api/schedules/batch/` | 多台 AGV 批量调度 |
| POST | `/api/tasks/{id}/start/` | 开始任务 |
| POST | `/api/tasks/{id}/complete/` | 完成任务 |
| POST | `/api/tasks/{id}/cancel/` | 取消任务 |
| GET | `/api/dispatches/` | 调度记录 |
| GET | `/api/schedule-runs/` | 调度优化记录与指标 |
| POST | `/api/vision/crack/` | 表面裂纹检测（上传图片或内置数据集样例） |
| POST | `/api/vision/detect/` | 几何工件识别（形状分类与定位） |
| GET | `/api/vision/samples/` | 视觉内置数据集样例列表 |
| GET | `/api/vision/records/` | 视觉检测记录（支持 `?task_type=` 筛选） |
| GET | `/api/vision/overview/` | 视觉检测统计概览 |

单台 AGV 多任务顺序优化示例：

```json
POST /api/schedules/single/
{
  "task_ids": [1, 2, 3, 4],
  "agv_id": null
}
```

- `agv_id` 为空时自动选择综合成本最低的一台 AGV。
- 接口返回优化后的执行顺序、makespan、总里程、基线结果和改进率。

多台 AGV 联合优化示例：

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

## 9. 调度算法说明

### 9.1 单台 AGV 多任务顺序优化

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

### 9.2 多台 AGV 联合优化

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

### 9.3 障碍地图路径规划

1. 地图由 12×8 网格节点构成，障碍区域不生成可通行节点。
2. 相邻可通行网格之间建立双向道路边。
3. 使用 Dijkstra 算法从起点搜索到终点，因此不会穿过障碍区域。
4. 根据 AGV 速度计算行驶时间，根据路径长度计算预计电量消耗。
5. 若指定 AGV 执行且安全电量不足，则拒绝该规划结果。
6. 地图前端同时渲染障碍块、道路、工作站、AGV 和多条彩色路线。

## 10. 测试

后端测试：

```powershell
C:\Users\ssync\miniconda3\envs\pmp\python.exe manage.py test SchedulingDecision -v 2
```

覆盖内容：

- Dijkstra 路线生成
- 单台 AGV 自动选车
- 多台 AGV 批量分配
- 多车路线与避碰等待
- 任务开始、完成、车辆位置和电量更新
- Dashboard 与地图 API
- 单台调度 API

前端检查：

```powershell
cd frontend
npm run build
```

## 11. 部署注意事项

- 生产环境必须修改 `DJANGO_SECRET_KEY`、数据库密码和 `DJANGO_DEBUG=False`。
- 当前 API 默认开放匿名访问，便于课程设计和演示；生产环境建议接入 JWT 或 Session 权限。
- 开发时使用 Vite，生产时可将 `frontend/dist` 部署到 Nginx，并将 `/api` 反向代理到 Django。
- 可进一步接入 WebSocket，用于真实 AGV 遥测数据和实时任务进度推送。
- 视觉模块的输入图与结果图写入 `media/`，已在 `.gitignore` 中忽略；仅在 DEBUG 下由 Django 托管静态访问。

## 12. 视觉模块（任务 4 裂纹检测 / 任务 5 工件识别）

由 `ManufacturingVision` 应用实现，全部为 OpenCV 传统算法（无深度学习），算法原理、接口契约、
指标结果、调参记录与 AI 使用记录详见 [`ManufacturingVision/README.md`](ManufacturingVision/README.md)；
数据集来源与抽样规则详见 [`datasets/vision/README.md`](datasets/vision/README.md)。

```powershell
# 安装依赖（新增 opencv-python / numpy）
C:\Users\ssync\miniconda3\envs\pmp\python.exe -m pip install -r requirements.txt

# 建表（新增 ManufacturingVision_visionrecord）
C:\Users\ssync\miniconda3\envs\pmp\python.exe manage.py migrate

# 生成合成工件数据集（任务 5，固定 seed 可复现）
C:\Users\ssync\miniconda3\envs\pmp\python.exe manage.py generate_workpiece_dataset --count 120 --size 400 --seed 42

# 批量评估，输出 reports/crack_metrics.json 与 reports/workpiece_metrics.json
C:\Users\ssync\miniconda3\envs\pmp\python.exe manage.py evaluate_vision --task all --out ManufacturingVision/reports

# 本模块测试（需要 MySQL）
C:\Users\ssync\miniconda3\envs\pmp\python.exe manage.py test ManufacturingVision -v 2
```

实测指标：裂纹检测准确率 **0.8662**、F1 **0.8235**；工件检测 F1 **0.9901**、形状分类准确率 **0.9767**。
