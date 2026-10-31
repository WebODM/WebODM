import datetime
import math
import logging
import time
from django import template
from webodm import settings
from django.utils.translation import gettext as _
from app.oidc_providers import get_oidc_providers

register = template.Library()
logger = logging.getLogger('app.logger')

@register.simple_tag
def task_options_docs_link():
    return settings.TASK_OPTIONS_DOCS_LINK

@register.simple_tag
def gcp_docs_link():
    return settings.GCP_DOCS_LINK

@register.simple_tag
def splat_docs_link():
    return settings.SPLAT_DOCS_LINK

@register.simple_tag
def reset_password_link():
    return settings.RESET_PASSWORD_LINK

@register.simple_tag
def has_external_auth():
    return settings.EXTERNAL_AUTH_ENDPOINT != ""

@register.simple_tag
def has_oidc_auth():
    return len(get_oidc_providers()) > 0

@register.simple_tag
def html_after_body():
    return settings.HTML_AFTER_BODY

@register.simple_tag
def oidc_auth_providers():
    return get_oidc_providers()

@register.filter
def disk_size(megabytes):
    k = 1000
    k2 = k ** 2
    k3 = k ** 3
    if megabytes <= k2:
        return str(round(megabytes / k, 2)) + ' GB'
    elif megabytes <= k3:
        return str(round(megabytes / k2, 2)) + ' TB'
    else:
        return str(round(megabytes / k3, 2)) + ' PB'

@register.simple_tag
def percentage(num, den, maximum=None):
    if den == 0:
        return 100
    perc = max(0, num / den * 100)
    if maximum is not None:
        perc = min(perc, maximum)
    return perc

@register.simple_tag(takes_context=True)
def quota_exceeded_grace_period(context):
    deadline = context.request.user.profile.get_quota_deadline()
    now = time.time()
    if deadline is None:
        deadline = now + settings.QUOTA_EXCEEDED_GRACE_PERIOD * 60 * 60
    diff = max(0, deadline - now)
    if diff >= 60*60*24*2:
        return _("in %(num)s days") % {"num": math.floor(diff / (60*60*24))}
    elif diff >= 60*60*2:
        return _("in %(num)s hours") % {"num": math.floor(diff / (60*60))}
    elif diff > 1:
        return _("in %(num)s minutes") % {"num": math.floor(diff / 60)}
    else:
        return _("very soon")
    

@register.simple_tag
def is_single_user_mode():
    return settings.SINGLE_USER_MODE

@register.simple_tag
def is_desktop_mode():
    return settings.DESKTOP_MODE

@register.simple_tag
def is_dev_mode():
    return settings.DEV

@register.simple_tag(takes_context=True)
def settings_image_url(context, image):
    try:
        img_cache = getattr(context['SETTINGS'], image)
    except KeyError:
        logger.warning("Cannot get SETTINGS key from context. Something's wrong in settings_image_url.")
        return ''

    try:
        return img_cache.url
    except FileNotFoundError:
        logger.warning("Cannot get %s, this could mean the image was deleted." % image)
        return ''

@register.simple_tag(takes_context=True)
def get_footer(context):
    try:
        settings = context['SETTINGS']
    except KeyError:
        logger.warning("Cannot get SETTINGS key from context. The footer will not be displayed.")
        return ""

    if settings.theme.html_footer == "": return ""

    organization = ""
    if settings.organization_name != "" and settings.organization_website != "":
        organization = "<a href='{}'>{}</a>".format(settings.organization_website, settings.organization_name)
    elif settings.organization_name != "":
        organization = settings.organization_name

    footer = settings.theme.html_footer
    footer = footer.replace("{ORGANIZATION}", organization)
    footer = footer.replace("{YEAR}", str(datetime.datetime.now().year))

    return "<footer>" + \
           footer + \
            "</footer>"

@register.simple_tag(takes_context=True)
def theme(context, color):
    """Return a theme color from the currently selected theme"""
    try:
        return getattr(context['SETTINGS'].theme, color)
    except Exception as e:
        logger.warning("Cannot load configuration from theme(): " + str(e))
        return "#0000FF" # dah buh dih ah buh daa..

@register.simple_tag
def complementary(hexcolor):
    """Returns complementary RGB color
    Example: complementaryColor('#FFFFFF') --> '#000000'
    """
    if hexcolor[0] == '#':
        hexcolor = hexcolor[1:]
    rgb = (hexcolor[0:2], hexcolor[2:4], hexcolor[4:6])
    comp = ['%02X' % (255 - int(a, 16)) for a in rgb]
    return '#' + ''.join(comp)

@register.simple_tag
def scaleby(hexcolor, scalefactor, ignore_value = False):
    """
    Scales a hex string by ``scalefactor``, but is color dependent, unless ignore_value is True
    scalefactor is now always between 0 and 1. A value of 0.8
    will cause bright colors to become darker and
    dark colors to become brigther by 20%
    """

    def calculate(hexcolor, scalefactor):
        """
        Scales a hex string by ``scalefactor``. Returns scaled hex string.
        To darken the color, use a float value between 0 and 1.
        To brighten the color, use a float value greater than 1.

        >>> colorscale("#DF3C3C", .5)
        #6F1E1E
        >>> colorscale("#52D24F", 1.6)
        #83FF7E
        >>> colorscale("#4F75D2", 1)
        #4F75D2
        """

        def clamp(val, minimum=0, maximum=255):
            if val < minimum:
                return minimum
            if val > maximum:
                return maximum
            return int(val)

        hexcolor = hexcolor.strip('#')

        if scalefactor < 0 or len(hexcolor) != 6:
            return hexcolor

        r, g, b = int(hexcolor[:2], 16), int(hexcolor[2:4], 16), int(hexcolor[4:], 16)

        r = clamp(r * scalefactor)
        g = clamp(g * scalefactor)
        b = clamp(b * scalefactor)

        return "#%02x%02x%02x" % (r, g, b)


    hexcolor = hexcolor.strip('#')
    scalefactor = abs(float(scalefactor))
    scalefactor = min(1.0, max(0, scalefactor))

    r, g, b = int(hexcolor[:2], 16), int(hexcolor[2:4], 16), int(hexcolor[4:], 16)
    value = max(r, g, b)

    return calculate(hexcolor, scalefactor if ignore_value or value >= 127 else 2 - scalefactor)

@register.simple_tag
def scalebyiv(hexcolor, scalefactor):
    return scaleby(hexcolor, scalefactor, True)