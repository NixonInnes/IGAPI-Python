import json
import logging
import requests as req
from datetime import datetime, timedelta

from .exceptions import status_code_exceptions


def check_auth(func):
    def wrapper(self, *args, **kwargs):
        if not self.authd:
            self.login()
        return func(self, *args, **kwargs)
    return wrapper


class IGClient:
    STRF = "%Y-%m-%d %H:%M:%S"
    cli_hooks = ['authd', 'get_positions']
    def __init__(self, api_key: str, identifier: str, password: str) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.__api_key = api_key
        self._identifier = identifier
        self.__password = password
        self.__security_token = None
        self.__cst = None

        self.base_url = 'https://demo-api.ig.com/gateway/deal'

    @property
    def authd(self):
        if not self.__security_token is None and not self.__cst is None:
            return True
        return False

    def _get(self, endpoint, params={}):
        self.logger.debug(f'GET: {self.base_url+endpoint}')
        r = req.get(self.base_url+endpoint,
                    params=params,
                    headers=self.get_headers())
        if r.ok:
            return r.json()
        try:
            msg = r.json()["errorCode"]
            E = status_code_exceptions.get(r.status_code, Exception)
            raise E(f'Error {r.status_code}: {msg}')
        except json.JSONDecodeError:
            raise Exception(f'Error {r.status_code}: {r.content.decode()}')


    def get_headers(self):
        headers = {
            'User-Agent': 'IGAPIv2-Python (alpha)',
            'Content-Type': 'application/json; charset=UTF-8 ',
            'Accept': 'application/json; charset=UTF-8 ',
            'VERSION': '2',
            'X-IG-API-KEY': self.__api_key
        }
        if self.__security_token and self.__cst:
            headers['X-SECURITY-TOKEN'] = self.__security_token
            headers['CST'] = self.__cst
        return headers

    def login(self):
        data = json.dumps({'identifier':self._identifier, 'password':self.__password})
        r = req.post(self.base_url+'/session', headers=self.get_headers(), data=data)
        if r.ok:
            self.__security_token = r.headers['X-SECURITY-TOKEN']
            self.__cst = r.headers['CST']

    @check_auth
    def get_positions(self):
        return self._get('/positions')

    def get_positions_profitloss(self):
        positions = self.get_positions()['positions']
        for position in positions:
            if position['position']['direction'] == 'BUY':
                position['profitloss'] = position['market']['bid'] - position['position']['level']
            elif position['position']['direction'] == 'SELL':
                position['profitloss'] = position['position']['level'] - position['market']['offer']
        return positions

    @check_auth
    def get_position(self, deal_id):
        return self._get(f'/positions/{deal_id}')

    @check_auth
    def get_activity(self):
        return self._get('/history/activity')

    @check_auth
    def get_transactions(self):
        return self._get('/history/transactions')

    @check_auth
    def get_working_orders(self):
        return self._get('/workingorders')

    @check_auth
    def get_markets(self, *args):
        return self._get('/markets', params={'epics':','.join(args)})

    @check_auth
    def get_market(self, epic):
        return self._get(f'/markets/{epic}')

    @check_auth
    def get_prices(self, epic, resolution='DAY', num_points=100):
        return self._get(f'/prices/{epic}/{resolution}/{num_points}')

    @check_auth
    def get_prices_date(self, epic, resolution='DAY', start_date=None, end_date=None):
        now = datetime.utcnow()
        if not start_date:
            start_date = (now - timedelta(days=7)).strftime(self.STRF)
        if not end_date:
            end_date = now.strftime(self.STRF)
        return self._get(f'/prices/{epic}/{resolution}/{start_date}/{end_date}')
