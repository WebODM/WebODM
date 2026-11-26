import logging
import os
from shutil import rmtree

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import signals
from django.dispatch import receiver
from imagekit.models import ImageSpecField
from imagekit.processors import ResizeToFit
from django.utils.translation import gettext_lazy as _

from webodm import settings
from .theme import Theme, update_theme_css

logger = logging.getLogger('app.logger')


class Setting(models.Model):
    app_name = models.CharField(max_length=255, blank=False, null=False, help_text=_("The name of your application"), verbose_name=_("App name"))
    app_logo = models.ImageField(upload_to="settings/", blank=False, null=False, help_text=_("A 512x512 logo of your application (.png or .jpeg)"), verbose_name=_("App logo"))
    app_logo_36 = ImageSpecField(source='app_logo',
                                      processors=[ResizeToFit(36, 36)],
                                      format='PNG',
                                      options={'quality': 90})
    app_logo_108 = ImageSpecField(source='app_logo',
                                      processors=[ResizeToFit(108, 108)],
                                      format='PNG',
                                      options={'quality': 90})
    app_logo_favicon = ImageSpecField(source='app_logo',
                                      processors=[ResizeToFit(48, 48)],
                                      format='PNG',
                                      options={'quality': 90})

    organization_name = models.CharField(default='WebODM', max_length=255, blank=True, null=True, help_text=_("The name of your organization"), verbose_name=_("Organization name"))
    organization_website = models.URLField(default='https://github.com/WebODM/WebODM/', max_length=255, blank=True, null=True, help_text=_("The website URL of your organization"), verbose_name=_("Organization website"))
    theme = models.ForeignKey(Theme, blank=False, null=False, on_delete=models.DO_NOTHING, verbose_name=_("Theme"),
                              help_text=_("Active theme"))

    def __init__(self, *args, **kwargs):
        super(Setting, self).__init__(*args, **kwargs)

        # To help keep track of changes to the app_logo
        self.__original_app_logo_name = self.app_logo.name

    def save(self, *args, **kwargs):
        # Cleanup old logo files if needed
        if self.__original_app_logo_name != "" and \
                self.app_logo.name != self.__original_app_logo_name and \
                os.path.basename(self.app_logo.name) != os.path.basename(self.__original_app_logo_name): # This last line will leave an old copy in the cache if the filename is the same name as the previous, but we don't care

            old_logo_path = os.path.join(settings.MEDIA_ROOT, self.__original_app_logo_name)
            old_logo_path_caches = os.path.join(settings.MEDIA_ROOT,
                                                "CACHE",
                                                "images",
                                                os.path.splitext(self.__original_app_logo_name)[0])

            if os.path.exists(old_logo_path):
                try:
                    os.unlink(old_logo_path)
                    logger.info("Removed {}".format(old_logo_path))
                except:
                    logger.warning("Cannot cleanup {}".format(old_logo_path))

            if os.path.exists(old_logo_path_caches):
                try:
                    rmtree(old_logo_path_caches)
                    logger.info("Removed {}".format(old_logo_path_caches))
                except:
                    logger.warning("Cannot cleanup {}".format(old_logo_path_caches))

            self.__original_app_logo_name = self.app_logo.name

        super(Setting, self).save(*args, **kwargs)

    def __str__(self):
        return str(_("Application"))
    
    class Meta:
        verbose_name = _("Settings")
        verbose_name_plural = _("Settings")


@receiver(signals.pre_save, sender=Setting, dispatch_uid="setting_pre_save")
def setting_pre_save(sender, instance, **kwargs):
    if Setting.objects.exists() and instance.id != Setting.objects.get().id:
        raise ValidationError("Can only create 1 %s instance" % Setting.__name__)


@receiver(signals.post_save, sender=Setting, dispatch_uid="setting_post_save")
def setting_post_save(sender, instance, created, **kwargs):
    update_theme_css()


