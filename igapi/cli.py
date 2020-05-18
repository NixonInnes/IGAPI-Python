from __future__ import unicode_literals

import os
import logging
import time
from prompt_toolkit import Application
from prompt_toolkit.layout.containers import VSplit, HSplit, Window
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import SearchToolbar, TextArea
from prompt_toolkit.document import Document
from threading import Thread, Event, get_ident

from .client import IGClient

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

class RepeatTimer(Thread):
    def __init__(self, func, interval=5):
        Thread.__init__(self)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.debug(f'{get_ident()}: Created')
        self.interval = interval
        self.func = func

    def run(self):
        self.logger.debug(f'{get_ident()}: Running...')
        while not stop_threads.wait(self.interval):
            self.logger.debug(f'{get_ident()}: Updating...')
            self.func()


class IGCLI:
    kb = KeyBindings()
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.authd = False
        self.__api_key = os.getenv('IG_API_KEY')
        self._id = os.getenv('IG_ID')
        self.__password = os.getenv('IG_PWD')
        self._stop_update = Event()
        if self.__api_key and self._id and self.__password:
            self.client = IGClient(self.__api_key, self._id, self.__password)
            self.authd = True
            self.update_thread = RepeatTimer(self.update_positions)
        else:
            self.client = None
            self.update_thread = None

        self.style = Style([
            ('output-field', 'bg:#5F9EA0 #F0FFFF'),
            ('input-field', 'bg:#20B2AA #F0FFFF'),
            ('separator', '#000000'),
            ('status-bar', 'bg:#D3D3D3 #2F4F4F')
        ])

        self.lhs_output_field = TextArea(style='class:output-field')

        self.rhs_output_field = TextArea(style='class:output-field')

        self.logging_field = TextArea(height=7, style='class:output-field')

        self.output_container = HSplit([
               VSplit([self.lhs_output_field,
                       Window(width=1, char='|', style='class:separator'),
                       self.rhs_output_field]),
               Window(height=1, char='-', style='class:separator'),
               self.logging_field])

        self.search_field = SearchToolbar()

        self.input_field = TextArea(height=1,
                                    prompt='>>> ',
                                    style='class:input-field',
                                    multiline=False,
                                    wrap_lines=False,
                                    search_field=self.search_field)

        self.input_field.accept_handler = self.parse

        self.status_bar = TextArea(height=1,
                                   style='class:status-bar',
                                   multiline=False,
                                   wrap_lines=False,
                                   text=self.status)

        self.container = HSplit([self.output_container,
                                Window(height=1, char='-', style='class:separator'),
                                self.input_field,
                                self.search_field,
                                self.status_bar])

        self.app = Application(Layout(self.container,
                                      focused_element=self.input_field),
                               style=self.style,
                               full_screen=True,
                               mouse_support=True,
                               key_bindings=self.kb)


    @property
    def status(self):
        s = 'Status | '
        if not self.authd:
            s += 'Offline |'
        else:
            s += f'Online | ID: {self._id}'
        return s


    def parse(self, buf):
        self.logger.debug(f'Input: {buf.text}')
        args = buf.text.split()
        if args:
            if args[0] == 'api':
                self.set_api(args[1:])
                self.append_logging('Added api key')
            elif args[0] == 'config':
                self.config()
            elif args[0] == 'update':
                self.update_positions()
            else:
                if args[0] in self.client.cli_hooks:
                    self.append_logging(str(getattr(self.client, args[0])()))
                else:
                    self.append_logging('Unrecognised command: ' + buf.text)


    def append_logging(self, text):
        new_text = self.logging_field.text + f'\n{text}'
        self.logging_field.buffer.document = \
            Document(text=new_text, cursor_position=len(new_text))


    def set_api(self, api_key):
        self.__api_key = api_key

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
                   '|| <{profitloss_colour}>{updown:3} {profitloss:.2f}</{profitloss_colour}>'
            line = line.format(dir_colour='up' if pos['position']['direction'] == 'BUY' else 'down',
                               direction=pos['position']['direction'],
                               name=pos['market']['instrumentName'],
                               size=pos['position']['size'],
                               currency=pos['position']['currency'],
                               level=pos['position']['level'],
                               profitloss_colour='up' if pos['profitloss'] > 0 else 'down',
                               profitloss=pos['profitloss'],
                               updown='^^^' if pos['profitloss'] > 0 else 'vvv')
            #line = to_formatted_text(line, Style.from_dict({'up': '#32CD32',
            #                                                'down': '#FF4500' }))
            buf += line
            if i+1 != len(positions): #not last
                buf += '\n'

        self.rhs_output_field.buffer.document = \
            Document(text=buf)


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
        if self.authd:
            self.update_thread.start()
        self.app.run()


    def __del__(self):
        self._stop_update.set()
