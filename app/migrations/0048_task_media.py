from django.db import migrations
import django.contrib.postgres.fields


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0047_task_wkt'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='media',
            field=django.db.models.JSONField(blank=True, default=list, help_text='List of media files associated with this task', verbose_name='Media'),
        ),
    ]
