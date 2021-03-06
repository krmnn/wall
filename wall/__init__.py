# Wall

# Python forward compatibility
from __future__ import (division, absolute_import, print_function,
    unicode_literals)

import sys
import os
import json
import exceptions
from datetime import datetime
from logging import StreamHandler, Formatter, getLogger, DEBUG
from ConfigParser import SafeConfigParser, Error as ConfigParserError
from subprocess import Popen
from string import ascii_lowercase
from random import choice
from collections import OrderedDict
from tornado.ioloop import IOLoop
from tornado.web import Application, RequestHandler, StaticFileHandler
import tornado.autoreload
from tornado.websocket import WebSocketHandler
from redis import StrictRedis
from wall.util import EventTarget, Event, ObjectRedis, RedisContainer, truncate

release = 20

res_path = os.path.join(os.path.dirname(__file__), 'res')
static_path = os.path.join(res_path, 'static')
template_path = os.path.join(res_path, 'templates')

class WallApp(Application, EventTarget):
    def __init__(self, config={}, config_path=None):
        Application.__init__(self, template_path=template_path, autoescape=None)
        EventTarget.__init__(self)

        self.logger = getLogger('wall')
        self.bricks = {}
        self.post_types = {}
        self.clients = []
        self.current_post = None
        self._init = True

        self._setup_logger()

        config_paths = [os.path.join(res_path, 'default.cfg')]
        if config_path:
            config_paths.append(config_path)
        try:
            parser = SafeConfigParser()
            parser.read(config_paths)
        except ConfigParserError as e:
            self.logger.error('failed to parse configuration file')
            self._init = False
            return

        self.config = {}
        for section in parser.sections():
            prefix = section + '.' if section != 'wall' else ''
            for key, value in parser.items(section):
                self.config[prefix + key] = value
        self.config.update(config)

        self.db = ObjectRedis(StrictRedis(db=int(self.config['db'])),
            self._decode_redis_hash)
        self.posts = RedisContainer(self.db, 'posts')

        self.add_post_type(TextPost)
        self.add_post_type(ImagePost)
        self.msg_handlers = {
            'post': self.post_msg,
            'post_new': self.post_new_msg,
            'get_history': self.get_history_msg
        }
        self.add_event_listener('posted', self._posted)

        # initialize bricks
        bricks = self.config['bricks'].split()
        for name in bricks:
            module = __import__(name, globals(), locals(), [b'foo'])
            brick = module.Brick(self)
            self.bricks[brick.id] = brick

        self.do_post_handlers = []
        for handler in self.config['do_post_handlers'].split():
            if handler not in ['note', 'history']:
                self.logger.warning('configuration: invalid item in do_post_handlers: "{}" unknown'.format(handler));
                continue
            if handler in self.do_post_handlers:
                self.logger.warning('configuration: invalid item in do_post_handlers: "{}" non-unique'.format(handler))
                continue
            self.do_post_handlers.append(handler)

        if self.config['debug'] == 'True':
            self.settings['debug'] = True
            tornado.autoreload.watch(os.path.join(res_path, 'default.cfg'))
            tornado.autoreload.start()

        # setup URL handlers
        urls = [
            ('/$', ClientPage),
            ('/display$', DisplayPage),
            ('/display/post$', DisplayPostPage),
            ('/api/socket$', Socket),
        ]
        for brick in self.bricks.values():
            urls.append(('/static/{0}/(.+)$'.format(brick.id),
                StaticFileHandler, {'path': brick.static_path}))
        urls.append(('/static/(.+)$', StaticFileHandler, {'path': static_path}))
        self.add_handlers('.*$', urls)

    @property
    def js_modules(self):
        return [b.js_module for b in self.bricks.values()]

    @property
    def scripts(self):
        scripts = []
        for brick in self.bricks.values():
            scripts.extend(brick.id + '/' + s for s in brick.scripts)
        return scripts

    @property
    def stylesheets(self):
        stylesheets = []
        for brick in self.bricks.values():
            stylesheets.extend(brick.id + '/' + s for s in brick.stylesheets)
        return stylesheets

    def run(self):
        if not self._init:
            return
        self.listen(8080)
        self.logger.info('server started')
        IOLoop.instance().start()

    def add_message_handler(self, type, handler):
        """
        Extension API: register a new message `handler` for messages of the
        given `type`.

        A message handler is a function `handle(msg)` that processes a received
        message. It may return a `Message`, which is sent back to the sender as
        response. If a (subclass of) `Error` is raised, it is converted to a
        `Message` and sent back to the sender as error response.
        """
        self.msg_handlers[type] = handler

    def sendall(self, msg):
        for client in self.clients:
            client.send(msg)

    def post_msg(self, msg):
        # TODO: error handling
        post = self.post(msg.data['id'])
        return Message('post', post.json())

    def post_new_msg(self, msg):
        # wake display
        Popen('DISPLAY=:0.0 xset dpms force on', shell=True)

        post_type = msg.data.pop('type')
        post = self.post_new(post_type, **msg.data)
        return Message('post_new', post.json())

    def get_history_msg(self, msg):
        return Message('get_history',
            [p.json('common') for p in self.get_history()])

    def post(self, id):
        try:
            post = self.posts[id]
        except KeyError:
            raise ValueError('id_nonexistent')

        if self.current_post:
            self.current_post.deactivate()

        self.current_post = post
        post.posted = datetime.utcnow().isoformat()
        self.db.hset(post.id, 'posted', post.posted)
        post.activate()

        self.dispatch_event(Event('posted', post=post))
        return post

    def post_new(self, type, **args):
        try:
            post_type = self.post_types[type]
        except KeyError:
            raise ValueError('type_nonexistent')

        post = post_type.create(self, **args)
        self.db.sadd('posts', post.id)
        return self.post(post.id)

    def get_history(self):
        return sorted(self.posts.values(), key=lambda p: p.posted, reverse=True)

    def add_post_type(self, post_type):
        """
        Extension API: register a new post type. `post_type` is a class (type)
        that extends `Post`.
        """
        self.post_types[post_type.__name__] = post_type

    def _decode_redis_hash(self, hash):
        post_type = self.post_types[hash['__type__']]
        return post_type(self, **hash)

    def _setup_logger(self):
        logger = getLogger()
        logger.setLevel(DEBUG)
        handler = StreamHandler()
        handler.setFormatter(
            Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
        logger.addHandler(handler)

    def _posted(self, event):
        self.sendall(Message('posted', {'post': event.args['post'].json()}))

class Socket(WebSocketHandler):
    def initialize(self):
        self.app = self.application

    def send(self, msg):
        self.write_message(str(msg))
        self.app.logger.debug('sent message %s to %s', truncate(str(msg)),
            self.request.remote_ip)

    def open(self):
        self.app.clients.append(self)
        self.app.logger.debug('client %s connected', self.request.remote_ip)
        self.app.dispatch_event(Event('connected', client=self))

        # TODO: announce current post as response to hello message
        if self.app.current_post:
            self.send(Message('posted', {'post': self.app.current_post.json()}))

    def on_close(self):
        self.app.clients.remove(self)
        self.app.logger.debug('client %s disconnected', self.request.remote_ip)
        self.app.dispatch_event(Event('disconnected', client=self))

    def on_message(self, msgstr):
        msg = Message.parse(msgstr, self)
        self.app.logger.debug('received message %s from %s', truncate(str(msg)),
            self.request.remote_ip)

        handle = self.app.msg_handlers[msg.type]
        try:
            # TODO: support Future for asynchronous handlers (see
            # https://code.google.com/p/pythonfutures/ )
            response = handle(msg)
        except Error as e:
            response = Message(msg.type, e.json())

        if response:
            msg.frm.send(response)

class Message(object):
    @classmethod
    def parse(cls, msgstr, frm=None):
        msg = json.loads(msgstr)
        return Message(msg['type'], msg['data'], frm)

    def __init__(self, type, data=None, frm=None):
        self.type = type
        self.data = data
        self.frm  = frm

    def __str__(self):
        return json.dumps(
            OrderedDict([('type', self.type), ('data', self.data)])
        )

class ClientPage(RequestHandler):
    def get(self):
        self.render('remote.html', app=self.application)

class DisplayPage(RequestHandler):
    def get(self):
        # TODO: make app.config['info'] available via API
        self.render('display.html', app=self.application)

class DisplayPostPage(RequestHandler):
    def get(self):
        self.render('display-post.html', app=self.application)

class Post(object):
    @classmethod
    def create(cls, app, **args):
        """
        Extension API: create a post of this type. Must be overridden and create
        a post, store it in the database and return it. Specific arguments are
        passed to `create` as `args`. `app` is the wall instance.

        Called when a new post of this type should be created via
        `Wall.post_new`.
        """
        raise NotImplementedError()

    def __init__(self, app, id, title, posted, **kwargs):
        self.app = app
        self.id = id
        self.title = title
        self.posted = posted

    def activate(self):
        """
        Activate the post.

        Extension API: may be overridden for advanced posts. Called when the
        post is posted to / shown on the wall.
        """
        pass

    def deactivate(self):
        """
        Deactivate the post.

        Extension API: may be overridden for advanced posts. Called when the
        post is removed / hidden from the wall.
        """
        pass

    def json(self, view=None):
        if not view:
            filter = lambda k: not k.startswith('_') and k != 'app'
        elif view == 'common':
            filter = lambda k: k in ['id', 'title', 'posted']
        else:
            raise ValueError('view')

        return dict(((k, v) for k, v in vars(self).items() if filter(k)),
            __type__=type(self).__name__)

    def __eq__(self, other):
        # TODO: replace this by identity mapping / caching (see
        # https://docs.python.org/2/library/weakref.html )
        return self.id == other.id

    def __str__(self):
        return '<{} {}>'.format(self.__class__.__name__, self.id)
    __repr__ = __str__

class Brick(object):
    """
    An extension (plugin) for Wall.

    Static attributes:

     * id: unique brick identifier. Must be set by subclass.
     * maintainer: brick maintainer. Must be set by subclass.
     * js_module: corresponding JavaScript module (i.e. namespace). Defaults to
       the name of the Python module.
     * static_path: path to static resources. Defaults to '<module_dir>/static'.
     * scripts: corresponding JavaScript scripts. Defaults to ['<id>.js'].
     * stylesheets: corresponding stylesheets. Defaults to ['<id>.css'] if
       existant, else [].

    Attributes:

     * app: Wall application.
    """
    id = None
    maintainer = None
    js_module = None
    static_path = None
    scripts = None
    stylesheets = None

    def __init__(self, app):
        self.app = app
        self.config = app.config
        self.logger = getLogger('wall.' + self.id)

        # set defaults
        self.js_module = self.js_module or type(self).__module__
        self.static_path = self.static_path or os.path.join(
            os.path.dirname(sys.modules[self.__module__].__file__), 'static')
        self.scripts = self.scripts or [self.id + '.js']
        if not self.stylesheets:
            if os.path.isfile(os.path.join(self.static_path, self.id + '.css')):
                self.stylesheets = [self.id + '.css']
            else:
                self.stylesheets = []

class TextPost(Post):
    @classmethod
    def create(cls, app, **kwargs):
        try:
            content = kwargs['content'].strip()
        except KeyError:
            raise ValueError('content_missing')
        if not content:
            raise ValueError('content_empty')

        title = truncate(content.splitlines()[0])

        post = TextPost(app, 'text_post:' + randstr(), title, None, content)
        app.db.hmset(post.id, post.json())
        return post

    def __init__(self, app, id, title, posted, content, **kwargs):
        super(TextPost, self).__init__(app, id, title, posted, **kwargs)
        self.content = content

class ImagePost(Post):
    @classmethod
    def create(cls, app, **kwargs):
        # TODO: check args
        url = kwargs['url']
        post = ImagePost(app, 'image_post:' + randstr(), 'Image', None, url)
        app.db.hmset(post.id, post.json())
        return post

    def __init__(self, app, id, title, posted, url, **kwargs):
        super(ImagePost, self).__init__(app, id, title, posted, **kwargs)
        self.url = url

class Error(Exception):
    def json(self):
        return {'args': self.args, '__type__': type(self).__name__}

class ValueError(Error, exceptions.ValueError): pass

def randstr(length=8, charset=ascii_lowercase):
    return ''.join(choice(charset) for i in xrange(length))

# ==== Tests ====

from wall.test import TestCase, CommonPostTest
from tempfile import NamedTemporaryFile

class WallTest(TestCase):
    def test_init(self):
        # without config file
        app = WallApp()
        self.assertTrue(app._init)

        # valid config file
        f = NamedTemporaryFile(delete=False)
        f.write('[wall]\ndebug = True\n')
        f.close()
        app = WallApp(config_path=f.name)
        self.assertTrue(app._init)

        # invalid config file
        f = NamedTemporaryFile(delete=False)
        f.write('foo')
        f.close()
        app = WallApp(config_path=f.name)
        self.assertFalse(app._init)

    def test_post(self):
        post = self.app.post_new('TestPost')
        self.assertIn(post.id, self.app.posts)
        self.assertEqual(self.app.current_post, post)
        self.assertTrue(post.activate_called)
        self.app.post(post.id)
        self.assertTrue(post.deactivate_called)

    def test_post_new(self):
        post = self.app.post_new('TestPost')
        self.assertIn(post.id, self.app.posts)

    def test_post_new_unknown_type(self):
        with self.assertRaises(ValueError):
            self.app.post_new('foo')

    def test_get_history(self):
        posts = []
        posts.insert(0, self.app.post_new('TestPost'))
        posts.insert(0, self.app.post_new('TestPost'))
        self.assertEqual(posts, self.app.get_history()[0:2])

class TextPostTest(TestCase, CommonPostTest):
    def setUp(self):
        super(TextPostTest, self).setUp()
        CommonPostTest.setUp(self)
        self.post_type = TextPost
        self.create_args = {'content': 'Babylon 5'}

class ImagePostTest(TestCase, CommonPostTest):
    def setUp(self):
        super(ImagePostTest, self).setUp()
        CommonPostTest.setUp(self)
        self.post_type = ImagePost
        self.create_args = {'url': 'https://welcome.b5/logo.png'}
