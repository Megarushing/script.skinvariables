# -*- coding: utf-8 -*-
# License: GPL v.3 https://www.gnu.org/copyleft/gpl.html
import threading
import xbmc
from jurialmunkey.ftools import cached_property
from resources.lib.multisearch.discover import DiscoverSearchSources
from resources.lib.multisearch.results import SourceResults
from resources.lib.multisearch.sources import SearchSource, get_path_origin
from resources.lib.multisearch.window import SOURCES_ID, MultiSearchControl, MultiSearchWindow


TMDBHELPER_PLUGIN = 'plugin://plugin.video.themoviedb.helper/'
TRAKT_DISCOVER_LABEL = 'Trakt Discover'
TRAKT_DISCOVER_ICON = 'special://home/addons/script.module.tmdbhelper.sync.trakt/resources/icons/trakt/trakt.png'
TRAKT_DISCOVER_TARGET = 'videos'
TRAKT_DISCOVER_PATH_INFOLABEL = 'Window(Home).Property(TMDbHelper.TraktDiscover.Path)'
TRAKT_DISCOVER_DEFAULT_PATH = f'{TMDBHELPER_PLUGIN}?info=trakt_trending&tmdb_type=movie'
TRAKT_DISCOVER_EDITOR = f'RunPlugin({TMDBHELPER_PLUGIN}?info=trakt_discover&use_winprops=true)'
TRAKT_FILTERS_ID = 110
TRAKT_PATH_POLL_SECONDS = 1


def get_trakt_discover_path():
    """Path saved by the TMDbHelper Trakt Discover editor, otherwise trending movies."""
    return xbmc.getInfoLabel(TRAKT_DISCOVER_PATH_INFOLABEL) or TRAKT_DISCOVER_DEFAULT_PATH


class TraktDiscoverResults(SourceResults):
    """All items of the saved Trakt Discover path for one search. The search text is added as the query param."""

    def __init__(self, source, query, path):
        super().__init__(source, query)
        self.discover_path = path

    def get_path(self):
        if not self.query.raw:
            return self.discover_path
        return f'{self.discover_path}&query={self.query.encoded}'


class TraktDiscoverSource(SearchSource):
    """TMDbHelper Trakt Discover with the filters saved by its editor.

    Searches without search text too, listing the saved Trakt Discover results. The genre, decade and sort method of
    the window narrow and order the results like a search source, as Trakt looks up its own filters.
    """

    def __init__(self, index, search_cache, widget_style=None):
        super().__init__(index, self.get_meta(widget_style), {}, search_cache)

    def get_meta(self, widget_style):
        return {
            'label': TRAKT_DISCOVER_LABEL,
            'icon': TRAKT_DISCOVER_ICON,
            'target': TRAKT_DISCOVER_TARGET,
            'widget_style': widget_style or '',
        }

    @property
    def template(self):
        """Read each search because the editor changes the saved path while the window is open."""
        return get_trakt_discover_path()

    def get_origin(self):
        return get_path_origin(TMDBHELPER_PLUGIN)

    def accepts(self, query, options):
        return True

    def get_cache_key(self, query, options):
        return (query.raw, self.template)

    def get_source_results(self, query, options):
        return TraktDiscoverResults(self, query, self.template)


class TraktDiscoverSearchSources(DiscoverSearchSources):
    """TMDbHelper discover sources followed by Trakt Discover and the search widgets of the shortcuts menu."""

    @cached_property
    def trakt_discover_item(self):
        """Indexed after the TMDbHelper discover sources."""
        return TraktDiscoverSource(len(self.menu_meta) + len(self.discover_items), self.search_cache, self.widget_style)

    def get_items(self):
        items = super().get_items()
        position = len(self.discover_items)
        return [*items[:position], self.trakt_discover_item, *items[position:]]


class TraktFiltersButton(MultiSearchControl):
    """Optional button that searches Trakt Discover alone and opens the TMDbHelper Trakt Discover editor with the
    saved filters. Reset enables every source again.
    """

    control_id = TRAKT_FILTERS_ID

    def onclick(self, window):
        window.select_trakt_discover()
        xbmc.executebuiltin(TRAKT_DISCOVER_EDITOR)


class TraktDiscoverPathWatcher:
    """Searches again whenever the Trakt Discover editor saves a new path while the window is open."""

    def __init__(self, window):
        self.window = window
        self.stopped = threading.Event()
        self.path = get_trakt_discover_path()

    @cached_property
    def thread(self):
        return threading.Thread(target=self.watch, daemon=True)

    def start(self):
        self.thread.start()

    def watch(self):
        monitor = xbmc.Monitor()
        while not self.stopped.is_set() and not monitor.waitForAbort(TRAKT_PATH_POLL_SECONDS):
            self.check()

    def check(self):
        path = get_trakt_discover_path()
        if path == self.path:
            return
        self.path = path
        self.window.research()

    def stop(self):
        self.stopped.set()


class TraktDiscoverMultiSearchWindow(MultiSearchWindow):
    """Multi search window with the Trakt filters button, searching again when the Trakt filters change."""

    @cached_property
    def controls(self):
        return {**super().controls, TRAKT_FILTERS_ID: TraktFiltersButton()}

    @cached_property
    def trakt_path_watcher(self):
        return TraktDiscoverPathWatcher(self)

    def onInit(self):
        super().onInit()
        if not self.trakt_path_watcher.thread.is_alive():
            self.trakt_path_watcher.start()

    @cached_property
    def trakt_discover_position(self):
        return self.get_trakt_discover_position()

    def get_trakt_discover_position(self):
        return next(
            position
            for position, source in enumerate(self.search.sources.items)
            if isinstance(source, TraktDiscoverSource)
        )

    def select_trakt_discover(self):
        """Search only Trakt Discover, as the other sources would mix their own results into its list."""
        self.search.sources.set_enabled_positions([self.trakt_discover_position])
        with self.lock:
            self.refresh_view()
            self.controls[SOURCES_ID].set_properties(self)
        self.research()

    def stop(self):
        self.trakt_path_watcher.stop()
        super().stop()
