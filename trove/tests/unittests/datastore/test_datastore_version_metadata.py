#    Copyright (c) 2014 Rackspace Hosting
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from trove.tests.unittests.datastore.base import TestDatastoreBase
from trove.datastore.models import DBDatastoreVersionMetadata
from trove.datastore.models import DatastoreVersionMetadata


class TestDatastoreVersionMetadata(TestDatastoreBase):
    def setUp(self):
        super(TestDatastoreVersionMetadata, self).setUp()

    def tearDown(self):
        super(TestDatastoreVersionMetadata, self).tearDown()

    def test_map_flavors_to_datastore(self):
        mapping = DBDatastoreVersionMetadata.load(datastore_version_id=
                                                  self.datastore_version_id,
                                                  flavor=self.flavor)
        assertEqual(mapping.datastore_version_id, self.datastore_version_id)
        assertEqual(mapping.flavor, self.flavor)

    def test_load_nonexistent_mapping(self):
        self.assertRaises(DatastoreFlavorAssociationNotFound,
                          DBDatastoreVersionMetadata.find_by)

    def test_delete_mapping(self):
        ds_version = str(uuid.uuid4())
        flavor = 2
        DatastoreVersionMetadata.datastore_flavor_add(ds_version, flavor)
        dsflavor.datastore_flavor_delete(ds_version, flavor)
        mapping = DBDatastoreVersionMetadata.load(datastore_version_id=
                                                  ds_version, flavor=flavor)
        assertEqual(True, mapping.deleted)
