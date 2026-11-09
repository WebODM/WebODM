import os
import re
import shutil
import tempfile

from django.utils.translation import gettext_lazy as _
from rest_framework import status, exceptions, parsers
from rest_framework.response import Response
from django.core.files.uploadedfile import InMemoryUploadedFile

from app import splats
from app.api.tasks import TaskNestedView, flatten_files, download_file_stream
from worker.tasks import export_splats, process_splats, TestSafeAsyncResult
from .common import check_project_perms, get_asset_download_filename
from app.security import sanitize_filename
from webodm import settings

MAX_SPLAT_FILE_SIZE = 128 * 1024 * 1024 * 1024  # 128 GB
SPLAT_EXTENSIONS = ('.ply', '.spz', '.splat', '.ksplat', '.sog', '.sogs', '.zip', '.rad')


class TaskSplatsDownload(TaskNestedView):
    def post(self, request, pk=None, project_pk=None):
        task = self.get_and_check_task(request, pk)

        try:
            image_size = int(request.data.get('image_size', 0))
        except ValueError:
            raise exceptions.ValidationError(detail=_("Invalid image size"))
        if image_size != 0 and image_size < 16:
            raise exceptions.ValidationError(detail=_("Invalid image size"))

        for asset in ('cameras.json', 'shots.geojson'):
            if asset not in task.available_assets:
                raise exceptions.ValidationError(detail=_("Task is missing %(asset)s") % {'asset': asset})

        celery_task_id = export_splats.delay(task.id, image_size=image_size).task_id

        return Response({
            'celery_task_id': celery_task_id
        }, status=status.HTTP_200_OK)

    def get(self, request, pk=None, project_pk=None, celery_task_id=""):
        task = self.get_and_check_task(request, pk)

        res = TestSafeAsyncResult(celery_task_id)
        if not res.ready():
            raise exceptions.NotFound(_("Export is not ready"))

        result = res.get()
        if not isinstance(result, dict) or result.get('error') is not None:
            raise exceptions.ValidationError(detail=(result or {}).get('error', _("Invalid export")))

        # Same directory that the export_splats worker task writes to
        export_dir = os.path.join(settings.MEDIA_TMP, "splats_export_{}".format(re.sub('[^0-9a-zA-Z-]+', '', celery_task_id)))
        if not os.path.isdir(export_dir):
            raise exceptions.NotFound(_("Export has expired, please generate a new one"))

        filename = request.query_params.get('filename', get_asset_download_filename(task, "training.zip"))

        return download_file_stream(request, splats.export_zip(export_dir), 'attachment',
                                    download_filename=filename)


class TaskSplatsUpload(TaskNestedView):
    parser_classes = (parsers.MultiPartParser, parsers.FormParser)

    def post(self, request, pk=None, project_pk=None):
        task = self.get_and_check_task(request, pk)
        check_project_perms(request, task.project, perms=("change_project", ))

        if 'georeferenced_model.laz' not in task.available_assets:
            raise exceptions.ValidationError(detail=_("Cannot upload a splats model (task is missing a point cloud)"))

        files = flatten_files(request.FILES)
        if len(files) != 1:
            raise exceptions.ValidationError(detail=_("A single file must be uploaded"))
        file = files[0]

        name = file.name
        if name is None:
            raise exceptions.ValidationError(detail=_("Invalid filename"))
        safe_name = sanitize_filename(name)
        ext = os.path.splitext(safe_name)[1].lower()
        if ext not in SPLAT_EXTENSIONS:
            raise exceptions.ValidationError(detail=_("Invalid file type"))

        chunk_info = None
        chunk_index = request.data.get('dzchunkindex')
        uuid = request.data.get('dzuuid')
        total_chunk_count = request.data.get('dztotalchunkcount', None)
        if chunk_index is not None and uuid is not None and total_chunk_count is not None:
            byte_offset = request.data.get('dzchunkbyteoffset', 0)
            try:
                chunk_index = int(chunk_index)
                byte_offset = int(byte_offset)
                total_chunk_count = int(total_chunk_count)
            except ValueError:
                raise exceptions.ValidationError(detail="chunkIndex is not an int")

            chunk_info = {
                'uuid': re.sub('[^0-9a-zA-Z-]+', "", uuid),
                'chunk_index': chunk_index,
                'byte_offset': byte_offset,
                'total_chunk_count': total_chunk_count,
            }
            chunk_info['tmp_upload_file'] = os.path.join(settings.FILE_UPLOAD_TEMP_DIR, "{}.upload".format(chunk_info['uuid']))

        if chunk_info is not None:
            if os.path.isfile(chunk_info['tmp_upload_file']) and chunk_info['chunk_index'] == 0:
                os.unlink(chunk_info['tmp_upload_file'])

            with open(chunk_info['tmp_upload_file'], 'ab') as fd:
                fd.truncate(chunk_info['byte_offset'])
                fd.seek(chunk_info['byte_offset'])
                if isinstance(file, InMemoryUploadedFile):
                    for chunk in file.chunks():
                        fd.write(chunk)
                else:
                    with open(file.temporary_file_path(), 'rb') as f:
                        shutil.copyfileobj(f, fd)

            if chunk_info['chunk_index'] + 1 < chunk_info['total_chunk_count']:
                return Response({'success': True, 'partial': True}, status=status.HTTP_200_OK)

            uploaded_file = chunk_info['tmp_upload_file']
        else:
            uploaded_file = os.path.join(settings.FILE_UPLOAD_TEMP_DIR, "{}.upload".format(sanitize_filename(safe_name)))
            with open(uploaded_file, 'wb+') as fd:
                if isinstance(file, InMemoryUploadedFile):
                    for chunk in file.chunks():
                        fd.write(chunk)
                else:
                    with open(file.temporary_file_path(), 'rb') as f:
                        shutil.copyfileobj(f, fd)

        fsize = os.path.getsize(uploaded_file)
        if fsize > MAX_SPLAT_FILE_SIZE:
            os.unlink(uploaded_file)
            raise exceptions.ValidationError(detail=_("File exceeds maximum allowed size"))

        if ext == '.rad':
            # No processing needed
            os.makedirs(task.assets_path('splats'), exist_ok=True)
            shutil.move(uploaded_file, task.get_asset_file_or_stream('splats.rad'))

            task.update_available_assets_field()
            task.update_size()
            task.save()

            return Response({'success': True, 'celery_task_id': None}, status=status.HTTP_200_OK)
        else:
            tmp_splats_file = tempfile.mktemp('_splats' + ext, dir=settings.MEDIA_TMP)
            shutil.move(uploaded_file, tmp_splats_file)

            celery_task_id = process_splats.delay(task.id, tmp_splats_file).task_id
            return Response({'success': True, 'celery_task_id': celery_task_id}, status=status.HTTP_200_OK)


class TaskSplatsDelete(TaskNestedView):
    def post(self, request, pk=None, project_pk=None):
        """
        Delete a task's splats model
        """
        task = self.get_and_check_task(request, pk)
        check_project_perms(request, task.project, perms=("change_project", ))

        model_rad = task.get_asset_file_or_stream('splats.rad')
        if not os.path.isfile(model_rad):
            raise exceptions.NotFound(_("Asset does not exist"))
        
        if os.path.isfile(model_rad):
            os.unlink(model_rad)

        task.update_available_assets_field()
        task.update_size()
        task.save()

        return Response({'success': True}, status=status.HTTP_200_OK)
