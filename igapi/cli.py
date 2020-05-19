from __future__ import unicode_literals

import os
import logging
import time
import yaml
from datetime import datetime
from prompt_toolkit import Application
from prompt_toolkit.layout.containers import VSplit, HSplit, Window
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import SearchToolbar, TextArea
from prompt_toolkit.document import Document
from threading import Thread, Event, get_ident

from .client import IGClient
from .utils import req_auth

# Fix for Windows ##################
import asyncio
import selectors
selector = selectors.SelectSelector()
loop = asyncio.SelectorEventLoop(selector)
asyncio.set_event_loop(loop)
####################################

logging.basicConfig(filename='log.txt',
                    level=logging.DEBUG,
                    format='%(asctime)s %(name)s:%(levelname)s:%(message)s')

stop_threads = Event()

DEFAULT_REFRESH = 5


class RepeatTimer(Thread):
    """Timer thread to run every 'interval' seconds.

    args:
    func -- function to call each loop

    kwargs:
    interval -- (default: 5) time between each function call (in seconds)
    """
    def __init__(self, func, interval=5):
        Thread.__init__(self)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.debug(f'{get_ident()}: Created')
        self.interval = int(interval)
        self.func = func

    def run(self):
        self.logger.debug(f'{get_ident()}: Running...')
        while not stop_threads.wait(self.interval):
            self.logger.debug(f'{get_ident()}: Updating...')
            self.func()


