# 订单 API 契约

首版采用“一单一运输任务”：创建订单时在同一事务内生成一条待调度
`TransportTask`。订单状态复用任务状态，执行中禁止由订单接口手工修改。

## 状态映射

| 订单状态 | 触发动作 | 时间轴事件 |
| --- | --- | --- |
| `pending` | 创建订单 | `created` |
| `assigned` | 单台/多台调度成功 | `scheduled` |
| `in_progress` | 运输任务开始 | `started` |
| `completed` | 运输任务完成 | `completed` |
| `failed` | 未来异常处理流程 | `failed` |
| `cancelled` | 待调度/已分配订单取消 | `cancelled` |

## 内部接口

### 创建订单

`POST /api/orders/`

```json
{
  "customer_name": "张伟",
  "customer_phone": "13800000001",
  "cargo_name": "电子元件箱",
  "cargo_weight": 35,
  "pickup_node": 1,
  "dropoff_node": 2,
  "priority": 2,
  "notes": "轻拿轻放"
}
```

响应包含 `order_no`、客户、取放货点、`transport_task` 和 `events`。订单号由
服务端生成；手机号去除空格与连字符后必须匹配中国大陆 11 位手机号格式。

### 列表、详情与修改

- `GET /api/orders/?search=&status=&page=`：分页列表。
- `GET /api/orders/{id}/`：订单详情，`events` 按发生时间正序返回。
- `PATCH /api/orders/{id}/`：仅 `pending` 可修改货物、取放货点、优先级和备注；
  不允许修改客户身份。
- `DELETE /api/orders/{id}/`：不支持，返回 405；使用取消保留审计链。
- `POST /api/orders/{id}/cancel/`：仅 `pending`、`assigned` 可取消。

## 公开查询

`POST /api/orders/lookup/`

```json
{
  "order_no": "ORD-20261102-ABC123",
  "phone_tail": "0001"
}
```

凭证不匹配统一返回 404。手机号按 `138****0001` 脱敏，姓名保留首尾字符；响应不包含
内部 ID、任务号、AGV 编号或路线 JSON。接口按客户端 IP 限制为每分钟 20 次。

`GET /api/overview/` 额外返回 `order_total`、`order_status_counts` 和
`today_order_count`，供工作台待办卡片使用。
