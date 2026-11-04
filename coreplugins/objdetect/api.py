import os
import json
from rest_framework import status
from rest_framework.response import Response
from app.plugins.views import TaskView, GetTaskResult, TaskResultOutputError
from app.plugins.worker import run_function_async
from django.utils.translation import gettext_lazy as _

def detect(orthophoto, model, classes=None, crop=None, progress_callback=None):
    import os
    import subprocess
    import shutil
    import tempfile
    from webodm import settings

    try:
        from geodeep import detect as gdetect, models
        models.cache_dir = os.path.join(settings.MEDIA_CACHE, "detection_models")
    except ImportError:
        return {'error': "GeoDeep library is missing"}

    try:
        if crop is not None:
            # Make a VRT with the crop area

            gdalwarp_bin = shutil.which("gdalwarp")
            if gdalwarp_bin is None:
                return {'error': 'Cannot find gdalwarp'}
            
            tmpdir = os.path.join(settings.MEDIA_TMP, os.path.basename(tempfile.mkdtemp('_objdetect', dir=settings.MEDIA_TMP)))
    
            crop_geojson = os.path.join(tmpdir, "crop.geojson")
            ortho_vrt = os.path.join(tmpdir, "orthophoto.vrt")
            with open(crop_geojson, "w", encoding="utf-8") as f:
                f.write(json.dumps(crop))
            p = subprocess.Popen([gdalwarp_bin, "-cutline", crop_geojson,
                    '--config', 'GDALWARP_DENSIFY_CUTLINE', 'NO', 
                    '-crop_to_cutline', '-of', 'VRT',
                    orthophoto, ortho_vrt], cwd=tmpdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = p.communicate()
            out = out.decode('utf-8').strip()
            err = err.decode('utf-8').strip()
            if p.returncode != 0:
                return {'error': f'Error calling gdalwarp: {str(err)}'}

            orthophoto = ortho_vrt

        return {'output': gdetect(orthophoto, model, output_type='geojson', classes=classes, max_threads=settings.WORKERS_MAX_THREADS, progress_callback=progress_callback)}
    except Exception as e:
        return {'error': str(e)}
     
class TaskObjDetect(TaskView):
    def post(self, request, pk=None):
        task = self.get_and_check_task(request, pk)

        if task.orthophoto_extent is None:
            return Response({'error': _('No orthophoto is available.')})

        orthophoto = os.path.abspath(task.get_asset_download_path("orthophoto.tif"))
        model = request.data.get('model', 'cars')

        # model --> (modelID, classes)
        model_map = {
            'cars': ('cars', None),
            'trees': ('trees', None),
            'athletic': ('aerovision', ['tennis-court', 'track-field', 'soccer-field', 'baseball-field', 'swimming-pool', 'basketball-court']),
            'boats': ('aerovision', ['boat']),
            'planes': ('aerovision', ['plane']),
        }

        if not model in model_map:
            return Response({'error': 'Invalid model'}, status=status.HTTP_200_OK)

        model_id, classes = model_map[model]
        celery_task_id = run_function_async(detect, orthophoto, model_id, classes, task.crop, with_progress=True).task_id

        return Response({'celery_task_id': celery_task_id}, status=status.HTTP_200_OK)

class TaskObjDownload(GetTaskResult):
    def handle_output(self, output, result, **kwargs):
        try:
            return json.loads(output)
        except:
            raise TaskResultOutputError("Invalid GeoJSON")
