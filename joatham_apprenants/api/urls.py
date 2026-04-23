from rest_framework.routers import DefaultRouter

from .views import ApprenantViewSet, FormationViewSet, InscriptionViewSet


router = DefaultRouter()
router.register("apprenants", ApprenantViewSet, basename="api-apprenants")
router.register("formations", FormationViewSet, basename="api-formations")
router.register("inscriptions", InscriptionViewSet, basename="api-inscriptions")

urlpatterns = router.urls
