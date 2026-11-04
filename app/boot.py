import os
import sys

import kombu
from django.contrib.auth.models import Permission
from django.contrib.auth.models import User, Group
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned
from django.core.files import File
from django.db.utils import ProgrammingError
from guardian.shortcuts import assign_perm

from worker import tasks as worker_tasks
from app.models import Preset
from app.models import Theme
from app.plugins import init_plugins
from nodeodm.models import ProcessingNode
from webodm.settings import MEDIA_ROOT
from . import signals
import logging
from .models import Task, Setting
from webodm import settings
from webodm.wsgi import booted


def boot():
    # booted is a shared memory variable to keep track of boot status
    # as multiple gunicorn workers could trigger the boot sequence twice
    if (not settings.DEBUG and booted.value) or settings.MIGRATING or settings.FLUSHING: return

    booted.value = True
    logger = logging.getLogger('app.logger')

    logger.info("Booting WebODM {}".format(settings.VERSION))

    if settings.DEBUG:
        logger.warning("Debug mode is ON (for development this is OK)")

    # Silence django's "Warning: Session data corrupted" messages
    session_logger = logging.getLogger("django.SuspiciousOperation.SuspiciousSession")
    session_logger.disabled = True

    # Make sure our app/media/tmp folder exists
    if not os.path.exists(settings.MEDIA_TMP):
        os.makedirs(settings.MEDIA_TMP)

    # Check default group
    try:
        default_group, created = Group.objects.get_or_create(name='Default')
        if created:
            logger.info("Created default group")

            # Assign viewprocessing node object permission to default processing node (if present)
            # Otherwise non-root users will not be able to process
            try:
                pnode = ProcessingNode.objects.get(hostname="node-odx-1")
                assign_perm('view_processingnode', default_group, pnode)
                logger.info("Added view_processingnode permissions to default group")
            except ObjectDoesNotExist:
                pass


        # Add default permissions (view_project, change_project, delete_project, etc.)
        for permission in ('_project', '_task', '_preset'):
            default_group.permissions.add(
                *list(Permission.objects.filter(codename__endswith=permission))
            )

        # Add permission to view processing nodes
        default_group.permissions.add(Permission.objects.get(codename="view_processingnode"))

        add_default_presets()

        # Add settings
        default_theme, created = Theme.objects.get_or_create(name='Default')
        if created:
            logger.info("Created default theme")

            if settings.DEFAULT_THEME_CSS:
                default_theme.css = settings.DEFAULT_THEME_CSS
                default_theme.save()

        if not Setting.objects.exists():
            s = Setting.objects.create(
                    app_name=settings.APP_NAME,
                    theme=default_theme)
            s.app_logo.save(os.path.basename(settings.APP_DEFAULT_LOGO), File(open(settings.APP_DEFAULT_LOGO, 'rb')))

            logger.info("Created settings")
        
        init_plugins()

        if not settings.TESTING:
            try:
                worker_tasks.update_nodes_info.delay()
            except kombu.exceptions.OperationalError as e:
                logger.error("Cannot connect to celery broker at {}. Make sure that valkey is running at that address: {}".format(settings.CELERY_BROKER_URL, str(e)))


    except ProgrammingError:
        logger.warning("Could not touch the database. If running a migration, this is expected.")


def add_default_presets():
    try:
        Preset.objects.update_or_create(name='Multispectral', system=True,
                                        defaults={'options': [{'name': 'auto-boundary', 'value': True},
                                                              {'name': 'radiometric-calibration', 'value': 'camera'}]})
        Preset.objects.update_or_create(name='Volume Analysis', system=True,
                                        defaults={'options': [{'name': 'auto-boundary', 'value': True},
                                                              {'name': 'dsm', 'value': True},
                                                              {'name': 'dem-resolution', 'value': '2'},
                                                              {'name': 'pc-quality', 'value': 'high'}]})
        Preset.objects.update_or_create(name='3D Model', system=True,
                                        defaults={'options': [{'name': 'auto-boundary', 'value': True},
                                                              {'name': 'mesh-octree-depth', 'value': "12"},
                                                              {'name': 'use-3dmesh', 'value': True},
                                                              {'name': 'pc-quality', 'value': 'high'},
                                                              {'name': 'mesh-size', 'value': '300000'}]})
        Preset.objects.update_or_create(name='Buildings', system=True,
                                        defaults={'options': [{'name': 'auto-boundary', 'value': True},
                                                              {'name': 'mesh-size', 'value': '300000'},
                                                              {'name': 'feature-quality', 'value': 'high'},
                                                              {'name': 'pc-quality', 'value': 'high'}]})
        Preset.objects.update_or_create(name='Forest', system=True,
                                        defaults={'options': [{'name': 'auto-boundary', 'value': True},
                                                              {'name': 'min-num-features', 'value': '18000'},
                                                              {'name': 'use-3dmesh', 'value': True},
                                                              {'name': 'feature-quality', 'value': 'medium'}]})
        Preset.objects.update_or_create(name='DSM + DTM', system=True,
                                        defaults={'options': [{'name': 'auto-boundary', 'value': True},
                                                              {'name': 'dsm', 'value': True},
                                                              {'name': 'dtm', 'value': True}]})
        Preset.objects.update_or_create(name='Field', system=True,
                                        defaults={'options': [{'name': 'sfm-algorithm', 'value': 'planar'},
                                                              {'name': 'fast-orthophoto', 'value': True},
                                                              {'name': 'matcher-neighbors', 'value': 4}]})
        Preset.objects.update_or_create(name='Fast Orthophoto', system=True,
                                        defaults={'options': [{'name': 'auto-boundary', 'value': True},
                                                              {'name': 'fast-orthophoto', 'value': True}]})
        Preset.objects.update_or_create(name='High Resolution', system=True,
                                        defaults={'options': [{'name': 'auto-boundary', 'value': True},
                                                              {'name': 'dsm', 'value': True},
                                                              {'name': 'dem-resolution', 'value': "1.0"},
                                                              {'name': 'orthophoto-resolution', 'value': "1.0"}]})
        Preset.objects.update_or_create(name='Default', system=True,
                                        defaults={'options': [{'name': 'auto-boundary', 'value': True},
                                                              {'name': 'dsm', 'value': True}]})

    except MultipleObjectsReturned:
        # Mostly to handle a legacy code problem where
        # multiple system presets with the same name were
        # created if we changed the options
        Preset.objects.filter(system=True).delete()
        add_default_presets()
