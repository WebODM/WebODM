from .tasks import TaskNestedView
from .common import check_project_perms
from rest_framework.response import Response
from rest_framework import exceptions


class Scene(TaskNestedView):
    def get(self, request, pk=None, project_pk=None):
        """
        Retrieve Potree scene information
        """
        task = self.get_and_check_task(request, pk)

        return Response(task.potree_scene)
    
    def post(self, request, pk=None, project_pk=None):
        """
        Store potree scene information (except camera view)
        """
        task = self.get_and_check_task(request, pk)
        if task.check_public_edit():
            check_project_perms(request, task.project, perms=("change_project", ))
        scene = request.data

        # Quick type check
        if scene.get('type') != 'Potree':
            raise exceptions.ValidationError(detail="Invalid potree scene")
        
        for k in scene:
            if not k in ["view", "pointclouds", "settings"]:
                task.potree_scene[k] = scene[k]

        task.save()
        return Response({'success': True})

class CameraView(TaskNestedView):
    def post(self, request, pk=None, project_pk=None):
        """
        Store camera view information
        """
        task = self.get_and_check_task(request, pk)
        if task.check_public_edit():
            check_project_perms(request, task.project, perms=("change_project", ))

        view = request.data
        if not view:
            raise exceptions.ValidationError(detail="view parameter missing")

        if not task.potree_scene:
            init_p = {
                'type': 'Potree',
                'version': 2.0
            } 
            task.potree_scene = init_p
        
        task.potree_scene['view'] = view
        task.save()
            
        return Response({'success': True})