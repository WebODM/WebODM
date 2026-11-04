import os
import json
import tempfile
import zipfile
import shutil
import hashlib

from django.urls import re_path
from django.contrib import admin
from django.contrib import messages
from django.contrib.admin.widgets import AdminFileWidget
from django.core.files import File
from app.geoutils import polygon_to_wkt
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import reverse
from django.utils.html import format_html
from guardian.admin import GuardedModelAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from app.models import PluginDatum
from app.models import Preset
from app.models import Plugin
from app.models import Profile
from app.models import Redirect
from app.models import Basemap
from app.plugins import get_plugin_by_name, enable_plugin, disable_plugin, delete_plugin, valid_plugin, \
    get_plugins_persistent_path, clear_plugins_cache, init_plugins, get_plugins
from .models import Project, Task, Setting, Theme
from django import forms
from webodm import settings
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.utils.translation import gettext_lazy as _, gettext


class ProjectAdmin(GuardedModelAdmin):
    list_display = ('id', 'name', 'owner', 'created_at', 'tasks_count', 'tags')
    list_filter = ('owner',)
    search_fields = ('id', 'name', 'owner__username')


admin.site.register(Project, ProjectAdmin)


class TaskAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    list_display = ('id', 'name', 'project', 'processing_node', 'created_at', 'status', 'last_error')
    list_filter = ('status', 'project',)
    search_fields = ('id', 'name', 'project__name')
    exclude = ('orthophoto_extent', 'dsm_extent', 'dtm_extent', 'crop', )
    readonly_fields = ('orthophoto_extent_wkt', 'dsm_extent_wkt', 'dtm_extent_wkt', 'crop_wkt', )

    def orthophoto_extent_wkt(self, obj):
        return polygon_to_wkt(obj.orthophoto_extent)
    
    def dsm_extent_wkt(self, obj):
        return polygon_to_wkt(obj.dsm_extent)
    
    def dtm_extent_wkt(self, obj):
        return polygon_to_wkt(obj.dtm_extent)
    
    def crop_wkt(self, obj):
        return polygon_to_wkt(obj.crop)

admin.site.register(Task, TaskAdmin)

admin.site.register(Preset, admin.ModelAdmin)


class AppLogoWidget(AdminFileWidget):
    template_name = 'admin/widgets/app_logo_file_input.html'


class SettingAdminForm(forms.ModelForm):
    class Meta:
        model = Setting
        fields = '__all__'
        widgets = {
            'app_logo': AppLogoWidget(),
        }


class SettingAdmin(admin.ModelAdmin):
    form = SettingAdminForm
    fields = ('app_name', 'app_logo', 'app_logo_preview', 'restore_default_logo',
              'organization_name', 'organization_website', 'theme')
    readonly_fields = ('app_logo_preview', 'restore_default_logo')

    @staticmethod
    def set_default_logo(obj):
        default_logo_path = os.path.join(settings.BASE_DIR, 'app', 'static', 'app', 'img', 'logo512.png')
        if not os.path.exists(default_logo_path):
            return False

        with open(default_logo_path, 'rb') as default_logo_file:
            obj.app_logo.save('logo512.png', File(default_logo_file), save=False)
        return True

    def save_model(self, request, obj, form, change):
        if '_restore_default_logo' in request.POST:
            if not self.set_default_logo(obj):
                messages.error(request, _("Cannot restore default logo"))

        super().save_model(request, obj, form, change)

    def app_logo_preview(self, obj):
        if not obj or not obj.app_logo:
            return '-'

        logo_url = obj.app_logo.url
        return format_html(f'<img src="{logo_url}" style="max-height: 64px; padding: 4px; background: {obj.theme.header_background};"/>')

    def restore_default_logo(self, obj):
        return format_html(
            '<button type="submit" style="padding: 6px;" class="button" name="_restore_default_logo" value="1">{}</button>',
            _('Restore Default')
        )

    def has_add_permission(self, request):
        # if there's already an entry, do not allow adding
        return not Setting.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return Setting.objects.count() > 1
    
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.base_fields['theme'].widget.can_add_related = False
        form.base_fields['theme'].widget.can_change_related = False
        form.base_fields['theme'].widget.can_delete_related = False
        
        return form

admin.site.register(Setting, SettingAdmin)


class ThemeModelForm(forms.ModelForm):
    css = forms.CharField(help_text=_("Enter custom CSS"),
                          label=_("CSS"),
                          required=False,
                          widget=forms.Textarea)
    html_before_header = forms.CharField(help_text=_("HTML that will be displayed above site header"),
                                         label=_("HTML (before header)"),
                                         required=False,
                                         widget=forms.Textarea)
    html_after_header = forms.CharField(help_text=_("HTML that will be displayed after site header"),
                                        label=_("HTML (after header)"),
                                        required=False,
                                        widget=forms.Textarea)
    html_after_body = forms.CharField(help_text=_("HTML that will be displayed after the body tag"),
                                      label=_("HTML (after body)"),
                                      required=False,
                                      widget=forms.Textarea)
    html_footer = forms.CharField(help_text=_(
        "HTML that will be displayed in the footer. You can also use the special tags such as {ORGANIZATION} and {YEAR}."),
        label=_("HTML (footer)"),
        required=False,
        widget=forms.Textarea)

    class Meta:
        model = Theme
        fields = '__all__'


