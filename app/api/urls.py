from django.urls import re_path, include

from app.api.presets import PresetViewSet
from app.plugins.views import api_view_handler
from .projects import ProjectViewSet
from .tasks import TaskViewSet, TaskDownloads, TaskThumbnail, TaskAssets, TaskBackup, \
  TaskAssetsImport, TaskExternalImportInit, TaskExternalImportUpload, TaskExternalImportCommit, TaskSafeTexturedModel, TaskRtc
from .media import TaskMediaUpload, TaskMediaManage, TaskMediaDownload, TaskMediaThumbnail, TaskMediaList, TaskMediaGeoJSON, TaskVideoFlightPath
from .splats import TaskSplatsDownload, TaskSplatsUpload, TaskSplatsDelete
from .overlays import TaskOverlayConvert, TaskOverlaysSync, TaskOverlay, overlayStamp
from .panorama import TaskPanoramaTiles
from .imageuploads import Thumbnail, ImageDownload
from .processingnodes import ProcessingNodeViewSet, ProcessingNodeOptionsView
from .admin import AdminUserViewSet, AdminGroupViewSet, AdminProfileViewSet
from rest_framework_nested import routers
from .jwt import obtain_jwt_token, refresh_jwt_token
from .tiler import TileJson, Bounds, Metadata, Tiles, Export
from .potree import Scene, CameraView
from .workers import CheckTask, GetTaskResult, CancelTask
from .users import UsersList, UsersProfile
from .groups import GroupsList
from .externalauth import ExternalTokenAuth
from webodm import settings

router = routers.DefaultRouter()
router.register(r'projects', ProjectViewSet)
router.register(r'processingnodes', ProcessingNodeViewSet)
router.register(r'presets', PresetViewSet, basename='presets')

tasks_router = routers.NestedSimpleRouter(router, r'projects', lookup='project')
tasks_router.register(r'tasks', TaskViewSet, basename='projects-tasks')

admin_router = routers.DefaultRouter()
admin_router.register(r'admin/users', AdminUserViewSet, basename='admin-users')
admin_router.register(r'admin/groups', AdminGroupViewSet, basename='admin-groups')
admin_router.register(r'admin/profiles', AdminProfileViewSet, basename='admin-profiles')

urlpatterns = [
    re_path(r'processingnodes/options/$', ProcessingNodeOptionsView.as_view()),

    re_path(r'^', include(router.urls)),
    re_path(r'^', include(tasks_router.urls)),
    re_path(r'^', include(admin_router.urls)),

    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/(?P<tile_type>orthophoto|dsm|dtm)/tiles\.json$', TileJson.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/(?P<tile_type>orthophoto|dsm|dtm)/bounds$', Bounds.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/(?P<tile_type>orthophoto|dsm|dtm)/metadata$', Metadata.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/(?P<tile_type>orthophoto|dsm|dtm)/tiles/(?P<z>[\d]+)/(?P<x>[\d]+)/(?P<y>[\d]+)\.?(?P<ext>png|jpg|webp)?$', Tiles.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/(?P<tile_type>orthophoto|dsm|dtm)/tiles/(?P<z>[\d]+)/(?P<x>[\d]+)/(?P<y>[\d]+)@(?P<scale>[\d]+)x\.?(?P<ext>png|jpg|webp)?$', Tiles.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/(?P<asset_type>orthophoto|dsm|dtm|georeferenced_model)/export$', Export.as_view()),

    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/download/(?P<asset>.+)$', TaskDownloads.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/textured_model/$', TaskSafeTexturedModel.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/assets/(?P<unsafe_asset_path>.+)$', TaskAssets.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/import$', TaskAssetsImport.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/import/external/init$', TaskExternalImportInit.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/import/external/upload$', TaskExternalImportUpload.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/import/external/commit$', TaskExternalImportCommit.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/thumbnail$', TaskThumbnail.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/backup$', TaskBackup.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/rtc$', TaskRtc.as_view()),

    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/overlays/(?P<overlay_id>[^/]+)\.geojson$', TaskOverlay.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/overlays/convert$', TaskOverlayConvert.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/overlays/sync$', TaskOverlaysSync.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/overlays/stamp$', overlayStamp),

    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/media.geojson$', TaskMediaGeoJSON.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/media/$', TaskMediaList.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/media/upload$', TaskMediaUpload.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/media/download/(?P<filename>.+)$', TaskMediaDownload.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/media/thumbnail/(?P<filename>.+)$', TaskMediaThumbnail.as_view()),
    
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/media/video/(?P<filename>[^/]+)/flightpath\.geojson$', TaskVideoFlightPath.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/media/manage/(?P<filename>.+)$', TaskMediaManage.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/media/panorama/(?P<filename>[^/]+)/tiles/(?P<level>\d+)/(?P<face>\w)/(?P<row>\d+)/(?P<col>\d+)\.jpg$', TaskPanoramaTiles.as_view()),

    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/splats/download$', TaskSplatsDownload.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/splats/download/(?P<celery_task_id>[^/]+)$', TaskSplatsDownload.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/splats/upload$', TaskSplatsUpload.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/splats/delete$', TaskSplatsDelete.as_view()),

    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/images/thumbnail/(?P<image_filename>.+)$', Thumbnail.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/images/download/(?P<image_filename>.+)$', ImageDownload.as_view()),

    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/3d/scene$', Scene.as_view()),
    re_path(r'projects/(?P<project_pk>[^/.]+)/tasks/(?P<pk>[^/.]+)/3d/cameraview$', CameraView.as_view()),

    re_path(r'workers/check/(?P<celery_task_id>.+)', CheckTask.as_view()),
    re_path(r'workers/get/(?P<celery_task_id>.+)', GetTaskResult.as_view()),
    re_path(r'workers/cancel/(?P<celery_task_id>.+)', CancelTask.as_view()),
    

    re_path(r'^auth/', include('rest_framework.urls')),
    
    re_path(r'^token-auth/refresh/?$', refresh_jwt_token),
    re_path(r'^token-auth/?$', obtain_jwt_token),
    

    re_path(r'^plugins/(?P<plugin_name>[^/.]+)/(.*)$', api_view_handler),
    
    re_path(r'^user/profile/$', UsersProfile.as_view())
]

if settings.ENABLE_USERS_API:
    urlpatterns.append(re_path(r'users', UsersList.as_view()))
    urlpatterns.append(re_path(r'groups', GroupsList.as_view()))

if settings.EXTERNAL_AUTH_ENDPOINT != '':
    urlpatterns.append(re_path(r'^external-token-auth/', ExternalTokenAuth.as_view()))

