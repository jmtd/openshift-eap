#!/bin/sh
# Openshift EAP launch script

. /tmp/launch_envs

exec $JBOSS_HOME/bin/standalone.sh -c standalone-openshift.xml -bmanagement 127.0.0.1 $JBOSS_HA_ARGS ${JBOSS_MESSAGING_ARGS}
