import json
import os
import time
from django import template
from django.conf import settings
from django.templatetags.static import static
from django.utils.safestring import mark_safe

register = template.Library()
STATS_FILE = os.path.join(settings.BASE_DIR, 'webpack-stats.json')
BUNDLE_DIR = 'app/bundles/'
_stats = None


def load_stats():
    with open(STATS_FILE, encoding='utf-8') as f:
        return json.load(f)


def get_stats():
    global _stats
    if settings.DEBUG:
        stats = load_stats()
        while stats.get('status') == 'compiling':
            time.sleep(0.1)
            stats = load_stats()
        return stats
    if _stats is None:
        _stats = load_stats()
    return _stats


@register.simple_tag
def render_bundle(bundle_name, attrs=''):
    stats = get_stats()
    if stats.get('status') != 'done':
        raise RuntimeError("webpack-stats.json status is '{}': {} {}".format(stats.get('status'), stats.get('error', ''), stats.get('message', '')))
    tags = []
    for chunk in stats['chunks'][bundle_name]:
        url = static(BUNDLE_DIR + chunk['name'])
        if chunk['name'].endswith('.js'):
            tags.append('<script type="text/javascript" src="{}" {}></script>'.format(url, attrs))
        elif chunk['name'].endswith('.css'):
            tags.append('<link type="text/css" href="{}" rel="stylesheet" {}/>'.format(url, attrs))
    return mark_safe('\n'.join(tags))
