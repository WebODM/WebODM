from django.http import Http404
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import render

from django.contrib import messages
from django.utils.translation import gettext as _
from django import forms
from webodm import settings
from django.http import JsonResponse
from django.utils.translation import get_language
import requests
import json, tempfile, os, logging, shutil, subprocess, zipfile, glob, pathlib

logger = logging.getLogger('app.logger')

def download_file(url, destination):
    download_stream = requests.get(url, stream=True, timeout=90)

    with open(destination, 'wb') as fd:
        for chunk in download_stream.iter_content(4096):
            fd.write(chunk)

def copymerge(src, dst, symlinks=False, ignore=None):
    for item in os.listdir(src):
        s = os.path.join(src, item)
        d = os.path.join(dst, item)
        if os.path.isdir(s):
            pathlib.Path(d).mkdir(parents=True, exist_ok=True)
            copymerge(s, d, symlinks, ignore)
        else:
            shutil.copy2(s, d)


@user_passes_test(lambda u: u.is_superuser)
def dev_tools(request, action):
    if not settings.DEV:
        raise Http404()

    if request.method == 'POST':
        if action == "reloadTranslation":
            try:
                args = json.loads(request.body).get('args')

                fd, tmpzipPath = tempfile.mkstemp(suffix=".zip")
                os.close(fd)

                logger.info("Downloading %s" % args[0])
                download_file(args[0], tmpzipPath)

                tmpPath = tempfile.mkdtemp()

                logger.info("Extracting... %s" % tmpzipPath)
                with zipfile.ZipFile(tmpzipPath, 'r') as zip:
                    zip.extractall(path=tmpPath)
                os.unlink(tmpzipPath)
                                
                locale_paths = glob.glob(os.path.join(tmpPath, "**", "locale"), recursive=True)
                if len(locale_paths) == 0:
                    raise Exception(_("Cannot find locale/ folder in .zip archive"))
                
                webodm_locale_dir = os.path.join(settings.BASE_DIR, "locale")

                for locale_path in locale_paths:
                    logger.info("Found locale at %s" % locale_path)
                    logger.info("Moving %s to %s..." % (locale_path, webodm_locale_dir))
                    copymerge(locale_path, webodm_locale_dir)

                logger.info("Running python manage.py translate extract && python manage.py translate build --safe")
                subprocess.call(['bash', '-c', 'python manage.py translate extract && %s python manage.py translate build --safe'], cwd=settings.BASE_DIR)
                
                return JsonResponse({'message': _("Translation files reloaded!"), 'reload': True})
            except Exception as e:
                return JsonResponse({'error': str(e)})
        else:
            return JsonResponse({'error': _("Invalid action")})
    else:
        return render(request, 'app/dev_tools.html', { 
                'title': _('Developer Tools'),
                'current_locale': get_language()
            })

