import unittest
import mock
import xml
import tempfile
import sys
import os
import shutil

# test the datasources stuff

# XXX should probably restructure the module like base
from run import Run

from cct.errors import CCTError

class TestDataSources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workdir = tempfile.mkdtemp(prefix="TestDataSources")

        f = open("os-eap7-openshift/added/standalone-openshift.xml").read()
        with open(os.path.join(cls.workdir,"standalone-openshift.xml"),"w") as fh:
            fh.write(f.replace('##DEFAULT_JMS##', ''))

    @classmethod
    def tearDownClass(cls):
        #sys.stderr.write(cls.workdir)
        shutil.rmtree(cls.workdir)

    def setUp(self):
        self.run = Run('run','run') # XXX check module args for cct.module.Module
        # clone of Run.setup_xml tweaked for tests
        self.run.config = xml.dom.minidom.parse(os.path.join(self.workdir, "standalone-openshift.xml"))
        self.run.config_file = os.path.join(self.workdir, "out.xml")

    def tearDown(self):
        self.run.teardown_xml()

    def test_parse_standalone_xml(self):
        """Ensure the module can read in, parse and write out the config file"""
        self.run.teardown_xml()

    def test_datasources_all(self):
        """Replicate running the whole datasources at once"""
        self.assertEqual(dom_object.getAttribute("datasource-jndi-name"), jndi)
        self.assertEqual(dom_object.getAttribute("name"), "{}_ds".format(service))
        self.assertEqual(dom_object.getAttribute("partition"), "{}_part".format(service))

    def test_inject_default_job_repository(self):
        ss = self.run._get_tag_by_attr("subsystem", "xmlns", "urn:jboss:domain:batch-jberet:1.0")
        self.assertIsNotNone(ss)

        orig_children = ss.childNodes[:]
        self.run.inject_default_job_repository("testname")
        self.assertEqual(len(ss.childNodes), 1 + len(orig_children))

        new_elem = (set(ss.childNodes) - set(orig_children)).pop()
        self.assertEqual(new_elem.getAttribute('name'), "testname")

    def test_inject_job_repository(self):
        ss = self.run._get_tag_by_attr("subsystem", "xmlns", "urn:jboss:domain:batch-jberet:1.0")
        self.assertIsNotNone(ss)

        orig_children = ss.childNodes[:]
        self.run.inject_job_repository("testname")
        self.assertEqual(len(ss.childNodes), 1 + len(orig_children))

        new_elem = (set(ss.childNodes) - set(orig_children)).pop()
        self.assertEqual(new_elem.getAttribute('name'), "testname")

        self.assertEqual(len(new_elem.childNodes), 1)
        child = new_elem.childNodes[0]
        self.assertEqual(child.getAttribute('data-source'), "testname")
        self.assertEqual("jdbc", child.tagName)

    def test_inject_timer_service(self):
        self.run.inject_timer_service("default-file-store")
        # XXX: more

    def test_inject_timer_service_datastore(self):
        default = "testservice_ds"
        service = "testservice"
        jndi = "testjndi"
        database = "testdatabase"
        self.run.inject_timer_service(default, service, jndi, database)

        ss = self.run._get_tag_by_attr("subsystem", "xmlns", "urn:jboss:domain:ejb3:4.0")
        child = ss.getElementsByTagName('database-data-store')[0]

        self.assertIsNotNone(child)
        self.assertEqual(child.getAttribute("database"), database)
        self.assertEqual(child.getAttribute("datasource-jndi-name"), jndi)
        self.assertEqual(child.getAttribute("name"), "{}_ds".format(service))
        self.assertEqual(child.getAttribute("partition"), "{}_part".format(service))

    def test_inject_default_job_repository(self):
        self.run.inject_default_job_repository("in-memory")
        # XXX: more

    def test_generate_datasource(self):
        mylist = []
        self.run.generate_datasource(mylist)
        # XXX: more

    def test_generate_datasource_mysql(self):
        mylist = []
        self.run.generate_datasource(mylist, pool_name="", jndi_name="", username="", password="", host="", port="", database="", checker="", sorter="", driver="mysql", service_name="", orig_service_name="", datasource_jta="", NON_XA_DATASOURCE="", tx_isolation="", min_pool_size="", max_pool_size="")

    def test_datasources_all(self):
        """Replicate running the whole datasources at once"""
        self.run.inject_datasources()

if __name__ == '__main__':
    unittest.main()
