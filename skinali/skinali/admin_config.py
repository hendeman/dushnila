from django.contrib.admin.apps import AdminConfig


class SkinaliAdminConfig(AdminConfig):
    default_site = 'skinali.admin_site.SkinaliAdminSite'
