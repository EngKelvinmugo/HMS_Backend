from django.contrib import admin
from .models import HealthProgram, Enrollment

@admin.register(HealthProgram)
class HealthProgramAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'is_active', 'created_at']
    search_fields = ['name']
    list_filter = ['is_active']

@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ['id', 'client', 'program', 'date_enrolled', 'active']
    search_fields = ['client__user__first_name', 'client__user__last_name', 'program__name']
    list_filter = ['program', 'active']
