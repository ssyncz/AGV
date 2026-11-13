"""换刀闭环：刀具状态 → 换刀建议 → 生成刀具配送运输任务 → 执行换刀。"""
from __future__ import annotations

import uuid

from django.db import transaction
from django.utils import timezone

from .models import Tool, ToolChangeRecord

# 两端都从设备档案读：刀具库 = 设备 TOOL-CRIB 的 map_node，机床 = 该设备的 map_node
TOOL_CRIB_EQUIPMENT_CODE = "TOOL-CRIB"
TOOL_CRIB_NODE_CODE = "S10"          # 兜底：没建刀具库档案时用
DEFAULT_EQUIPMENT_NODE_CODE = "S6"   # 兜底：没填站点时用


def _node_code_of(equipment, fallback: str) -> str:
    if equipment is not None and isinstance(equipment.metadata, dict):
        return str(equipment.metadata.get("map_node") or fallback)
    return fallback


def _crib_node_code() -> str:
    from Operations.models import Equipment

    crib = Equipment.objects.filter(code=TOOL_CRIB_EQUIPMENT_CODE).first()
    return _node_code_of(crib, TOOL_CRIB_NODE_CODE)


class ToolError(ValueError):
    """换刀流程异常。"""


def recommend(tool: Tool, next_task_minutes: float = 90.0) -> dict:
    """换刀建议：磨损阈值 + 剩余寿命能否覆盖下一单。"""
    next_task_minutes = max(float(next_task_minutes or 0), 0.0)
    remaining = tool.remaining_minutes
    reasons: list[str] = []

    if tool.wear_ratio >= tool.threshold:
        reasons.append(
            f"磨损率 {tool.wear_ratio:.2f} 已达阈值 {tool.threshold:.2f}"
        )
    if remaining <= 0:
        reasons.append("额定寿命已用尽")
    elif remaining < next_task_minutes:
        reasons.append(
            f"剩余寿命 {remaining:.0f} 分钟 < 下一单需求 {next_task_minutes:.0f} 分钟"
        )
    elif remaining < next_task_minutes * 2:
        reasons.append(
            f"剩余寿命 {remaining:.0f} 分钟不足以覆盖两单（{next_task_minutes:.0f} 分钟/单）"
        )

    if tool.wear_ratio >= tool.threshold or remaining <= 0 or remaining < next_task_minutes:
        decision = "change_now"
        label = "立即换刀"
        window = "本单结束后、下一单开始前（建议 ≤ 30 分钟窗口）"
    elif remaining < next_task_minutes * 2:
        decision = "change_soon"
        label = "准备换刀"
        window = "下一单开始前安排，可先备刀到刀具库出口"
    else:
        decision = "continue"
        label = "可继续使用"
        window = "无需换刀"

    return {
        "decision": decision,
        "decision_label": label,
        "reasons": reasons,
        "remaining_minutes": round(remaining, 1),
        "required_minutes": round(next_task_minutes, 1),
        "suggested_window": window,
        "can_continue": decision == "continue",
        "needs_dispatch": decision != "continue" and tool.status != Tool.Status.PENDING_CHANGE,
    }


@transaction.atomic
def create_change_task(tool: Tool, *, actor: str = "system", notes: str = ""):
    """送新刀：刀具库 → 机床，同时登记一条待完成的换刀记录。"""
    from SchedulingDecision.models import MapNode, TransportTask

    if tool.status == Tool.Status.PENDING_CHANGE:
        raise ToolError("该刀具已经在待换状态，可能已有配送任务。")

    replacement = (
        Tool.objects.filter(equipment__isnull=True, status=Tool.Status.IN_USE)
        .exclude(id=tool.id)
        .order_by("code")
        .first()
    )
    if replacement is None:
        raise ToolError("没有可用的备用刀具，请先在刀具库补一把（equipment 为空的在机刀）")

    equipment = tool.equipment
    equipment_code = equipment.code if equipment else "未绑定设备"
    node_code = _node_code_of(equipment, DEFAULT_EQUIPMENT_NODE_CODE)
    crib_code = _crib_node_code()

    pickup = MapNode.objects.filter(code=crib_code).first()
    dropoff = MapNode.objects.filter(code=node_code).first()
    if pickup is None or dropoff is None:
        raise ToolError(f"地图节点缺失：刀具库 {crib_code} 或机床站点 {node_code}")
    if pickup.id == dropoff.id:
        raise ToolError("刀具库与机床站点相同，无法生成配送任务")

    task = TransportTask.objects.create(
        task_no=f"TOOL-{replacement.code}-{uuid.uuid4().hex[:6].upper()}",
        pickup_node=pickup,
        dropoff_node=dropoff,
        cargo_name=f"新刀 {replacement.code}",
        cargo_weight=2,
        priority=3,
        status=TransportTask.Status.PENDING,
        notes=notes or f"换刀配送：{replacement.code} → {equipment_code}（替换 {tool.code}）",
    )
    record = ToolChangeRecord.objects.create(
        equipment=equipment,
        old_tool=tool,
        new_tool=replacement,
        old_wear=tool.wear_ratio,
        old_used_minutes=tool.used_minutes,
        status=ToolChangeRecord.Status.PENDING,
        operator=actor,
        change_task_no=task.task_no,
        note=notes,
    )
    tool.status = Tool.Status.PENDING_CHANGE
    tool.save(update_fields=["status", "updated_at"])
    return task, record


