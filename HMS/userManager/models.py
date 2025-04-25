from django.db import models
from django.contrib.auth.models import AbstractUser
import uuid
from django.db.models.signals import post_save
from django.dispatch import receiver

# Address Model (Reusable)
class Address(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    street = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100, blank=True, null=True)
    country = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20, blank=True, null=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)

    def __str__(self):
        return f"{self.city}, {self.country}"

# Custom User Model
class CustomUser(AbstractUser):
    ROLE_CHOICES = (
        ('admin', 'Admin'),
        ('doctor', 'Doctor'),
        ('client', 'Client'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    phone = models.CharField(max_length=15, blank=True, null=True)
    role = models.CharField(max_length=15, choices=ROLE_CHOICES, default='client')
    profile_image = models.ImageField(upload_to='profile_images/', blank=True, null=True)
    address = models.ForeignKey(Address, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username', 'first_name', 'last_name']

    def __str__(self):
        return f"{self.get_full_name()} ({self.email})"

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"

# Time Range (optional, used if needed)
class TimeRange(models.Model):
    start = models.TimeField(default='09:00')
    end = models.TimeField(default='17:00')

    def __str__(self):
        return f"{self.start} - {self.end}"

# Doctor Model
class Doctor(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, limit_choices_to={'role': 'doctor'})
    specialization = models.CharField(max_length=100)
    license_number = models.CharField(max_length=50, unique=True)
    experience_years = models.PositiveIntegerField(default=0)
    working_hours = models.OneToOneField(TimeRange, on_delete=models.CASCADE, related_name='doctor_working_hours', null=True, blank=True)
    bio = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Dr. {self.user.get_full_name()} - {self.specialization}"

# Client Model
class Client(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, limit_choices_to={'role': 'client'})
    national_id = models.CharField(max_length=20, unique=True)
    date_of_birth = models.DateField(null=True, blank=True)
    medical_history = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.user.get_full_name()

# Signal to auto-create default working hours for doctors
@receiver(post_save, sender=Doctor)
def create_default_doctor_hours(sender, instance, created, **kwargs):
    if created and not instance.working_hours:
        default_hours = TimeRange.objects.create(start='09:00', end='17:00')
        instance.working_hours = default_hours
        instance.save()
