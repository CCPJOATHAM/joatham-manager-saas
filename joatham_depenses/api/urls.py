from rest_framework.routers import DefaultRouter

from .views import DepenseViewSet


router = DefaultRouter()
router.register("depenses", DepenseViewSet, basename="api-depenses")

urlpatterns = router.urls
