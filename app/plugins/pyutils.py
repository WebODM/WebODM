import os
import re
import subprocess
import hashlib

def parse_requirements(requirements_file):
    """
    Parse a requirements.txt file
    :param requirements_file: path to requirements.txt file
    :return: package names
    """
    if os.path.exists(requirements_file):
        with open(requirements_file, 'r') as f:
            deps = list(filter(lambda x: len(x) > 0, map(str.strip, f.read().split('\n'))))
            return [re.split('==|<=|>=|<|>', d)[0] for d in deps]

    return []


def requirements_installed(requirements_file, python_path):
    """
    Checks if the packages in requirements.txt have been installed in the specified
    python path. Note that this does NOT check for versions, just package names
    :param requirements_file: path to requirements.txt
    :param python_path: path to directory where packages are installed
    :return: True if all requirements are installed, false otherwise
    """
    reqs = subprocess.check_output(['python', '-m', 'pip', 'freeze', '--path', python_path])
    installed_packages = [r.decode().split('==')[0] for r in reqs.split()]
    deps = parse_requirements(requirements_file)

    return set(deps) & set(installed_packages) == set(deps)

def compute_file_md5(filename):
    return hashlib.md5(open(filename, 'rb').read()).hexdigest()
