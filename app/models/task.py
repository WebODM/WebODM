import logging
import os
import shutil
import time
import struct
import zlib
import tempfile
from datetime import datetime
import uuid as uuid_module
from zipstream.ng import ZipStream

import json
import redis
from shlex import quote
from concurrent.futures import ThreadPoolExecutor
import threading

import errno
import re

import zipfile
import rasterio
from shutil import copyfile
import requests
from PIL import Image
Image.MAX_IMAGE_PIXELS = 4096000000
from django.contrib.gis.geos import GEOSGeometry
from django.contrib.postgres import fields
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.exceptions import ValidationError, SuspiciousFileOperation
from django.db import models
from django.db import transaction
from django.db import connection
from django.utils import timezone
from urllib3.exceptions import ReadTimeoutError

from app import pending_actions
from django.contrib.gis.db.models.fields import GeometryField

from app.net import patch_dns_resolution, is_dns_resolution_problem
from app.cogeo import assure_cogeo
from app.pointcloud_utils import is_pointcloud_georeferenced
from app.testwatch import testWatch
from app.security import path_traversal_check
from app.geoutils import geom_transform, epsg_from_wkt, get_raster_bounds_wkt, get_srs_name_units_from_epsg_or_wkt
from app.imageutils import extract_gps_from_image, is_panorama
from app.video import extract_subtitles, srt_file_for_video, extract_gps_from_srt, VIDEO_EXTENSIONS as VIDEO_MOD_EXTENSIONS
from nodeodm import status_codes
from nodeodm.models import ProcessingNode
from pyodx.exceptions import NodeResponseError, NodeConnectionError, NodeServerError, GenericError
from webodm import settings
from app.classes.gcp import GCPFile
from .project import Project
from django.utils.translation import gettext_lazy as _, gettext


from functools import partial
import subprocess
import glob
from app.classes.console import Console

logger = logging.getLogger('app.logger')
redis_client = redis.Redis.from_url(settings.CELERY_BROKER_URL)


class TaskInterruptedException(Exception):
    pass

def task_directory_path(taskId, projectId):
    return 'project/{0}/task/{1}/'.format(projectId, taskId)


def full_task_directory_path(taskId, projectId, *args):
    return os.path.join(settings.MEDIA_ROOT, task_directory_path(taskId, projectId), *args)


def assets_directory_path(taskId, projectId, filename):
    # files will be uploaded to MEDIA_ROOT/project/<id>/task/<id>/<filename>
    return '{0}{1}'.format(task_directory_path(taskId, projectId), filename)


def gcp_directory_path(task, filename):
    return assets_directory_path(task.id, task.project.id, filename)


def validate_task_options(value):
    """
    Make sure that the format of this options field is valid
    """
    if len(value) == 0: return

    try:
        for option in value:
            if not option['name']: raise ValidationError("Name key not found in option")
            if not option['value']: raise ValidationError("Value key not found in option")
    except:
        raise ValidationError("Invalid options")



