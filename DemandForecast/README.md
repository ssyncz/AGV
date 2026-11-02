# 订单需求预测模块

对应课程任务 7，使用历史订单时间序列预测未来订单量。

## 输入数据

CSV 或 JSON 序列必须包含：

- `date`：订单日期
- `order_count`：订单数量

## 预测模型

1. 移动平均：适合作为稳定需求的基准模型。
2. Holt-Winters：同时建模趋势和 7 天周期。
3. ARIMA：对差分后的自相关结构进行建模。
4. 自动模式：使用最后一段历史数据回测，以 RMSE、MAPE 作为选择依据，再使用完整历史数据预测未来。

## 接口

| 方法 | 地址 | 说明 |
| --- | --- | --- |
| GET | `/api/forecast/overview/` | 预测统计与最近记录 |
| GET | `/api/forecast/sample/` | 获取内置订单序列 |
| POST | `/api/forecast/predict/` | 上传 CSV、提交序列或使用内置样例预测 |
| GET | `/api/forecast/runs/` | 历史预测记录 |

## 预测结果进入生产排程

预测记录保存后，可调用调度模块接口把它转换成带释放时间和交期的运输任务：

```json
POST /api/production-plans/generate/
{
  "forecast_run_id": 12,
  "planning_start_date": "2026-11-03",
  "tasks_per_order": 0.01,
  "demand_buffer_percent": 10,
  "release_lead_hours": 24,
  "due_hour": 18,
  "max_tasks": 500,
  "pickup_node_id": 1,
  "dropoff_node_id": 20
}
```

生成计划后调用 `POST /api/production-plans/{id}/schedule/` 执行多 AGV 联合排程。排程结果会返回准点率、拖期任务数和总拖期；传入 `"strict_deadlines": true` 时，只要存在预计拖期任务就拒绝该方案。

预测序列会按原周期间隔映射到 `planning_start_date`，因此历史数据集也可作为未来场景回放，但报告中应明确标注这是场景生成结果，而非历史真实 AGV 任务。

预测请求示例：

```json
{
  "horizon": 14,
  "model": "auto"
}
```

上传 CSV 时使用 multipart 字段 `file`，并同时提交 `horizon` 和 `model`。

## 真实数据集（可选）

`datasets/forecast/` 下可放入真实订单序列 CSV（字段 `date, order_count`），模块会自动识别：

- `online_retail_daily.csv`：UCI Online Retail 真实交易按天聚合的订单量（374 天，2010-12 ~ 2011-12）。

```json
GET  /api/forecast/series/                              // 列出可用真实序列
GET  /api/forecast/sample/?series=online_retail_daily    // 查看真实序列
POST /api/forecast/predict/  {"series": "online_retail_daily", "horizon": 14, "model": "auto"}
```

不传 `series` 时仍使用内置合成序列，原有行为不变。

**采样频率自适应**：预测前会根据相邻日期间隔自动推断频率与季节周期
（日 → 周期 7、周 → 周期 52/4、月 → 周期 12），并据此选择移动平均窗口与 Holt-Winters 季节周期；
返回值中新增 `frequency`、`seasonal_period`、`ma_window` 字段，便于核对。

**实测对比（真实数据 vs 合成数据，horizon=14）**

| 数据 | 移动平均 MAPE | Holt-Winters MAPE | ARIMA MAPE | auto 选中 |
| --- | --- | --- | --- | --- |
| 内置合成序列 | 约 5%~10% | 约 5%~10% | 约 5%~10% | 视数据而定 |
| **Online Retail 真实日订单** | 35.30% | **24.32%** | 32.71% | **Holt-Winters** |

> 真实数据误差明显高于合成数据属于正常现象；报告中应如实呈现，并说明可引入外生变量或换用 Prophet/LightGBM 进一步改进。
> 详见 [`datasets/forecast/README.md`](../datasets/forecast/README.md)。
