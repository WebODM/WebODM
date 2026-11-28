from rest_framework import status
from rest_framework.response import Response

from app.plugins import PluginBase, Menu, MountPoint, get_current_plugin
from app.plugins.views import TaskView
from django.shortcuts import render
from django import forms

class TestForm(forms.Form):
    testField = forms.CharField(label='Test')


class TestTaskView(TaskView):
    def get(self, request, pk=None):
        task = self.get_and_check_task(request, pk)
        return Response(task.id, status=status.HTTP_200_OK)


class Plugin(PluginBase):

    def main_menu(self):
        return [Menu("Test", self.public_url("menu_url/"), "test-icon")]
    
    def admin_menu(self):
        return [Menu("Admin Test", self.public_url("admin_menu_url/"), "test-icon")]

    def include_js_files(self):
        return ['test.js']

    def include_css_files(self):
        return ['test.css']

    def build_jsx_components(self):
        return ['component.jsx']

    def app_mount_points(self):
        # Show script only if '?print=1' is set
        def dynamic_cb(request):
            if 'print' in request.GET:
                return {'name': 'WebODM'} # Test template substitution
            else:
                return False

        return [
            MountPoint('/app_mountpoint/$', lambda request: render(request, self.template_path("app.html"), {
                'title': 'Test',
                'test_form': TestForm()
            })),
            MountPoint('task/(?P<pk>[^/.]+)/', TestTaskView.as_view()),
            MountPoint('/app_dynamic_script.js$', self.get_dynamic_script('dynamic.js', dynamic_cb))
        ]

    def get_current_plugin_test(self):
        return get_current_plugin()
