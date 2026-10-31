from django.conf import settings
from django.db import models
from django.utils import timezone
from .task import validate_task_options
from django.utils.translation import gettext_lazy as _

class Preset(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, blank=True, null=True, on_delete=models.CASCADE, help_text=_("The person who owns this preset"), verbose_name=_("Owner"))
    name = models.CharField(max_length=255, blank=False, null=False, help_text=_("A label used to describe the preset"), verbose_name=_("Name"))
    options = models.JSONField(default=list, blank=True, help_text=_("Options that define this preset (same format as in a Task's options)."), verbose_name=_("Options"),
                               validators=[validate_task_options])
    created_at = models.DateTimeField(default=timezone.now, help_text=_("Creation date"), verbose_name=_("Created at"))
    system = models.BooleanField(db_index=True, default=False, help_text=_("Whether this preset is available to every user in the system or just to its owner."), verbose_name=_("System"))

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = _("Preset")
        verbose_name_plural = _("Presets")
