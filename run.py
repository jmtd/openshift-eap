"""
Copyright (c) 2015 Red Hat, Inc
All rights reserved.

This software may be modified and distributed under the terms
of the MIT license. See the LICENSE file for details.
"""

import ssl
import shutil
import urllib2
from jinja2 import Template
import xml.dom.minidom

import os

from cct.module import Module

class Run(Module):

    def configure(self):
        """
        Aggregate method that calls all configure_ methods in sequence.
        """
        self.run_shell_launch_script()
        self.setup_xml()
        self.inject_datasources()
        self.inject_datasources_2()
        self.teardown_xml()

    def run_shell_launch_script(self):
        """
        Executes the original shell wrapper script.

        This step is necessary until such time as all the shell has been
        re-implemented: we need to be able to run some Python code *after*
        the shell code.
        """
        return os.system('/opt/eap/bin/openshift-configure.sh')

    # this can't run until run_shell_launch_script has completed or the XML is not valid.
    # otherwise these could just be setup/teardown
    def setup_xml(self):
        jboss_home = os.getenv("JBOSS_HOME")
        self.config_file = "{}/standalone/configuration/standalone-openshift.xml".format(jboss_home)
        self.config = xml.dom.minidom.parse(self.config_file)

    def teardown_xml(self):
        with open(self.config_file, "w") as fh:
            self.config.writexml(fh)

    def _get_tag_by_attr(self, tag, attr, val):
        """Convenience method for getting a tag via an attribute value"""
        for elem in self.config.getElementsByTagName(tag):
            if elem.getAttribute(attr) == val:
                return elem
        self.logger.error("couldn't find correct {} element".format(tag))
        return

    def generate_datasource(self, pool_name="", jndi_name="", username="", password="", host="", port="", database="", checker="", sorter="", driver="", service_name="", orig_service_name="", datasource_jta="", NON_XA_DATASOURCE="", tx_isolation="", min_pool_size="", max_pool_size=""):
        createElement = self.config.createElement
        createTextNode = self.config.createTextNode

        if driver in ["postgresql", "mysql"]:
            if NON_XA_DATASOURCE == "true":
                ds = self.mkelement('datasource', {
                    'jta': datasource_jta,
                    'jndi-name': jndi_name,
                    'pool-name': pool_name,
                    'use-java-context': "true",
                    'enabled': "true",
                })

                cu = createElement('connection-url')
                cu.appendChild(createTextNode("jdbc:{}://{}:{}/{}".format(driver,host,port,database)))
                ds.appendChild(cu)

                d = createElement('driver')
                d.appendChild(createTextNode(driver))
                ds.appendChild(d)

            else:
                ds = self.mkelement('xa-datasource', {
                    'jndi-name': jndi_name,
                    'pool-name': pool_name,
                    'use-java-context': "true",
                    'enabled': "true",
                })

                attrs = [('ServerName', host), ('Port', port), ('DatabaseName', database)]
                if driver == "postgresql":
                    attrs[1] = ('PortNumber', port)

                for attr, txt in attrs:
                    p = createElement('xa-datasource-property')
                    p.setAttribute('name', attr)
                    p.appendChild(createTextNode(txt))
                    ds.appendChild(p)

                d = createElement('driver')
                d.appendChild(createTextNode(driver))
                ds.appendChild(d)

            if tx_isolation:
                ti = createElement('transaction-isolation')
                ti.appendChild(createTextNode(tx_isolation))
                ds.appendChild(ti)

            if min_pool_size or max_pool_size:
                if NON_XA_DATASOURCE == "true":
                    pool = createElement('pool')
                else:
                    pool = createElement('xa-pool')

                if min_pool_size:
                    mps = createElement('min-pool-size')
                    mps.appendChild(createTextNode(min_pool_size))
                    pool.appendChild(mps)

                if max_pool_size:
                    mps = createElement('max-pool-size')
                    mps.appendChild(createTextNode(max_pool_size))
                    pool.appendChild(mps)

                ds.appendChild(pool)

            s = createElement('security')
            u = createElement('user-name')
            u.appendChild(createTextNode(username))
            s.appendChild(u)
            p = createElement('password')
            p.appendChild(createTextNode(password))
            s.appendChild(p)
            ds.appendChild(s)

            v = createElement('validation')
            vom = createElement('validate-on-match')
            vom.appendChild(createTextNode('true'))
            v.appendChild(vom)
            vcc = createElement('valid-connection-checker')
            vcc.setAttribute('class-name', checker)
            v.appendChild(vcc)
            es = createElement('exception-sorter')
            es.setAttribute('class-name', sorter)
            v.appendChild(es)
            ds.appendChild(v)

        else:
            driver = "hsql"
            jndi_name = os.getenv("DB_JNDI", "java:jboss/datasources/ExampleDS")
            pool_name = os.getenv("DB_POOL", "ExampleDS")
            service_name = "ExampleDS"

            ds = createElement('datasource')
            ds.setAttribute('jndi-name', jndi_name)
            ds.setAttribute('pool-name', pool_name)
            ds.setAttribute('enabled', "true")
            ds.setAttribute('use-java-context', "true")

            cu = createElement('connection-url')
            cu.appendChild(createTextNode("jdbc:h2:mem:test;DB_CLOSE_DELAY=-1;DB_CLOSE_ON_EXIT=FALSE"))
            ds.appendChild(cu)
            d = createElement('driver')
            d.appendChild(createTextNode('h2'))
            ds.appendChild(d)
            s = createElement('security')
            u = createElement('user-name')
            u.appendChild(createTextNode('sa'))
            s.appendChild(u)
            p = createElement('password')
            p.appendChild(createTextNode('sa'))
            s.appendChild(p)
            ds.appendChild(s)

        if os.getenv("TIMER_SERVICE_DATA_STORE", "") == service_name:
            datastores = self.inject_timer_service("{}_ds".format(pool_name))
            if datastores:
                datastores.appendChild(self.inject_datastore(pool_name, jndi_name, driver))

        if os.getenv("DEFAULT_JOB_REPOSITORY", "") == service_name:
            self.inject_default_job_repository(pool_name)
            self.inject_job_repository(pool_name)

        return ds

    def inject_timer_service(self, arg):
        ts = self.config.createElement("timer-service")
        ts.setAttribute('thread-pool-name', 'default')
        ts.setAttribute('default-data-store', arg)

        ds = self.config.createElement('data-stores')
        ts.appendChild(ds)

        fds = self.config.createElement('file-data-store')
        fds.setAttribute('name', 'default-file-store')
        fds.setAttribute('path', 'timer-service-data')
        fds.setAttribute('relative-to', 'jboss.server.data.dir')

        ds.appendChild(fds)

        ss = self._get_tag_by_attr("subsystem", "xmlns", "urn:jboss:domain:ejb3:4.0")
        if ss:
            ss.appendChild(ts)
            # returning the internal <data-stores> node, caller sometimes append children
            return ds
        return

    def inject_datastore(self, service, jndi_name, database):
        dds = self.config.createElement("database-data-store")
        dds.setAttribute('name', "{}_ds".format(service))
        dds.setAttribute('datasource-jndi-name', jndi_name)
        dds.setAttribute('database', database)
        dds.setAttribute('partition', '{}_part'.format(service))
        return dds

    def inject_default_job_repository(self, name):
        ss = self._get_tag_by_attr("subsystem", "xmlns", "urn:jboss:domain:batch-jberet:1.0")
        if ss:
            djr = self.config.createElement('default-job-repository')
            djr.setAttribute('name', name)
            ss.appendChild(djr)

    def inject_job_repository(self, name):
        ss = self._get_tag_by_attr("subsystem", "xmlns", "urn:jboss:domain:batch-jberet:1.0")
        if ss:
            jobrepo = self.config.createElement('job-repository')
            jobrepo.setAttribute('name', name)
            jdbc = self.config.createElement('jdbc')
            jdbc.setAttribute('data-source', name)
            jobrepo.appendChild(jdbc)

            ss.appendChild(jobrepo)

    def inject_datasources(self):

        db_backends = filter(None, os.getenv("DB_SERVICE_PREFIX_MAPPING", "").split(","))

        if "TIMER_SERVICE_DATA_STORE" not in os.environ:
            self.inject_timer_service("default-file-store")

        if "DEFAULT_JOB_REPOSITORY" not in os.environ:
            self.inject_default_job_repository("in-memory")

        defaultDatasourceJndi=os.getenv("DEFAULT_DATASOURCE", "")

        datasources = []

        if len(db_backends) == 0:
            datasources.append(self.generate_datasource()) # XXX: arguments?
            if not defaultDatasourceJndi:
                    defaultDatasourceJndi="java:jboss/datasources/ExampleDS"

        else:
            for db_backend in db_backends:

                service_name = db_backend.split('=')[0] # XXX double check this one
                service = service_name.upper().replace('-','_')
                db = service.split('_')[-1]
                prefix = "=".join(db_backend.split('=')[1:])

                if service.find('_') < 0:
                        self.logger.error( "There is a problem with the DB_SERVICE_PREFIX_MAPPING environment variable!")
                        self.logger.error( "You provided the following database mapping (via DB_SERVICE_PREFIX_MAPPING): {}. The mapping does not contain the database type.".format(db_backend))
                        self.logger.error("")
                        self.logger.error( "Please make sure the mapping is of the form <name>-<database_type>=PREFIX, where <database_type> is either MYSQL or POSTGRESQL.")
                        self.logger.error("")
                        self.logger.error( "WARNING! The datasource for {} service WILL NOT be configured.".format(prefix))
                        continue

                host = os.getenv("{}_SERVICE_HOST".format(service))
                port = os.getenv("{}_SERVICE_PORT".format(service))

                if not (host or port):
                    self.logger.error( "There is a problem with your service configuration!")
                    self.logger.error( "You provided following database mapping (via DB_SERVICE_PREFIX_MAPPING environment variable): {db_backend}. To configure datasources we expect {service}_SERVICE_HOST and {service}_SERVICE_PORT to be set.".format(db_backend=db_backend,service=service))
                    self.logger.error("")
                    self.logger.error( "Current values:")
                    self.logger.error("")
                    self.logger.error( "{}_SERVICE_HOST: {}".format(service,host))
                    self.logger.error( "{}_SERVICE_PORT: {}".format(service,port))
                    self.logger.error("")
                    self.logger.error( "Please make sure you provided correct service name and prefix in the mapping. Additionally please check that you do not set portalIP to None in the {} service. Headless services are not supported at this time.".format(service_name))
                    self.logger.error("")
                    self.logger.error( "WARNING! The {} datasource for {} service WILL NOT be configured.".format(db.lower(),prefix))
                    continue

                # Custom JNDI environment variable name format: [NAME]_[DATABASE_TYPE]_JNDI
                jndi_name = os.getenv("{}_JNDI".format(prefix), "java:jboss/datasources/{}".format(service.lower()))

                # Database username environment variable name format: [NAME]_[DATABASE_TYPE]_USERNAME
                username = os.getenv("{}_USERNAME".format(prefix))

                # Database password environment variable name format: [NAME]_[DATABASE_TYPE]_PASSWORD
                password = os.getenv("{}_PASSWORD".format(prefix))

                # Database name environment variable name format: [NAME]_[DATABASE_TYPE]_DATABASE
                database = os.getenv("{}_DATABASE".format(prefix))

                if not all([jndi_name, username, password, database]):
                    self.logger.error( "Ooops, there is a problem with the {} datasource!".format(db.lower()))
                    self.logger.error( "In order to configure {db} datasource for {prefix} service you need to provide following environment variables: {prefix}_USERNAME, {prefix}_PASSWORD, {prefix}_DATABASE.".format(db=db.lower(),prefix=prefix))
                    self.logger.error("")
                    self.logger.error( "Current values:")
                    self.logger.error("")
                    self.logger.error( "{}_USERNAME: {}".format(prefix,username))
                    self.logger.error( "{}_PASSWORD: {}".format(prefix,password))
                    self.logger.error( "{}_DATABASE: {}".format(prefix,database))
                    self.logger.error("")
                    self.logger.error( "WARNING! The {} datasource for {} service WILL NOT be configured.".format(db.lower(), prefix))
                    continue

                # Transaction isolation level environment variable name format: [NAME]_[DATABASE_TYPE]_TX_ISOLATION
                tx_isolation = os.getenv("{}_TX_ISOLATION".format(prefix))

                # min pool size environment variable name format: [NAME]_[DATABASE_TYPE]_MIN_POOL_SIZE
                min_pool_size = os.getenv("{}_MIN_POOL_SIZE".format(prefix))

                # max pool size environment variable name format: [NAME]_[DATABASE_TYPE]_MAX_POOL_SIZE
                max_pool_size = os.getenv("{}_MAX_POOL_SIZE".format(prefix))

                # jta environment variable name format: [NAME]_[DATABASE_TYPE]_JTA
                jta = os.getenv("{}_JTA".format(prefix), "true")

                # $NON_XA_DATASOURCE: [NAME]_[DATABASE_TYPE]_NONXA (DB_NONXA)
                NON_XA_DATASOURCE = os.getenv("{}_NONXA".format(prefix), "false")

                if db == "MYSQL":
                    driver="mysql"
                    checker="org.jboss.jca.adapters.jdbc.extensions.mysql.MySQLValidConnectionChecker"
                    sorter="org.jboss.jca.adapters.jdbc.extensions.mysql.MySQLExceptionSorter"

                elif db == "POSTGRESQL":
                    driver="postgresql"
                    checker="org.jboss.jca.adapters.jdbc.extensions.postgres.PostgreSQLValidConnectionChecker"
                    sorter="org.jboss.jca.adapters.jdbc.extensions.postgres.PostgreSQLExceptionSorter"

                elif db == "MONGODB":
                    continue

                else:
                    self.logger.error( "There is a problem with the DB_SERVICE_PREFIX_MAPPING environment variable!")
                    self.logger.error( "You provided the following database mapping (via DB_SERVICE_PREFIX_MAPPING): {}.".format(db_backend))
                    self.logger.error( "The mapping contains the following database type: {}, which is not supported. Currently, only MYSQL and POSTGRESQL are supported.".format(db))
                    self.logger.error("")
                    self.logger.error( "Please make sure you provide the correct database type in the mapping.")
                    self.logger.error("")
                    self.logger.error( "WARNING! The {} datasource for {} service WILL NOT be configured.".format(db.lower(), prefix))
                    continue

                datasources.append(self.generate_datasource(
                    pool_name="{}-{}".format(service.lower(), prefix),
                    jndi_name=jndi_name,
                    username=username,
                    password=password,
                    host=host,
                    port=port,
                    database=database,
                    checker=checker,
                    sorter=sorter,
                    driver=driver,
                    service_name=service_name,
                    # orig_service_name elided
                    datasource_jta=jta,
                    NON_XA_DATASOURCE=NON_XA_DATASOURCE,
                    tx_isolation=tx_isolation,
                    min_pool_size=min_pool_size,
                    max_pool_size=max_pool_size
                ))

                if not defaultDatasourceJndi:
                    defaultDatasourceJndi=jndi_name

        datasources.append(self.inject_tx_datasource())

        if defaultDatasourceJndi:
            db = self.config.getElementsByTagName("default-bindings")[0]
            db.setAttribute("datasource", defaultDatasourceJndi)

        ds = self.config.getElementsByTagName("datasources")[0]
        for source in datasources:
            if source:
                ds.appendChild(source)

        # stuff from tx-datasource.sh
    # XXX: this is VERY similar to stuff in inject_datasources, lots of opportunity for common
    def inject_tx_datasource(self):
        tx_backend = os.getenv("TX_DATABASE_PREFIX_MAPPING", "")

        if tx_backend:
            service_name = '='.join(tx_backend.split('=')[:-1]) # XXX double check this one
            service = service_name.upper().replace('-','_')
            db = service.split('_')[-1]
            prefix = '='.join(tx_backend.split('=')[1:])

            host = os.getenv("{}_SERVICE_HOST".format(service), "")
            port = os.getenv("{}_SERVICE_PORT".format(service), "")

            if not host or not port:
                self.logger.error("There is a problem with your service configuration!")
                self.logger.error("You provided following database mapping (via TX_SERVICE_PREFIX_MAPPING environment variable): {tx_backend}. To configure datasources we expect {service}_SERVICE_HOST and {service}_SERVICE_PORT to be set.".format(tx_backend=tx_backend,service=service))
                self.logger.error("Current values:")
                self.logger.error("{}_SERVICE_HOST: {}".format(service,host))
                self.logger.error("{}_SERVICE_PORT: {}".format(service,port))
                self.logger.error("Please make sure you provided correct service name and prefix in the mapping. Additionally please check that you do not set portalIP to None in the {} service. Headless services are not supported at this time.".format(service_name))
                self.logger.error("WARNING! The {} datasource for {} service WILL NOT be configured.".format(db.lower(),prefix))
                return

            # Custom JNDI environment variable name format: [NAME]_[DATABASE_TYPE]_JNDI appended by ObjectStore
            jndi_name = os.getenv("{}_JNDI".format(prefix), "java:jboss/datasources/{}".format(service.lower()))

            # Database username environment variable name format: [NAME]_[DATABASE_TYPE]_USERNAME
            username = os.getenv("{}_USERNAME".format(prefix))

            # Database password environment variable name format: [NAME]_[DATABASE_TYPE]_PASSWORD
            password = os.getenv("{}_PASSWORD".format(prefix))

            # Database name environment variable name format: [NAME]_[DATABASE_TYPE]_DATABASE
            database = os.getenv("{}_DATABASE".format(prefix))

            if not all([jndi_name, username, password, database]):
                self.logger.error( "Ooops, there is a problem with the {} datasource!".format(db.lower()))
                self.logger.error( "In order to configure {db} transactional datasource for {prefix} service you need to provide following environment variables: {prefix}_USERNAME, {prefix}_PASSWORD, {prefix}_DATABASE.".format(db=db.lower(),prefix=prefix))
                self.logger.error("")
                self.logger.error( "Current values:")
                self.logger.error("")
                self.logger.error( "{}_USERNAME: {}".format(prefix,username))
                self.logger.error( "{}_PASSWORD: {}".format(prefix,password))
                self.logger.error( "{}_DATABASE: {}".format(prefix,database))
                self.logger.error("")
                self.logger.error( "WARNING! The {} datasource for {} service WILL NOT be configured.".format(db.lower(),prefix))
                db="ignore"

            # Transaction isolation level environment variable name format: [NAME]_[DATABASE_TYPE]_TX_ISOLATION
            tx_isolation = os.getenv("{}_TX_ISOLATION".format(prefix))

            # min pool size environment variable name format: [NAME]_[DATABASE_TYPE]_MIN_POOL_SIZE
            min_pool_size = os.getenv("{}_MIN_POOL_SIZE".format(prefix))

            # max pool size environment variable name format: [NAME]_[DATABASE_TYPE]_MAX_POOL_SIZE
            max_pool_size = os.getenv("{}_MAX_POOL_SIZE".format(prefix))

            if db == "MYSQL":
                driver = "mysql"
                datasource = self.generate_tx_datasource(service.lower(), jndi_name, username, password, host, port, database, driver)
                self.inject_jdbc_store(jndi_name)

            elif db == "POSTGRESQL":
                driver = "postgresql"
                datasource = self.generate_tx_datasource(service.lower(), jndi_name, username, password, host, port, database, driver)
                self.inject_jdbc_store(jndi_name)

            else:
                datasource = ""

            return datasource

    def mkelement(self, name, attrs):
        """Convenience method for creating a node and setting attributes"""
        node = self.config.createElement(name)
        for key,val in attrs.items():
            node.setAttribute(key,val)
        return node

    def generate_tx_datasource(self, service_name, jndi_name, username, password, host, port, database):
        createElement = self.config.createElement
        createTextNode = self.config.createTextNode

        ds = self.mkelement('datasource', {
            'jta': 'false',
            'jndi-name': "{}ObjectStore".format(jndi_name),
            'pool-name': "{}ObjectStorePool".format(service_name),
            'enabled': "true",
        })

        cu = createElement('connection-url')
        cu.appendChild(createTextNode("jdbc:{}://{}:{}/{}".format(driver,host,port,database))) # XXX: confirm argument orders here
        ds.appendChild(cu)

        d = createElement('driver')
        d.appendChild(createTextNode(driver))
        ds.appendChild(d)

        if tx_isolation:
            ti = createElement('transaction-isolation')
            ti.appendChild(createTextNode(tx_isolation))
            ds.appendChild(ti)

            if min_pool_size or max_pool_size:
                pool = createElement('pool')

                if min_pool_size:
                    mps = createElement('min-pool-size')
                    mps.appendChild(createTextNode(min_pool_size))
                    ds.appendChild(mps)

                if max_pool_size:
                    mps = createElement('max-pool-size')
                    mps.appendChild(createTextNode(max_pool_size))
                    ds.appendChild(mps)

                ds.appendChild(pool)

        s = createElement('security')
        u = createElement('user-name')
        u.appendChild(createTextNode(username))
        s.appendChild(u)
        p = createElement('password')
        p.appendChild(createTextNode(password))
        s.appendChild(p)
        ds.appendChild(s)

        return ds

    def inject_jdbc_store(self, jndi_name):
        js = self.config.createElement('jdbc-store')
        js.setAttribute('datasource-jndi-name', "{}ObjectStore".format(jndi_name))

        ss = self._get_tag_by_attr("subsystem", "xmlns", "urn:jboss:domain:transactions:3.0")
        if ss:
            ss.appendChild(js)

    def inject_datasources_2(self):
        helloworld = Template(self._get_resource("hello.txt"))
        self.logger.debug("inject_datasources_2: {}".format(helloworld.render()))