class IGCLI:
    kb = KeyBindings()
    strf_string = '%a %d %b %Y - %H:%M:%S'
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.config_file = os.getenv('IG_CLI_CONFIG', 'config.yml')
        self.config = {}
        self.__api_key = os.getenv('IG_API_KEY')
        self._id = os.getenv('IG_ID')
        self.__password = os.getenv('IG_PWD')
        self._stop_update = Event()
        self.client = None
        self.positions_thread = None
        self.trackers_thread = None
        self.status_thread = None

        self.style = Style([
            ('output-field', 'bg:#5F9EA0 #F0FFFF'),
            ('input-field', 'bg:#20B2AA #F0FFFF'),
            ('separator', '#000000'),
            ('status-bar', 'bg:#D3D3D3 #2F4F4F')
        ])

        self.trackers_field = TextArea(style='class:output-field')
        self.positions_field = TextArea(style='class:output-field')
        self.msg_field = TextArea(height=7, style='class:output-field')

        self.output_container = HSplit([
               VSplit([self.trackers_field,
                       Window(width=1, char='|', style='class:separator'),
                       self.positions_field]),
               Window(height=1, char='-', style='class:separator'),
               self.msg_field])

        self.search_field = SearchToolbar()
        self.input_field = TextArea(height=1,
                                    prompt='>>> ',
                                    style='class:input-field',
                                    multiline=False,
                                    wrap_lines=False,
                                    search_field=self.search_field)

        self.input_field.accept_handler = self.parse

        self.status_field = TextArea(height=1,
                                   style='class:status-bar',
                                   multiline=False,
                                   wrap_lines=False,
                                   text=self.status)
        self.time_field = TextArea(height=1,
                                   style='class:status-bar',
                                   multiline=False,
                                   wrap_lines=False,
                                   text=self.get_time())

        self.container = HSplit([self.output_container,
                                Window(height=1, char='-', style='class:separator'),
                                self.input_field,
                                self.search_field,
                                self.status_field])

        self.app = Application(Layout(self.container,
                                      focused_element=self.input_field),
                               style=self.style,
                               full_screen=True,
                               mouse_support=True,
                               key_bindings=self.kb)
        self.autologin()

    def get_time(self):
        return datetime.utcnow().strftime(self.strf_string)

    @req_auth
    def load_config(self, filename='config.yml'):
        self.msg_out(f'Loading {self._id} configuration...')
        with open(filename) as f:
            loaded = yaml.safe_load(f)
        self.config = loaded.get(self._id, {})
        # Set some defaults
        if 'refresh' not in self.config:
            self.config['refresh'] = DEFAULT_REFRESH
        if 'tracked' not in self.config:
            self.config['tracked'] = []
        self.msg_out(f'... Refresh rate {self.refresh} s\n'
                     f'... Added {len(self.tracked)} trackers')

    @property
    def authd(self):
        if self.__api_key and self._id and self.__password:
            return True
        return False

    @property
    def refresh(self):
        return self.config.get('refresh')

    @property
    def tracked(self):
        return self.config.get('tracked')

    @property
    def status(self):
        s = self.get_time()
        s += ' || Status | '
        if not self.authd:
            s += 'Offline |'
        else:
            s += f'Online | ID: {self._id} '

        return s

    def update_status(self):
        self.status_field.buffer.document = Document(text=self.status)


    def autologin(self):
        api_key = os.getenv('IG_API_KEY')
        identifier = os.getenv('IG_ID')
        password = os.getenv('IG_PWD')
        if api_key and identifier and password:
            self.login(api_key, identifier, password)

    def login(self, api_key, identifier, password):
        self.__api_key = api_key
        self._id = identifier
        self.__password = password
        self.load_config()
        self.start_client()
        self.start_threads()

    @req_auth
    def logout(self):
        self.__api_key = None
        self._id = None
        self.__password = None
        self.config = {}
        self.stop_treads()

    @req_auth
    def start_client(self):
        global stop_threads
        if stop_threads is None:
            stop_threads = Event()
        self.client = IGClient(self.__api_key, self._id, self.__password)

    @req_auth
    def start_threads(self):
        if self.positions_thread and self.trackers_thread:
            self.logger.error('Threads already exist!')
            return

        # Reset stop _threads if needed
        global stop_threads
        if stop_threads is None:
            stop_threads = Event()

        self.positions_thread = RepeatTimer(self.update_positions,
                                            self.refresh)
        self.trackers_thread = RepeatTimer(self.update_trackers,
                                           self.refresh)
        self.status_thread = RepeatTimer(self.update_status,
                                         1)

        self.positions_thread.start()
        self.trackers_thread.start()
        self.status_thread.start()

    @req_auth
    def stop_threads(self):
        global stop_threads
        stop_threads.set()
        self.positions_thread = None
        self.trackers_thread = None
        stop_threads = None

    @req_auth
    def restart_threads(self):
        self.stop_threads()
        self.start_threads()

    @req_auth
    def write_config(self):
        with open(self.config_file, 'r') as f:
            loaded = yaml.safe_load(f)
        loaded[self._id] = self.config
        with open(self.config_file, 'w') as f:
            yaml.dumps(loaded, f)

    def parse(self, buf):
        self.logger.debug(f'Input: {buf.text}')
        args = buf.text.split()
        if args:
            if args[0] == 'api':
                self.set_api(args[1:])
                self.output('Added api key')
            elif args[0] == 'config':
                self.config()
            elif args[0] == 'update':
                self.update_positions()
                self.update_trackers()
            else:
                if args[0] in self.client.cli_hooks:
                    self.msg_out(str(getattr(self.client, args[0])()))
                else:
                    self.msg_out('Unrecognised command: ' + buf.text)

    def msg_out(self, text):
        new_text = self.msg_field.text + f'\n{text}'
        self.msg_field.buffer.document = \
            Document(text=new_text, cursor_position=len(new_text))

    # this doesn't work, need to figure out how to pop-up dialogs
    # with Application
    def config(self):
        api = Dialog(title='API',
                     body='Please enter your API key:')

    # cant figure out how to colour text for the Document
    def update_positions(self):
        self.logger.debug('Updating positions...')
        positions = self.client.get_positions_profitloss()
        buf = ''
        for i, pos in enumerate(positions):
            line = '<{dir_colour}>{direction:4}</{dir_colour}> ' +\
                   '{name:15} {size:3} {currency:3} @ {level:6} ' +\
                   '|| <{profitloss_colour}>{profitloss:10.2f}</{profitloss_colour}>'
            line = line.format(#dir_colour='up' if pos['position']['direction'] == 'BUY' else 'down',
                               dir_colour='',
                               direction=pos['position']['direction'],
                               name=pos['market']['instrumentName'],
                               size=pos['position']['size'],
                               currency=pos['position']['currency'],
                               level=pos['position']['level'],
                               #profitloss_colour='up' if pos['profitloss'] > 0 else 'down',
                               profitloss_colour='',
                               profitloss=pos['profitloss'])
            #line = to_formatted_text(line, Style.from_dict({'up': '#32CD32',
            #                                                'down': '#FF4500' }))
            buf += line
            if i+1 != len(positions): #not last
                buf += '\n'
        self.positions_field.buffer.document = Document(text=buf)

    @req_auth
    def update_trackers(self):
        self.logger.debug('Updating trackers...')
        markets = self.client.get_markets(*self.tracked)['marketDetails']
        buf = ''
        for i, market in enumerate(markets):
            line = '{name:15} || {low:6} | {high:6} || {bid:>6} | {offer:6}'
            line = line.format(name=market['instrument']['name'],
                               low=market['snapshot']['low'],
                               high=market['snapshot']['high'],
                               bid=market['snapshot']['bid'],
                               offer=market['snapshot']['offer'])
            buf += line
            if i+1 != len(self.config['tracked']):
                buf += '\n'
        self.trackers_field.buffer.document = Document(text=buf)

    # This does some super weird shit. The decorator calls this
    # without passing self. I'm too dumb to figure out where/how this
    # happens to monkey-patch (I think a flag on self would be better)
    # Thus, the global stop_threads.

    @kb.add('c-q')
    @kb.add('c-c')
    def exit_ctrl_q(event):
        global stop_threads
        stop_threads.set()
        event.app.exit()

    def __call__(self):
        self.logger.info('Starting CLI...')
        self.app.run()

    def __del__(self):
        self.stop_threads()
