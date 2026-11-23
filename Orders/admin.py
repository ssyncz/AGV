from django.contrib import admin

from .models import Customer, Order, OrderEvent


class OrderEventInline(admin.TabularInline):
    model = OrderEvent
    extra = 0
    readonly_fields = (
        "event_type",
        "from_status",
        "to_status",
        "title",
        "description",
        "occurred_at",
    )
    can_delete = False


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "created_at")
    search_fields = ("name", "phone")
    readonly_fields = ("created_at",)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_no",
        "customer",
        "cargo_name",
        "pickup_node",
        "dropoff_node",
        "priority",
        "status",
        "created_at",
    )
    list_filter = ("status", "priority", "created_at")
    search_fields = ("order_no", "cargo_name", "customer__name", "customer__phone")
    readonly_fields = ("order_no", "status", "created_at", "updated_at")
    inlines = [OrderEventInline]


@admin.register(OrderEvent)
class OrderEventAdmin(admin.ModelAdmin):
    list_display = ("order", "event_type", "title", "from_status", "to_status", "occurred_at")
    list_filter = ("event_type", "to_status")
    search_fields = ("order__order_no", "title", "description")
    readonly_fields = (
        "order",
        "event_type",
        "from_status",
        "to_status",
        "title",
        "description",
        "occurred_at",
    )
