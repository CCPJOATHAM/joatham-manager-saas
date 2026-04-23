from rest_framework.routers import DefaultRouter

from .views import ClientViewSet


router = DefaultRouter()
router.register("clients", ClientViewSet, basename="api-clients")

urlpatterns = router.urls
