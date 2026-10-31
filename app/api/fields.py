import json

from django.core.exceptions import ValidationError
from rest_framework.fields import Field
from app.geoutils import polygon_ring, polygon_from_ring

class PolygonGeometryField(Field):
    type_name = 'PolygonGeometryField'

    def to_representation(self, value):
        return value

    def to_internal_value(self, value):
        if value == '' or value is None:
            return None

        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                raise ValidationError('Invalid format: not GeoJSON')

        if isinstance(value, dict) and value.get('geometry'):
            value = value['geometry']

        ring = polygon_ring(value)
        if ring is None:
            raise ValidationError('Invalid format: not a GeoJSON Polygon')

        return polygon_from_ring(ring)
