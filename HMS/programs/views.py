from django.shortcuts import render

# Create your views here.
from rest_framework import viewsets
from .models import HealthProgram, Enrollment
from .serializers import HealthProgramSerializer, EnrollmentSerializer
from rest_framework.permissions import IsAuthenticated

class HealthProgramViewSet(viewsets.ModelViewSet):
    queryset = HealthProgram.objects.all()
    serializer_class = HealthProgramSerializer
    permission_classes = [IsAuthenticated]

class EnrollmentViewSet(viewsets.ModelViewSet):
    queryset = Enrollment.objects.all()
    serializer_class = EnrollmentSerializer
    permission_classes = [IsAuthenticated]
