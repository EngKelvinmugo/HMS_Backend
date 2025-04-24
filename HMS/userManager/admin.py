from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser

class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ("email", "role", "phone_number", "address", "is_verified", "date_joined")
    list_filter = ("role", "is_verified", "date_joined")
    search_fields = ("email", "phone_number", "address", "specialization")
    ordering = ("-date_joined",)

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal Info", {
            "fields": ("phone_number", "address", "specialization", "age")
        }),
        ("Permissions", {
            "fields": ("role", "is_verified", "is_staff", "is_superuser", "groups", "user_permissions")
        }),
        ("Important Dates", {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "password1", "password2", "role", "phone_number", "address", "specialization", "age"),
        }),
    )

admin.site.register(CustomUser, CustomUserAdmin)
