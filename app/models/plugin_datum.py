from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _

class PluginDatum(models.Model):
    key = models.CharField(max_length=255, help_text=_("Setting key"), db_index=True, verbose_name=_("Key"))
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, default=None, on_delete=models.CASCADE, help_text=_("The user this setting belongs to. If NULL, the setting is global."), verbose_name=_("User"))
    int_value = models.IntegerField(blank=True, null=True, default=None, verbose_name=_("Integer value"))
    float_value = models.FloatField(blank=True, null=True, default=None, verbose_name=_("Float value"))
    bool_value = models.BooleanField(blank=True, null=True, default=None, verbose_name=_("Bool value"))
    string_value = models.TextField(blank=True, null=True, default=None, verbose_name=_("String value"))
    json_value = models.JSONField(default=None, blank=True, null=True, verbose_name=_("JSON value"))

    def __str__(self):
        return self.key

    class Meta:
        verbose_name = _("Plugin Datum")
        verbose_name_plural = _("Plugin Datum")