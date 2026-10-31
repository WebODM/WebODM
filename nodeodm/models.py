from __future__ import unicode_literals

from django.db import models
from django.utils import timezone
from django.dispatch import receiver
from guardian.models import GroupObjectPermissionBase
from guardian.models import UserObjectPermissionBase
from guardian.shortcuts import get_objects_for_user
from django.utils.translation import gettext_lazy as _

from webodm import settings

import json
from pyodx import Node
from pyodx import exceptions
from django.db.models import signals
from datetime import timedelta
import logging

logger = logging.getLogger('app.logger')

class ProcessingNode(models.Model):
    hostname = models.CharField(verbose_name=_("Hostname"), max_length=255, help_text=_("Hostname or IP address where the node is located (can be an internal hostname as well). If you are using Docker, this is never 127.0.0.1 or localhost. Find the IP address of your host machine by running ifconfig on Linux or by checking your network settings."))
    port = models.PositiveIntegerField(verbose_name=_("Port"), help_text=_("Port that connects to the node's API"))
    api_version = models.CharField(verbose_name=_("API Version"), max_length=32, null=True, help_text=_("API version used by the node"))
    last_refreshed = models.DateTimeField(verbose_name=_("Last Refreshed"), null=True, help_text=_("When was the information about this node last retrieved?"))
    queue_count = models.PositiveIntegerField(verbose_name=_("Queue Count"), default=0, help_text=_("Number of tasks currently being processed by this node (as reported by the node itself)"))
    available_options = models.JSONField(verbose_name=_("Available Options"), default=dict, help_text=_("Description of the options that can be used for processing"))
    token = models.CharField(verbose_name=_("Token"), max_length=1024, blank=True, default="", help_text=_("Token to use for authentication. If the node doesn't have authentication, you can leave this field blank."))
    max_images = models.PositiveIntegerField(verbose_name=_("Max Images"), help_text=_("Maximum number of images accepted by this node."), blank=True, null=True)
    engine_version = models.CharField(verbose_name=_("Engine Version"), max_length=32, null=True, help_text=_("Engine version used by the node."))
    label = models.CharField(verbose_name=_("Label"), max_length=255, default="", blank=True, help_text=_("Optional label for this node. When set, this label will be shown instead of the hostname:port name."))
    engine = models.CharField(verbose_name=_("Engine"), max_length=255, null=True, help_text=_("Engine used by the node."))

    class Meta:
        verbose_name = _("Processing Node")
        verbose_name_plural = _("Processing Nodes")

    def __str__(self):
        if self.label != "":
            return self.label
        else:
            return '{}:{}'.format(self.hostname, self.port)

    @staticmethod
    def find_best_available_node(user = None):
        """
        Attempts to find an available node (seen in the last 5 minutes, and with lowest queue count)
        :return: ProcessingNode | None
        """
        if user is not None:
            nodes = get_objects_for_user(user, 'view_processingnode', ProcessingNode, accept_global_perms=False)
        else:
            nodes = ProcessingNode.objects.all()

        if not settings.NODE_OPTIMISTIC_MODE:
            nodes = nodes.filter(last_refreshed__gte=timezone.now() - timedelta(minutes=settings.NODE_OFFLINE_MINUTES))
        
        return nodes.order_by('queue_count').first()

    def is_online(self):
        if settings.NODE_OPTIMISTIC_MODE:
            return True

        return self.last_refreshed is not None and \
               self.last_refreshed >= timezone.now() - timedelta(minutes=settings.NODE_OFFLINE_MINUTES)

    def update_node_info(self, save=True):
        """
        Retrieves information and options from the node API
        and saves it into the database.

        :param save: whether to save the updated information into the database
        :returns: True if information could be updated, False otherwise
        """
        api_client = self.api_client(timeout=5)
        try:
            info = api_client.info()

            self.api_version = info.version
            self.queue_count = info.task_queue_count

            if isinstance(info.max_images, (int, float)):
                self.max_images = max(0, info.max_images)
            else:
                self.max_images = None
            self.engine_version = info.engine_version
            self.engine = info.engine

            options = list(map(lambda o: o.__dict__, api_client.options()))
            self.available_options = options
            self.last_refreshed = timezone.now()
            if save:
                self.save()
            return True
        except exceptions.GenericError:
            return False

    def api_client(self, timeout=30):
        return Node(self.hostname, self.port, self.token, timeout)

    def get_available_options_json(self, pretty=False):
        """
        :returns available options in JSON string format
        """
        kwargs = dict(indent=4, separators=(',', ": ")) if pretty else dict() 
        return json.dumps(self.available_options, **kwargs)

    def options_list_to_dict(self, options = []):
        """
        Convers options formatted as a list ([{'name': optionName, 'value': optionValue}, ...])
        to a dictionary {optionName: optionValue, ...}
        :param options: options
        :return: dict
        """
        opts = {}
        if options is not None:
            for o in options:
                opts[o['name']] = o['value']

        return opts

    def process_new_task(self, images, name=None, options=[], progress_callback=None):
        """
        Sends a set of images (and optional GCP file) via the API
        to start processing.

        :param images: list of path images
        :param name: name of the task
        :param options: options to be used for processing ([{'name': optionName, 'value': optionValue}, ...])
        :param progress_callback: optional callback invoked during the upload images process to be used to report status.

        :returns UUID of the newly created task
        """
        if len(images) < 1: raise exceptions.NodeServerError("Need at least 1 file")

        api_client = self.api_client()

        opts = self.options_list_to_dict(options)

        task = api_client.create_task(images, opts, name, progress_callback, parallel_uploads=settings.NODE_CONNECTIONS)
        return task.uuid

    def get_task_info(self, uuid, with_output=None):
        """
        Gets information about this task, such as name, creation date, 
        processing time, status, command line options and number of 
        images being processed.
        """
        api_client = self.api_client()
        task = api_client.get_task(uuid)
        task_info = task.info(with_output)

        # Output support for older clients
        if not api_client.version_greater_or_equal_than("1.5.1") and with_output:
            task_info.output = self.get_task_console_output(uuid, with_output)

        return task_info

    def get_task_console_output(self, uuid, line):
        """
        Retrieves the console output of the OpenDroneMap's process.
        Useful for monitoring execution and to provide updates to the user.
        """
        api_client = self.api_client()
        task = api_client.get_task(uuid)
        return task.output(line)

    def cancel_task(self, uuid):
        """
        Cancels a task (stops its execution, or prevents it from being executed)
        """
        api_client = self.api_client()
        task = api_client.get_task(uuid)
        return task.cancel()

    def remove_task(self, uuid):
        """
        Removes a task and deletes all of its assets
        """
        api_client = self.api_client()
        task = api_client.get_task(uuid)
        return task.remove()

    def download_task_assets(self, uuid, destination, progress_callback, parallel_downloads=16):
        """
        Downloads a task asset
        """
        api_client = self.api_client()
        task = api_client.get_task(uuid)
        return task.download_zip(destination, progress_callback, parallel_downloads=parallel_downloads)

    def restart_task(self, uuid, options = None):
        """
        Restarts a task that was previously canceled or that had failed to process
        """

        api_client = self.api_client()
        task = api_client.get_task(uuid)
        return task.restart(self.options_list_to_dict(options))

    def delete(self, using=None, keep_parents=False):
        pnode_id = self.id
        super(ProcessingNode, self).delete(using, keep_parents)

        from app.plugins import signals as plugin_signals
        plugin_signals.processing_node_removed.send_robust(sender=self.__class__, processing_node_id=pnode_id)


# First time a processing node is created, automatically try to update
@receiver(signals.post_save, sender=ProcessingNode, dispatch_uid="update_processing_node_info")
def auto_update_node_info(sender, instance, created, **kwargs):
    if created:
        try:
            instance.update_node_info()
        except exceptions.GenericError:
            pass
        except Exception as e:
            logger.warning("auto_update_node_info: " + str(e))

class ProcessingNodeUserObjectPermission(UserObjectPermissionBase):
    content_object = models.ForeignKey(ProcessingNode, on_delete=models.CASCADE)


class ProcessingNodeGroupObjectPermission(GroupObjectPermissionBase):
    content_object = models.ForeignKey(ProcessingNode, on_delete=models.CASCADE)
