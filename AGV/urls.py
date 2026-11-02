from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path


api_patterns = [
    path('operations/', include('Operations.urls')),
    path('', include('SchedulingDecision.urls')),
    path('vision/', include('ManufacturingVision.urls')),
    path('equipment/', include('EquipmentMonitoring.urls')),
    path('forecast/', include('DemandForecast.urls')),
]

urlpatterns = [
    path('admin/', admin.site.urls),
    # 保留 /api/ 兼容现有前端和课程演示，同时提供版本化入口。
    path('api/', include(api_patterns)),
    path('api/v1/', include(api_patterns)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
