import os
import sys
import logging
import importlib
import subprocess
import traceback
import platform

import json
import glob

import shutil
from functools import reduce
from string import Template

from django.http import HttpResponse

from app.models import Plugin
from app.models import Setting
from django.conf import settings
from app.security import path_traversal_check

logger = logging.getLogger('app.logger')

# Add additional python path to discover plugins
if not settings.MEDIA_ROOT in sys.path:
    sys.path.append(settings.MEDIA_ROOT)

def init_plugins():
    # Make sure app/media/plugins exists
    if not os.path.exists(get_plugins_persistent_path()):
        os.mkdir(get_plugins_persistent_path())

    # Make sure app/media/plugins is importable as a module
    if not os.path.isfile(os.path.join(get_plugins_persistent_path(), "__init__.py")):
        try:
            with open(os.path.join(get_plugins_persistent_path(), "__init__.py"), 'w') as f:
                f.write("\n")
        except Exception as e:
            logger.warning("Cannot create __init__.py: %s" % str(e))
    
    build_plugins()
    sync_plugin_db()
    register_plugins()

def sync_plugin_db():
    """
    Creates db entries for undiscovered plugins to keep track
    of enabled/disabled plugins
    """
    if settings.MIGRATING: return

    # Erase cache
    clear_plugins_cache()

    db_plugins = Plugin.objects.all()
    fs_plugins = get_plugins()

    # Remove plugins that are in the database but not on the file system
    for db_plugin in db_plugins:
        fs_found = next((fs_plugin for fs_plugin in fs_plugins if db_plugin.name == fs_plugin.get_name()), None)
        if not fs_found:
            Plugin.objects.filter(name=db_plugin.name).delete()
            logger.info("Cleaned [{}] plugin from database (not found in file system)".format(db_plugin.name))

    # Add plugins found in the file system, but not yet in the database
    for plugin in get_plugins():
        # Plugins that have a "disabled" file are disabled
        disabled_path = plugin.get_path("disabled")
        disabled =  os.path.isfile(disabled_path)

        _, created = Plugin.objects.get_or_create(
            name=plugin.get_name(),
            defaults={'enabled': not disabled},
        )
        if created:
            logger.info("Added [{}] plugin to database".format(plugin))


def clear_plugins_cache():
    global plugins
    plugins = None


def build_plugins():
    for plugin in get_plugins():
        # Build translations (.po --> .mo) if needed
        if plugin.path_exists("locale"):
            for po in glob.glob(plugin.get_path("locale", "*", "LC_MESSAGES", "*.po")):
                mo = po[:-3] + ".mo"
                if not os.path.exists(mo):
                    logger.info("Building {}".format(mo))
                    try:
                        subprocess.call(["msgfmt", "--check-format", "-o", mo, po])
                    except FileNotFoundError:
                        logger.warning("msgfmt is not installed, cannot build translations for {}".format(plugin))
                        break

        # Check for package.json in public directory
        # and run npm install if needed
        if plugin.path_exists("public", "package.json") and not plugin.path_exists("public", "node_modules") and not plugin.path_exists("public", "build"):
            logger.info("Running npm install for {}".format(plugin))

            try:
                npm = "npm"
                if platform.system() == "Windows":
                    npm = "npm.cmd"
                command = [npm, 'install']
                if plugin.is_persistent():
                    command.append('--ignore-scripts')
                subprocess.call(command, cwd=plugin.get_path("public"))
            except FileNotFoundError:
                logger.warn("npm is not installed, will skip this plugin")
                continue

        # Check if we need to generate a webpack.config.js
        if len(plugin.build_jsx_components()) > 0 and plugin.path_exists('public'):
            build_paths = map(lambda p: os.path.join(plugin.get_path('public'), p), plugin.build_jsx_components())
            paths_ok = not (False in map(lambda p: os.path.exists, build_paths))

            if paths_ok:
                wpc_path = os.path.join(settings.BASE_DIR, 'app', 'plugins', 'templates', 'webpack.config.js.tmpl')
                with open(wpc_path) as f:
                    tmpl = Template(f.read())

                    # Create entry configuration
                    entry = {}
                    for e in plugin.build_jsx_components():
                        entry[os.path.splitext(os.path.basename(e))[0]] = ['./' + e]
                    wpc_content = tmpl.substitute({
                        'entry_json': json.dumps(entry)
                    })

                    with open(plugin.get_path('public/webpack.config.js'), 'w') as f:
                        f.write(wpc_content)
            else:
                logger.warning(
                    "Cannot generate webpack.config.js for {}, a path is missing: {}".format(plugin, ' '.join(build_paths)))

        # Check for webpack.config.js (if we need to build it)
        if plugin.path_exists("public/webpack.config.js"):
            if settings.DEV and webpack_watch_process_count() <= 2 and settings.DEV_WATCH_PLUGINS:
                logger.info("Running webpack with watcher for {}".format(plugin.get_name()))
                subprocess.Popen(['webpack-cli', '--watch'], cwd=plugin.get_path("public"))
            elif not plugin.path_exists("public", "build"):
                logger.info("Running webpack for {}".format(plugin.get_name()))

                try:
                    webpack = "webpack-cli"
                    if platform.system() == "Windows":
                        webpack = "webpack-cli.cmd"

                    subprocess.call([webpack], cwd=plugin.get_path("public"))
                except FileNotFoundError:
                    logger.warn("webpack-cli is not installed, plugin will not work")

