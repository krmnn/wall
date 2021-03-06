# Wall

# Python forward compatibility
from __future__ import (division, absolute_import, print_function,
    unicode_literals)

from tornado.testing import AsyncTestCase
from tornado.ioloop import IOLoop
from logging import getLogger, CRITICAL
from redis import StrictRedis
from wall import WallApp, Post, randstr

class TestCase(AsyncTestCase):
    """
    Extension API: Base for Wall unit tests. Takes care of setting / cleaning up
    the test environment and provides utilities for testing.

    Attributes:

     * `db`: connection to temporary Redis database (`15`)
     * `app`: Wall application. `TestPost` is available as registered post type.
    """

    @classmethod
    def setUpClass(cls):
        getLogger('wall').setLevel(CRITICAL)

    def setUp(self):
        super(TestCase, self).setUp()
        self.db = StrictRedis(db=15)
        self.db.flushdb()
        self.app = WallApp(config={'db': 15})
        self.app.add_post_type(TestPost)

    def get_new_ioloop(self):
        return IOLoop.instance()

class CommonPostTest(object):
    """
    Extension API: Mixin for `Post` tests. Provides common tests of the `Post`
    API.

    Attributes:

     * `post_type`: Post type to test. Must be set by subclass during `setUp`.
     * `create_args`: Valid `args` for `post_type`'s `create` method. Must
           be set by subclass during `setUp`.
    """

    def setUp(self):
        self.post_type = None
        self.create_args = None

    def test_create(self):
        post = self.post_type.create(self.app, **self.create_args)
        self.assertTrue(post.id)

class TestPost(Post):
    @classmethod
    def create(cls, app, **args):
        post = TestPost(app, 'test_post:' + randstr(), 'Test', None)
        app.db.hmset(post.id, post.json())
        return post

    def __init__(self, app, id, title, posted, **kwargs):
        super(TestPost, self).__init__(app, id, title, posted, **kwargs)
        self.activate_called = False
        self.deactivate_called = False

    def activate(self):
        self.activate_called = True

    def deactivate(self):
        self.deactivate_called = True
