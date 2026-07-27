import os
from rest_framework import serializers
from rest_framework import status
from rest_framework.response import Response
from app.api.workers import GetTaskResult, TaskResultOutputError
from app.models import Task
from app.plugins.views import TaskView
from django.utils.translation import gettext_lazy as _
from app.plugins.worker import run_function_async

from .volume import calc_volume

class VolumeRequestSerializer(serializers.Serializer):
    area = serializers.JSONField(help_text="GeoJSON Polygon contour defining the volume area to compute")
    method = serializers.CharField(help_text="One of: [plane,triangulate,average,custom,highest,lowest]", default="triangulate", allow_blank=True)
    dem_type = serializers.ChoiceField(choices=["dsm", "dtm"], help_text="Which elevation model to compute the volume against", default="dsm")

class TaskVolume(TaskView):
    def post(self, request, pk=None):
        task = self.get_and_check_task(request, pk)

        serializer = VolumeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        area = serializer['area'].value
        method = serializer['method'].value
        dem_type = serializer['dem_type'].value

        if dem_type == "dtm":
            if task.dtm_extent is None:
                return Response({'error': _('No terrain model available. From the Dashboard, select this task, press Edit, from the options make sure to check "dtm", then press Restart --> From DEM.')})
        else:
            if task.dsm_extent is None:
                return Response({'error': _('No surface model available. From the Dashboard, select this task, press Edit, from the options make sure to check "dsm", then press Restart --> From DEM.')})

        points = [coord for coord in area['geometry']['coordinates'][0]]
        dem = os.path.abspath(task.get_asset_download_path(f"{dem_type}.tif"))

        try:
            celery_task_id = run_function_async(calc_volume, input_dem=dem, pts=points, pts_epsg=4326, base_method=method).task_id
            return Response({'celery_task_id': celery_task_id}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_200_OK)

class TaskVolumeResult(GetTaskResult):
    def get(self, request, pk=None, celery_task_id=None):
        task = Task.objects.only('dsm_extent').get(pk=pk)
        return super().get(request, celery_task_id, task=task)


