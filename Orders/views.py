from django.db.models import Q
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from SchedulingDecision.models import TransportTask

from .models import Order
from .serializers import OrderLookupSerializer, OrderSerializer, PublicOrderSerializer
from .services import OrderError, cancel_order


class OrderViewSet(viewsets.ModelViewSet):
    serializer_class = OrderSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]
    throttle_scope = "order_lookup"

    def get_throttles(self):
        if self.action == "lookup":
            return [ScopedRateThrottle()]
        return super().get_throttles()

    def get_queryset(self):
        queryset = (
            Order.objects.select_related(
                "customer",
                "pickup_node",
                "dropoff_node",
                "transport_task",
                "transport_task__assigned_agv",
            )
            .prefetch_related("events")
            .order_by("-created_at")
        )
        status = self.request.query_params.get("status", "").strip()
        if status in TransportTask.Status.values:
            queryset = queryset.filter(status=status)
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(order_no__icontains=search)
                | Q(cargo_name__icontains=search)
                | Q(customer__name__icontains=search)
                | Q(customer__phone__icontains=search)
            )
        return queryset

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        order = self.get_object()
        try:
            order = cancel_order(order.pk)
        except OrderError as exc:
            return Response({"detail": str(exc)}, status=400)
        refreshed = self.get_queryset().get(pk=order.pk)
        return Response(self.get_serializer(refreshed).data)

    @action(
        detail=False,
        methods=["post"],
    )
    def lookup(self, request):
        serializer = OrderLookupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = (
            Order.objects.select_related(
                "customer",
                "pickup_node",
                "dropoff_node",
                "transport_task",
            )
            .prefetch_related("events")
            .filter(
                order_no=serializer.validated_data["order_no"],
                customer__phone__endswith=serializer.validated_data["phone_tail"],
            )
            .first()
        )
        if order is None:
            raise NotFound("订单号或手机尾号不正确。")
        return Response(PublicOrderSerializer(order).data)
