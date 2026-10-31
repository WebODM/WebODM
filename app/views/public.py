import json
from django.http import Http404
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from django.shortcuts import render

from app.api.tasks import TaskSerializer
from app.models import Basemap
from app.views.utils import get_permissions, get_task_or_raise, get_project_or_raise, handle_302, csrf_samesite_none_if_secure
from django.views.decorators.csrf import ensure_csrf_cookie
from webodm import settings

def get_public_task(task_pk):
    """
    Get a task and raise a 404 if it's not public
    """
    task = get_task_or_raise(pk=task_pk)
    if not (task.public or task.project.public):
       raise Http404()
    return task

def get_public_project(public_id):
    project = get_project_or_raise(public_id=public_id)
    if not project.public:
        raise Http404()
    return project

@ensure_csrf_cookie
@handle_302
def handle_map(request, template, uuid_type=None, uuid=None, hide_title=False):
    if uuid_type == 'task':
        task = get_public_task(uuid)
        title = task.name or task.id
        mapItems = [task.get_map_items()]
        public_edit = task.public_edit
        permissions = get_permissions(request.user, task.project)
        projectInfo = None
        thumb = f'/api/projects/{task.project.id}/tasks/{task.id}/thumbnail?size=630'
    else:
        project = get_public_project(uuid)
        title = project.name or project.id
        mapItems = project.get_map_items()
        public_edit = project.public_edit
        permissions = get_permissions(request.user, project)
        projectInfo = project.get_public_info()
        thumb = ''

    return render(request, template, {
        'title': title,
        'thumb': thumb,
        'params': {
            'map-items': json.dumps(mapItems),
            'title': title if not hide_title else '',
            'public': 'true',
            'public-edit': str(public_edit).lower(),
            'share-buttons': 'true',
            'selected-map-type': request.GET.get('t', 'auto'),
            'permissions': json.dumps(permissions),
            'project': json.dumps(projectInfo),
            'basemaps': json.dumps(Basemap.get_cached_basemaps())
        }.items()
    })

def map(request, uuid_type=None, uuid=None):
    return handle_map(request, 'app/public/map.html', uuid_type, uuid, False)

@csrf_samesite_none_if_secure
def map_iframe(request, uuid_type=None, uuid=None):
    return handle_map(request, 'app/public/map_iframe.html', uuid_type, uuid, True)

@ensure_csrf_cookie
@handle_302
def handle_model_display(request, template, task_pk=None, hide_title=False):
    task = get_public_task(task_pk)
    thumb = f'/api/projects/{task.project.id}/tasks/{task.id}/thumbnail?size=630'

    return render(request, template, {
            'title': task.name,
            'thumb': thumb,
            'params': {
                'task': json.dumps(task.get_model_display_params()),
                'title': task.name if not hide_title else '',
                'public': 'true',
                'public-edit': str(task.public_edit).lower(),
                'share-buttons': 'true',
                'model-type': request.GET.get('t', 'cloud'),
            }.items()
        })

def model_display(request, task_pk=None):
    return handle_model_display(request, 'app/public/3d_model_display.html', task_pk)

def model_display_iframe(request, task_pk=None):
    return handle_model_display(request, 'app/public/3d_model_display_iframe.html', task_pk, hide_title=True)

@handle_302
def task_json(request, task_pk=None):
    task = get_public_task(task_pk)
    serializer = TaskSerializer(task)
    return JsonResponse(serializer.data)