@transaction.atomic
def complete_change(tool: Tool, *, actor: str = "system", destination: str = "刀具库待刃磨") -> ToolChangeRecord:
    """换刀完成：旧刀下机、新刀装上，记录旧刀磨损与去向。"""
    record = (
        ToolChangeRecord.objects.filter(old_tool=tool, status=ToolChangeRecord.Status.PENDING)
        .order_by("-id")
        .first()
    )
    if record is None or record.new_tool is None:
        # 兜底：没有登记记录时，仍按“寿命复位”处理
        tool.wear_ratio = 0.0
        tool.used_minutes = 0.0
        tool.status = Tool.Status.IN_USE
        tool.changed_at = timezone.now()
        tool.save(update_fields=["wear_ratio", "used_minutes", "status", "changed_at", "updated_at"])
        return None

    equipment = tool.equipment
    old_code, new_code = tool.code, record.new_tool.code

    tool.status = Tool.Status.CHANGED
    tool.equipment = None
    tool.notes = f"{tool.notes}\n[{timezone.now():%Y-%m-%d %H:%M}] 换下，去向：{destination}".strip()
    tool.save(update_fields=["status", "equipment", "notes", "updated_at"])

    new_tool = record.new_tool
    new_tool.equipment = equipment
    new_tool.status = Tool.Status.IN_USE
    new_tool.wear_ratio = 0.0
    new_tool.used_minutes = 0.0
    new_tool.changed_at = timezone.now()
    new_tool.save(update_fields=["equipment", "status", "wear_ratio", "used_minutes",
                                 "changed_at", "updated_at"])

    record.status = ToolChangeRecord.Status.DONE
    record.completed_at = timezone.now()
    record.operator = actor or record.operator
    record.note = f"{record.note}\n[{timezone.now():%Y-%m-%d %H:%M}] {old_code} 下机 → {new_code} 装机".strip()
    record.save(update_fields=["status", "completed_at", "operator", "note"])
    return record


@transaction.atomic
def create_return_task(record: ToolChangeRecord, *, actor: str = "system") -> "object":
    """旧刀回收：机床站点 → 刀具库，自动带上旧刀编号。"""
    from SchedulingDecision.models import MapNode, TransportTask

    if record.status != ToolChangeRecord.Status.DONE:
        raise ToolError("换刀还没完成，不能回收旧刀")
    if record.return_task_no:
        raise ToolError(f"已经生成过回收任务（{record.return_task_no}）")
    if record.old_tool is None:
        raise ToolError("该记录没有旧刀信息")

    machine_code = _node_code_of(record.equipment, DEFAULT_EQUIPMENT_NODE_CODE)
    crib_code = _crib_node_code()
    pickup = MapNode.objects.filter(code=machine_code).first()
    dropoff = MapNode.objects.filter(code=crib_code).first()
    if pickup is None or dropoff is None:
        raise ToolError(f"地图节点缺失：机床 {machine_code} 或刀具库 {crib_code}")

    task = TransportTask.objects.create(
        task_no=f"RET-{record.old_tool.code}-{uuid.uuid4().hex[:6].upper()}",
        pickup_node=pickup,
        dropoff_node=dropoff,
        cargo_name=f"旧刀 {record.old_tool.code}（待刃磨）",
        cargo_weight=2,
        priority=2,
        status=TransportTask.Status.PENDING,
        notes=f"旧刀回收：{record.old_tool.code} → {crib_code}（磨损 {record.old_wear:.0%}）",
    )
    record.return_task_no = task.task_no
    record.save(update_fields=["return_task_no"])
    return task


def sync_from_diagnosis(equipment, feature_summary, series=None) -> list[dict]:
    """把在线诊断算出的刀具磨损写回在机刀具（换刀闭环的第一环）。"""
    if equipment is None:
        return []
    tools = list(
        Tool.objects.filter(equipment=equipment).exclude(
            status__in=[Tool.Status.CHANGED, Tool.Status.RETIRED]
        )
    )
    if not tools:
        return []

    entry = (feature_summary or {}).get("tool_wear") or {}
    wear = entry.get("mean")
    if wear is None:
        wear = entry.get("latest")
    if wear is None and series:
        values = [
            float(row["tool_wear"]) for row in series
            if isinstance(row, dict) and isinstance(row.get("tool_wear"), (int, float))
        ]
        wear = sum(values) / len(values) if values else None
    if wear is None:
        return []

    wear = max(0.0, min(float(wear), 1.0))
    updates = []
    for tool in tools:
        old = tool.wear_ratio
        tool.wear_ratio = round(wear, 4)
        tool.used_minutes = round(min(wear * tool.life_minutes, tool.life_minutes), 1)
        tool.save(update_fields=["wear_ratio", "used_minutes", "updated_at"])
        updates.append({
            "code": tool.code,
            "old_wear": round(old, 3),
            "new_wear": round(wear, 3),
            "remaining_minutes": round(tool.remaining_minutes, 1),
        })
    return updates
