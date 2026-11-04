import django.dispatch

task_completed = django.dispatch.Signal()
task_removing = django.dispatch.Signal()
task_removed = django.dispatch.Signal()
task_failed = django.dispatch.Signal()
task_resizing_images = django.dispatch.Signal()
task_duplicated = django.dispatch.Signal()

processing_node_removed = django.dispatch.Signal()
