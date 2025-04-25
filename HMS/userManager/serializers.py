from rest_framework import serializers
from dj_rest_auth.registration.serializers import RegisterSerializer
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from django.core.exceptions import ObjectDoesNotExist
from rest_framework.exceptions import ValidationError
from .models import Doctor, Client, Address

User = get_user_model()

class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        fields = '__all__'

class CustomRegisterSerializer(RegisterSerializer):
    role = serializers.ChoiceField(choices=User.ROLE_CHOICES)
    phone = serializers.CharField(required=False, allow_blank=True)
    address = AddressSerializer(required=False)

    # Doctor-specific fields
    specialization = serializers.CharField(required=False)
    license_number = serializers.CharField(required=False)

    # Client-specific fields
    national_id = serializers.CharField(required=False)
    date_of_birth = serializers.DateField(required=False)

    class Meta:
        model = User
        fields = [
            "email", "password1", "password2", "role",
            "first_name", "last_name", "phone", "address",
            "specialization", "license_number",
            "national_id", "date_of_birth",
        ]

    def validate(self, attrs):
        role = attrs.get("role")
        if role == "doctor":
            if not attrs.get("specialization") or not attrs.get("license_number"):
                raise serializers.ValidationError("Doctors must provide specialization and license number.")
        elif role == "client":
            if not attrs.get("national_id") or not attrs.get("date_of_birth"):
                raise serializers.ValidationError("Clients must provide national ID and date of birth.")
        return super().validate(attrs)

    def custom_signup(self, request, user):
        user.role = self.validated_data.get("role")
        user.phone = self.validated_data.get("phone")

        address_data = self.validated_data.get("address")
        if address_data:
            address = Address.objects.create(**address_data)
            user.address = address

        user.save()

        if user.role == "doctor":
            Doctor.objects.create(
                user=user,
                specialization=self.validated_data.get("specialization"),
                license_number=self.validated_data.get("license_number")
            )
        elif user.role == "client":
            Client.objects.create(
                user=user,
                national_id=self.validated_data.get("national_id"),
                date_of_birth=self.validated_data.get("date_of_birth")
            )
        return user


class UserUpdateSerializer(serializers.ModelSerializer):
    address = AddressSerializer(required=False)

    class Meta:
        model = User
        fields = ["phone", "address"]

    def update(self, instance, validated_data):
        address_data = validated_data.pop('address', None)
        if address_data:
            if instance.address:
                for attr, value in address_data.items():
                    setattr(instance.address, attr, value)
                instance.address.save()
            else:
                instance.address = Address.objects.create(**address_data)
        return super().update(instance, validated_data)

class UserSerializer(serializers.ModelSerializer):
    address = AddressSerializer()

    class Meta:
        model = User
        fields = [
            "id", "email", "first_name", "last_name",
            "role", "phone", "address", "date_joined"
        ]

class ResendEmailVerificationSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        if not User.objects.filter(email=value).exists():
            raise serializers.ValidationError("No account found with this email.")
        return value

class CustomTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        try:
            return super().validate(attrs)
        except ObjectDoesNotExist:
            raise ValidationError("User no longer exists.")
