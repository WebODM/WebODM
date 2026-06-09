from django.db import migrations
from django.core.cache import cache


SWISSIMAGE = {
    'type': 'tms',
    'url': 'https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.swissimage/default/current/3857/{z}/{x}/{y}.jpeg',
    'attribution': '&copy; swisstopo',
    'label': 'SWISSIMAGE (swisstopo)',
    'maxzoom': 20,
    'minzoom': 0,
}


def add_swissimage(apps, schema_editor):
    Basemap = apps.get_model('app', 'Basemap')
    Basemap.objects.get_or_create(label=SWISSIMAGE['label'], defaults=SWISSIMAGE)
    cache.delete('app_basemaps')


def remove_swissimage(apps, schema_editor):
    Basemap = apps.get_model('app', 'Basemap')
    Basemap.objects.filter(
        label=SWISSIMAGE['label'],
        url=SWISSIMAGE['url'],
    ).delete()
    cache.delete('app_basemaps')


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0051_init_basemaps'),
    ]

    operations = [
        migrations.RunPython(add_swissimage, remove_swissimage),
    ]
