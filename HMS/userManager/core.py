from django.shortcuts import render, redirect
from django.urls import reverse
from allauth.account.models import EmailConfirmationHMAC, EmailConfirmation
from rest_framework import  status
from rest_framework.response import Response
from .serializers import ResendEmailVerificationSerializer,CustomTokenRefreshSerializer
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.decorators import action
from dj_rest_auth.views import PasswordResetView
from django.conf import settings
from rest_framework_simplejwt.views import TokenRefreshView
from allauth.account.models import EmailAddress  # Import EmailAddress from allauth
from django.utils.translation import gettext_lazy as _
from rest_framework.pagination import PageNumberPagination

class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100
class CustomTokenRefreshView(TokenRefreshView):
    serializer_class = CustomTokenRefreshSerializer
    
class CustomPasswordResetView(PasswordResetView):
    def get_email_options(self):
        email_options = super().get_email_options()
        email_options['extra_email_context'] = {
            'frontend_domain': settings.FRONTEND_DOMAIN
        }
        return email_options
def confirm_email(request, key):
    """
    View to handle email confirmation from a unique key.
    
    If the key is valid and the confirmation is successful,
    the user is redirected to the 'email_confirmation_done' page.
    """
    try:
        confirmation = EmailConfirmationHMAC.from_key(key)
        if confirmation:
            confirmation.confirm(request)
            return redirect(reverse('email_confirmation_done'))
        else:
            return redirect(reverse('email_confirmation_failure'))
        
    except EmailConfirmation.DoesNotExist:
        pass

    return render(request, 'account/confirm_email.html', {'key': key})

def email_confirmation_done(request):
    """
    View to render a success page after email confirmation.
    """
    return render(request, 'account/email_confirmation_done.html')
def email_confirmation_failure(request):
    """
    View to render a success page after email confirmation.
    """
    return render(request, 'account/email_confirmation_failure.html')

class CustomPasswordResetConfirmView(APIView):
    """
    View to render password reset confirmation form and handle password reset logic.
    """

    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        uidb64 = kwargs.get('uidb64')
        token = kwargs.get('token')

        # Render password reset form with uidb64 and token
        return render(request, 'account/password_reset_confirmation.html', {
            'uid': uidb64,
            'token': token,
        })


  
class ResendEmailVerificationView(APIView):
    """
    Resends another email to an unverified email.
    Accepts the following POST parameter: email.
    """

    permission_classes = (AllowAny,)
    serializer_class = ResendEmailVerificationSerializer

    def post(self, request, *args, **kwargs):
        # Instantiate the serializer with the request data
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Retrieve the email from the validated data
        email = serializer.validated_data['email']

        # Check if the email exists and is not verified
        email_obj = EmailAddress.objects.filter(email=email).first()
        if email_obj and not email_obj.verified:
            # Send the confirmation email if not already verified
            email_obj.send_confirmation(request)
            return Response({'detail': _('A new confirmation email has been sent.')}, status=status.HTTP_200_OK)

        return Response({'detail': _('Email not found or already verified.')}, status=status.HTTP_400_BAD_REQUEST)