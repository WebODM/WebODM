import os
import logging
from app.models import Task
from app.plugins.views import TaskView
from app.plugins.worker import run_function_async
from rest_framework.response import Response
from rest_framework import exceptions, serializers, status

logger = logging.getLogger('app.logger')


def get_resources(task, assets, custom_assets):
    if assets not in ["all", "backup", "custom"]:
        raise exceptions.ValidationError({"assets": "Invalid"})
    if assets == "custom":
        INCLUDE_ALWAYS = ["cameras.json", "shots.geojson", "ground_control_points.geojson"]
        if not isinstance(custom_assets, list):
            raise exceptions.ValidationError({"customAssets": "Invalid"})
        
        if len(custom_assets) > 0:
            custom_assets = list(set(custom_assets) | set(INCLUDE_ALWAYS))
    else:
        custom_assets = []
    
    resources = []
    base_path = task.assets_path()

    if assets == "all":
        resources.append(base_path)
    elif assets == "backup":
        base_path = task.task_path()
        resources.append(base_path)
    elif assets == "custom":
        for asset in custom_assets:
            try:
                file = task.get_asset_download_path(asset)
            except FileNotFoundError:
                raise exceptions.ValidationError({"customAssets": "Invalid"})

            if os.path.isfile(file):
                resources.append(file)
            
            # Include EPT folder if available
            if asset == "georeferenced_model.laz":
                ept_dir = task.assets_path("entwine_pointcloud")
                if os.path.isdir(ept_dir):
                    resources.append(ept_dir)
            
            # Include entire texturing folder (GLB + OBJ)
            if asset == "textured_model.zip":
                tex_dir = task.assets_path("odm_texturing")
                if os.path.isdir(tex_dir):
                    resources.append(tex_dir)

    return resources, base_path

def get_size_bytes(resources):
    total_bytes = 0

    for res in resources:
        try:
            if os.path.isdir(res):
                for dirpath, _, filenames in os.walk(res):
                    for f in filenames:
                        fp = os.path.join(dirpath, f)
                        if not os.path.islink(fp):
                            total_bytes += os.path.getsize(fp)
            elif os.path.isfile(res):
                total_bytes += os.path.getsize(res)
        except Exception as e:
            logger.warn("Cannot get size: {}".format(str(e)))

    return total_bytes

class TaskSizeSerializer(serializers.Serializer):
    assets = serializers.CharField(help_text="One of: [all,backup,custom]")
    customAssets = serializers.JSONField(help_text="List of custom assets", default=[])

class ShareTaskSerializer(TaskSizeSerializer):
    project = serializers.CharField(help_text="Remote project ID or empty", default="", allow_blank=True)
    cloudUrl = serializers.CharField(help_text="Cloud URL or empty", default="")
    cloudToken = serializers.CharField(help_text="Cloud token or empty", default="")
    
class GetTaskSize(TaskView):
    def post(self, request, pk):
        task = self.get_and_check_task(request, pk)
        serializer = TaskSizeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        resources, _ = get_resources(task, serializer['assets'].value, serializer['customAssets'].value)

        return Response({'size': get_size_bytes(resources)})

