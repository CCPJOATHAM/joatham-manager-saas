from rest_framework.routers import DefaultRouter

from .views import FactureViewSet

router = DefaultRouter()
router.register("factures", FactureViewSet, basename="api-factures")

urlpatterns = router.urls
