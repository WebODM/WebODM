import json

from django.contrib.auth import login
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from guardian.shortcuts import get_objects_for_user

from nodeodm.models import ProcessingNode
from app.models import Project, Task, Basemap
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils.html import format_html
from django.utils.translation import gettext as _
from django import forms
from app.views.utils import get_permissions, get_project_or_raise, get_task_or_raise, handle_302, ResponseClusterRedirect, cluster_mode
from webodm import settings

def index(request):
    # Check first access
    if User.objects.filter(is_superuser=True).count() == 0:
        if settings.SINGLE_USER_MODE:
            # Automatically create a default account
            User.objects.create_superuser('admin', 'admin@localhost', 'admin')
        else:
            # the user is expected to create an admin account
            return redirect('welcome')

    if not request.user.is_authenticated:
        if settings.SINGLE_USER_MODE:
            login(request, User.objects.get(username="admin"), 'django.contrib.auth.backends.ModelBackend')
        elif settings.AUTO_LOGIN_USER:
            login(request, User.objects.get(username=settings.AUTO_LOGIN_USER), 'django.contrib.auth.backends.ModelBackend')

    return redirect(settings.LOGIN_REDIRECT_URL if request.user.is_authenticated
                    else settings.LOGIN_URL)

@login_required
def dashboard(request):
    if cluster_mode():    
        if request.user.profile.cluster_id is not None and request.user.profile.cluster_id != settings.CLUSTER_ID:
            return ResponseClusterRedirect(request, request.user.profile.cluster_id)
    
    no_processingnodes = ProcessingNode.objects.count() == 0
    if no_processingnodes and settings.PROCESSING_NODES_ONBOARDING is not None:
        return redirect(settings.PROCESSING_NODES_ONBOARDING)

    no_tasks = Task.objects.filter(project__owner=request.user).count() == 0
    no_projects = Project.objects.filter(owner=request.user).count() == 0

    permissions = []
    if request.user.has_perm('app.add_project'):
        permissions.append('add_project')
    
    # Create first project automatically
    if settings.DASHBOARD_ONBOARDING and no_projects and 'add_project' in permissions:
        Project.objects.create(owner=request.user, name=_("First Project"))

    return render(request, 'app/dashboard.html', {'title': _('Dashboard'),
        'no_processingnodes': no_processingnodes,
        'no_tasks': no_tasks,
        'onboarding': settings.DASHBOARD_ONBOARDING,
        'params': {
            'permissions': json.dumps(permissions),
            'basemaps': json.dumps(Basemap.get_cached_basemaps())
        }.items()
    })


@login_required
@handle_302
def map(request, project_pk=None, task_pk=None):
    title = _("Map")

    if project_pk is not None:
        project = get_project_or_raise(pk=project_pk)
        if not request.user.has_perm('app.view_project', project):
            raise Http404()
        
        if task_pk is not None:
            task = get_task_or_raise(pk=task_pk, project=project)
            title = task.name or task.id
            mapItems = [task.get_map_items()]
            projectInfo = None
        else:
            title = project.name or project.id
            mapItems = project.get_map_items()
            projectInfo = project.get_public_info()

    return render(request, 'app/map.html', {
            'title': title,
            'params': {
                'map-items': json.dumps(mapItems),
                'title': title,
                'public': 'false',
                'share-buttons': 'true',
                'permissions': json.dumps(get_permissions(request.user, project)),
                'project': json.dumps(projectInfo),
                'basemaps': json.dumps(Basemap.get_cached_basemaps()),
            }.items()
        })


@login_required
@handle_302
def model_display(request, project_pk=None, task_pk=None):
    title = _("3D Model Display")

    if project_pk is not None:
        project = get_project_or_raise(pk=project_pk)
        if not request.user.has_perm('app.view_project', project):
            raise Http404()

        if task_pk is not None:
            task = get_task_or_raise(pk=task_pk, project=project)
            title = task.name or task.id
        else:
            raise Http404()

    return render(request, 'app/3d_model_display.html', {
            'title': title,
            'params': {
                'task': json.dumps(task.get_model_display_params()),
                'title': title,
                'public': 'false',
                'share-buttons': 'true',
                'model-type': request.GET.get('t', 'cloud'),
            }.items()
        })

def about(request):
    return render(request, 'app/about.html', {'title': _('About'), 'version': settings.VERSION})

@login_required
def processing_node(request, processing_node_id):
    pn = get_object_or_404(ProcessingNode, pk=processing_node_id)
    
    if settings.DEPRECATION_WARNINGS and pn.engine is not None and pn.engine == 'odm':
        messages.add_message(request, messages.constants.WARNING, format_html(
            _('%(node)s is deprecated might stop working in a future version. See the %(link_start)s migration guide %(link_end)s to upgrade.' % {'node': pn, 'link_start': '<a href="https://docs.webodm.org/tutorials/opendronemap-migration-guide/" target="_blank">', 'link_end': '</a>'}),
        ))

    if not pn.update_node_info():
        messages.add_message(request, messages.constants.WARNING, _('%(node)s seems to be offline.') % {'node': pn})

    return render(request, 'app/processing_node.html', 
            {
                'title': _('Processing Node'), 
                'processing_node': pn,
                'available_options_json': pn.get_available_options_json(pretty=True)
            })

class FirstUserForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ('username', 'password', )
        widgets = {
            'password': forms.PasswordInput(),
        }


def welcome(request):
    if User.objects.filter(is_superuser=True).count() > 0:
        return redirect('index')

    fuf = FirstUserForm()

    if request.method == 'POST':
        fuf = FirstUserForm(request.POST)
        if fuf.is_valid():
            admin_user = fuf.save(commit=False)
            admin_user.password = make_password(fuf.cleaned_data['password'])
            admin_user.is_superuser = admin_user.is_staff = True
            admin_user.save()

            # Log-in automatically
            login(request, admin_user, 'django.contrib.auth.backends.ModelBackend')
            return redirect('dashboard')

    return render(request, 'app/welcome.html',
                  {
                      'title': _('Welcome'),
                      'firstuserform': fuf
                  })


def handler404(request, exception):
    return render(request, '404.html', status=404)

def handler500(request):
    return render(request, '500.html', status=500)
