"""
Copyright (c) 2015 Red Hat, Inc
All rights reserved.

This software may be modified and distributed under the terms
of the MIT license. See the LICENSE file for details.
"""

import os
import shutil

from cct.module import Module

class Install(Module):

    def install(self):
        self.launch()

    def launch(self):
        added = "/tmp/cct/openshift-eap/os-eap7-launch/added"

        dst = os.path.join(os.getenv('JBOSS_HOME'), "bin", "launch")
        if not os.path.exists(dst):
            os.makedirs(dst)

        src = os.path.join(added, "launch")
        for f in os.listdir(src):
            shutil.move(os.path.join(src,f), dst)

        shutil.move(os.path.join(added, "openshift-launch.sh"), os.path.join(os.getenv("JBOSS_HOME"), "bin"))
