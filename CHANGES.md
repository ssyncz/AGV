# 企业级业务闭环集成

## 工序级制造调度升级（2026-11）

- 新增 `OperationStep` 工序模型：物料配送、生产加工、质量检验、完工入库；
- 工单按工序顺序执行，前序工序未完成时不能开始后续工序；
- 运输任务关联物流工序，任务完成后自动推进下一道工序；
- 质量检验工序设置为质量门禁，未通过视觉质检时不能完成；
- 新增 `WorkCalendar` 班次日历，工序计划时间按站点工作窗口生成；
- 新增 `ExecutionEvent` 幂等执行事件接口，支持 RCS/MES 上报任务和工序状态；
- 工单详情新增工序执行看板，任务页显示所属工序和全局调度顺序；
- 演示任务、执行事件和临时预测/质检/设备历史记录已清空。

本次改造新增 `Operations` 统一业务核心，引入生产工单、主数据、告警、领域事件和审计日志，并完成：

- 预测计划自动生成执行工单；
- 运输任务、视觉质检、设备诊断关联工单；
- 质检不合格和设备故障自动阻塞工单并生成告警；
- 工单状态机、全链路时间和生产总览；
- Vue Router、分组导航、工单中心、告警中心、生产计划与主数据页面；
- `/api/v1/` 版本化入口和 `X-Request-ID` 请求追踪。

详细实现说明见 `docs/企业级业务闭环集成说明.md`。

---

# 视觉部分切换到监督算法（DeepCrack）改动说明

为 `ManufacturingVision` 增加 DeepCrack 监督分割链路，并保留 Frangi 作为回退。
后续实测发现官方 DeepCrack 权重在 MT 磁瓦域迁移效果较差，因此**又把默认算法改回
Frangi**，DeepCrack 作为可选的实验算法保留。工件识别（任务 5）未改动。

## 改动文件

| 文件 | 改动 |
| --- | --- |
| `ManufacturingVision/services_supervised.py` | 新增 `analyze_crack_supervised`、`annotate_crack_supervised`、`supervised_available`，并让 `get_model` 按设备缓存 |
| `ManufacturingVision/views.py` | `/api/vision/crack/` 默认走 DeepCrack，失败自动回退 Frangi；响应新增 `algorithm / fallback / coverage / max_prob / mean_prob` |
| `ManufacturingVision/views_algo.py` | `algo/status/` 返回 DeepCrack 状态 |
| `ManufacturingVision/tests.py` | 新增默认算法、DeepCrack 回退、算法状态测试；原有断言显式指定 Frangi 以保持确定性 |
| `ManufacturingVision/README.md` | 更新算法说明、参数表、接口示例 |
| `frontend/src/views/VisionView.vue` | 裂纹页增加 DeepCrack / Frangi 算法切换与对应参数、指标展示 |

## 使用方式

直接把这 6 个文件按相对路径覆盖到 `AGV` 项目根目录即可，无需改数据库表。

- 默认算法：`Frangi`。本机在 157 张 MT 图片上实测：Frangi 准确率 0.8662 / F1 0.8235；
  官方 DeepCrack 权重最佳仅 F1 0.56 / 准确率 0.45，因此不作为默认。
- 可选算法：`DeepCrack`。需要 PyTorch（见 `requirements-ml.txt`）与域内微调权重
  `models/deepcrack.pth`；找不到时接口自动回退 Frangi，并在响应里返回 `"fallback": true`。
- 显式指定算法：`params` 里传 `"algorithm": "deepcrack"` 或 `"algorithm": "frangi"`。
- 权重与训练产物放在 `models/`、`runs/`，已在 `.gitignore` 中忽略，不入库。

## 验证

- 后端 4 个 Python 文件已通过语法编译检查。
- 未在本机运行 Django 测试和 Vue 构建，因为这里没有项目的 Python 虚拟环境和
  Node 依赖；覆盖到项目后建议执行：

```powershell
.\venv\Scripts\python.exe manage.py test ManufacturingVision -v 2
cd frontend; npm run build
```
