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
            #self.logger.debug(f'{get_ident()}: Updating...')
            self.func()


class IGCLI:
    kb = KeyBindings()
    strf_string = '%a %d %b %Y | %H:%M:%S'
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.config_file = os.getenv('IG_CLI_CONFIG', 'config.yml')
        self.config = {}
        self._id = None
        self.authd = False
        self._stop_update = Event()
        self.client = None
        self.positions_thread = None
        self.orders_thread = None
        self.trackers_thread = None
        self.status_thread = RepeatTimer(self.update_status, 1)

        self.style = Style([
            ('output-field', 'bg:#5F9EA0 #F0FFFF'),
            ('input-field', 'bg:#20B2AA #F0FFFF'),
            ('separator', '#000000'),
            ('status-bar', 'bg:#D3D3D3 #2F4F4F')
        ])

        self.trackers_field = TextArea(style='class:output-field')
        self.positions_field = TextArea(style='class:output-field')
        self.orders_field = TextArea(style='class:output-field')
        self.msg_field = TextArea(height=7, style='class:output-field')

        self.output_container = HSplit([
               VSplit([self.positions_field,
                       Window(width=1, char='|', style='class:separator'),
                       HSplit([self.trackers_field,
                              Window(height=1, char='-', style='class:separator'),
                              self.orders_field])
                       ]),
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
        self.status_thread.start()

    def get_time(self):
        return datetime.utcnow().strftime(self.strf_string)

    @req_auth
    def load_config(self, filename='config.yml'):
        self.msg_out(f'Loading {self._id} configuration...')
        with open(filename) as f:
            loaded = yaml.safe_load(f)
        if loaded:
            self.config = loaded.get(self._id, {})
        else:
            self.config = {}
        # Set some defaults
        if 'refresh' not in self.config:
            self.config['refresh'] = DEFAULT_REFRESH
        if 'tracked' not in self.config:
            self.config['tracked'] = []
        self.msg_out(f'... Refresh rate {self.refresh} s\n'
                     f'... Added {len(self.tracked)} trackers')

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
            self.set_api(api_key)
            self.login(api_key, identifier, password)

    def set_api(self, api_key):
        self.client = IGClient(api_key=api_key)

    def login(self, identifier, password):
        successful = self.client.login(identifier, password)
        if successful:
            self.authd = True
            self._id = identifier
            self.load_config()
            self.start_threads()
            return True
        return False

    @req_auth
    def logout(self):
        self.__api_key = None
        self._id = None
        self.__password = None
        self.config = {}
        self.stop_treads()

    @req_auth
    def start_threads(self):
        if self.positions_thread and self.trackers_thread:
            self.logger.error('Threads already running!')
            return

        # Reset stop _threads if needed
        global stop_threads
        if stop_threads is None:
            stop_threads = Event()

        self.positions_thread = RepeatTimer(self.update_positions,
                                            self.refresh)
        self.orders_thread = RepeatTimer(self.update_orders,
                                            self.refresh)
        self.trackers_thread = RepeatTimer(self.update_trackers,
                                           self.refresh)

        self.positions_thread.start()
        self.orders_thread.start()
        self.trackers_thread.start()

    @req_auth
    def stop_threads(self):
        global stop_threads
        stop_threads.set()
        self.positions_thread = None
        self.orders_thread = None
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
        if not loaded:
            loaded = {}
        loaded[self._id] = self.config
        with open(self.config_file, 'w') as f:
            yaml.dump(loaded, f)

    @req_auth
    def add_tracker(self, tracker):
        self.config['tracked'].append(tracker)

    @req_auth
    def del_tracker(self, tracker):
        if tracker in self.config['tracked']:
            self.config['tracked'].remove(tracker)

    def parse(self, buf):
        self.logger.debug(f'Input: {buf.text}')
        args = buf.text.split()
        try:
            command = getattr(self, f'_cmd__{args[0]}')
        except AttributeError:
            self.msg_out(f'Unrecognised command: {args[0]}')
        finally:
            command(*args[1:])

    def msg_out(self, text):
        new_text = self.msg_field.text + f'\n{text}'
        self.msg_field.buffer.document = \
            Document(text=new_text, cursor_position=len(new_text))


    # cant figure out how to colour text for the Document
    @req_auth
    def update_positions(self):
        self.logger.debug('Updating positions...')
        positions = self.client.get_positions_profitloss()
        buf = f"{' POSITIONS ':-^60}\n"
        for i, pos in enumerate(positions):
            line = '{direction:4} {name:15} {size:>5.2f} {currency:3} @ {level:>10.2f} ' +\
                   '|| {profitloss:>10.2f}'
            line = line.format(direction=pos['position']['direction'],
                               name=pos['market']['instrumentName'],
                               size=pos['position']['size'],
                               currency=pos['position']['currency'],
                               level=pos['position']['level'],
                               profitloss=pos['profitloss'])
            buf += line
            if i+1 != len(positions): #not last
                buf += '\n'
        self.positions_field.buffer.document = Document(text=buf)

    @req_auth
    def update_orders(self):
        self.logger.debug('Updating orders...')
        orders = self.client.get_working_orders()['workingOrders']
        buf = f"{' ORDERS ':-^60}\n"
        for i, order in enumerate(orders):
            line = '{direction:4} {name:15} {size:>5.2f} {currency:3} @ {level:>10.2f} '
            line = line.format(direction=order['workingOrderData']['direction'],
                               name=order['marketData']['instrumentName'],
                               size=order['workingOrderData']['orderSize'],
                               currency=order['workingOrderData']['currencyCode'],
                               level=order['workingOrderData']['orderLevel'])
            buf += line
            if i+1 != len(orders): #not last
                buf += '\n'
        self.orders_field.buffer.document = Document(text=buf)

    @req_auth
    def update_trackers(self):
        self.logger.debug('Updating trackers...')
        markets = self.client.get_markets(*self.tracked)['marketDetails']
        buf = f"{' TRACKERS ':-^60}\n"
        for i, market in enumerate(markets):
            line = '{name:15} || {low:>9.2f} | {high:>9.2f} || {bid:>9.2f} | {offer:>9.2f}'
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


    ## User Commands
    # all user commands should start with '_cmd__', and accept *args
    @req_auth
    def _cmd__update(self, *args):
        self.update_positions()
        self.update_orders()
        self.update_trackers()
        self.msg_out('Updated positions, orders and trackers')

    def _cmd__api(self, *args):
        if len(args) != 1:
            self.msg_out('Invalid syntax, expected: api <key>')
            return
        self.set_api(args[0])
        self.msg_out('Updated API key')

    def _cmd__login(self, *args):
        if len(args) != 2:
            self.msg_out('Invalid syntax, expected: login: <username> <password>')
            return
        username, password = args
        successful = self.login(username, password)
        if successful:
            self.msg_out('Login successful')
        else:
            self.msg_out('Login failed')

    def _cmd__save(self, *args):
        self.write_config()
        self.msg_out('Configuration saved')

    def _cmd__track(self, *args):
        for arg in args:
            self.add_tracker(arg)
        self.msg_out('Added tracked market(s)')

    def _cmd__stoptrack(self, *args):
        for arg in args:
            self.del_tracker(arg)
        self.msg_out('Removed tracked market(s)')

    def _cmd__search(self, *args):
        markets = self.client.search_market(args[0])['markets']
        s = 'Found epics: '
        s += ', '.join([f'{market["instrumentName"]}: {market["epic"]}'\
                        for market in markets])
        self.msg_out(s)



