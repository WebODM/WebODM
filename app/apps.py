import os
from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _

class MainConfig(AppConfig):
    name = 'app'
    verbose_name = _('Application')

    def ready(self):
        from webodm import settings
        if not settings.DEV:
            return

        from django.utils import autoreload

        autoreload.autoreload_started.disconnect(dispatch_uid="template_loaders_watch_changes")

        def watch_templates(sender, **kwargs):
            sender.watch_dir(os.path.join(settings.BASE_DIR, 'app', 'templates'), '**/*')
            sender.watch_dir(os.path.join(settings.BASE_DIR, 'coreplugins'), '*/templates/**/*')

        autoreload.autoreload_started.connect(watch_templates, weak=False)
