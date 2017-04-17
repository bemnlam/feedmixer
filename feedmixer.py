"""
Instances of `FeedMixer` are initialized with a list of Atom/RSS feeds and
generate an Atom/RSS/JSON feed consisting of the most recent `num_keep` entries
from each.

Usage
-----

First initialize the `FeedMixer` object with its metadata and list of feeds::

>>> from feedmixer import FeedMixer
>>> title = "Title"
>>> link = "http://example.com/feedmixer/feed"
>>> desc = "Description of feed"
>>> feeds = ['http://americancynic.net/atom.xml', 'http://hnrss.org/newest']
>>> fm = FeedMixer(title=title, link=link, desc=desc, feeds=feeds)

Nothing is fetched until you ask for the list of mixed entries or for a feed to
be generated:

>>> mixed = fm.mixed_entries
>>> # The first time there will be a pause here while the
>>> # feeds are fetched over the network. On subsequent calls,
>>> # feeds will likely be returned from the cache quickly.
>>> len(mixed)
6

Feeds of various flavours are generated by calling one of the following methods:

    - `atom_feed()`
    - `rss_feed()`
    - `json_feed()`

>>> atom_feed = fm.atom_feed()
>>> atom_feed
'<?xml version="1.0" encoding="utf-8"?>...and so on...'

Feeds are fetched in parallel (using threads), and cached to disk (using
FeedCache_).

If any of the `feeds` URLs cannot be fetched or parsed, the errors will be
reported in the `error_urls` attribute.

To set a timeout on network requests, do this in your app::

>>> TIMEOUT = 120  # time to wait for http requests (seconds)
>>> import socket
>>> socket.setdefaulttimeout(TIMEOUT)

.. _FeedCache: https://github.com/cristoper/shelfcache

Interface
---------
"""
import datetime
import logging
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
import json
from typing import Type, List, Optional, Callable, Dict, Union

# https://docs.djangoproject.com/en/1.10/_modules/django/utils/feedgenerator/
import feedgenerator
from feedgenerator import Rss201rev2Feed, Atom1Feed, SyndicationFeed

import feedparser
from feedparser.util import FeedParserDict

from shelfcache.cache_get import cache_get
from shelfcache.shelfcache import ShelfCache
from urllib.error import URLError
from requests.exceptions import RequestException

# Types:
class ParseError(Exception): pass
FCException = Union[RequestException, ParseError]
error_dict_t = Dict[str, FCException]
cacher_t = Callable[[str], FeedParserDict]

logger = logging.getLogger(__name__)


