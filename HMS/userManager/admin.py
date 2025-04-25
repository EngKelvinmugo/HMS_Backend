from django.contrib import admin
from .models import CustomUser, Address, Doctor, Client, TimeRange
from django.contrib.auth.admin import UserAdmin

# Address Admin
@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ['id', 'city', 'state', 'country', 'postal_code']
    search_fields = ['city', 'state', 'country', 'postal_code']
    list_filter = ['country', 'state']

# Custom User Admin
@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ['email', 'username', 'first_name', 'last_name', 'role', 'phone', 'is_active', 'is_staff']
    list_editable = ['role']  # Allow inline editing of role
    list_filter = ['role', 'is_active', 'is_staff']
    search_fields = ['email', 'username', 'first_name', 'last_name']
    ordering = ['email']

    fieldsets = UserAdmin.fieldsets + (
        (None, {'fields': ('role', 'phone', 'profile_image', 'address')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (None, {'fields': ('role', 'phone', 'profile_image', 'address')}),
    )

# Doctor Admin
@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):
    list_display = ['id', 'get_name', 'specialization', 'license_number', 'experience_years']
    search_fields = ['user__first_name', 'user__last_name', 'license_number', 'specialization']
    list_filter = ['specialization', 'experience_years']
    raw_id_fields = ['user', 'working_hours']

    def get_name(self, obj):
        return obj.user.get_full_name()
    get_name.short_description = 'Doctor Name'

# Client Admin
@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ['id', 'get_name', 'national_id', 'date_of_birth']
    search_fields = ['user__first_name', 'user__last_name', 'national_id']
    raw_id_fields = ['user']

    def get_name(self, obj):
        return obj.user.get_full_name()
    get_name.short_description = 'Client Name'

# TimeRange Admin (optional)
@admin.register(TimeRange)
class TimeRangeAdmin(admin.ModelAdmin):
    list_display = ['id', 'start', 'end']
    search_fields = ['start', 'end']
