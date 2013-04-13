# Wall

# Python forward compatibility
from __future__ import (division, absolute_import, print_function,
    unicode_literals)

import json
from wall import Brick as _Brick, randstr, Message
from urllib import urlencode
from tornado.httpclient import AsyncHTTPClient

class Brick(_Brick):
    id        = 'youtube'
    js_module = 'wall.youtube'
    post_type = 'YoutubePost'

    def __init__(self, app):
        super(Brick, self).__init__(app)
        self.app.msg_handlers['youtube.search'] = self._search_msg

    def post_new(self, type, **args):
        url = args['url'].strip()
        title = args['title'].strip()
        videoid = args['videoid'].strip()

        if not videoid:
            raise ValueError('videoid')
        if not url:
            raise ValueError('url')
        if not url.startswith(('http://', 'https://')):
            url = 'http://' + url
        if not title:
            title = 'No title'

        return YoutubePost(randstr(), videoid, url, title)

    def search(self, query, callback):
        def cb(response):
            if response.error:
                self.logger.error(self.id + ': response: ' + response.error)

            data = json.load(response.buffer)
            entries = data['feed']['entry']

            results = []
            for entry in entries:
                meta = entry['media$group']

                # get default video URL and enable autoplay
                video = filter(lambda v: 'isDefault' in v,
                    meta['media$content'])[0]
                video = video['url'] + '&autoplay=1'
                # alternative: video = meta['media$player']['url']

                thumbnail = filter(lambda t: t['yt$name'] == 'default',
                    meta['media$thumbnail'])[0]
                thumbnail = thumbnail['url']

                videoid = meta['yt$videoid']['$t']

                results.append({
                    'videoid':   videoid,
                    'title':     meta['media$title']['$t'],
                    'url':       video,
                    'thumbnail': thumbnail,
                    'provider':  'Youtube'
                })

            callback(results)

        # Youtube API documentation:
        # https://developers.google.com/youtube/2.0/developers_guide_protocol
        client = AsyncHTTPClient()
        qs = urlencode({
            'q':           query,
            'max-results': '5',
            'alt':         'json',
            'v':           '2'
        })
        client.fetch('https://gdata.youtube.com/feeds/api/videos/?' + qs, cb)

    def _search_msg(self, msg):
        def cb(results):
            msg.frm.send(Message(msg.type, results))
        self.search(msg.data['query'], cb)

class YoutubePost(object):
    def __init__(self, id, videoid, url, title):
        self.id       = id
        self.videoid  = videoid
        self.url      = url
        self.title    = title
        self.__type__ = type(self).__name__

