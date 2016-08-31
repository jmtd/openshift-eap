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
        self.openshift_scripts()
        self.launch()

    def launch(self):
        added = "/tmp/cct/openshift-eap/os-eap7-launch/added"

        dst = os.path.join(os.getenv('JBOSS_HOME'), "bin", "launch")
        if not os.path.exists(dst):
            os.makedirs(dst)

        src = os.path.join(added, "launch")
        for f in os.listdir(src):
            shutil.move(os.path.join(src,f), dst)

        shutil.move(os.path.join(added, "openshift-configure.sh"), os.path.join(os.getenv("JBOSS_HOME"), "bin"))
        shutil.move(os.path.join(added, "openshift-launch.sh"), os.path.join(os.getenv("JBOSS_HOME"), "bin"))

    def openshift_scripts(self):
        """
        re-implementation of os-eap7-openshift
        """

        added = "/tmp/cct/openshift-eap/os-eap7-openshift/added"
        jboss_home = os.getenv("JBOSS_HOME")

        with open("{}/bin/standalone.conf".format(jboss_home), "a") as out_fh:
            with open("{}/standalone.conf".format(added), "r") as in_fh:
                out_fh.write(in_fh.read())

        shutil.move("{}/standalone-openshift.xml".format(added), "{}/standalone/configuration/".format(jboss_home))