def resize_image(image_path, resize_to, done=None):
    """
    :param image_path: path to the image
    :param resize_to: target size to resize this image to (largest side)
    :param done: optional callback
    :return: path and resize ratio
    """
    is_jpeg = re.match(r'.*\.jpe?g$', image_path, re.IGNORECASE)
    path, ext = os.path.splitext(image_path)
    resized_image_path = os.path.join(path + '.resized' + ext)
    exiftool = None

    try:
        with Image.open(image_path) as im:
            width, height = im.size
            max_side = max(width, height)
            if max_side < resize_to:
                logger.warning('You asked to make {} bigger ({} --> {}), but we are not going to do that.'.format(image_path, max_side, resize_to))
                retval = {'path': image_path, 'resize_ratio': 1}
                if done is not None:
                    done(retval)
                return retval

            ratio = float(resize_to) / float(max_side)
            resized_width = int(width * ratio)
            resized_height = int(height * ratio)
            xmp = im.info.get("xmp")
            exif = im.info.get("exif")

            resized = im.resize((resized_width, resized_height), Image.LANCZOS)
            params = {}
            if is_jpeg:
                params['quality'] = 100
            
            if is_jpeg:
                if exif is not None:
                    params['exif'] = exif
                if xmp is not None:
                    params['xmp'] = xmp
            else:
                # For TIFFs, we need to use exiftool
                exiftool = shutil.which('exiftool')
                if not exiftool:
                    raise Exception("Exiftool missing, but needed")

            resized.save(resized_image_path, **params)

            if exiftool:
                subprocess.run([exiftool, '-tagsfromfile', image_path, '-all', '-unsafe', resized_image_path, '-overwrite_original_in_place'], 
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run([exiftool, '-tagsfromfile', image_path, '-xmp', resized_image_path, '-overwrite_original_in_place'], 
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Delete original image, rename resized image to original
        os.remove(image_path)
        os.rename(resized_image_path, image_path)
    except Exception as e:
        logger.warning("Cannot resize {}: {}.".format(image_path, str(e)))
        
        # Cleanup
        if os.path.isfile(resized_image_path):
            os.remove(resized_image_path)
        
        if done is not None:
            done()
        return None

    retval = {'path': image_path, 'resize_ratio': ratio}

    if done is not None:
        done(retval)

    return retval

class Task(models.Model):
    ASSETS_MAP = {
            'all.zip': {
                'deferred_path': 'all.zip',
                'deferred_compress_dir': '.'
            },
            'orthophoto.tif': os.path.join('odm_orthophoto', 'odm_orthophoto.tif'),
            'orthophoto.png': os.path.join('odm_orthophoto', 'odm_orthophoto.png'),
            'orthophoto.mbtiles': os.path.join('odm_orthophoto', 'odm_orthophoto.mbtiles'),
            'orthophoto.kmz': os.path.join('odm_orthophoto', 'odm_orthophoto.kmz'),
            'cutline.gpkg': os.path.join('odm_orthophoto', 'cutline.gpkg'),
            'georeferenced_model.las': os.path.join('odm_georeferencing', 'odm_georeferenced_model.las'),
            'georeferenced_model.laz': os.path.join('odm_georeferencing', 'odm_georeferenced_model.laz'),
            'georeferenced_model.ply': os.path.join('odm_georeferencing', 'odm_georeferenced_model.ply'),
            'georeferenced_model.csv': os.path.join('odm_georeferencing', 'odm_georeferenced_model.csv'),
            'textured_model.zip': {
                'deferred_path': 'textured_model.zip',
                'deferred_compress_dir': 'odm_texturing',
                'deferred_exclude_files': ('odm_textured_model_geo.glb', )
            },
            'textured_model.glb': os.path.join('odm_texturing', 'odm_textured_model_geo.glb'),
            '3d_tiles_model.zip': {
                'deferred_path': '3d_tiles_model.zip',
                'deferred_compress_dir': os.path.join('3d_tiles', 'model')
            },
            '3d_tiles_pointcloud.zip': {
                'deferred_path': '3d_tiles_pointcloud.zip',
                'deferred_compress_dir': os.path.join('3d_tiles', 'pointcloud')
            },
            'dtm.tif': os.path.join('odm_dem', 'dtm.tif'),
            'dsm.tif': os.path.join('odm_dem', 'dsm.tif'),
            'dtm_tiles.zip': {
                'deferred_path': 'dtm_tiles.zip',
                'deferred_compress_dir': 'dtm_tiles'
            },
            'dsm_tiles.zip': {
                'deferred_path': 'dsm_tiles.zip',
                'deferred_compress_dir': 'dsm_tiles'
            },
            'orthophoto_tiles.zip': {
                'deferred_path': 'orthophoto_tiles.zip',
                'deferred_compress_dir': 'orthophoto_tiles'
            },
            'cameras.json': 'cameras.json',
            'shots.geojson': os.path.join('odm_report', 'shots.geojson'),
            'report.pdf': os.path.join('odm_report', 'report.pdf'),
            'ground_control_points.geojson': os.path.join('odm_georeferencing', 'ground_control_points.geojson'),
    }

    STATUS_CODES = (
        (status_codes.QUEUED, 'QUEUED'),
        (status_codes.RUNNING, 'RUNNING'),
        (status_codes.FAILED, 'FAILED'),
        (status_codes.COMPLETED, 'COMPLETED'),
        (status_codes.CANCELED, 'CANCELED'),
    )

    PENDING_ACTIONS = (
        (pending_actions.CANCEL, 'CANCEL'),
        (pending_actions.REMOVE, 'REMOVE'),
        (pending_actions.RESTART, 'RESTART'),
        (pending_actions.RESIZE, 'RESIZE'),
        (pending_actions.IMPORT, 'IMPORT'),
        (pending_actions.COMPACT, 'COMPACT'),
    )

    TASK_PROGRESS_LAST_VALUE = 0.85

    id = models.UUIDField(primary_key=True, default=uuid_module.uuid4, unique=True, serialize=False, editable=False, verbose_name=_("Id"))

    uuid = models.CharField(max_length=255, db_index=True, default='', blank=True, help_text=_("Identifier of the task (as returned by NodeODM API)"), verbose_name=_("UUID"))
    project = models.ForeignKey(Project, on_delete=models.CASCADE, help_text=_("Project that this task belongs to"), verbose_name=_("Project"))
    name = models.CharField(max_length=255, null=True, blank=True, help_text=_("A label for the task"), verbose_name=_("Name"))
    processing_time = models.IntegerField(default=-1, help_text=_("Number of milliseconds that elapsed since the beginning of this task (-1 indicates that no information is available)"), verbose_name=_("Processing Time"))
    processing_node = models.ForeignKey(ProcessingNode, on_delete=models.SET_NULL, null=True, blank=True, help_text=_("Processing node assigned to this task (or null if this task has not been associated yet)"), verbose_name=_("Processing Node"))
    auto_processing_node = models.BooleanField(default=True, help_text=_("A flag indicating whether this task should be automatically assigned a processing node"), verbose_name=_("Auto Processing Node"))
    status = models.IntegerField(choices=STATUS_CODES, db_index=True, null=True, blank=True, help_text=_("Current status of the task"), verbose_name=_("Status"))
    last_error = models.TextField(null=True, blank=True, help_text=_("The last processing error received"), verbose_name=_("Last Error"))
    options = fields.JSONField(default=dict, blank=True, help_text=_("Options that are being used to process this task"), validators=[validate_task_options], verbose_name=_("Options"))
    available_assets = fields.ArrayField(models.CharField(max_length=80), default=list, blank=True, help_text=_("List of available assets to download"), verbose_name=_("Available Assets"))

    orthophoto_extent = GeometryField(null=True, blank=True, srid=4326, help_text=_("Extent of the orthophoto"), verbose_name=_("Orthophoto Extent"))
    dsm_extent = GeometryField(null=True, blank=True, srid=4326, help_text=_("Extent of the DSM"), verbose_name=_("DSM Extent"))
    dtm_extent = GeometryField(null=True, blank=True, srid=4326, help_text=_("Extent of the DTM"), verbose_name=_("DTM Extent"))

    # mission
    created_at = models.DateTimeField(default=timezone.now, help_text=_("Creation date"), verbose_name=_("Created at"))
    pending_action = models.IntegerField(choices=PENDING_ACTIONS, db_index=True, null=True, blank=True, help_text=_("A requested action to be performed on the task. The selected action will be performed by the worker at the next iteration."), verbose_name=_("Pending Action"))

    public = models.BooleanField(default=False, help_text=_("A flag indicating whether this task is available to the public"), verbose_name=_("Public"))
    public_edit = models.BooleanField(default=False, help_text=_("A flag indicating whether this public task can be edited"), verbose_name=_("Public Edit"))

    resize_to = models.IntegerField(default=-1, help_text=_("When set to a value different than -1, indicates that the images for this task have been / will be resized to the size specified here before processing."), verbose_name=_("Resize To"))

    upload_progress = models.FloatField(default=0.0,
                                        help_text=_("Value between 0 and 1 indicating the upload progress of this task's files to the processing node"),
                                        verbose_name=_("Upload Progress"),
                                        blank=True)
    resize_progress = models.FloatField(default=0.0,
                                        help_text=_("Value between 0 and 1 indicating the resize progress of this task's images"),
                                        verbose_name=_("Resize Progress"),
                                        blank=True)
    running_progress = models.FloatField(default=0.0,
                                        help_text=_("Value between 0 and 1 indicating the running progress (estimated) of this task"),
                                        verbose_name=_("Running Progress"),
                                        blank=True)
    import_url = models.TextField(null=False, default="", blank=True, help_text=_("URL this task is imported from (only for imported tasks)"), verbose_name=_("Import URL"))
    images_count = models.IntegerField(null=False, blank=True, default=0, help_text=_("Number of images associated with this task"), verbose_name=_("Images Count"))
    partial = models.BooleanField(default=False, help_text=_("A flag indicating whether this task is currently waiting for information or files to be uploaded before being considered for processing."), verbose_name=_("Partial"))
    potree_scene = fields.JSONField(default=dict, blank=True, help_text=_("Serialized potree scene information used to save/load measurements and camera view angle"), verbose_name=_("Potree Scene"))
    epsg = models.IntegerField(null=True, default=None, blank=True, help_text=_("EPSG code of the dataset (if georeferenced)"), verbose_name="EPSG")
    wkt = models.TextField(null=True, default=None, blank=True, help_text=_("WKT definition of the dataset (if georeferenced and EPSG code is not available)"), verbose_name="WKT")
    tags = models.TextField(db_index=True, default="", blank=True, help_text=_("Task tags"), verbose_name=_("Tags"))
    orthophoto_bands = fields.JSONField(default=list, blank=True, help_text=_("List of orthophoto bands"), verbose_name=_("Orthophoto Bands"))
    size = models.FloatField(default=0.0, blank=True, help_text=_("Size of the task on disk in megabytes"), verbose_name=_("Size"))
    compacted = models.BooleanField(default=False, help_text=_("A flag indicating whether this task was compacted"), verbose_name=_("Compact"))
    crop = GeometryField(null=True, blank=True, srid=4326, help_text=_("Polygon defining the crop area of this task"), verbose_name=_("Crop Polygon"))
    media = fields.JSONField(default=list, blank=True, help_text=_("List of media files associated with this task"), verbose_name=_("Media"))

    
    class Meta:
        verbose_name = _("Task")
        verbose_name_plural = _("Tasks")

    def __init__(self, *args, **kwargs):
        super(Task, self).__init__(*args, **kwargs)

        # To help keep track of changes to the project id
        self.__original_project_id = self.project.id
        
        self.console = Console(self.data_path("console_output.txt"))

    def __str__(self):
        name = self.name if self.name is not None else gettext("unnamed")

        return 'Task [{}] ({})'.format(name, self.id)

    def move_assets(self, old_project_id, new_project_id):
        """
        Moves the task's folder, update ImageFields and orthophoto files to a new project
        """
        old_task_folder = full_task_directory_path(self.id, old_project_id)
        new_task_folder = full_task_directory_path(self.id, new_project_id)
        new_task_folder_parent = os.path.abspath(os.path.join(new_task_folder, os.pardir))

        try:
            if os.path.exists(old_task_folder) and not os.path.exists(new_task_folder):
                # Use parent, otherwise we get a duplicate directory in there
                if not os.path.exists(new_task_folder_parent):
                    os.makedirs(new_task_folder_parent)

                shutil.move(old_task_folder, new_task_folder_parent)

                logger.info("Moved task folder from {} to {}".format(old_task_folder, new_task_folder))
            else:
                logger.warning("Project changed for task {}, but either {} doesn't exist, or {} already exists. This doesn't look right, so we will not move any files.".format(self,
                                                                                                             old_task_folder,
                                                                                                             new_task_folder))
        except shutil.Error as e:
            logger.warning("Could not move assets folder for task {}. We're going to proceed anyway, but you might experience issues: {}".format(self, e))

    def save(self, *args, **kwargs):
        if self.project.id != self.__original_project_id:
            self.move_assets(self.__original_project_id, self.project.id)
            self.__original_project_id = self.project.id

        # Manually validate the fields we want,
        # since Django's clean_fields() method obliterates 
        # our foreign keys without explanation :/
        errors = {}
        for f in self._meta.fields:
            if f.attname in ["options"]:
                raw_value = getattr(self, f.attname)
                if f.blank and raw_value in f.empty_values:
                    continue

                try:
                    setattr(self, f.attname, f.clean(raw_value, self))
                except ValidationError as e:
                    errors[f.name] = e.error_list

        if errors:
            raise ValidationError(errors)

        # Validate crop area
        # must be enclosed within all raster extents
        # and have a positive area
        if self.crop is not None:
            if self.crop.valid:
                has_extents = False
                for extent in [self.orthophoto_extent, self.dsm_extent, self.dtm_extent]:
                    if extent is not None:
                        has_extents = True
                        self.crop = extent.intersection(self.crop)
                if not has_extents or self.crop.area <= 0:
                    self.crop = None
            else:
                self.crop = None

        self.clean()
        self.validate_unique()

        super(Task, self).save(*args, **kwargs)
    
    def get_extent(self):
        if self.orthophoto_extent is not None:
            return self.orthophoto_extent.extent
        elif self.dsm_extent is not None:
            return self.dsm_extent.extent
        elif self.dtm_extent is not None:
            return self.dtm_extent.extent
        else:
            return None

    def assets_path(self, *args):
        """
        Get a path relative to the place where assets are stored
        """
        return self.task_path("assets", *args)

    def media_directory_path(self, *args):
        """
        Get a path relative to the media directory for this task
        """
        return self.assets_path("media", *args)

    def data_path(self, *args):
        """
        Path to task data that does not fit in database fields (e.g. console output)
        """
        return self.task_path("data", *args)

    def task_path(self, *args):
        """
        Get path relative to the root task directory
        """
        return os.path.join(settings.MEDIA_ROOT,
                            assets_directory_path(self.id, self.project.id, ""),
                            *args)

    def is_asset_available_slow(self, asset):
        """
        Checks whether a particular asset is available in the file system
        Generally this should never be used directly, as it's slow. Use the available_assets field
        in the database instead.
        :param asset: one of ASSETS_MAP keys
        :return: boolean
        """
        if asset in self.ASSETS_MAP:
            value = self.ASSETS_MAP[asset]
            if isinstance(value, str):
                return os.path.exists(self.assets_path(value))
            elif isinstance(value, dict):
                if 'deferred_compress_dir' in value:
                    return os.path.exists(self.assets_path(value['deferred_compress_dir']))

        return False

    def get_statistics(self):
        """
        Parse ODM's stats.json if available
        """
        stats_json = self.assets_path("odm_report", "stats.json")
        if os.path.exists(stats_json):
            try:
                with open(stats_json) as f:
                    j = json.loads(f.read())
            except Exception as e:
                logger.warning("Malformed JSON {}: {}".format(stats_json, str(e)))
                return {}

            points = None
            if j.get('point_cloud_statistics', {}).get('dense', False):
                points = j.get('point_cloud_statistics', {}).get('stats', {}).get('statistic', [{}])[0].get('count')
            else:
                points = j.get('reconstruction_statistics', {}).get('reconstructed_points_count')

            spatial_refs = []
            if j.get('reconstruction_statistics', {}).get('has_gps'):
                spatial_refs.append("gps")
            if j.get('reconstruction_statistics', {}).get('has_gcp') and 'average_error' in j.get('gcp_errors', {}):
                spatial_refs.append("gcp")
            if 'align' in j:
                spatial_refs.append("alignment")

            return {
                'pointcloud':{
                    'points': points,
                },
                'gsd': j.get('odm_processing_statistics', {}).get('average_gsd'),
                'area': j.get('processing_statistics', {}).get('area'),
                'start_date': j.get('processing_statistics', {}).get('start_date'),
                'end_date': j.get('processing_statistics', {}).get('end_date'),
                'spatial_refs': spatial_refs,
            }
        else:
            return {}

    def duplicate(self, set_new_name=True):
        try:
            with transaction.atomic():
                task = Task.objects.get(pk=self.pk)
                task.pk = None
                if set_new_name:
                    task.name = gettext('Copy of %(task)s') % {'task': self.name}
                task.created_at = timezone.now()
                task.save()
                task.refresh_from_db()

                logger.info("Duplicating {} to {}".format(self, task))

                if os.path.isdir(self.task_path()):
                    try:
                        # Try to use hard links first
                        shutil.copytree(self.task_path(), task.task_path(), copy_function=os.link)
                    except Exception as e:
                        logger.warning("Cannot duplicate task using hard links, will use normal copy instead: {}".format(str(e)))
                        shutil.copytree(self.task_path(), task.task_path())
                else:
                    logger.warning("Task {} doesn't have folder, will skip copying".format(self))

                self.project.owner.profile.clear_used_quota_cache()

                from app.plugins import signals as plugin_signals
                plugin_signals.task_duplicated.send_robust(sender=self.__class__, task_id=task.id)

            return task
        except Exception as e:
            logger.warning("Cannot duplicate task: {}".format(str(e)))
        
        return False

    def write_backup_file(self):
        """Dump this tasks's fields to a backup file"""
        with open(self.data_path("backup.json"), "w") as f:
            f.write(json.dumps({
                'name': self.name,
                'processing_time': self.processing_time,
                'options': self.options,
                'created_at': self.created_at.astimezone(timezone.utc).timestamp(),
                'public': self.public,
                'resize_to': self.resize_to,
                'potree_scene': self.potree_scene,
                'tags': self.tags,
                'crop': json.loads(self.crop.geojson) if self.crop is not None else None,
            }))
    
    def read_backup_file(self):
        """Set this tasks fields based on the backup file (but don't save)"""
        backup_file = self.data_path("backup.json")
        if os.path.isfile(backup_file):
            try:
                with open(backup_file, "r") as f:
                    backup = json.loads(f.read())

                    self.name = backup.get('name', self.name)
                    self.processing_time = backup.get('processing_time', self.processing_time)
                    self.options = backup.get('options', self.options)
                    self.created_at = datetime.fromtimestamp(backup.get('created_at', self.created_at.astimezone(timezone.utc).timestamp()), tz=timezone.utc)
                    self.public = backup.get('public', self.public)
                    self.resize_to = backup.get('resize_to', self.resize_to)
                    self.potree_scene = backup.get('potree_scene', self.potree_scene)
                    self.tags = backup.get('tags', self.tags)

                    crop = backup.get('crop')
                    if crop is not None:
                        self.crop = json.dumps(crop)

            except Exception as e:
                logger.warning("Cannot read backup file: %s" % str(e))

    def get_task_backup_stream(self):
        self.write_backup_file()
        zip_dir = self.task_path("")
        paths = [{'n': os.path.relpath(os.path.join(dp, f), zip_dir), 'fs': os.path.join(dp, f)} for dp, dn, filenames in os.walk(zip_dir) for f in filenames]
        return self.zip_stream(paths)
    
    def get_asset_file_or_stream(self, asset):
        """
        Get a stream to an asset
        :param asset: one of ASSETS_MAP keys
        :return: (path|stream)
        """
        if asset in self.ASSETS_MAP:
            value = self.ASSETS_MAP[asset]
            if isinstance(value, str):
                return self.assets_path(value)

            elif isinstance(value, dict):
                if 'deferred_path' in value and 'deferred_compress_dir' in value:
                    zip_dir = self.assets_path(value['deferred_compress_dir'])
                    paths = [{'n': os.path.relpath(os.path.join(dp, f), zip_dir), 'fs': os.path.join(dp, f)} for dp, dn, filenames in os.walk(zip_dir) for f in filenames]
                    if 'deferred_exclude_files' in value and isinstance(value['deferred_exclude_files'], tuple):
                        paths = [p for p in paths if os.path.basename(p['fs']) not in value['deferred_exclude_files']]
                    
                    return self.zip_stream(paths)
                else:
                    raise FileNotFoundError("{} is not a valid asset (invalid dict values)".format(asset))
            else:
                raise FileNotFoundError("{} is not a valid asset (invalid map)".format(asset))
        else:
            raise FileNotFoundError("{} is not a valid asset".format(asset))

    def zip_stream(self, paths):
        if len(paths) == 0:
            raise FileNotFoundError("No files available for download")

        zs = ZipStream(sized=True)
        zs.comment = "Generated by WebODM"
        for p in paths:
            zs.add_path(p['fs'], p['n'])
        
        return zs

    def get_asset_download_path(self, asset):
        """
        Get the path to an asset download
        :param asset: one of ASSETS_MAP keys
        :return: path
        """
        if asset in self.ASSETS_MAP:
            value = self.ASSETS_MAP[asset]
            if isinstance(value, str):
                return self.assets_path(value)

            elif isinstance(value, dict):
                if 'deferred_path' in value and 'deferred_compress_dir' in value:
                    return value['deferred_path']
                else:
                    raise FileNotFoundError("{} is not a valid asset (invalid dict values)".format(asset))
            else:
                raise FileNotFoundError("{} is not a valid asset (invalid map)".format(asset))
        else:
            raise FileNotFoundError("{} is not a valid asset".format(asset))

    def handle_import(self):
        self.console += gettext("Importing assets...") + "\n"
        self.save()

        zip_path = self.assets_path("all.zip")
        # Import assets file from mounted system volume (media-dir)/imports by relative path.
        # Import file from relative path.
        if self.import_url and not os.path.exists(zip_path):
            if self.import_url == "file://external":
                # External asset import, files should already be in place
                pass 
            elif self.import_url.startswith("file://"):
                imports_folder_path = os.path.join(settings.MEDIA_ROOT, "imports")
                unsafe_path_to_import_file = os.path.join(settings.MEDIA_ROOT, "imports", self.import_url.replace("file://", ""))
                # check is file placed in shared media folder in /imports directory without traversing
                try:
                    checked_path_to_file = path_traversal_check(unsafe_path_to_import_file, imports_folder_path)
                    if os.path.isfile(checked_path_to_file):
                        copyfile(checked_path_to_file, zip_path)
                except SuspiciousFileOperation as e:
                    logger.error("Error due importing assets from {} for {} in cause of path checking error".format(self.import_url, self))
                    raise NodeServerError(e)
            else:
                try:
                    # TODO: this is potentially vulnerable to a zip bomb attack
                    #       mitigated by the fact that a valid account is needed to
                    #       import tasks
                    logger.info("Importing task assets from {} for {}".format(self.import_url, self))
                    download_stream = requests.get(self.import_url, stream=True, timeout=10)
                    content_length = download_stream.headers.get('content-length')
                    total_length = int(content_length) if content_length is not None else None
                    downloaded = 0
                    last_update = 0

                    with open(zip_path, 'wb') as fd:
                        for chunk in download_stream.iter_content(4096):
                            downloaded += len(chunk)

                            if time.time() - last_update >= 2:
                                # Update progress
                                if total_length is not None:
                                    Task.objects.filter(pk=self.id).update(running_progress=(float(downloaded) / total_length) * 0.9)

                                self.check_if_canceled()
                                last_update = time.time()

                            fd.write(chunk)

                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, ReadTimeoutError, requests.exceptions.MissingSchema) as e:
                    raise NodeServerError(e)

        self.refresh_from_db()

        try:
            self.extract_assets_and_complete()
        except (zipfile.BadZipFile, FileNotFoundError):
            raise NodeServerError(gettext("Invalid zip file"))
        except NotImplementedError:
            raise NodeServerError(gettext("Unsupported compression method"))
        
        images_json = self.assets_path("images.json")
        if os.path.exists(images_json):
            try:
                with open(images_json) as f:
                    images = json.load(f)
                    self.images_count = len(images)
            except:
                logger.warning("Cannot read images count from imported task {}".format(self))
                pass

        self.pending_action = None
        self.save()

    def process(self):
        """
        This method contains the logic for processing tasks asynchronously
        from a background thread or from a worker. Here tasks that are
        ready to be processed execute some logic. This could be communication
        with a processing node or executing a pending action.
        """

        try:
            if self.pending_action == pending_actions.IMPORT:
                self.handle_import()

            if self.pending_action == pending_actions.RESIZE:
                resized_images = self.resize_images()
                self.refresh_from_db()
                self.resize_gcp(resized_images)
                self.pending_action = None
                self.save()

            if self.auto_processing_node and not self.status in [status_codes.FAILED, status_codes.CANCELED]:
                # No processing node assigned and need to auto assign
                if self.processing_node is None:
                    # Assign first online node with lowest queue count
                    self.processing_node = ProcessingNode.find_best_available_node(self.project.owner)
                    if self.processing_node:
                        self.processing_node.queue_count += 1 # Doesn't have to be accurate, it will get overridden later
                        self.processing_node.save()

                        logger.info("Automatically assigned processing node {} to {}".format(self.processing_node, self))
                        self.save()

                # Processing node assigned, but is offline and no errors
                if self.processing_node and not self.processing_node.is_online():
                    # If we are queued up
                    # detach processing node, and reassignment
                    # will be processed at the next tick
                    if self.status == status_codes.QUEUED:
                        logger.info("Processing node {} went offline, reassigning {}...".format(self.processing_node, self))
                        self.uuid = ''
                        self.processing_node = None
                        self.status = None
                        self.save()

                    elif self.status == status_codes.RUNNING:
                        # Task was running and processing node went offline
                        # It could have crashed due to low memory
                        # or perhaps it went offline due to network errors.
                        # We can't easily differentiate between the two, so we need
                        # to notify the user because if it crashed due to low memory
                        # the user might need to take action (or be stuck in an infinite loop)
                        raise NodeServerError("Processing node went offline. This could be due to insufficient memory or a network error.")

            if self.processing_node:
                # Need to process some images (UUID not yet set and task doesn't have pending actions)?
                if not self.uuid and self.pending_action is None and self.status is None:
                    logger.info("Processing... {}".format(self))

                    images_path = self.task_path()
                    images = [os.path.join(images_path, i) for i in self.scan_images()]

                    # Track upload progress, but limit the number of DB updates
                    # to every 2 seconds (and always record the 100% progress)
                    last_update = 0
                    def callback(progress):
                        nonlocal last_update

                        time_has_elapsed = time.time() - last_update >= 2
                        if time_has_elapsed:
                            testWatch.manual_log_call("Task.process.callback")
                            self.check_if_canceled()
                            Task.objects.filter(pk=self.id).update(upload_progress=float(progress) / 100.0)
                            last_update = time.time()

                    # This takes a while
                    try:
                        uuid = self.processing_node.process_new_task(images, self.name, self.options, callback)
                    except NodeConnectionError as e:
                        # If we can't create a task because the node is offline
                        # We want to fail instead of trying again
                        raise NodeServerError(gettext('Connection error: %(error)s') % {'error': str(e)})

                    # Refresh task object before committing change
                    self.refresh_from_db()
                    self.upload_progress = 1.0
                    self.uuid = uuid
                    self.save()

                    # TODO: log process has started processing

            if self.pending_action is not None:
                if self.pending_action == pending_actions.CANCEL:
                    # Do we need to cancel the task on the processing node?
                    logger.info("Canceling {}".format(self))
                    if self.processing_node and self.uuid:
                        # Attempt to cancel the task on the processing node
                        # We don't care if this fails (we tried)
                        try:
                            self.processing_node.cancel_task(self.uuid)
                        except GenericError:
                            logger.warning("Could not cancel {} on processing node. We'll proceed anyway...".format(self))

                        self.status = status_codes.CANCELED
                        self.pending_action = None
                        self.save()
                    else:
                        # Tasks with no processing node or UUID need no special action
                        self.status = status_codes.CANCELED
                        self.pending_action = None
                        self.save()

                elif self.pending_action == pending_actions.RESTART:
                    logger.info("Restarting {}".format(self))
                    if self.processing_node:

                        # Check if the UUID is still valid, as processing nodes purge
                        # results after a set amount of time, the UUID might have been eliminated.
                        uuid_still_exists = False

                        if self.uuid:
                            try:
                                info = self.processing_node.get_task_info(self.uuid)
                                uuid_still_exists = info.uuid == self.uuid
                            except GenericError:
                                pass

                        need_to_reprocess = False

                        if uuid_still_exists:
                            # Good to go
                            try:
                                self.processing_node.restart_task(self.uuid, self.options)
                            except (NodeServerError, NodeResponseError) as e:
                                # Something went wrong
                                logger.warning("Could not restart {}, will start a new one".format(self))
                                need_to_reprocess = True
                        else:
                            need_to_reprocess = True

                        if need_to_reprocess:
                            logger.info("{} needs to be reprocessed".format(self))

                            # Task has been purged (or processing node is offline)
                            # Process this as a new task
                            # Removing its UUID will cause the scheduler
                            # to process this the next tick
                            self.uuid = ''

                            # We also remove the "rerun-from" parameter if it's set
                            self.options = list(filter(lambda d: d['name'] != 'rerun-from', self.options))
                            self.upload_progress = 0

                        self.console.reset()
                        self.processing_time = -1
                        self.status = None
                        self.last_error = None
                        self.pending_action = None
                        self.running_progress = 0
                        self.save()
                    else:
                        raise NodeServerError(gettext("Cannot restart a task that has no processing node"))

                elif self.pending_action == pending_actions.REMOVE:
                    logger.info("Removing {}".format(self))
                    if self.processing_node and self.uuid:
                        # Attempt to delete the resources on the processing node
                        # We don't care if this fails, as resources on processing nodes
                        # Are expected to be purged on their own after a set amount of time anyway
                        try:
                            self.processing_node.remove_task(self.uuid)
                        except GenericError:
                            pass

                    # What's more important is that we delete our task properly here
                    self.delete()

                    # Stop right here!
                    return
                
                elif self.pending_action == pending_actions.COMPACT:
                    logger.info("Compacting {}".format(self))
                    time.sleep(2) # Purely to make sure the user sees the "compacting..." message in the UI since this is so fast
                    self.compact()
                    self.pending_action = None
                    self.save()
                    return

            if self.processing_node:
                # Need to update status (first time, queued or running?)
                if self.uuid and self.status in [None, status_codes.QUEUED, status_codes.RUNNING]:
                    # Update task info from processing node
                    if not self.console.output():
                        current_lines_count = 0
                    else:
                        current_lines_count = len(self.console.output().split("\n"))

                    info = self.processing_node.get_task_info(self.uuid, current_lines_count)

                    self.processing_time = info.processing_time
                    self.status = info.status.value

                    if len(info.output) > 0:
                        self.console += "\n".join(info.output) + '\n'

                    # Update running progress
                    self.running_progress = (info.progress / 100.0) * self.TASK_PROGRESS_LAST_VALUE

                    if info.last_error != "":
                        self.last_error = info.last_error

                    # Has the task just been canceled, failed, or completed?
                    if self.status in [status_codes.FAILED, status_codes.COMPLETED, status_codes.CANCELED]:
                        logger.info("Processing status: {} for {}".format(self.status, self))

                        if self.status == status_codes.COMPLETED:
                            assets_dir = self.assets_path("")

                            # Remove previous assets directory
                            if os.path.exists(assets_dir):
                                logger.info("Removing old assets directory: {} for {}".format(assets_dir, self))
                                shutil.rmtree(assets_dir)

                            os.makedirs(assets_dir)

                            # Download and try to extract results up to 4 times
                            # (~5% of the times, on large downloads, the archive could be corrupted)
                            retry_num = 0
                            extracted = False
                            last_update = 0

                            def callback(progress):
                                nonlocal last_update

                                time_has_elapsed = time.time() - last_update >= 2

                                if time_has_elapsed or int(progress) == 100:
                                    Task.objects.filter(pk=self.id).update(running_progress=(
                                        self.TASK_PROGRESS_LAST_VALUE + (float(progress) / 100.0) * 0.1))
                                    last_update = time.time()

                            while not extracted:
                                last_update = 0
                                logger.info("Downloading all.zip for {}".format(self))

                                # Download all assets
                                zip_path = self.processing_node.download_task_assets(self.uuid, assets_dir, progress_callback=callback, parallel_downloads=max(1, int(16 / (2 ** retry_num))))

                                # Rename to all.zip
                                all_zip_path = self.assets_path("all.zip")
                                os.rename(zip_path, all_zip_path)

                                logger.info("Extracting all.zip for {}".format(self))

                                try:
                                    self.extract_assets_and_complete()
                                    extracted = True
                                except zipfile.BadZipFile:
                                    if retry_num < 5:
                                        logger.warning("{} seems corrupted. Retrying...".format(all_zip_path))
                                        retry_num += 1
                                        os.remove(all_zip_path)
                                    else:
                                        raise NodeServerError(gettext("Invalid zip file"))
                        else:
                            # FAILED, CANCELED
                            self.save()
                            
                            if self.status == status_codes.FAILED:
                                from app.plugins import signals as plugin_signals
                                plugin_signals.task_failed.send_robust(sender=self.__class__, task_id=self.id)

                    else:
                        # Still waiting...
                        self.save()

        except (NodeServerError, NodeResponseError) as e:
            if is_dns_resolution_problem(e) and patch_dns_resolution():
                logger.warning("{} DNS resolution failed with {}, we're going to attempt to patch the DNS resolution process and retry...".format(self, str(e)))
            else:
                self.set_failure(str(e))
        except NodeConnectionError as e:
            logger.warning("{} connection/timeout error: {}. We'll try reprocessing at the next tick.".format(self, str(e)))
        except TaskInterruptedException as e:
            # Task was interrupted during image resize / upload
            logger.warning("{} interrupted: {}".format(self, str(e)))

    def extract_assets_and_complete(self):
        """
        Extracts assets/all.zip (if available), populates task fields where required and assure COGs
        It will raise a zipfile.BadZipFile exception if the archive is corrupted.
        :return:
        """
        assets_dir = self.assets_path("")
        zip_path = self.assets_path("all.zip")
        is_backup = False

        if os.path.isfile(zip_path):
            # Extract from zip
            try:
                with zipfile.ZipFile(zip_path, "r") as zip_h:
                    zip_h.extractall(assets_dir)
            except zlib.error as e:
                raise zipfile.BadZipFile(str(e))
            finally:
                os.remove(zip_path)
            
            logger.info("Extracted all.zip for {}".format(self))

            # Check if this looks like a backup file, in which case we need to move the files
            # a directory level higher
            is_backup = os.path.isfile(self.assets_path("data", "backup.json")) and os.path.isdir(self.assets_path("assets"))
            if is_backup:
                logger.info("Restoring from backup")
                try:
                    tmp_dir = os.path.join(settings.FILE_UPLOAD_TEMP_DIR, f"{self.id}.backup")
                    
                    shutil.move(assets_dir, tmp_dir)
                    shutil.rmtree(self.task_path(""))
                    shutil.move(tmp_dir, self.task_path(""))
                except shutil.Error as e:
                    logger.warning("Cannot restore from backup: %s" % str(e))
                    raise NodeServerError("Cannot restore from backup")
            else:
                # Check if the zip file contained a top level directory
                # which shouldn't be there and try to fix the structure
                top_level = [os.path.join(assets_dir, d) for d in os.listdir(assets_dir)]
                if len(top_level) == 1 and os.path.isdir(top_level[0]) and (not top_level[0].endswith("odm_orthophoto")):
                    second_level = [os.path.join(top_level[0], f) for f in os.listdir(top_level[0])]
                    if len(second_level) > 0:
                        logger.info("Top level directory found in imported archive, attempting to fix")
                        for f in second_level:
                            shutil.move(f, assets_dir)
                        shutil.rmtree(top_level[0])

        elif self.import_url != "file://external":
            # all.zip should be missing only when doing external data import
            logger.warning("Cannot find assets archive for {} ({})".format(self, zip_path))
            raise NodeServerError("Cannot import task")

        # Populate *_extent fields
        extent_fields = self.get_extent_fields()

        for raster_path, field in extent_fields:
            if os.path.exists(raster_path):
                # Make sure this is a Cloud Optimized GeoTIFF
                # if not, it will be created
                try:
                    assure_cogeo(raster_path)
                except IOError as e:
                    logger.warning("Cannot create Cloud Optimized GeoTIFF for %s (%s). This will result in degraded visualization performance." % (raster_path, str(e)))

                # Read extent
                extent_wkt = get_raster_bounds_wkt(raster_path)
                if extent_wkt is not None:
                    extent = GEOSGeometry(extent_wkt, srid=4326)
                    setattr(self, field, extent)
                    logger.info("Populated extent field with {} for {}".format(raster_path, self))
                else:
                    logger.warning("Cannot populate extent field with {} for {}, not georeferenced".format(raster_path, self))
        
        self.check_ept()
        self.update_available_assets_field()
        self.update_georef_fields()
        self.update_orthophoto_bands_field()
        self.update_media_field()
        self.update_size()
        self.clear_task_assets_cache()
        self.potree_scene = {}
        self.running_progress = 1.0
        self.crop = None
        self.status = status_codes.COMPLETED

        if is_backup:
            self.read_backup_file()
            self.import_url = ""
        else:
            self.console += gettext("Done!") + "\n"

        task_output = self.assets_path("task_output.txt")
        if os.path.isfile(task_output):
            # Guarantee consistency, save space
            self.console.link(task_output)
        
        self.save()

        from app.plugins import signals as plugin_signals
        plugin_signals.task_completed.send_robust(sender=self.__class__, task_id=self.id)

    def check_ept(self, threads=1):
        # Make sure that the entwine_pointcloud/ept.json file exists
        # and generate it otherwise
        ept_file = self.assets_path("entwine_pointcloud", "ept.json")
        if os.path.isfile(ept_file):
            return
        
        point_cloud = self.get_point_cloud()
        if point_cloud is None:
            return
        
        # We have the point cloud, but no EPT. Generate EPT.
        entwine = shutil.which('entwine')
        if not entwine:
            logger.warning("Cannot create EPT, entwine program is missing")
            return None
        
        ept_dir = self.assets_path("entwine_pointcloud")
        try:
            if not os.path.exists(settings.MEDIA_TMP):
                os.makedirs(settings.MEDIA_TMP)

            tmp_ept_path = tempfile.mkdtemp('_ept', dir=settings.MEDIA_TMP)
            params = [entwine, "build", "--threads", str(threads), 
                "--tmp", quote(tmp_ept_path),
                "-i", quote(point_cloud),
                "-o", quote(ept_dir)]
            
            subprocess.run(params, timeout=12*60*60)

            if os.path.isdir(tmp_ept_path):
                shutil.rmtree(tmp_ept_path)
            return True
        except Exception as e:
            logger.warning("Cannot create EPT for %s (%s). 3D point cloud will not display properly." % (point_cloud, str(e)))


    def get_extent_fields(self):
        return [
            (os.path.realpath(self.assets_path("odm_orthophoto", "odm_orthophoto.tif")),
             'orthophoto_extent'),
            (os.path.realpath(self.assets_path("odm_dem", "dsm.tif")),
             'dsm_extent'),
            (os.path.realpath(self.assets_path("odm_dem", "dtm.tif")),
             'dtm_extent'),
        ]

    def get_reference_raster(self):
        extent_fields = self.get_extent_fields()
        for file, field in extent_fields:
            if getattr(self, field) is not None:
                return file 
    
    def get_point_cloud(self):
        for asset in ["georeferenced_model.laz", "georeferenced_model.las"]:
            f = os.path.realpath(self.assets_path(self.ASSETS_MAP[asset]))
            if os.path.isfile(f):
                return f

    def get_tile_path(self, tile_type, z, x, y):
        return self.assets_path("{}_tiles".format(tile_type), z, x, "{}.png".format(y))

    def get_tile_base_url(self, tile_type):
        # plant is just a special case of orthophoto
        if tile_type == 'plant':
            tile_type = 'orthophoto'

        return "/api/projects/{}/tasks/{}/{}/".format(self.project.id, self.id, tile_type)

    def get_map_items(self):
        types = []
        if 'orthophoto.tif' in self.available_assets: 
            types.append('orthophoto')
            types.append('plant')
        if 'dsm.tif' in self.available_assets: types.append('dsm')
        if 'dtm.tif' in self.available_assets: types.append('dtm')

        camera_shots = ''
        if 'shots.geojson' in self.available_assets: camera_shots = '/api/projects/{}/tasks/{}/download/shots.geojson'.format(self.project.id, self.id)

        ground_control_points = ''
        if 'ground_control_points.geojson' in self.available_assets: ground_control_points = '/api/projects/{}/tasks/{}/download/ground_control_points.geojson'.format(self.project.id, self.id)

        media = ''
        if isinstance(self.media, list) and len(self.media) > 0:
             media = '/api/projects/{}/tasks/{}/media.geojson'.format(self.project.id, self.id)

        return {
            'tiles': [{'url': self.get_tile_base_url(t), 'type': t} for t in types],
            'meta': {
                'task': {
                    'id': str(self.id),
                    'name': self.name,
                    'project': self.project.id,
                    'public': self.public,
                    'public_edit': self.public_edit,
                    'camera_shots': camera_shots,
                    'ground_control_points': ground_control_points,
                    'epsg': self.epsg,
                    'wkt': self.wkt,
                    'srs': get_srs_name_units_from_epsg_or_wkt(self.epsg, self.wkt),
                    'orthophoto_bands': self.orthophoto_bands,
                    'crop': self.crop is not None,
                    'extent': self.get_extent(),
                    'media': media
                }
            }
        }

    def get_projected_crop(self):
        if self.crop is None or (self.epsg is None and self.wkt is None):
            return None
        
        return geom_transform(self.crop, self.epsg if self.epsg is not None else self.wkt)

    def get_model_display_params(self):
        """
        Subset of a task fields used in the 3D model display view
        """
        return {
            'id': str(self.id),
            'project': self.project.id,
            'available_assets': self.available_assets,
            'public': self.public,
            'public_edit': self.public_edit,
            'epsg': self.epsg,
            'srs': get_srs_name_units_from_epsg_or_wkt(self.epsg, self.wkt),
            'crop_projected': self.get_projected_crop() 
        }

    def generate_deferred_asset(self, archive, directory, stream=False):
        """
        :param archive: path of the destination .zip file (relative to /assets/ directory)
        :param directory: path of the source directory to compress (relative to /assets/ directory)
        :param stream: return a stream instead of a path to the file
        :return: full path of the generated archive
        """
        archive_path = self.assets_path(archive)
        directory_path = self.assets_path(directory)

        if not os.path.exists(directory_path):
            raise FileNotFoundError("{} does not exist".format(directory_path))

        if not os.path.exists(archive_path):
            shutil.make_archive(os.path.splitext(archive_path)[0], 'zip', directory_path)

        return archive_path

    def update_available_assets_field(self, commit=False):
        """
        Updates the available_assets field with the actual types of assets available
        :param commit: when True also saves the model, otherwise the user should manually call save()
        """
        all_assets = list(self.ASSETS_MAP.keys())
        self.available_assets = [asset for asset in all_assets if self.is_asset_available_slow(asset)]
        if commit: self.save()

    
    def update_georef_fields(self, commit=False):
        """
        Updates the epsg and wkt field with the correct values
        :param commit: when True also saves the model, otherwise the user should manually call save()
        """
        epsg = None
        wkt = None

        for asset in ['orthophoto.tif', 'dsm.tif', 'dtm.tif']:
            asset_path = self.assets_path(self.ASSETS_MAP[asset])
            if os.path.isfile(asset_path):
                try:
                    with rasterio.open(asset_path) as f:
                        if f.crs is not None:
                            code = f.crs.to_epsg()
                            if code is not None:
                                epsg = code
                                break # We assume all assets are in the same CRS
                            else:
                                # Try to get code from WKT
                                wkt = f.crs.to_wkt()
                                if wkt is not None:
                                    code = epsg_from_wkt(wkt)
                                    if code is not None:
                                        epsg = code
                                        break
                except Exception as e:
                    logger.warning(e)

        # If point cloud is not georeferenced, dataset is not georeferenced
        # (2D assets might be using pseudo-georeferencing)
        point_cloud = self.assets_path(self.ASSETS_MAP['georeferenced_model.laz'])
        if (epsg is not None or wkt is not None) and os.path.isfile(point_cloud):
            if not is_pointcloud_georeferenced(point_cloud):
                logger.info("{} is not georeferenced".format(self))
                epsg = None
                wkt = None

        self.epsg = epsg
        if epsg is None:
            self.wkt = wkt
        else:
            self.wkt = None # Only save one or the other

        if commit: self.save()


    def update_orthophoto_bands_field(self, commit=False):
        """
        Updates the orthophoto bands field with the correct value
        :param commit: when True also saves the model, otherwise the user should manually call save()
        """
        bands = []
        orthophoto_path = self.assets_path(self.ASSETS_MAP['orthophoto.tif'])

        if os.path.isfile(orthophoto_path):
            with rasterio.open(orthophoto_path) as f:
                names = [c.name for c in f.colorinterp]
                for i, n in enumerate(names):
                    bands.append({
                        'name': n,
                        'description': f.descriptions[i]
                    })

        self.orthophoto_bands = bands
        if commit: self.save()

    PHOTO_EXTENSIONS = {'.jpg', '.jpeg', '.png'}
    VIDEO_EXTENSIONS = VIDEO_MOD_EXTENSIONS
    MEDIA_EXTENSIONS = PHOTO_EXTENSIONS | VIDEO_EXTENSIONS | {'.srt'}
    MEDIA_TYPE_ORDER = {'photo': 0, 'pano': 1, 'video': 2}

    @staticmethod
    def get_media_type(filepath):
        ext = os.path.splitext(filepath)[1].lower()
        if ext in Task.VIDEO_EXTENSIONS:
            return 'video'
        if ext in Task.PHOTO_EXTENSIONS:
            if is_panorama(filepath):
                return 'pano'
            return 'photo'
        return None

    def build_media_entry(self, filepath):
        filename = os.path.basename(filepath)
        media_type = self.get_media_type(filepath)
        if media_type is None:
            return None

        size = os.path.getsize(filepath)
        geolocation = None

        existing = None
        if self.media:
            for entry in self.media:
                if entry.get('filename') == filename:
                    existing = entry
                    break   

        entry = {
            'type': media_type,
            'filename': filename,
            'description': existing.get('description', '') if existing else '',
            'size': size,
        }

        if media_type in ['photo', 'pano']:
            geolocation = extract_gps_from_image(filepath)
            if media_type == 'pano':
                try:
                    with Image.open(filepath) as im:
                        entry['width'] = im.size[0]
                        entry['height'] = im.size[1]
                except Exception:
                    pass

        elif media_type == 'video':
            # Try to extract SRT, parse geolocation at t = 0
            if extract_subtitles(filepath):
                srt_file = srt_file_for_video(filepath)
                geolocation = extract_gps_from_srt(srt_file)
                entry['srt'] = True
        
        entry['geolocation'] = geolocation
        
        return entry

    def update_media_field(self, commit=False):
        media_dir = self.media_directory_path()
        if not os.path.isdir(media_dir):
            if self.media:
                self.media = []
                if commit:
                    self.save()
            return

        entries = []
        for f in os.listdir(media_dir):
            fp = os.path.join(media_dir, f)
            if not os.path.isfile(fp):
                continue
            entry = self.build_media_entry(fp)
            if entry is not None:
                entries.append(entry)

        entries.sort(key=lambda e: (self.MEDIA_TYPE_ORDER.get(e['type'], 99), e['filename'].lower()))
        self.media = entries
        if commit:
            self.save()
    
    def get_media_entry(self, filename):
        for entry in self.media:
            if entry.get('filename') == filename:
                return entry

    def delete(self, using=None, keep_parents=False):
        task_id = self.id
        from app.plugins import signals as plugin_signals
        plugin_signals.task_removing.send_robust(sender=self.__class__, task_id=task_id)

        directory_to_delete = os.path.join(settings.MEDIA_ROOT,
                                           task_directory_path(self.id, self.project.id))
        self.clear_task_assets_cache()

        super(Task, self).delete(using, keep_parents)

        # Remove files related to this task
        try:
            shutil.rmtree(directory_to_delete)
        except FileNotFoundError as e:
            logger.warning(e)

        self.project.owner.profile.clear_used_quota_cache()

        plugin_signals.task_removed.send_robust(sender=self.__class__, task_id=task_id)

    def compact(self):
        # Remove all images
        images_path = self.task_path()
        images = [os.path.join(images_path, i) for i in self.scan_images()]
        for im in images:
            try:
                os.unlink(im)
            except Exception as e:
                logger.warning(e)

        self.compacted = True
        self.update_size(commit=True)

    def check_public_edit(self):
        """
        Returns whether we need to check change permissions on this task
        during an API call that needs to make edits
        """
        public = self.public or self.project.public
        public_edit = self.public_edit or self.project.public_edit

        return (not public) or (public and not public_edit)

    def set_failure(self, error_message):
        logger.error("FAILURE FOR {}: {}".format(self, error_message))
        self.last_error = error_message
        self.status = status_codes.FAILED
        self.pending_action = None
        self.save()
        
    def find_all_files_matching(self, regex):
        directory = full_task_directory_path(self.id, self.project.id)
        return [os.path.join(directory, f) for f in os.listdir(directory) if
                       re.match(regex, f, re.IGNORECASE)]

    def check_if_canceled(self):
        # Check if task has been canceled/removed
        if Task.objects.only("pending_action").get(pk=self.id).pending_action in [pending_actions.CANCEL,
                                                                                  pending_actions.REMOVE,
                                                                                  pending_actions.COMPACT]:
            raise TaskInterruptedException()

    def resize_images(self):
        """
        Destructively resize this task's JPG images while retaining EXIF tags.
        Resulting images are always converted to JPG.
        TODO: add support for tiff files
        :return list containing paths of resized images and resize ratios
        """
        if self.resize_to < 0:
            logger.warning("We were asked to resize images to {}, this might be an error.".format(self.resize_to))
            return []
        # Add a signal to notify that we are resizing images
        from app.plugins import signals as plugin_signals

        plugin_signals.task_resizing_images.send_robust(sender=self.__class__, task_id=self.id)

        images_path = self.find_all_files_matching(r'.*\.(jpe?g|tiff?|png)$')
        total_images = len(images_path)
        resized_images_count = 0
        last_update = 0
        lock = threading.Lock()

        def callback(retval=None):
            nonlocal last_update
            nonlocal resized_images_count
            nonlocal total_images

            resized_images_count += 1
            if time.time() - last_update >= 2:
                with lock:
                    if settings.TESTING:
                        # In testing, django is unable to find the Task object, so we skip this
                        return
                    
                    # Update progress
                    Task.objects.filter(pk=self.id).update(resize_progress=(float(resized_images_count) / float(total_images)))
                    self.check_if_canceled()
                    last_update = time.time()

        max_workers = max(1, min(settings.WORKERS_MAX_THREADS, len(images_path)))
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for image_path in images_path:
                f = executor.submit(resize_image, image_path, self.resize_to, callback)
                futures.append(f)
            
            resized_images = []
            for f in futures:
                try:
                    resized_images.append(f.result())
                except Exception as e:
                    logger.warning(f"Error resizing image: {str(e)}")
        
        resized_images = [im for im in resized_images if im is not None]
        
        Task.objects.filter(pk=self.id).update(resize_progress=1.0)

        return resized_images

    def resize_gcp(self, resized_images):
        """
        Destructively change this task's GCP file (if any)
        by resizing the location of GCP entries.
        :param resized_images: list of objects having "path" and "resize_ratio" keys
            for example [{'path': 'path/to/DJI_0018.jpg', 'resize_ratio': 0.25}, ...]
        :return: path to changed GCP file or None if no GCP file was found/changed
        """
        gcp_path = self.find_all_files_matching(r'.*\.txt$')

        # Skip geo.txt, image_groups.txt, align.(las|laz|tif) files
        gcp_path = list(filter(lambda p: os.path.basename(p).lower() not in ['geo.txt', 'image_groups.txt', 'align.las', 'align.laz', 'align.tif'], gcp_path))
        if len(gcp_path) == 0: return None

        # Assume we only have a single GCP file per task
        gcp_path = gcp_path[0]

        image_ratios = {}
        for ri in resized_images:
            image_ratios[os.path.basename(ri['path']).lower()] = ri['resize_ratio']

        try:
            gcpFile = GCPFile(gcp_path)
            gcpFile.create_resized_copy(gcp_path, image_ratios)
            logger.info("Resized GCP file {}".format(gcp_path))
            return gcp_path
        except Exception as e:
            logger.warning("Could not resize GCP file {}: {}".format(gcp_path, str(e)))


    def create_task_directories(self):
        """
        Create directories for this task (if they don't exist already)
        """
        assets_dir = self.assets_path("")
        try:
            os.makedirs(assets_dir)
        except OSError as exc:  # Python >2.5
            if exc.errno == errno.EEXIST and os.path.isdir(assets_dir):
                pass
            else:
                raise

    def scan_images(self):
        tp = self.task_path()
        try:
            return [e.name for e in os.scandir(tp) if e.is_file()]
        except:
            return []

    def get_image_path(self, filename):
        p = self.task_path(filename)
        return path_traversal_check(p, self.task_path())

    def set_alignment_file_from(self, align_task):
        tp = self.task_path()
        if not os.path.exists(tp):
            os.makedirs(tp, exist_ok=True)

        alignment_file = align_task.assets_path(self.ASSETS_MAP['georeferenced_model.laz'])
        dst_file = self.task_path("align.laz")

        if os.path.exists(dst_file):
            os.unlink(dst_file)

        if os.path.exists(alignment_file):
            try:
                os.link(alignment_file, dst_file)
            except:
                shutil.copy(alignment_file, dst_file)
        else:
            logger.warn("Cannot set alignment file for {}, {} does not exist".format(self, alignment_file))
    
    def get_check_file_asset_path(self, asset):
        file = self.assets_path(self.ASSETS_MAP[asset])
        if isinstance(file, str) and os.path.isfile(file):
            return file

    def handle_images_upload(self, files, chunk_info=None):
        uploaded = {}
        for file in files:
            name = file.name
            if name is None:
                continue

            tp = self.task_path()
            if not os.path.exists(tp):
                os.makedirs(tp, exist_ok=True)

            if chunk_info is not None:
                if os.path.isfile(chunk_info['tmp_upload_file']) and chunk_info['chunk_index'] == 0:
                    os.unlink(chunk_info['tmp_upload_file'])
                
                with open(chunk_info['tmp_upload_file'], 'ab') as fd:
                    fd.seek(chunk_info['byte_offset'])
                    if isinstance(file, InMemoryUploadedFile):
                        for chunk in file.chunks():
                            fd.write(chunk)
                    else:
                        with open(file.temporary_file_path(), 'rb') as f:
                            shutil.copyfileobj(f, fd)
                
                if chunk_info['chunk_index'] + 1 < chunk_info['total_chunk_count']:
                    continue # will wait for next chunk

            dst_path = self.get_image_path(name)

            if chunk_info is not None:
                if chunk_info['tmp_upload_file'] is not None and os.path.isfile(chunk_info['tmp_upload_file']):
                    shutil.move(chunk_info['tmp_upload_file'], dst_path)
            else:
                with open(dst_path, 'wb+') as fd:
                    if isinstance(file, InMemoryUploadedFile):
                        for chunk in file.chunks():
                            fd.write(chunk)
                    else:
                        with open(file.temporary_file_path(), 'rb') as f:
                            shutil.copyfileobj(f, fd)
            
            uploaded[name] = os.path.getsize(dst_path)
        return uploaded

    def update_size(self, commit=False):
        try:
            total_bytes = 0
            for dirpath, _, filenames in os.walk(self.task_path()):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    if not os.path.islink(fp):
                        total_bytes += os.path.getsize(fp)
            self.size = (total_bytes / 1024 / 1024)
            if commit: self.save()

            self.project.owner.profile.clear_used_quota_cache()
        except Exception as e:
            logger.warn("Cannot update size for task {}: {}".format(self, str(e)))


    def get_task_assets_cache(self):
        if self.id is None:
            return None
        return os.path.join(settings.MEDIA_CACHE, "task_assets", str(self.id))
    
    def clear_task_assets_cache(self):
        d = self.get_task_assets_cache()
        if d is None:
            return
        
        if os.path.isdir(d):
            try:
                shutil.rmtree(d)
            except Exception as e:
                logger.warning("Cannot clear task assets cache {}: {}".format(d, str(e)))

    def get_safe_textured_model(self, max_size_mb=150):
        input_glb = self.get_check_file_asset_path('textured_model.glb')
        if input_glb is None or (not 'textured_model.glb' in self.available_assets):
            raise FileNotFoundError("GLB asset does not exist")
        
        if settings.TESTING:
            rescale = 2
        else:
            size = os.path.getsize(input_glb)
            if size <= max_size_mb * 1024 * 1024:
                return input_glb
            
            rescale = 1

            while size > max_size_mb * 1024 * 1024:
                rescale *= 2
                size = size // 2.6  # Texture size reduction factor (not science)

        p, ext = os.path.splitext(input_glb)
        base = os.path.basename(p)
        cache_dir = self.get_task_assets_cache()
        output_glb = os.path.join(cache_dir, f"{base}-{rescale}{ext}")
        if os.path.isfile(output_glb):
            # Cached, return immediately
            return output_glb

        # Prevent multiple requests from generating the same rescale
        # by putting an exclusive lock on the process
        lock_id = 'glb_gen_lock_{}_{}'.format(rescale, str(self.id))

        try:

            lod_lock_last_update = redis_client.getset(lock_id, time.time())
            while lod_lock_last_update is not None:
                # Check if lock has expired
                if time.time() - float(lod_lock_last_update) <= 60:
                    # Locked, wait
                    time.sleep(2)
                    lod_lock_last_update = redis_client.get(lock_id)
                else:
                    # Expired
                    logger.warning("GLB generation lock {} has expired! Generation might be taking too long.".format(str(self.id)))
                    redis_client.set(lock_id, time.time())
                    break
            
            if os.path.isfile(output_glb):
                # Cached, return immediately
                return output_glb

            if not os.path.isdir(cache_dir):
                os.makedirs(cache_dir, exist_ok=True)

            glbopti_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts/glbopti.js"))
            output_glb_tmp = output_glb + ".tmp.glb"

            params = ["node", glbopti_path,
                            "--input", quote(input_glb), 
                            "--output", quote(output_glb_tmp),
                            "--texture-rescale", str(rescale)]
            if settings.TESTING:
                params += ["--test"]
            subprocess.run(params, timeout=180)

            if not os.path.isfile(output_glb_tmp):
                raise FileNotFoundError("GLB generation failed")
            
            os.rename(output_glb_tmp, output_glb)            
            return output_glb
        except Exception as e:
            logger.warning("Could not generate GLB for {}: {}".format(str(self.id), str(e)))
            return input_glb
        finally:
            try:
                redis_client.delete(lock_id)
            except redis.exceptions.RedisError:
                # Ignore errors, the lock will expire at some point
                pass