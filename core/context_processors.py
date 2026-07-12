from .models import Company, AppSettings
from . import sync_service


def site_context(request):
    """Injects sidebar globals into every template — no need to pass them from each view."""
    company = Company.objects.filter(is_default=True, is_active=True).first()
    settings = AppSettings.get()
    return {
        "site_company": company,
        "site_app_version": "1.5.1",
        "app_settings": settings,
        "sync_status": sync_service.get_status(settings),
        "catalog_nav_items": [
            "preparati", "rabotnici", "lichni_danni",
           "vrediteli", "nehim",
        ]
    }