def webpack_watch_process_count():
    count = 0
    try:
        pids = [pid for pid in os.listdir('/proc') if pid.isdigit()]
        for pid in pids:
            try:
                if "/usr/bin/webpack-cli" in open(os.path.join('/proc', pid, 'cmdline'), 'r').read().split('\0'):
                    count += 1
            except IOError:  # proc has already terminated
                continue
    except:
        logger.warning("webpack_watch_process_count is not supported on this platform.")

    return count


def register_plugins():
    for plugin in get_active_plugins():
        try:
            plugin.register()
            logger.info("Registered {}".format(plugin))
        except Exception as e:
            disable_plugin(plugin.get_name())
            logger.warning("Cannot register {}: {}".format(plugin, str(e)))

def register_plugin_locales():
    for plugin in get_active_plugins():
        plugin.register_locale()

def valid_plugin(plugin_path):
    initpy_path = os.path.join(plugin_path, "__init__.py")
    pluginpy_path = os.path.join(plugin_path, "plugin.py")
    manifest_path = os.path.join(plugin_path, "manifest.json")
    return os.path.isfile(initpy_path) and os.path.isfile(manifest_path) and os.path.isfile(pluginpy_path)

plugins = None
def get_plugins():
    """
    :return: all plugins instances (enabled or not)
    """
    # Cache plugins search
    global plugins
    if plugins != None: return plugins

    plugins_paths = get_plugins_paths()
    plugins = []

    for plugins_path in plugins_paths:
        if not os.path.isdir(plugins_path):
            continue

        for dir in os.listdir(plugins_path):
            # Each plugin must have a manifest.json and a plugin.py
            plugin_path = os.path.join(plugins_path, dir)

            # Do not load test plugin unless we're in test mode
            if os.path.basename(plugin_path).endswith('test') and not settings.TESTING:
                continue

            # Ignore .gitignore
            if os.path.basename(plugin_path) == '.gitignore':
                continue

            # Check plugin required files
            if not valid_plugin(plugin_path):
                continue

            # Instantiate the plugin
            try:
                try:
                    if settings.TESTING:
                        module = importlib.import_module("app.media_test.plugins.{}".format(dir))
                    else:
                        module = importlib.import_module("plugins.{}".format(dir))

                    plugin = (getattr(module, "Plugin"))()
                except (ImportError, AttributeError) as plugin_error:
                    try:
                        module = importlib.import_module("coreplugins.{}".format(dir))
                        plugin = (getattr(module, "Plugin"))()
                    except (ImportError, AttributeError) as coreplugin_error:
                        raise coreplugin_error from plugin_error

                # Check version
                manifest = plugin.get_manifest()
                if 'webodmMinVersion' in manifest:
                    min_version = manifest['webodmMinVersion']
                    manifest_path = os.path.join(plugin_path, "manifest.json")

                    if versionToInt(min_version) > versionToInt(settings.VERSION):
                        logger.warning(
                            "In {} webodmMinVersion is set to {} but WebODM version is {}. Plugin will not be loaded. Update WebODM.".format(
                                manifest_path, min_version, settings.VERSION))
                        continue

                # Skip plugins in blacklist
                if plugin.get_name() in settings.PLUGINS_BLACKLIST:
                    continue

                # Skip plugins already added
                if plugin.get_name() in [p.get_name() for p in plugins]:
                    logger.warning("Duplicate plugin name found in {}, skipping".format(plugin_path))
                    continue

                plugins.append(plugin)
            except Exception as e:
                logger.warning("Failed to instantiate plugin {}: {}: {}".format(dir, e, e.__cause__))

    return plugins


