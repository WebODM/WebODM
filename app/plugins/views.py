import os

from app.api.tasks import TaskNestedView as TaskView
from app.api.workers import CheckTask as CheckTask
from app.api.workers import GetTaskResult as GetTaskResult
from app.api.workers import TaskResultOutputError

from django.http import HttpResponse, Http404
from .functions import get_plugin_by_name, get_active_plugins
from django.urls import re_path
from django.views.static import serve
from urllib.parse import urlparse


def try_resolve_url(request, url):
    o = urlparse(request.get_full_path())
    res = url.resolve(o.path)
    if res:
        return res
    else:
        return (None, None, None)

def app_view_handler(request, plugin_name=None):
    plugin = get_plugin_by_name(plugin_name) # TODO: this pings the server, which might be bad for performance with very large amount of files
    if plugin is None:
        raise Http404("Plugin not found")

    # Try mountpoints first
    for mount_point in plugin.app_mount_points():
        view, args, kwargs = try_resolve_url(request, re_path(r'^/plugins/{}/{}'.format(plugin_name, mount_point.url),
                                                 mount_point.view,
                                                 *mount_point.args,
                                                 **mount_point.kwargs))
        if view:
            return view(request, *args, **kwargs)

    # Try public assets
    if os.path.exists(plugin.get_path("public")) and plugin.serve_public_assets(request):
        view, args, kwargs = try_resolve_url(request, re_path('^/plugins/{}/(.*)'.format(plugin_name),
                                                            serve,
                                                            {'document_root': plugin.get_path("public")}))
        if view:
            return view(request, *args, **kwargs)

    raise Http404("No valid routes")


def api_view_handler(request, plugin_name=None):
    plugin = get_plugin_by_name(plugin_name) # TODO: this pings the server, which might be bad for performance with very large amount of files
    if plugin is None:
        raise Http404("Plugin not found")

    for mount_point in plugin.api_mount_points():
        view, args, kwargs = try_resolve_url(request, re_path(r'^/api/plugins/{}/{}'.format(plugin_name, mount_point.url),
                                                 mount_point.view,
                                                 *mount_point.args,
                                                 **mount_point.kwargs))

        if view:
            return view(request, *args, **kwargs)

    raise Http404("No valid routes")

def root_url_patterns():
    result = []
    for p in get_active_plugins():
        for mount_point in p.root_mount_points():
            result.append(re_path(mount_point.url, mount_point.view, *mount_point.args, **mount_point.kwargs))
            
    return result