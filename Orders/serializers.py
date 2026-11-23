import re

from rest_framework import serializers

from SchedulingDecision.models import MapNode, TransportTask

from .models import Customer, Order, OrderEvent
from .services import OrderError, create_order, update_pending_order


def mask_customer_name(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) == 1:
        return f"{value}*"
    if len(value) == 2:
        return f"{value[0]}*"
    return f"{value[0]}{'*' * (len(value) - 2)}{value[-1]}"


def mask_phone(value: str) -> str:
    value = value or ""
    if len(value) < 7:
        return "*" * len(value)
    return f"{value[:3]}****{value[-4:]}"


class CustomerSerializer(serializers.ModelSerializer):
    masked_phone = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = ["id", "name", "phone", "masked_phone", "created_at"]
        read_only_fields = fields

    def get_masked_phone(self, obj):
        return mask_phone(obj.phone)


class OrderEventSerializer(serializers.ModelSerializer):
    event_type_display = serializers.CharField(
        source="get_event_type_display", read_only=True
    )
    from_status_display = serializers.SerializerMethodField()
    to_status_display = serializers.SerializerMethodField()

    class Meta:
        model = OrderEvent
        fields = [
            "id",
            "event_type",
            "event_type_display",
            "from_status",
            "from_status_display",
            "to_status",
            "to_status_display",
            "title",
            "description",
            "occurred_at",
        ]
        read_only_fields = fields

    def get_from_status_display(self, obj):
        return dict(TransportTask.Status.choices).get(obj.from_status, obj.from_status)

    def get_to_status_display(self, obj):
        return dict(TransportTask.Status.choices).get(obj.to_status, obj.to_status)


class PublicOrderEventSerializer(serializers.ModelSerializer):
    event_type_display = serializers.CharField(
        source="get_event_type_display", read_only=True
    )

    class Meta:
        model = OrderEvent
        fields = ["event_type", "event_type_display", "title", "description", "occurred_at"]
        read_only_fields = fields


class OrderTaskSummarySerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    assigned_agv_code = serializers.CharField(
        source="assigned_agv.code", read_only=True, allow_null=True
    )

    class Meta:
        model = TransportTask
        fields = [
            "id",
            "task_no",
            "status",
            "status_display",
            "assigned_agv_code",
            "scheduled_start",
            "scheduled_end",
            "started_at",
            "completed_at",
            "total_distance",
            "estimated_duration",
        ]
        read_only_fields = fields


class NodeSummarySerializer(serializers.ModelSerializer):
    node_type_display = serializers.CharField(source="get_node_type_display", read_only=True)

    class Meta:
        model = MapNode
        fields = ["id", "code", "name", "node_type", "node_type_display"]
        read_only_fields = fields


class OrderSerializer(serializers.ModelSerializer):
    customer = CustomerSerializer(read_only=True)
    customer_name = serializers.CharField(write_only=True, required=False, allow_blank=False)
    customer_phone = serializers.CharField(write_only=True, required=False, allow_blank=False)
    pickup_node_detail = NodeSummarySerializer(source="pickup_node", read_only=True)
    dropoff_node_detail = NodeSummarySerializer(source="dropoff_node", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    priority_display = serializers.CharField(source="get_priority_display", read_only=True)
    transport_task = serializers.SerializerMethodField()
    events = OrderEventSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "order_no",
            "customer",
            "customer_name",
            "customer_phone",
            "cargo_name",
            "cargo_weight",
            "pickup_node",
            "pickup_node_detail",
            "dropoff_node",
            "dropoff_node_detail",
            "priority",
            "priority_display",
            "notes",
            "status",
            "status_display",
            "transport_task",
            "events",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "order_no",
            "customer",
            "status",
            "transport_task",
            "events",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "cargo_weight": {"min_value": 0.1},
        }

    def get_transport_task(self, obj):
        try:
            task = obj.transport_task
        except TransportTask.DoesNotExist:
            return None
        return OrderTaskSummarySerializer(task).data

    def validate(self, attrs):
        if self.instance is not None:
            if self.instance.status != TransportTask.Status.PENDING:
                raise serializers.ValidationError("只有待调度订单可以修改。")
            if "customer_name" in attrs or "customer_phone" in attrs:
                raise serializers.ValidationError("订单提交后不能修改客户身份信息。")

        pickup = attrs.get("pickup_node", getattr(self.instance, "pickup_node", None))
        dropoff = attrs.get("dropoff_node", getattr(self.instance, "dropoff_node", None))
        if pickup and dropoff and pickup.pk == dropoff.pk:
            raise serializers.ValidationError("取货点和放货点不能相同。")
        if pickup and not pickup.is_active:
            raise serializers.ValidationError({"pickup_node": "取货点未启用。"})
        if dropoff and not dropoff.is_active:
            raise serializers.ValidationError({"dropoff_node": "放货点未启用。"})

        if self.instance is None:
            missing = [
                field for field in ("customer_name", "customer_phone")
                if not attrs.get(field)
            ]
            if missing:
                raise serializers.ValidationError(
                    {field: "该字段为必填项。" for field in missing}
                )
        return attrs

    def create(self, validated_data):
        try:
            return create_order(**validated_data)
        except (OrderError, ValueError) as exc:
            raise serializers.ValidationError({"detail": str(exc)}) from exc

    def update(self, instance, validated_data):
        try:
            return update_pending_order(instance.pk, **validated_data)
        except OrderError as exc:
            raise serializers.ValidationError({"detail": str(exc)}) from exc


class PublicOrderSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()
    customer_phone = serializers.SerializerMethodField()
    pickup_point = serializers.CharField(source="pickup_node.name", read_only=True)
    dropoff_point = serializers.CharField(source="dropoff_node.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    priority_display = serializers.CharField(source="get_priority_display", read_only=True)
    scheduled_start = serializers.SerializerMethodField()
    scheduled_end = serializers.SerializerMethodField()
    events = PublicOrderEventSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = [
            "order_no",
            "customer_name",
            "customer_phone",
            "cargo_name",
            "cargo_weight",
            "pickup_point",
            "dropoff_point",
            "priority_display",
            "status",
            "status_display",
            "scheduled_start",
            "scheduled_end",
            "events",
            "created_at",
        ]
        read_only_fields = fields

    def get_customer_name(self, obj):
        return mask_customer_name(obj.customer.name)

    def get_customer_phone(self, obj):
        return mask_phone(obj.customer.phone)

    def get_scheduled_start(self, obj):
        try:
            return obj.transport_task.scheduled_start
        except TransportTask.DoesNotExist:
            return None

    def get_scheduled_end(self, obj):
        try:
            return obj.transport_task.scheduled_end
        except TransportTask.DoesNotExist:
            return None


class OrderLookupSerializer(serializers.Serializer):
    order_no = serializers.CharField(max_length=32, trim_whitespace=True)
    phone_tail = serializers.CharField(max_length=4, min_length=4, trim_whitespace=True)

    def validate_order_no(self, value):
        return value.upper()

    def validate_phone_tail(self, value):
        if not re.fullmatch(r"\d{4}", value):
            raise serializers.ValidationError("手机尾号必须是四位数字。")
        return value
