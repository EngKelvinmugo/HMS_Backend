from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.permissions import IsAuthenticated, AllowAny
from dj_rest_auth.registration.views import RegisterView
from .models import CustomUser
from .serializers import UserSerializer, UserUpdateSerializer, CustomRegisterSerializer

class UserViewSet(viewsets.ModelViewSet):
    queryset = CustomUser.objects.all().order_by("-date_joined")
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    search_fields = ["email", "phone", "first_name", "last_name", "role"]

    def get_serializer_class(self):
        if self.action in ["update", "partial_update"]:
            return UserUpdateSerializer
        return UserSerializer

class CustomRegisterView(RegisterView):
    serializer_class = CustomRegisterSerializer
    permission_classes = [AllowAny]
