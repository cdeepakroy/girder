#!/usr/bin/env python
# -*- coding: utf-8 -*-

###############################################################################
#  Copyright Kitware Inc.
#
#  Licensed under the Apache License, Version 2.0 ( the "License" );
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
###############################################################################

import json
import os
import time
import six

from subprocess import check_output, CalledProcessError

from .. import base
from girder.api.describe import API_VERSION
from girder.constants import SettingKey, SettingDefault, ROOT_DIR
from girder.utility import config


def setUpModule():
    base.startServer()


def tearDownModule():
    base.stopServer()


class SystemTestCase(base.TestCase):
    """
    Contains tests of the /system API endpoints.
    """

    def setUp(self):
        base.TestCase.setUp(self)

        self.users = [self.model('user').createUser(
            'usr%s' % num, 'passwd', 'tst', 'usr', 'u%s@u.com' % num)
            for num in [0, 1]]

    def tearDown(self):
        # Restore the state of the plugins configuration
        conf = config.getConfig()
        if 'plugins' in conf:
            del conf['plugins']

    def testGetVersion(self):
        usingGit = True
        resp = self.request(path='/system/version', method='GET')
        self.assertEqual(resp.json['apiVersion'], API_VERSION)

        try:
            # Get the current git head
            sha = check_output(
                ['git', 'rev-parse', 'HEAD'],
                cwd=ROOT_DIR
            ).decode().strip()
        except CalledProcessError:
            usingGit = False

        # Ensure a valid response
        self.assertEqual(usingGit, resp.json['git'])
        if usingGit:
            self.assertEqual(resp.json['SHA'], sha)
            self.assertEqual(sha.find(resp.json['shortSHA']), 0)

    def testSettings(self):
        users = self.users

        # Only admins should be able to get or set settings
        for method in ('GET', 'PUT', 'DELETE'):
            resp = self.request(path='/system/setting', method=method, params={
                'key': 'foo',
                'value': 'bar'
            }, user=users[1])
            self.assertStatus(resp, 403)

        # Only valid setting keys should be allowed
        obj = ['oauth', 'geospatial', '_invalid_']
        resp = self.request(path='/system/setting', method='PUT', params={
            'key': 'foo',
            'value': json.dumps(obj)
        }, user=users[0])
        self.assertStatus(resp, 400)
        self.assertEqual(resp.json['field'], 'key')

        # Only a valid JSON list is permitted
        resp = self.request(path='/system/setting', method='GET', params={
            'list': json.dumps('not_a_list')
        }, user=users[0])
        self.assertStatus(resp, 400)

        resp = self.request(path='/system/setting', method='PUT', params={
            'list': json.dumps('not_a_list')
        }, user=users[0])
        self.assertStatus(resp, 400)

        # Set a valid setting key
        resp = self.request(path='/system/setting', method='PUT', params={
            'key': SettingKey.PLUGINS_ENABLED,
            'value': json.dumps(obj)
        }, user=users[0])
        self.assertStatusOk(resp)

        # We should now be able to retrieve it
        resp = self.request(path='/system/setting', method='GET', params={
            'key': SettingKey.PLUGINS_ENABLED
        }, user=users[0])
        self.assertStatusOk(resp)
        self.assertEqual(set(resp.json), set(['geospatial', 'oauth']))

        # We should now clear the setting
        resp = self.request(path='/system/setting', method='DELETE', params={
            'key': SettingKey.PLUGINS_ENABLED
        }, user=users[0])
        self.assertStatusOk(resp)

        # Setting should now be ()
        setting = self.model('setting').get(SettingKey.PLUGINS_ENABLED)
        self.assertEqual(setting, [])

        # We should be able to ask for a different default
        setting = self.model('setting').get(SettingKey.PLUGINS_ENABLED,
                                            default=None)
        self.assertEqual(setting, None)

        # We should also be able to put several setting using a JSON list
        resp = self.request(path='/system/setting', method='PUT', params={
            'list': json.dumps([
                {'key': SettingKey.PLUGINS_ENABLED, 'value': json.dumps(obj)},
                {'key': SettingKey.COOKIE_LIFETIME, 'value': None},
            ])
        }, user=users[0])
        self.assertStatusOk(resp)

        # We can get a list as well
        resp = self.request(path='/system/setting', method='GET', params={
            'list': json.dumps([
                SettingKey.PLUGINS_ENABLED,
                SettingKey.COOKIE_LIFETIME,
            ])
        }, user=users[0])
        self.assertStatusOk(resp)
        self.assertEqual(set(resp.json[SettingKey.PLUGINS_ENABLED]),
                         set(['oauth', 'geospatial']))

        # We can get the default values, or ask for no value if the current
        # value is taken from the default
        resp = self.request(path='/system/setting', method='GET', params={
            'key': SettingKey.PLUGINS_ENABLED,
            'default': 'default'
        }, user=users[0])
        self.assertStatusOk(resp)
        self.assertEqual(resp.json, [])

        resp = self.request(path='/system/setting', method='GET', params={
            'key': SettingKey.COOKIE_LIFETIME,
            'default': 'none'
        }, user=users[0])
        self.assertStatusOk(resp)
        self.assertEqual(resp.json, None)

        # But we have to ask for a sensible value in the default parameter
        resp = self.request(path='/system/setting', method='GET', params={
            'key': SettingKey.COOKIE_LIFETIME,
            'default': 'bad_value'
        }, user=users[0])
        self.assertStatus(resp, 400)

        # Try to set each key in turn to test the validation.  First test with
        # am invalid value, then test with the default value.  If the value
        # 'bad' won't trigger a validation error, the key should be present in
        # the badValues table.
        badValues = {
            SettingKey.EMAIL_FROM_ADDRESS: '',
            SettingKey.EMAIL_HOST: {},
            SettingKey.SMTP_HOST: '',
            SettingKey.CORS_ALLOW_ORIGIN: {},
            SettingKey.CORS_ALLOW_METHODS: {},
            SettingKey.CORS_ALLOW_HEADERS: {},
        }
        allKeys = dict.fromkeys(six.viewkeys(SettingDefault.defaults))
        allKeys.update(badValues)
        for key in allKeys:
            resp = self.request(path='/system/setting', method='PUT', params={
                'key': key,
                'value': badValues.get(key, 'bad')
            }, user=users[0])
            self.assertStatus(resp, 400)
            resp = self.request(path='/system/setting', method='PUT', params={
                'key': key,
                'value': json.dumps(SettingDefault.defaults.get(key, ''))
            }, user=users[0])
            self.assertStatusOk(resp)
            resp = self.request(path='/system/setting', method='PUT', params={
                'list': json.dumps([{'key': key, 'value': None}])
            }, user=users[0])
            self.assertStatusOk(resp)
            resp = self.request(path='/system/setting', method='GET', params={
                'key': key,
                'default': 'default'
            }, user=users[0])
            self.assertStatusOk(resp)

    def testPlugins(self):
        resp = self.request(path='/system/plugins', user=self.users[0])
        self.assertStatusOk(resp)
        self.assertIn('all', resp.json)
        pluginRoots = [os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                    'test_plugins'),
                       os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                    'test_additional_plugins')]
        conf = config.getConfig()
        conf['plugins'] = {'plugin_directory': ':'.join(pluginRoots)}

        resp = self.request(
            path='/system/plugins', method='PUT', user=self.users[0],
            params={'plugins': 'not_a_json_list'})
        self.assertStatus(resp, 400)
        resp = self.request(
            path='/system/plugins', method='PUT', user=self.users[0],
            params={'plugins': '["has_deps"]'})
        self.assertStatusOk(resp)
        enabled = resp.json['value']
        self.assertEqual(len(enabled), 3)
        self.assertTrue('test_plugin' in enabled)
        self.assertTrue('does_nothing' in enabled)
        resp = self.request(
            path='/system/plugins', method='PUT', user=self.users[0],
            params={'plugins': '["has_nonexistent_deps"]'},
            exception=True)
        self.assertStatus(resp, 500)
        self.assertEqual(resp.json['message'],
                         ("Required dependency a_plugin_that_does_not_exist"
                          " does not exist."))

    def testBadPlugin(self):
        pluginRoot = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                  'test_plugins')
        conf = config.getConfig()
        conf['plugins'] = {'plugin_directory': pluginRoot}
        # Try to enable a good plugin and a bad plugin.  Only the good plugin
        # should be enabled.
        resp = self.request(
            path='/system/plugins', method='PUT', user=self.users[0],
            params={'plugins': '["test_plugin","bad_json","bad_yaml"]'})
        self.assertStatusOk(resp)
        enabled = resp.json['value']
        self.assertEqual(len(enabled), 1)
        self.assertTrue('test_plugin' in enabled)
        self.assertTrue('bad_json' not in enabled)
        self.assertTrue('bad_yaml' not in enabled)

    def testRestart(self):
        resp = self.request(path='/system/restart', method='PUT',
                            user=self.users[0])
        self.assertStatusOk(resp)

    def testCheck(self):
        resp = self.request(path='/token/session', method='GET')
        self.assertStatusOk(resp)
        token = resp.json['token']
        # 'basic' mode should work for a token or for anonymous
        resp = self.request(path='/system/check', token=token)
        self.assertStatusOk(resp)
        check = resp.json
        self.assertLess(check['bootTime'], time.time())
        resp = self.request(path='/system/check')
        self.assertStatusOk(resp)
        check = resp.json
        self.assertLess(check['bootTime'], time.time())
        # but should fail for 'quick' mode
        resp = self.request(path='/system/check', token=token, params={
            'mode': 'quick'})
        self.assertStatus(resp, 401)
        # Admin can ask for any mode
        resp = self.request(path='/system/check', user=self.users[0])
        self.assertStatusOk(resp)
        check = resp.json
        self.assertLess(check['bootTime'], time.time())
        self.assertNotIn('cherrypyThreadsInUse', check)
        resp = self.request(path='/system/check', user=self.users[0], params={
            'mode': 'quick'})
        self.assertStatusOk(resp)
        check = resp.json
        self.assertLess(check['bootTime'], time.time())
        self.assertGreaterEqual(check['cherrypyThreadsInUse'], 1)
        self.assertIn('rss', check['processMemory'])
        resp = self.request(path='/system/check', user=self.users[0], params={
            'mode': 'slow'})
        self.assertStatusOk(resp)
        check = resp.json
        self.assertGreater(check['girderDiskUsage']['free'], 0)
        resp = self.request(path='/system/check', method='PUT',
                            user=self.users[0], params={'progress': True})
        self.assertStatusOk(resp)
        # tests that check repair of different models are convered in the
        # individual models' tests

    def testLogRoute(self):
        logRoot = os.path.join(ROOT_DIR, 'tests', 'cases', 'dummylogs')
        config.getConfig()['logging'] = {'log_root': logRoot}

        resp = self.request(path='/system/log', user=self.users[1], params={
            'log': 'error',
            'bytes': 0
        })
        self.assertStatus(resp, 403)

        resp = self.request(path='/system/log', user=self.users[0], params={
            'log': 'error',
            'bytes': 0
        }, isJson=False)
        self.assertStatusOk(resp)
        self.assertEqual(
            self.getBody(resp),
            '=== Last 12 bytes of %s/error.log: ===\n\nHello world\n' % logRoot)

        resp = self.request(path='/system/log', user=self.users[0], params={
            'log': 'error',
            'bytes': 6
        }, isJson=False)
        self.assertStatusOk(resp)
        self.assertEqual(
            self.getBody(resp),
            '=== Last 6 bytes of %s/error.log: ===\n\nworld\n' % logRoot)

        resp = self.request(path='/system/log', user=self.users[0], params={
            'log': 'info',
            'bytes': 6
        }, isJson=False)
        self.assertStatusOk(resp)
        self.assertEqual(
            self.getBody(resp),
            '=== Last 0 bytes of %s/info.log: ===\n\n' % logRoot)

        del config.getConfig()['logging']
