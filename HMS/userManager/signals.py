from django.db.models.signals import post_migrate, post_save, pre_save
from django.dispatch import receiver
from django.contrib.auth.models import Group
from django.conf import settings
from .models import CustomUser
from django.contrib.sites.models import Site

@receiver(post_migrate)
def update_default_site(sender, **kwargs):
    """
    Update the default site with the name and domain specified in settings.
    """
    if hasattr(settings, "SITE_ID") and hasattr(settings, "SITENAME"):
        site_id = getattr(settings, "SITE_ID", 1)
        site_name = getattr(settings, "SITENAME", "Default Site Name")
        site_domain = getattr(settings, "SITE_DOMAIN", "example.com")
        
        try:
            site = Site.objects.get(id=site_id)
            site.name = site_name
            site.domain = site_domain
            site.save()
        except Site.DoesNotExist:
            Site.objects.create(id=site_id, name=site_name, domain=site_domain)
@receiver(post_migrate)
def create_admin(sender, **kwargs):
    # Create default admin user if it doesn't exist
    if not CustomUser.objects.filter(username='admin').exists():
        admin_user = CustomUser.objects.create_superuser(
            username='admin',
            email='admin@gmail.com',
            password=settings.ADMIN_PASSWORD,  # Use environment variable or settings
            role = 'admin'
        )
        admin_user.save()
        print(f"Default admin user created: {admin_user}")
    else:
        pass

@receiver(post_migrate)
def create_default_user_groups(sender, **kwargs):
    """Ensure all role-based groups exist after migrations."""
    if sender.name == "users":  # Only run for this app
        role_names = [role[0] for role in CustomUser.ROLE_CHOICES]
        
        for role in role_names:
            group, created = Group.objects.get_or_create(name=role)
            if created:
                print(f"Created missing group: {role}")  # Debugging log