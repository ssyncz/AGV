"""订单闭环 API 端到端走查：下单 -> 调度 -> 开始 -> 完成 -> 公开查询。

运行前请启动 Django，并准备至少一台空闲 AGV：
    python manage.py seed_demo --reset
    python scripts/e2e_orders.py
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import urllib.error
import urllib.request


API_BASE = os.environ.get("AGV_API_BASE", "http://127.0.0.1:8000/api").rstrip("/")


def request_json(path: str, method: str = "GET", payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw).get("detail", raw)
        except json.JSONDecodeError:
            detail = raw
        raise RuntimeError(f"{method} {path} 失败（HTTP {exc.code}）：{detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接后端 {API_BASE}：{exc.reason}") from exc


def list_items(path: str) -> list[dict]:
    data = request_json(path)
    return data if isinstance(data, list) else data.get("results", [])


def main() -> int:
    nodes = list_items("/nodes/")
    pickup = next((node for node in nodes if node["code"] == "S2"), None)
    dropoff = next((node for node in nodes if node["code"] == "S6"), None)
    if pickup is None or dropoff is None:
        raise RuntimeError("缺少 S2/S6 演示节点，请先执行 seed_demo --reset。")

    agvs = list_items("/agvs/")
    idle_agv = next((agv for agv in agvs if agv["status"] == "idle"), None)
    if idle_agv is None:
        raise RuntimeError("没有空闲 AGV，请先执行 seed_demo --reset。")

    phone = f"139{secrets.randbelow(100_000_000):08d}"
    order = request_json(
        "/orders/",
        method="POST",
        payload={
            "customer_name": "端到端测试客户",
            "customer_phone": phone,
            "cargo_name": "E2E 测试货物",
            "cargo_weight": 12.5,
            "pickup_node": pickup["id"],
            "dropoff_node": dropoff["id"],
            "priority": 2,
            "notes": "scripts/e2e_orders.py 自动创建",
        },
    )
    order_no = order["order_no"]
    task_id = order["transport_task"]["id"]
    print(f"[1/5] 已创建订单 {order_no}，任务 {order['transport_task']['task_no']}")

    schedule = request_json(
        "/schedules/single/",
        method="POST",
        payload={"task_ids": [task_id], "agv_id": idle_agv["id"]},
    )
    if schedule["tasks"][0]["status"] != "assigned":
        raise RuntimeError("调度后运输任务状态不是 assigned。")
    print(f"[2/5] 调度完成，任务分配给 {idle_agv['code']}")

    request_json(f"/tasks/{task_id}/start/", method="POST", payload={})
    print("[3/5] 运输任务已开始")
    request_json(f"/tasks/{task_id}/complete/", method="POST", payload={})
    print("[4/5] 运输任务已完成")

    public_order = request_json(
        "/orders/lookup/",
        method="POST",
        payload={"order_no": order_no, "phone_tail": phone[-4:]},
    )
    if public_order["status"] != "completed":
        raise RuntimeError(f"公开查询状态异常：{public_order['status']}")
    if "****" not in public_order["customer_phone"]:
        raise RuntimeError("公开查询未返回脱敏手机号。")
    if "transport_task" in public_order or "assigned_agv_code" in str(public_order):
        raise RuntimeError("公开查询泄露了内部运输信息。")

    detail = request_json(f"/orders/{order['id']}/")
    event_types = [event["event_type"] for event in detail["events"]]
    expected = ["created", "scheduled", "started", "completed"]
    if event_types != expected:
        raise RuntimeError(f"订单时间轴异常：{event_types}")

    print(f"[5/5] 公开查询通过：{public_order['customer_name']} / {public_order['customer_phone']}")
    print(f"完成：{order_no} 的状态为 completed，时间轴共 {len(event_types)} 条事件。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"E2E 失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
