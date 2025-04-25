
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import HealthProgramViewSet, EnrollmentViewSet

router = DefaultRouter()
router.register(r'programs', HealthProgramViewSet)
router.register(r'enrollments', EnrollmentViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
