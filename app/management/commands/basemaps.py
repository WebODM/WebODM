from django.core.management.base import BaseCommand
from django.db import transaction

from app.models import Basemap


DEFAULT_BASEMAPS = [
    {
        'default': True,
        'type': 'tms',
        'url': '//{s}.google.com/vt/lyrs=s,h&x={x}&y={y}&z={z}',
        'attribution': 'Map data: &copy; Google Maps',
        'label': 'Google Maps Hybrid',
        'maxzoom': 21,
        'minzoom': 0,
        'subdomains': 'mt0,mt1,mt2,mt3',
    },
    {
        'type': 'tms',
        'url': '//server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        'attribution': 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
        'label': 'ESRI Satellite',
        'maxzoom': 21,
        'minzoom': 0,
    },
    {
        'type': 'tms',
        'url': '//tile.openstreetmap.org/{z}/{x}/{y}.png',
        'attribution': '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        'label': 'OpenStreetMap',
        'maxzoom': 19,
        'minzoom': 0,
    },
    {
        'type': 'tms',
        'url': 'https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.swissimage/default/current/3857/{z}/{x}/{y}.jpeg',
        'attribution': '&copy; swisstopo',
        'label': 'SWISSIMAGE (swisstopo)',
        'maxzoom': 20,
        'minzoom': 0,
    },
]


class Command(BaseCommand):
    help = 'Manage basemaps'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('action', type=str, choices=['reset'])
        super(Command, self).add_arguments(parser)

    def handle(self, **options):
        if options.get('action') == 'reset':
            with transaction.atomic():
                deleted, _ = Basemap.objects.all().delete()
                for basemap in DEFAULT_BASEMAPS:
                    Basemap.objects.create(**basemap)

            print(f'Reset basemaps: deleted {deleted} created {len(DEFAULT_BASEMAPS)}')
        else:
            print('Invalid action')
