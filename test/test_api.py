from u2fval import app, exc
from u2fval.model import db, Client
from .soft_u2f_v2 import SoftU2FDevice
import unittest
import json


class RestApiTest(unittest.TestCase):

    def setUp(self):
        app.config['TESTING'] = True
        app.config['ALLOW_UNTRUSTED'] = True

        db.session.close()
        db.drop_all()
        db.create_all()
        db.session.add(Client('fooclient', 'https://example.com',
                              ['https://example.com']))
        db.session.commit()

        self.app = app.test_client()

    def test_call_without_client(self):
        err = json.loads(self.app.get('/').data.decode('utf8'))
        self.assertEqual(err['errorCode'], exc.BadInputException.code)

    def test_call_with_invalid_client(self):
        err = json.loads(
            self.app.get('/', environ_base={'REMOTE_USER': 'invalid'}
                         ).data.decode('utf8'))
        self.assertEqual(err['errorCode'], exc.BadInputException.code)

    def test_get_trusted_facets(self):
        resp = json.loads(
            self.app.get('/', environ_base={'REMOTE_USER': 'fooclient'}
                         ).data.decode('utf8'))
        self.assertIn('https://example.com', resp['trustedFacets'][0]['ids'])

    def test_list_empty_devices(self):
        resp = json.loads(
            self.app.get('/foouser', environ_base={'REMOTE_USER': 'fooclient'}
                         ).data.decode('utf8'))
        self.assertEqual(resp, [])

    def test_begin_auth_without_devices(self):
        err = json.loads(
            self.app.get('/foouser/authenticate',
                         environ_base={'REMOTE_USER': 'fooclient'}
                         ).data.decode('utf8'))
        self.assertEqual(err['errorCode'], exc.NoEligibleDevicesException.code)

    def test_register(self):
        device = SoftU2FDevice()
        self.do_register(device, {'foo': 'bar'})

    def test_authenticate(self):
        device = SoftU2FDevice()
        self.do_register(device, {'foo': 'bar', 'baz': 'one'})
        descriptor = self.do_authenticate(device, {'baz': 'two'})
        self.assertEqual(descriptor['properties'],
                         {'foo': 'bar', 'baz': 'two'})

    def test_get_properties(self):
        device = SoftU2FDevice()
        descriptor = self.do_register(device, {'foo': 'bar', 'baz': 'foo'})
        descriptor2 = json.loads(
            self.app.get('/foouser/' + descriptor['handle'],
                         environ_base={'REMOTE_USER': 'fooclient'}
                         ).data.decode('utf8'))
        self.assertEqual(descriptor2['properties'],
                         {'foo': 'bar', 'baz': 'foo'})

    def test_update_properties(self):
        device = SoftU2FDevice()
        desc = self.do_register(device,
                                {'foo': 'one', 'bar': 'one', 'baz': 'one'})
        self.assertEqual({
            'foo': 'one',
            'bar': 'one',
            'baz': 'one'
        }, desc['properties'])

        desc2 = json.loads(self.app.post(
            '/foouser/' + desc['handle'],
            environ_base={'REMOTE_USER': 'fooclient'},
            data=json.dumps({'bar': 'two', 'baz': None})
        ).data.decode('utf8'))
        self.assertEqual({
            'foo': 'one',
            'bar': 'two'
        }, desc2['properties'])

        desc3 = json.loads(self.app.get(
            '/foouser/' + desc['handle'],
            environ_base={'REMOTE_USER': 'fooclient'}
        ).data.decode('utf8'))
        self.assertEqual(desc2['properties'], desc3['properties'])

    def test_get_devices(self):
        self.do_register(SoftU2FDevice())
        self.do_register(SoftU2FDevice())
        self.do_register(SoftU2FDevice())

        resp = json.loads(
            self.app.get('/foouser', environ_base={'REMOTE_USER': 'fooclient'}
                         ).data.decode('utf8'))
        self.assertEqual(len(resp), 3)

    def test_delete_user(self):
        self.do_register(SoftU2FDevice())
        self.do_register(SoftU2FDevice())
        self.do_register(SoftU2FDevice())
        self.app.delete('/foouser',
                        environ_base={'REMOTE_USER': 'fooclient'})
        resp = json.loads(
            self.app.get('/foouser', environ_base={'REMOTE_USER': 'fooclient'}
                         ).data.decode('utf8'))
        self.assertEqual(resp, [])

    def test_delete_devices(self):
        d1 = self.do_register(SoftU2FDevice())
        d2 = self.do_register(SoftU2FDevice())
        d3 = self.do_register(SoftU2FDevice())

        self.app.delete('/foouser/' + d2['handle'],
                        environ_base={'REMOTE_USER': 'fooclient'})
        resp = json.loads(
            self.app.get('/foouser',
                         environ_base={'REMOTE_USER': 'fooclient'}
                         ).data.decode('utf8'))
        self.assertEqual(len(resp), 2)
        self.app.delete('/foouser/' + d1['handle'],
                        environ_base={'REMOTE_USER': 'fooclient'})
        resp = json.loads(
            self.app.get('/foouser',
                         environ_base={'REMOTE_USER': 'fooclient'}
                         ).data.decode('utf8'))
        self.assertEqual(len(resp), 1)
        self.assertEqual(d3, resp[0])
        self.app.delete('/foouser/' + d3['handle'],
                        environ_base={'REMOTE_USER': 'fooclient'})
        resp = json.loads(
            self.app.get('/foouser',
                         environ_base={'REMOTE_USER': 'fooclient'}
                         ).data.decode('utf8'))
        self.assertEqual(resp, [])

    def test_set_properties_during_register(self):
        device = SoftU2FDevice()
        reg_req = json.loads(self.app.post(
            '/foouser/register',
            data=json.dumps({
                'properties': {'foo': 'one', 'bar': 'one'}
            }),
            environ_base={'REMOTE_USER': 'fooclient'}
        ).data.decode('utf8'))

        reg_resp = device.register('https://example.com', reg_req['appId'],
                                   reg_req['registerRequests'][0]).json

        desc = json.loads(self.app.post(
            '/foouser/register',
            data=json.dumps({
                'registerResponse': reg_resp,
                'properties': {'baz': 'two', 'bar': 'two'}
            }),
            environ_base={'REMOTE_USER': 'fooclient'}
        ).data.decode('utf8'))
        self.assertEqual({'foo': 'one', 'bar': 'two', 'baz': 'two'},
                         desc['properties'])

    def test_set_properties_during_sign(self):
        device = SoftU2FDevice()
        self.do_register(device, {'foo': 'one', 'bar': 'one', 'baz': 'one'})

        aut_req = json.loads(self.app.post(
            '/foouser/authenticate',
            data=json.dumps({
                'properties': {'bar': 'two', 'boo': 'two'}
            }),
            environ_base={'REMOTE_USER': 'fooclient'}
        ).data.decode('utf8'))
        aut_resp = device.getAssertion('https://example.com', aut_req['appId'],
                                       aut_req['challenge'],
                                       aut_req['registeredKeys'][0]).json
        desc = json.loads(self.app.post(
            '/foouser/authenticate',
            data=json.dumps({
                'signResponse': aut_resp,
                'properties': {'baz': 'three', 'boo': None}
            }),
            environ_base={'REMOTE_USER': 'fooclient'}
        ).data.decode('utf8'))
        self.assertEqual({
            'foo': 'one',
            'bar': 'two',
            'baz': 'three',
        }, desc['properties'])

    def test_register_and_sign_using_post(self):
        device = SoftU2FDevice()
        reg_req = json.loads(self.app.post(
            '/foouser/register',
            data=json.dumps({
                'challenge': 'ThisIsAChallenge'
            }),
            environ_base={'REMOTE_USER': 'fooclient'}
        ).data.decode('utf8'))

        self.assertEqual(reg_req['registerRequests'][0]['challenge'],
                         'ThisIsAChallenge')
        reg_resp = device.register('https://example.com', reg_req['appId'],
                                   reg_req['registerRequests'][0]).json

        desc1 = json.loads(self.app.post(
            '/foouser/register',
            data=json.dumps({
                'registerResponse': reg_resp
            }),
            environ_base={'REMOTE_USER': 'fooclient'}
        ).data.decode('utf8'))

        aut_req = json.loads(self.app.post(
            '/foouser/authenticate',
            data=json.dumps({
                'challenge': 'ThisIsAChallenge'
            }),
            environ_base={'REMOTE_USER': 'fooclient'}
        ).data.decode('utf8'))
        self.assertEqual(aut_req['challenge'], 'ThisIsAChallenge')
        aut_resp = device.getAssertion('https://example.com', aut_req['appId'],
                                       aut_req['challenge'],
                                       aut_req['registeredKeys'][0]).json
        desc2 = json.loads(self.app.post(
            '/foouser/authenticate',
            data=json.dumps({
                'signResponse': aut_resp
            }),
            environ_base={'REMOTE_USER': 'fooclient'}
        ).data.decode('utf8'))
        self.assertEqual(desc1['handle'], desc2['handle'])

    def test_device_compromised_on_counter_error(self):
        dev = SoftU2FDevice()
        self.do_register(dev)
        self.do_authenticate(dev)
        self.do_authenticate(dev)
        self.do_authenticate(dev)
        dev.counter = 1

        aut_req = json.loads(
            self.app.get('/foouser/authenticate',
                         environ_base={'REMOTE_USER': 'fooclient'}
                         ).data.decode('utf8'))
        aut_resp = dev.getAssertion('https://example.com', aut_req['appId'],
                                    aut_req['challenge'],
                                    aut_req['registeredKeys'][0]).json
        resp = self.app.post(
            '/foouser/authenticate',
            data=json.dumps({
                'signResponse': aut_resp
            }),
            environ_base={'REMOTE_USER': 'fooclient'}
        )

        self.assertEqual(400, resp.status_code)
        self.assertEqual(12, json.loads(resp.data.decode('utf8'))['errorCode'])

        resp = self.app.get('/foouser/authenticate',
                            environ_base={'REMOTE_USER': 'fooclient'})
        self.assertEqual(400, resp.status_code)
        self.assertEqual(11, json.loads(resp.data.decode('utf8'))['errorCode'])

    def do_register(self, device, properties=None):
        reg_req = json.loads(
            self.app.get('/foouser/register',
                         environ_base={'REMOTE_USER': 'fooclient'}
                         ).data.decode('utf8'))
        self.assertEqual(len(reg_req['registeredKeys']),
                         len(reg_req['descriptors']))

        reg_resp = device.register('https://example.com', reg_req['appId'],
                                   reg_req['registerRequests'][0]).json

        if properties is None:
            properties = {}
        descriptor = json.loads(self.app.post(
            '/foouser/register',
            data=json.dumps({
                'registerResponse': reg_resp,
                'properties': properties
            }),
            environ_base={'REMOTE_USER': 'fooclient'}
        ).data.decode('utf8'))
        self.assertEqual(descriptor['properties'], properties)
        return descriptor

    def do_authenticate(self, device, properties=None):
        aut_req = json.loads(
            self.app.get('/foouser/authenticate',
                         environ_base={'REMOTE_USER': 'fooclient'}
                         ).data.decode('utf8'))
        aut_resp = device.getAssertion('https://example.com', aut_req['appId'],
                                       aut_req['challenge'],
                                       aut_req['registeredKeys'][0]).json
        if properties is None:
            properties = {}
        return json.loads(self.app.post(
            '/foouser/authenticate',
            data=json.dumps({
                'signResponse': aut_resp,
                'properties': properties
            }),
            environ_base={'REMOTE_USER': 'fooclient'}
        ).data.decode('utf8'))
