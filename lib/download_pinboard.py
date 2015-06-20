from datetime import datetime, timedelta
from dateutil.tz import tzutc
import dateutil.parser
import plistlib
import sys
import re
import logging


from lib import (
    AppleScript,
    configure_log,
    pinboard,
    Tags,
    PinboardPrefs
)

from settings import _SAVE_PATH


def to_dt(thing):
    return dateutil.parser.parse(thing)


class PinboardDownloader:
    def __init__(self, username=None, password=None, token=None, **kwargs):
        self.logger = configure_log('pinboarddownloader', verbose=kwargs.get('verbose'))
        self.p = self._get_pinboard_session(username, password, token)
        self.prefs = PinboardPrefs()
        self.pinboard_last_updated = to_dt(self.p.last_update())
        self.last_updated = self.get_last_updated()
        self.urls_already_seen = set()
        self.duplicate_count = 0

    @property
    def needs_update(self):
        return self.last_updated < self.pinboard_last_updated

    def get_last_updated(self):
        last_updated = self.prefs.get('last_updated')
        to_ret = datetime(1970, 1, 1, tzinfo=tzutc()) \
            if not last_updated else to_dt(last_updated)
        self.logger.info("Last updated locally: %s " % to_ret)
        return to_ret

    def set_last_updated(self, reset=None):
        if reset:
            timestamp = self.last_updated - timedelta(days=reset)
        else:
            timestamp = self.pinboard_last_updated
        self.prefs.set('last_updated', timestamp.isoformat())
        self.last_updated = timestamp
        self.logger.info("Setting last updated to %s" % timestamp)

    def get_posts(self, **kwargs):
        to_pass = dict()
        if kwargs.get('tag'):
            to_pass['tag'] = kwargs['tag']
            self.logger.info("Filtering posts by tags: %s" % kwargs['tag'])
        self.logger.info("Getting posts...")
        return self.p.posts(
            fromdt=self.last_updated,
            **to_pass
        )

    def write_to_file(self, filepath, data):
        self.logger.info("Writing to %s" % filepath.split('/')[-1])
        with open(filepath, 'w') as f:
            f.write(plistlib.writePlistToString(data))

    def download_posts(self, **kwargs):
        if not self.needs_update:
            self.logger.info("Pinboard download is up-to-date. Exiting...")
            sys.exit(1)
        posts_to_download = self.get_posts(**kwargs)
        self.logger.info("got %s posts..." % len(posts_to_download))
        for post in posts_to_download:
            if post['description'] in self.urls_already_seen:
                self.duplicate_count += 1
                continue
            filename = self._clean_filename(post['description'])
            data = {'URL':  post['href']}
            self.write_to_file(
                filename,
                data
            )
            Tags.set_tags(filename, post['tags'])
            AppleScript.set_comments(
                filename,
                u"%s\n\n%s\n\n%s" % (post['href'], post['description'], post['extended'])
            )
            self.urls_already_seen.add(post['description'])

        if self.duplicate_count:
            self.logger.info(
                "%s duplicates found. %s bookmarks saved"
                % (self.duplicate_count, len(self.urls_already_seen))
            )

        self.set_last_updated()

    def _clean_filename(self, description):
        # some filesystems HFS+) don't like very long filenames (255+ chars)
        # stripping at 248 characters + .webloc prevents issues on those systems
        cleaned_filename = re.sub(r'[/]', ' ', description)
        if len(cleaned_filename) > 248:
            cleaned_filename = cleaned_filename[0:248].strip()
        return _SAVE_PATH + cleaned_filename + '.webloc'

    def _get_pinboard_session(self, username, password, token):
        # todo: should maybe try attempting to connect a few times
        # before just giving up
        try:
            return pinboard.open(username, password, token)
        except Exception as e:
            self.logger.error("Error connecting with Pinboard API: %s" % e)
            sys.exit(0)
