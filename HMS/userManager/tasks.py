from celery import shared_task
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

@shared_task
def send_mass_registration_email(user_email, context):
    """Send an email with a password reset link."""
    
    subject = f"Your Account Has Been Created on {context['sitename']} - Reset Your Password"
    from_email = f"no-reply@{context['sitename'].lower()}.com"
    
    # Render email template
    html_message = render_to_string("emails/registration_email.html", context)

    # Create email
    email = EmailMultiAlternatives(subject, "", from_email, [user_email])
    email.attach_alternative(html_message, "text/html")
    
    # Send email
    email.send()