class ThemeAdmin(admin.ModelAdmin):
    form = ThemeModelForm

    def has_delete_permission(self, request, obj=None):
        if Theme.objects.count() <= 1:
            return False
        return super().has_delete_permission(request, obj)


admin.site.register(Theme, ThemeAdmin)
admin.site.register(PluginDatum, admin.ModelAdmin)


class BasemapModelForm(forms.ModelForm):
    class Meta:
        model = Basemap
        fields = '__all__'
        widgets = {
            'minzoom': forms.NumberInput(attrs={'min': 0, 'max': 99}),
            'maxzoom': forms.NumberInput(attrs={'min': 0, 'max': 99}),
        }


class BasemapAdmin(admin.ModelAdmin):
    form = BasemapModelForm
    list_display = ('label', 'type', 'maxzoom', 'layers', 'default')
    list_filter = ('type', 'default')
    search_fields = ('label', 'url', 'layers')
    list_display_links = ('label', )

admin.site.register(Basemap, BasemapAdmin)

if settings.CLUSTER_ID is not None:
    admin.site.register(Redirect, admin.ModelAdmin)


class PluginAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "version", "author", "enabled", "plugin_actions")
    readonly_fields = ("name",)
    change_list_template = "admin/change_list_plugin.html"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def description(self, obj):
        manifest = get_plugin_by_name(obj.name, only_active=False, refresh_cache_if_none=True).get_manifest()
        return _(manifest.get('description', ''))

    description.short_description = _("Description")

    def version(self, obj):
        manifest = get_plugin_by_name(obj.name, only_active=False, refresh_cache_if_none=True).get_manifest()
        return manifest.get('version', '')

    version.short_description = _("Version")

    def author(self, obj):
        manifest = get_plugin_by_name(obj.name, only_active=False, refresh_cache_if_none=True).get_manifest()
        return manifest.get('author', '')

    author.short_description = _("Author")

    def changelist_view(self, request, extra_context=None):
        installed = {}
        for p in get_plugins():
            installed[p.get_name()] = p.get_manifest().get('version', '')
        extra_context = extra_context or {}
        extra_context['installed_plugins'] = json.dumps(installed)
        extra_context['webodm_version'] = settings.VERSION
        extra_context['can_build'] = shutil.which("webpack") is not None
        return super().changelist_view(request, extra_context=extra_context)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            re_path(
                r'^(?P<plugin_name>.+)/enable/$',
                self.admin_site.admin_view(self.plugin_enable),
                name='plugin-enable',
            ),
            re_path(
                r'^(?P<plugin_name>.+)/disable/$',
                self.admin_site.admin_view(self.plugin_disable),
                name='plugin-disable',
            ),
            re_path(
                r'^(?P<plugin_name>.+)/delete/$',
                self.admin_site.admin_view(self.plugin_delete),
                name='plugin-delete',
            ),
            re_path(
                r'^actions/upload/$',
                self.admin_site.admin_view(self.plugin_upload),
                name='plugin-upload',
            ),
        ]
        return custom_urls + urls

    def plugin_enable(self, request, plugin_name, *args, **kwargs):
        try:
            p = enable_plugin(plugin_name)
            if p.requires_restart():
                messages.warning(request, _("Restart required. Please restart WebODM to enable %(plugin)s") % {
                    'plugin': plugin_name})
        except Exception as e:
            messages.warning(request, _("Cannot enable plugin %(plugin)s: %(message)s") % {'plugin': plugin_name,
                                                                                           'message': str(e)})

        return HttpResponseRedirect(reverse('admin:app_plugin_changelist'))

    def plugin_disable(self, request, plugin_name, *args, **kwargs):
        try:
            p = disable_plugin(plugin_name)
            if p.requires_restart():
                messages.warning(request, _("Restart required. Please restart WebODM to fully disable %(plugin)s") % {
                    'plugin': plugin_name})
        except Exception as e:
            messages.warning(request, _("Cannot disable plugin %(plugin)s: %(message)s") % {'plugin': plugin_name,
                                                                                            'message': str(e)})

        return HttpResponseRedirect(reverse('admin:app_plugin_changelist'))

    def plugin_delete(self, request, plugin_name, *args, **kwargs):
        try:
            delete_plugin(plugin_name)
        except Exception as e:
            messages.warning(request, _("Cannot delete plugin %(plugin)s: %(message)s") % {'plugin': plugin_name,
                                                                                           'message': str(e)})

        return HttpResponseRedirect(reverse('admin:app_plugin_changelist'))

    def plugin_upload(self, request, *args, **kwargs):
        file = request.FILES.get('file')
        upgrade = request.POST.get('upgrade') == '1'
        as_json = request.POST.get('json') == '1'
        success = False
        level = messages.WARNING
        sha256 = request.POST.get('sha256', '').strip().lower()

        if file is not None:
            tmp_zip_path = tempfile.mktemp('plugin.zip', dir=settings.MEDIA_TMP)
            tmp_extract_path = tempfile.mkdtemp('plugin', dir=settings.MEDIA_TMP)
            tmp_old_path = None

            try:
                with open(tmp_zip_path, 'wb+') as fd:
                    if isinstance(file, InMemoryUploadedFile):
                        for chunk in file.chunks():
                            fd.write(chunk)
                    else:
                        with open(file.temporary_file_path(), 'rb') as f:
                            shutil.copyfileobj(f, fd)

                if sha256:
                    h = hashlib.sha256()
                    with open(tmp_zip_path, 'rb') as f:
                        for chunk in iter(lambda: f.read(1024 * 1024), b''):
                            h.update(chunk)
                    if h.hexdigest() != sha256:
                        raise ValueError("Checksum mismatch. The downloaded file might be corrupted.")

                with zipfile.ZipFile(tmp_zip_path, "r") as zip_h:
                    zip_h.extractall(tmp_extract_path)

                folders = os.listdir(tmp_extract_path)
                if len(folders) != 1:
                    raise ValueError("The plugin has more than 1 root directory (it should have only one)")

                plugin_name = folders[0]
                plugin_path = os.path.join(tmp_extract_path, plugin_name)
                if not valid_plugin(plugin_path):
                    raise ValueError(
                        "This doesn't look like a plugin. Are plugin.py and manifest.json in the proper place?")

                try:
                    with open(os.path.join(plugin_path, "manifest.json")) as f:
                        display_name = json.load(f).get("name") or plugin_name
                except Exception:
                    display_name = plugin_name

                dest_path = get_plugins_persistent_path(plugin_name)
                if os.path.exists(dest_path):
                    if not upgrade:
                        raise ValueError(
                            "A plugin with the name {} already exist. Please remove it before uploading one with the same name.".format(
                                plugin_name))
                    tmp_old_path = tempfile.mkdtemp('plugin_old', dir=settings.MEDIA_TMP)
                    shutil.move(dest_path, tmp_old_path)

                try:
                    shutil.move(plugin_path, get_plugins_persistent_path())
                except Exception:
                    if tmp_old_path is not None:
                        if os.path.exists(dest_path):
                            shutil.rmtree(dest_path)
                        shutil.move(os.path.join(tmp_old_path, plugin_name), get_plugins_persistent_path())
                    raise

                clear_plugins_cache()
                init_plugins()

                if upgrade:
                    message = _("Plugin %(plugin)s updated successfully. Please restart WebODM to apply the changes.") % {'plugin': plugin_name}
                else:
                    message = _("%(plugin)s installed successfully") % {'plugin': display_name}
                success = True
                level = messages.INFO
            except Exception as e:
                message = _("Cannot load plugin: %(message)s") % {'message': str(e)}
            finally:
                if os.path.exists(tmp_zip_path):
                    os.remove(tmp_zip_path)
                if os.path.exists(tmp_extract_path):
                    shutil.rmtree(tmp_extract_path)
                if tmp_old_path is not None and os.path.exists(tmp_old_path):
                    shutil.rmtree(tmp_old_path)
        else:
            message = _("You need to upload a zip file")
            level = messages.ERROR

        if as_json:
            return JsonResponse({'success': success, 'message': str(message)})

        messages.add_message(request, level, message)
        return HttpResponseRedirect(reverse('admin:app_plugin_changelist'))

    def plugin_actions(self, obj):
        plugin = get_plugin_by_name(obj.name, only_active=False)
        return format_html(
            '<a class="button" href="{}" {}>{}</a>&nbsp;'
            '<a class="button" href="{}" {}>{}</a>'
            + (
                '&nbsp;<a class="button" href="{}" onclick="return confirm(\'Are you sure you want to delete {}?\')"><i class="fa fa-trash"></i></a>' if not plugin.is_persistent() else '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;')
            ,
            reverse('admin:plugin-disable', args=[obj.pk]) if obj.enabled else '#',
            'disabled' if not obj.enabled else '',
            _('Disable'),
            reverse('admin:plugin-enable', args=[obj.pk]) if not obj.enabled else '#',
            'disabled' if obj.enabled else '',
            _('Enable'),
            reverse('admin:plugin-delete', args=[obj.pk]),
            obj.name
        )

    plugin_actions.short_description = _('Actions')
    plugin_actions.allow_tags = True


admin.site.register(Plugin, PluginAdmin)

class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False

    # Hide "quota" profile field when adding (show during editing)
    def get_fields(self, request, obj=None):
        if obj is None:
            fields = list(super().get_fields(request, obj))
            fields.remove('quota')
            return fields
        else:
            return super().get_fields(request, obj)

class UserAdmin(BaseUserAdmin):
    inlines = [ProfileInline]


# Re-register UserAdmin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)