def get_active_plugins():
    if settings.MIGRATING: return []

    plugins = []
    try:
        enabled_plugins = [p.name for p in Plugin.objects.filter(enabled=True).all()]
        for plugin in get_plugins():
            if plugin.get_name() in enabled_plugins:
                plugins.append(plugin)
    except Exception as e:
        logger.warning("Cannot get active plugins. If running a migration this is expected: %s" % str(e))

    return plugins


def get_plugin_by_name(name, only_active=True, refresh_cache_if_none=False):
    if only_active:
        plugins = get_active_plugins()
    else:
        plugins = get_plugins()

    res = list(filter(lambda p: p.get_name() == name, plugins))
    res = res[0] if res else None

    if refresh_cache_if_none and res is None:
        # Retry after clearing the cache
        clear_plugins_cache()
        return get_plugin_by_name(name, only_active=only_active, refresh_cache_if_none=False)
    else:
        return res

def get_current_plugin(only_active=False):
    """
    When called from a python module inside a plugin's directory,
    it returns the plugin that this python module belongs to
    :return: Plugin instance
    """
    caller_filename = traceback.extract_stack()[-2][0]

    for p in get_plugins_paths():
        relp = os.path.relpath(caller_filename, p)
        if ".." in relp:
            continue

        parts = relp.split(os.sep)
        if len(parts) > 0:
            plugin_name = parts[0]
            return get_plugin_by_name(plugin_name, only_active=only_active)

    return None

def get_plugins_paths():
    current_path = os.path.dirname(os.path.realpath(__file__))
    return [
        os.path.abspath(get_plugins_persistent_path()),
        os.path.abspath(os.path.join(current_path, "..", "..", "coreplugins")),
    ]

def get_plugins_persistent_path(*paths):
    return path_traversal_check(os.path.join(settings.MEDIA_ROOT, "plugins", *paths), os.path.join(settings.MEDIA_ROOT, "plugins"))

def get_dynamic_script_handler(script_path, callback=None, **kwargs):
    def handleRequest(request):
        if callback is not None:
            template_params = callback(request, **kwargs)
            if not template_params:
                return HttpResponse("")
        else:
            template_params = kwargs

        with open(script_path) as f:
            tmpl = Template(f.read())
            try:
                return HttpResponse(tmpl.substitute(template_params))
            except TypeError as e:
                return HttpResponse("Template substitution failed with params: {}. {}".format(str(template_params), e))

    return handleRequest

def enable_plugin(plugin_name):
    p = get_plugin_by_name(plugin_name, only_active=False)
    p.register()
    try:
        p.enable()
    except Exception as e:
        logger.warning(f"Plugin: {plugin_name} enable error: {str(e)}")
        raise  # Propagate error to UI
    Plugin.objects.get(pk=plugin_name).enable()
    return p

def disable_plugin(plugin_name):
    p = get_plugin_by_name(plugin_name, only_active=False)
    try:
        p.disable()
    except Exception as e:
        logger.warning(f"Plugin: {plugin_name} disable error: {str(e)}")
        Plugin.objects.get(pk=plugin_name).disable()
        raise # Propagate error to UI
    Plugin.objects.get(pk=plugin_name).disable()
    return p

def delete_plugin(plugin_name):
    Plugin.objects.get(pk=plugin_name).delete()
    if os.path.exists(get_plugins_persistent_path(plugin_name)):
        shutil.rmtree(get_plugins_persistent_path(plugin_name))
    clear_plugins_cache()

def get_site_settings():
    return Setting.objects.first()

def versionToInt(version):
    """
    Converts a WebODM version string (major.minor.build) to a integer value
    for comparison
    >>> versionToInt("1.2.3")
    100203
    >>> versionToInt("1")
    100000
    >>> versionToInt("1.2.3.4")
    100203
    >>> versionToInt("wrong")
    -1
    """

    try:
        return sum([reduce(lambda mult, ver: mult * ver, i) for i in zip([100000, 100, 1], map(int, version.split(".")))])
    except:
        return -1
