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

    def generate_datasource(self, datasources, pool_name="", jndi_name="", username="", password="", host="", port="", database="", checker="", sorter="", driver="", service_name="", orig_service_name="", datasource_jta="", NON_XA_DATASOURCE="", tx_isolation="", min_pool_size="", max_pool_size="", validate="", protocol="", url=""):
        """Re-implementation of generate_datasources from os-eap7-launch/added/launch/datasources.sh
        corresponding to jboss-dockerfiles around f51474e044f8508412bb18f594099fb13c0d69f2"""

        attrs = []
        pooltag = ''
        connection_url = ''

        if driver in ["postgresql", "mysql"]:
            if NON_XA_DATASOURCE == "true":
                dstag = 'datasource'
                pooltag = 'pool'
            else:
                dstag = 'xa-datasource'
                pooltag = 'xa-pool'

                if url:
                    attrs = [('URL', url)]
                else:
                    attrs = [('ServerName', host), ('Port', port), ('DatabaseName', database)]

                    if driver == "postgresql":
                        attrs[1] = ('PortNumber', port)
        else:
            if driver:
                if NON_XA_DATASOURCE == "true":
                    if driver == "h2":
                         connection_url="{}:{}:{}".format(protocol, host, database)
                         h2_import=os.getenv("{}_IMPORT_SQL".format(prefix), "")
                         if h2_import:
                             connection_url += ";INIT=RUNSCRIPT FROM '{}'\;".format(h2_import)
                    else:
                        connection_url = url
                else:
                    if url:
                        attrs = [('URL', url)]
                    else:
                        attrs = [('ServerName', host), ('Port', port), ('DatabaseName', database)]

            else:
                driver = "h2"
                jndi_name = os.getenv("DB_JNDI", "java:jboss/datasources/ExampleDS")
                pool_name = os.getenv("DB_POOL", "ExampleDS")
                service_name = "ExampleDS"
                dstag = 'datasource'
                username = password = 'sa'

        t = Template(self._get_resource("templates/datasource.xml.jinja"))

        newdom = xml.dom.minidom.parseString(t.render(
            jndi_name=jndi_name,
            attrs=attrs,
            datasource_jta=datasource_jta,
            pool_name=pool_name,
            pooltag=pooltag,
            NON_XA_DATASOURCE=NON_XA_DATASOURCE,
            min_pool_size=min_pool_size,
            dstag=dstag,
            driver=driver,
            host=host,
            port=port,
            database=database,
            max_pool_size=max_pool_size,
            username=username,
            password=password,
            connection_url=connection_url,
            checker=checker,
            sorter=sorter,
            tx_isolation=tx_isolation,
            validate=validate,
        ))
        datasources.append(newdom.childNodes[0])

        if driver == "h2":
            driver = "hsql" # XXX: for later?

        if os.getenv("TIMER_SERVICE_DATA_STORE", "") == service_name:
            self.inject_timer_service("{}_ds".format(pool_name), pool_name, jndi_name, driver)

        if os.getenv("DEFAULT_JOB_REPOSITORY", "") == service_name:
            self.inject_default_job_repository(pool_name)
            self.inject_job_repository(pool_name)

    def inject_timer_service(self, arg, pool_name="", jndi_name="", driver=""):
        t = Template("""<timer-service thread-pool-name="default" default-data-store="{{ arg }}"><data-stores
            ><file-data-store
                name="default-file-store"
                path="timer-service-data"
                relative-to="jboss.server.data.dir"
           />{%- if pool_name != "" -%}
             <database-data-store name="{{ pool_name }}_ds"
                 datasource-jndi-name="{{ jndi_name }}"
                 database="{{ driver }}"
                 partition="{{ pool_name }}_part" />
           {%- endif -%}</data-stores></timer-service>""")

        ss = self._get_tag_by_attr("subsystem", "xmlns", "urn:jboss:domain:ejb3:4.0")
        if ss:
            self._append_xml_from_string(ss, t.render(
                arg=arg,
                pool_name=pool_name,
                jndi_name=jndi_name,
                driver=driver,
            ))

    def inject_default_job_repository(self, name):
        ss = self._get_tag_by_attr("subsystem", "xmlns", "urn:jboss:domain:batch-jberet:1.0")
        if ss:
            t = Template("""<default-job-repository name="{{ name }}" />""")
            self._append_xml_from_string(ss, t.render(name=name))

    def inject_job_repository(self, name):
        ss = self._get_tag_by_attr("subsystem", "xmlns", "urn:jboss:domain:batch-jberet:1.0")
        if ss:
            t = Template("""<job-repository name="{{ name }}"><jdbc data-source="{{ name }}" /></job-repository>""")
            self._append_xml_from_string(ss, t.render(name=name))

    def inject_datasources(self):

        db_backends = filter(None, os.getenv("DB_SERVICE_PREFIX_MAPPING", "").split(","))

        if "TIMER_SERVICE_DATA_STORE" not in os.environ:
            self.inject_timer_service("default-file-store")

        if "DEFAULT_JOB_REPOSITORY" not in os.environ:
            self.inject_default_job_repository("in-memory")

        defaultDatasourceJndi=os.getenv("DEFAULT_DATASOURCE", "")

        datasources = []

        if len(db_backends) == 0:
            self.generate_datasource(datasources)
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

                self.inject_datasource(datasources, prefix, service, db, service_name)

                if not defaultDatasourceJndi:
                    defaultDatasourceJndi=jndi_name

        datasources.append(self.inject_tx_datasource())

        if defaultDatasourceJndi:
            db = self.config.getElementsByTagName("default-bindings")[0]
            db.setAttribute("datasource", defaultDatasourceJndi)

        db="EXTERNAL"
        if os.getenv("EXTENSION_DATASOURCES", ""):
            for datasource_prefix in os.getenv("EXTENSION_DATASOURCES").split(","):
                # XXX: need to figure out what to pass after the prefix vars
                self.inject_datasource(datasources, datasource_prefix, datasource_prefix)
        if os.getenv("EXTENSION_RESOURCE_ADAPTERS", ""):
            self.inject_resource_adapters()
        if os.getenv("EXTENSIONS_PROPERTIES_FILES", ""):
            for prop_file in os.getenv("EXTENSIONS_PROPERTIES_FILES").split(","):
                EXTENSION_DATASOURCES=""
                EXTENSION_RESOURCE_ADAPTERS=""
                # . $prop_file
                # XXX: how on earth to manage this?

        # add datasources from properties
        if os.getenv("EXTENSION_DATASOURCES", ""):
            for datasource_prefix in os.getenv("EXTENSION_DATASOURCES").split(","):
                self.inject_datasource(datasources, datasource_prefix, datasource_prefix)

        # Add resource adapters from properties
        if os.getenv("EXTENSION_RESOURCE_ADAPTERS", ""):
            self.inject_resource_adapters()

        ds = self.config.getElementsByTagName("datasources")[0]
        for source in datasources:
            if source:
                ds.appendChild(source)

    def inject_datasource(self, datasources, prefix, service, db):
        self.logger.debug("inject_datasource!")

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
            return

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
            return

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

        driver=""

        if db == "MYSQL":
            driver="mysql"
            checker="org.jboss.jca.adapters.jdbc.extensions.mysql.MySQLValidConnectionChecker"
            sorter="org.jboss.jca.adapters.jdbc.extensions.mysql.MySQLExceptionSorter"

        elif db == "POSTGRESQL":
            driver="postgresql"
            checker="org.jboss.jca.adapters.jdbc.extensions.postgres.PostgreSQLValidConnectionChecker"
            sorter="org.jboss.jca.adapters.jdbc.extensions.postgres.PostgreSQLExceptionSorter"

        elif db == "MONGODB":
            return

        else:
            self.logger.error( "There is a problem with the DB_SERVICE_PREFIX_MAPPING environment variable!")
            self.logger.error( "You provided the following database mapping (via DB_SERVICE_PREFIX_MAPPING): {}.".format(db_backend))
            self.logger.error( "The mapping contains the following database type: {}, which is not supported. Currently, only MYSQL and POSTGRESQL are supported.".format(db))
            self.logger.error("")
            self.logger.error( "Please make sure you provide the correct database type in the mapping.")
            self.logger.error("")
            self.logger.error( "WARNING! The {} datasource for {} service WILL NOT be configured.".format(db.lower(), prefix))
            return

        if not jta:
            # XXX: this is a transcription of the shell logic but this is not actually possible
            self.logger.error("Warning - JTA flag not set, defaulting to true for datasource  {}".format(service_name))
            jta=false

        if not driver:
            self.logger.error("Warning - DRIVER not set for datasource {}. Datasource will not be configured.".format(service_name))
            return

        self.generate_datasource(
            datasources=datasources,
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
        )


    def inject_resource_adapters(self):
        resource_adapters=""
        hostname=os.uname()[1]

        class ResourceAdapter:
            pass # behaves like an OpenStruct
        ras = []

        for ra_prefix in os.getenv("EXTENSION_RESOURCE_ADAPTERS").split(","):
            ra = ResourceAdapter()
            ra.ra_id = os.getenv("{}_ID".format(ra_prefix), "")
            if not ra.ra_id:
                self.logger.error("Warning - {ra_prefix}_ID is missing from resource adapter configration, defaulting to {ra_prefix}".format(ra_prefix=ra_prefix))
                ra.ra_id = ra_prefix

            ra.module_slot = os.getenv("{}_MODULE_SLOT".format(ra_prefix), "")
            if not ra.module_slot:
                self.logger.error("Warning - {}_MODULE_SLOT is missing from resource adapter configration, defaulting to main".format(ra_prefix))
                ra.module_slot="main"

            ra.module_id = os.getenv("{}_MODULE_ID".format(ra_prefix), "")
            if not ra.module_id:
                self.logger.error("Warning - {}_MODULE_ID is missing from resource adapter configration. Resource adapter will not be configured".format(ra_prefix))
                continue

            ra.ra_class = os.getenv("{}_CONNECTION_CLASS".format(ra_prefix),"")
            if not ra.ra_class:
                self.logger.error("Warning - {}_CONNECTION_CLASS is missing from resource adapter configration. Resource adapter will not be configured".format(ra_prefix))
                continue

            ra.jndi = os.getenv("{}_CONNECTION_JNDI".format(ra_prefix),"")
            if not ra.jndi:
              self.logger.error("Warning - {}_CONNECTION_JNDI is missing from resource adapter configration. Resource adapter will not be configured".format(ra_prefix))
              continue

            # all environment variables beginning {ra_prefix}_PROPERTY_*
            prop_prefix="{}_PROPERTY_".format(ra_prefix)
            ra.properties = { k[len(prop_prefix):]: v for (k, v) in os.environ.items() if k.startswith(prop_prefix) }

        t = Template(self._get_resource("templates/resource_adapters.xml.jinja"))
        ss = self._get_tag_by_attr("subsystem", "xmlns", "urn:jboss:domain:resource-adapters:4.0")
        if ss:
            # XXX handle !0 length result
            db = ss.getElementsByTagName("resource-adapters")[0]
            self._append_xml_from_string(db, t.render(ras=ras))


        ##### stuff from tx-datasource.sh #####

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
        t = Template("<jdbc-store datasource-jndi-name=\"{{ jndi_name }}\" />\n")

        ss = self._get_tag_by_attr("subsystem", "xmlns", "urn:jboss:domain:transactions:3.0")
        if ss:
            self._append_xml_from_string(ss, t.render("{}ObjectStore".format(jndi_name)))

    def _append_xml_from_string(self, node, xmlstr):
        """helper function to ease importing XML from a string and inserting it
           into a DOM Node"""
        newdom = xml.dom.minidom.parseString(xmlstr)
        node.appendChild(self.config.importNode(newdom.childNodes[0], True))
