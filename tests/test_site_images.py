import base64
import json
import os
import tempfile
import io
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack
import server


class SiteImageTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))
        self.stack.enter_context(patch.object(server, 'DB_PATH', Path(directory) / 'test.sqlite3'))
        self.stack.enter_context(patch.object(server, '_DB_INITIALIZED', False))
        self.allowed = False
        self.stack.enter_context(patch.object(server.LumiHandler, 'admin_allowed', lambda handler: self.allowed))
        self.stack.enter_context(patch.object(server.LumiHandler, 'log_message', lambda *args: None))

    def tearDown(self):
        self.stack.close()

    def request(self, path, data=None):
        body = b'' if data is None else json.dumps(data).encode()
        environ = {'PATH_INFO':path, 'REQUEST_METHOD':'GET' if data is None else 'POST',
                   'CONTENT_LENGTH':str(len(body)), 'CONTENT_TYPE':'application/json',
                   'wsgi.input':io.BytesIO(body), 'SERVER_NAME':'localhost', 'SERVER_PORT':'80',
                   'REMOTE_ADDR':'127.0.0.1', 'wsgi.url_scheme':'http'}
        result = {}
        def start_response(status, headers):
            result['status'] = int(status.split()[0])
            result['headers'] = dict(headers)
        raw = b''.join(server.app(environ, start_response))
        value = json.loads(raw) if 'application/json' in result['headers'].get('Content-Type', '') else raw
        return result['status'], value

    def test_public_defaults_and_protected_edit(self):
        status, result = self.request('/api/site-images')
        self.assertEqual(status, 200)
        self.assertEqual(result['images'], server.SITE_IMAGES)
        self.assertEqual(self.request('/api/admin/site-images')[0], 401)
        self.assertEqual(self.request('/api/admin/site-images', {'hero':'assets/new.jpg'})[0], 401)
        self.assertEqual(self.request('/api/site-images')[1]['images'], server.SITE_IMAGES)

    def test_saved_images_visible_publicly_and_unchanged_slots_retained(self):
        self.allowed = True
        status, result = self.request('/api/admin/site-images', {'hero':'https://example.com/new.jpg','footer_logo':'assets/logo/updated.png'})
        self.assertEqual(status, 200)
        self.assertEqual(result['images']['hero'], 'https://example.com/new.jpg')
        self.assertEqual(result['images']['manifesto'], server.SITE_IMAGES['manifesto'])
        self.allowed = False
        self.assertEqual(self.request('/api/site-images')[1], result)

    def test_invalid_updates_are_atomic(self):
        self.allowed = True
        for data in [{'unknown':'assets/image.png'}, {'hero':'javascript:alert(1)'}, {'hero':'assets/../server.py'}, {'hero':''}, {'hero':'assets/good.jpg','footer_logo':'data:text/html,bad'}]:
            self.assertEqual(self.request('/api/admin/site-images', data)[0], 400)
        self.assertEqual(self.request('/api/site-images')[1]['images'], server.SITE_IMAGES)

    def test_uploaded_image_can_be_assigned_and_downloaded(self):
        self.allowed = True
        raw = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWOQAAAAASUVORK5CYII=')
        status, result = self.request('/api/admin/product-image', {'mime':'image/png','data':base64.b64encode(raw).decode()})
        self.assertEqual(status, 201)
        self.assertEqual(self.request('/api/admin/site-images', {'hero':result['image']})[0], 200)
        self.allowed = False
        self.assertEqual(self.request(result['image']), (200,raw))
        self.assertEqual(self.request('/api/site-images')[1]['images']['hero'], result['image'])
