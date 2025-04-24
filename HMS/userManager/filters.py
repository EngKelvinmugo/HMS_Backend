import django_filters
from .models import CustomUser

class UserFilter(django_filters.FilterSet):
    """Filter users by role, location, and verification status"""
    role = django_filters.ChoiceFilter(choices=CustomUser.ROLE_CHOICES)
    location = django_filters.CharFilter(lookup_expr='icontains')
    is_verified = django_filters.BooleanFilter()

    class Meta:
        model = CustomUser
        fields = ["role", "location", "is_verified"]