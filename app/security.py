from django.core.exceptions import SuspiciousFileOperation
import os
import re

def path_traversal_check(unsafe_path, known_safe_path):
    known_safe_path = os.path.abspath(known_safe_path)
    unsafe_path = os.path.abspath(unsafe_path)

    if (os.path.commonprefix([known_safe_path, unsafe_path]) != known_safe_path):
        raise SuspiciousFileOperation("{} is not safe".format(unsafe_path))

    # Passes the check
    return unsafe_path


def sanitize_filename(filename):
    filename = filename.replace('/', '').replace('\\', '')
    name, ext = os.path.splitext(filename)
    name = re.sub(r'[^\w\s.\-]', '', name).strip().strip('.')
    ext = re.sub(r'[^\w.]', '', ext)
    return name + ext