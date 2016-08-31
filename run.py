"""
Copyright (c) 2015 Red Hat, Inc
All rights reserved.

This software may be modified and distributed under the terms
of the MIT license. See the LICENSE file for details.
"""

import os

from cct.module import Module

class Run(Module):

    def configure(self):
        """
        Aggregate method that calls all configure_ methods in sequence.
        """
        self.run_shell_launch_script()

    def run_shell_launch_script(self):
        """
        Executes the original shell wrapper script.

        This step is necessary until such time as all the shell has been
        re-implemented: we need to be able to run some Python code *after*
        the shell code.
        """
        return os.system('/opt/eap/bin/openshift-configure.sh')
