#!/usr/bin/env python

import urllib.request
import zipfile
import os
import tempfile
import sys
import subprocess

with tempfile.TemporaryDirectory(prefix='ratester') as tmpd:
    url = 'https://github.com/ClusterLabs/pacemaker/archive/master.zip'
    pcmk_zip = os.path.join(tmpd, 'pacemaker-master.zip')

    print("Downloading CTS from latest pacemaker snapshot (%s)" % url)
    urllib.request.urlretrieve(url, pcmk_zip)

    print("CTS archive saved at %s. Make it installable by pip" % pcmk_zip)
    setup_py = os.path.abspath(os.path.join(__file__,'..','pcmk-setup.py'))
    with zipfile.ZipFile(pcmk_zip,'a') as z:
        z.write(setup_py, 'pacemaker-master/setup.py')

    pip_cmd = [sys.executable, '-m', 'pip', 'install', pcmk_zip]
    print("Installing CTS with \"%s\"" % " ".join(pip_cmd))
    subprocess.check_call(pip_cmd)