class FeedMixer(object):
    def __init__(self, title='Title', link='', desc='',
                 feeds: List[Optional[str]]=[], num_keep=3,
                 max_threads=5, max_feeds=100, cache_path='fmcache',
                 cache: Optional[ShelfCache]=None, cache_get=cache_get) -> None:
        """
        __init__(self, title, link='', desc='', feeds=[], num_keep=3, \
            max_thread=5, max_feeds=100, cache_path='fmcache')

        Args:
            title: the title of the generated feed
            link: the URL of the generated feed
            desc: the description of the generated feed
            feeds: the list of feed URLs to fetch and mix
            num_keep: the number of entries to keep from each member of `feeds`
            max_threads: the maximum number of threads to spin up while fetching
            feeds
            max_feeds: the maximum number of feeds to fetch
            cache: The ShelfCache instance to manage the cache. If not provided,
                an instance will be created with `cache_path`
            cache_path: path where the cache database should be created
            cache_get: the method to use for fetching remote feeds (this is
                injectable for testing purposes)
        """
        self.title = title
        self.link = link
        self.desc = desc
        self.max_feeds = max_feeds
        self._feeds = feeds[:max_feeds]
        self._num_keep = num_keep
        self.max_threads = max_threads
        self._mixed_entries = []  # type: List[Optional[dict]]
        self._error_urls = {}  # type: error_dict_t
        self.cache_get = cache_get
        if cache is None:
            cache = ShelfCache(db_path=cache_path, exp_seconds=300)
        self.cache = cache

    @property
    def num_keep(self) -> int:
        """
        The number of entries to keep from each feed in `feeds`. Setting this
        property will trigger the feeds to be re-fetched.
        """
        return self._num_keep

    @num_keep.setter
    def num_keep(self, value: int) -> None:
        self._num_keep = value
        self.feeds = self._feeds

    @property
    def mixed_entries(self) -> List[dict]:
        """
        The parsed feed entries fetched from the list of URLs in `feeds`.
        (Accessing the property triggers the feeds to be fetched/cached if they
        have not yet been.)
        """
        if len(self._mixed_entries) < 1:
            self.__fetch_entries()
        return self._mixed_entries

    @property
    def error_urls(self) -> error_dict_t:
        """
        A dictionary whose keys are the URLs which generated an error (if any
        did), and whose associated values are an Exception object which contains
        a description of the error (and http status code if applicable).
        """
        return self._error_urls

    @property
    def feeds(self) -> list:
        """
        Get or set list of feeds.
        """
        return self._feeds

    @feeds.setter
    def feeds(self, value: List[str]) -> None:
        """
        Reset _mixed_entries whenever we get a new list of feeds.
        """
        self._feeds = value[:self.max_feeds]
        self._mixed_entries = []

    def atom_feed(self) -> str:
        """
        Returns:
            An Atom feed consisting of the `num_keep` most recent entries from
            each of the `feeds`.
        """
        return self.__generate_feed(Atom1Feed).writeString('utf-8')

    def rss_feed(self) -> str:
        """
        Returns:
            An RSS 2 feed consisting of the `num_keep` most recent entries from
            each of the `feeds`.
        """
        return self.__generate_feed(Rss201rev2Feed).writeString('utf-8')

    def json_feed(self) -> str:
        """
        Returns:
            A JSON dict consisting of the `num_keep` most recent entries from
            each of the `feeds`.
        """
        # (The default encoding lambda is so that we can handle datetime
        # objects)
        return json.dumps(self.mixed_entries, default=lambda o: str(o),
                          sort_keys=True)

    def __fetch_entries(self) -> None:
        """
        Multi-threaded fetching of the `feeds`. Keeps the `num_keep` most recent
        entries from each feed, combines them (sorted chronologically), extracts
        `feedgernerator`-compatible metadata, and then stores the list of
        entries as `self.mixed_entries`
        """
        parsed_entries = []  # type: List[dict]
        self._error_urls = {}
        with ThreadPoolExecutor(max_workers=self.max_threads) as exec:
            future_to_url = {exec.submit(self.cache_get, self.cache, url): url
                             for url in self.feeds}
            for future in concurrent.futures.as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    resp = future.result()

                    # parse response and check for parse errors
                    f = feedparser.parse(resp.text)
                    parse_err = len(f.get('entries')) == 0 and f.get('bozo')
                    if f is None or parse_err:
                        logger.info("Parse error ({})"
                                    .format(f.get('bozo_exception')))
                        raise ParseError("Parse error: {}"
                                         .format(f.get('bozo_exception')))

                    logger.info("Got feed from feedparser {}".format(url))
                    logger.debug("Feed: {}".format(f))

                    if self._num_keep == -1:
                        newest = f.entries
                    else:
                        newest = f.entries[0:self._num_keep]
                    # use feed author if individual entries are missing
                    # author property
                    if 'author_detail' in f.feed:
                        for e in newest:
                            if 'author_detail' not in e:
                                e['author_detail'] = f.feed.author_detail
                                e.author_detail = f.feed.author_detail
                    parsed_entries += newest
                except (ParseError, RequestException) as e:
                    self._error_urls[url] = e
                    logger.info("{} generated an exception: {}".format(url, e))

        # sort entries by published date
        parsed_entries.sort(key=lambda e: e['published'], reverse=True)

        # extract metadata into a form usable by feedgenerator
        mixed_entries = self.extract_meta(parsed_entries)
        self._mixed_entries = mixed_entries

    @staticmethod
    def extract_meta(parsed_entries: List[dict]) -> List[dict]:
        """
        Convert a FeedParserDict object into a dict compatible with the Django
        feedgenerator classes.
        """
        mixed_entries = []
        for e in parsed_entries:
            metadata = {}

            # title, link, and description are mandatory
            metadata['title'] = e.get('title', '')
            metadata['link'] = e.get('link', '')
            metadata['description'] = e.get('description', '')

            if 'author_detail' in e:
                metadata['author_email'] = e['author_detail'].get('email')
                metadata['author_name'] = e['author_detail'].get('name')
                metadata['author_link'] = e['author_detail'].get('href')

            # convert time_struct tuples into datetime objects
            # (the min() prevents error in the off-chance that the
            # date contains a leap-second)
            tp = e.get('published_parsed')
            if tp:
                metadata['pubdate'] = datetime.datetime(*tp[:5] + (min(tp[5],
                                                                       59),))

            tu = e.get('updated_parsed')
            if tu:
                metadata['updateddate'] = datetime.datetime(*tu[:5] +
                                                            (min(tu[5], 59),))

            metadata['comments'] = e.get('comments')
            metadata['unique_id'] = e.get('id')
            metadata['item_copyright'] = e.get('license')

            if 'tags' in e:
                taglist = [tag.get('term') for tag in e['tags']]
                metadata['categories'] = taglist
            if 'enclosures' in e:
                enclist = []
                for enc in e['enclosures']:
                    enclist.append(feedgenerator.Enclosure(enc.href, enc.length,
                                                           enc.type))
                metadata['enclosures'] = enclist

            mixed_entries.append(metadata)
        return mixed_entries

    def __generate_feed(self, gen_cls: Type[SyndicationFeed]) -> SyndicationFeed:
        """
        Generate a feed using one of the generator classes from the Django
        `feedgenerator` module.
        """
        gen = gen_cls(title=self.title, link=self.link, description=self.desc)
        for e in self.mixed_entries:
            gen.add_item(**e)
        return gen