def share_task(task_name, project_name, project, cloud_token, cloud_url, resources, resources_base_path, progress_callback, should_cancel):
    import uuid
    import requests
    import os
    import time
    from zipstream.ng import ZipStream
    import logging
    import jwt
    logger = logging.getLogger('app.logger')

    CHUNK_SIZE = 8 * 1024 * 1024  # 8MB
    cloud_url = cloud_url.rstrip('/')
    session = requests.Session()
    session.headers.update({
        'Authorization': 'JWT {}'.format(cloud_token)
    })

    def check_refresh_token():
        nonlocal cloud_token

        try:
            meta = jwt.decode(cloud_token, options={'verify_signature': False})
            exp = meta.get('exp', time.time())

            # Refresh token if less than 1 hour remaining to expiry
            if exp - time.time() < 60 * 60:
                res = session.post(cloud_url + '/api/token-auth/refresh/', json={'token': cloud_token})
                if res.status_code == 200:
                    j = res.json()
                    if 'token' in j:
                        cloud_token = j['token']
                        session.headers.update({
                            'Authorization': 'JWT {}'.format(cloud_token)
                        })
        except Exception as e:
            logger.warning(f"Cannot check refresh token: {str(e)}")

    check_refresh_token()
    cleanup = lambda: None

    # If project is None, create a new project on the remote
    if project is None:
        res = session.post(cloud_url + '/api/projects/', json={'name': project_name})
        if res.status_code != 201:
            logger.info(res.content.decode("utf-8"))
            return {'error': 'Failed to create Lightning project. Try again in a bit.'}
        
        project = res.json().get('id')

        def cleanup():
            try:
                session.delete(cloud_url + f'/api/projects/{project}')
            except Exception as e:
                logger.warning(f"Cannot cleanup project: {str(e)}")

    dzuuid = str(uuid.uuid4())
    zs = ZipStream(sized=True)
    zs.comment = "Generated by WebODM Lightning Plugin"

    for res in resources:
        if os.path.isfile(res):
            zs.add_path(res, os.path.relpath(res, resources_base_path))
        else:
            for dirpath, _, filenames in os.walk(res):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    zs.add_path(fp, os.path.relpath(fp, resources_base_path))

    total_length = len(zs)
    stream = zs.finalize()

    if should_cancel():
        return cleanup()
    progress_callback("Preparing files", 5)

    if total_length == 0:
        return {'error': 'No data to upload'}

    # Calculate total chunk count (ceiling division)
    total_chunks = (total_length + CHUNK_SIZE - 1) // CHUNK_SIZE

    # Upload in 8MB chunks
    offset = 0
    chunk_index = 0
    buffer = b''

    while offset < total_length:
        if should_cancel():
            return cleanup()
        
        while len(buffer) < CHUNK_SIZE:
            buf = next(stream, b'')
            if not buf:
                break
            buffer += buf
        chunk = buffer[:CHUNK_SIZE]
        buffer = buffer[CHUNK_SIZE:]

        files = {'file': ('all.zip', chunk, 'application/zip')}
        data = {
            'name': task_name,
            'public': True,
            'dzchunkindex': chunk_index,
            'dzuuid': dzuuid,
            'dztotalchunkcount': total_chunks,
            'dzchunkbyteoffset': offset,
        }

        NUM_RETRIES = 15
        retry = 0

        while True:
            if should_cancel():
                return cleanup()
            check_refresh_token()
            
            try:
                res = session.post(cloud_url + '/api/projects/{}/tasks/import'.format(project),
                    files=files,
                    data=data
                )
            except Exception as e:
                if retry < NUM_RETRIES:
                    retry += 1
                    logger.warning(f"Failed upload ({str(e)}), retrying... ({retry})")
                    time.sleep(retry)
                    continue
                else:
                    return {'error': f"Cannot complete upload: {str(e)}"}
            break


        offset += len(chunk)
        chunk_index += 1

        pct = min(95, int((chunk_index / total_chunks) * 100))
        if should_cancel():
            return cleanup()
        progress_callback("Uploading part {} of {}".format(chunk_index, total_chunks), pct)

        try:
            j = res.json()
        except ValueError:
            return {'error': "Upload failed: not a JSON response from server"}

        if res.status_code == 403:
            return {'error': "Authentication expired. Please try sharing again."}

        if j.get('uploaded'):
            continue # next chunk
        elif j.get('id') and j.get('project'):
            # Final chunk
            task_id = j.get('id')
            project_id = j.get('project')
            count = 0
            view = 'map'

            # Wait 30 minutes max
            while j.get('pending_action') and count < 360:
                time.sleep(5)
                check_refresh_token()
                try:
                    res = session.get(cloud_url + f'/api/projects/{project_id}/tasks/{task_id}/')
                    j = res.json()
                except Exception as e:
                    logger.warning(f"Cannot retrieve task information: {str(e)}, retrying...")
                count += 1
            
            if 'orthophoto.tif' not in j['available_assets'] and \
                'dsm.tif' not in j['available_assets'] and \
                'dtm.tif' not in j['available_assets']:
                view = '3d'

            if should_cancel():
                return cleanup()

            progress_callback("Finalizing", 100)
            
            return {'link': cloud_url + f'/public/task/{task_id}/{view}/'}
        else:
            return {'error': "Upload failed: invalid response from server"}
    
    return {'error': "No data uploaded"}

class ShareTask(TaskView):
    def post(self, request, pk):
        task = self.get_and_check_task(request, pk)
        serializer = ShareTaskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        resources, base_path = get_resources(task, serializer['assets'].value, serializer['customAssets'].value)
        
        try:
            project = int(serializer['project'].value) if serializer['project'].value != "" else None
        except ValueError:
            project = None
        
        cloud_token = serializer['cloudToken'].value
        cloud_url = serializer['cloudUrl'].value
        
        if not cloud_token:
            raise exceptions.ValidationError({"cloudToken": "Missing parameter"})
        if not cloud_url:
            raise exceptions.ValidationError({"cloudUrl": "Missing parameter"})
        
        try: 
            celery_task_id = run_function_async(share_task, task_name=task.name, project_name=task.project.name, project=project, cloud_token=cloud_token, cloud_url=cloud_url, resources=resources, resources_base_path=base_path, with_progress=True, with_cancel=True).task_id
            return Response({'celery_task_id': celery_task_id}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_200_OK)
