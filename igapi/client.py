import os
import json
import logging
import requests as req
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Union

from .exceptions import status_code_exceptions


def check_auth(func: Callable) -> Callable:
    def wrapper(self, *args: List, **kwargs: Dict) -> Any:
        if not self.authd:
            self.login()
        return func(self, *args, **kwargs)
    return wrapper


class IGClient:
    STRF: str = "%Y-%m-%d %H:%M:%S"

    def __init__(self, api_key: str, demo: bool = False) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.__api_key = api_key
        self._id = None
        self.__security_token = None
        self.__cst = None
        if demo:
            self.base_url = 'https://demo-api.ig.com/gateway/deal'
        else:
            self.base_url = 'https://api.ig.com/gateway/deal'

    @property
    def authd(self) -> bool:
        if self.__security_token is not None and self.__cst is not None:
            return True
        return False

    def _get(self, method: Callable, endpoint: str,
             params: Dict[str, str] = {},
             version: int = 2) -> dict:
        assert method in ('get',)
        self.logger.debug(f'{method.upper()}: {self.base_url+endpoint}')
        headers = self.get_headers()
        headers['VERSION'] = str(version)
        r = getattr(req, method)(self.base_url+endpoint,
                                 params=params,
                                 headers=headers)
        if r.ok:
            return r.json()
        try:
            msg = r.json()["errorCode"]
            E = status_code_exceptions.get(r.status_code, Exception)
            raise E(f'Error {r.status_code}: {msg}')
        except json.JSONDecodeError:
            raise Exception(f'Error {r.status_code}: {r.content.decode()}')

    def _post(self, method: Callable, endpoint: str,
              params: dict = {}, data: dict = {},
              version: int = 2,
              extra_headers: dict = {}) -> dict:
        assert method in ('post', 'put', 'delete')
        self.logger.debug(f'{method.upper()}: {self.base_url+endpoint}')
        headers = self.get_headers()
        headers['VERSION'] = str(version)
        headers = {**headers, **extra_headers}
        data = json.dumps(data)
        # weird json format fix
        data = data.replace(': true', ': "true"').replace(': false',
                                                          ': "false"')
        r = getattr(req, method)(self.base_url+endpoint,
                                 params=params,
                                 data=data,
                                 headers=headers)
        if r.ok:
            return r.json()
        return r
        try:
            msg = r.json()["errorCode"]
            E = status_code_exceptions.get(r.status_code, Exception)
            raise E(f'Error {r.status_code}: {msg}')
        except json.JSONDecodeError:
            raise Exception(f'Error {r.status_code}: {r.content.decode()}')

    def get(self, endpoint: str,
            params: dict = {},
            version: int = 2) -> dict:
        return self._get('get', endpoint, params=params, version=version)

    def delete(self, endpoint: str,
               params: dict = {},
               data: dict = {},
               version: int = 2) -> dict:
        return self._post('delete', endpoint, params=params, data=data, version=version, extra_headers={'_method': 'DELETE'})

    def post(self, endpoint: str,
             params: dict = {},
             data: dict = {},
             version: int = 2,
             extra_headers: dict = {}) -> dict:
        return self._post('post', endpoint, params=params, data=data, version=version, extra_headers=extra_headers)

    def put(self, endpoint: str,
            params: dict = {},
            data: dict = {},
            version: int = 2) -> dict:
        return self._post('put', endpoint, params=params, data=data)

    def get_headers(self, version: int = 2, **kwargs) -> Dict[str, str]:
        headers = {
            'User-Agent': 'IGAPIv2-Python (alpha)',
            'Content-Type': 'application/json; charset=UTF-8 ',
            'Accept': 'application/json; charset=UTF-8 ',
            'VERSION': str(version),
            'X-IG-API-KEY': self.__api_key
        }
        headers = {**headers, **kwargs}
        if self.__security_token and self.__cst:
            headers['X-SECURITY-TOKEN'] = self.__security_token
            headers['CST'] = self.__cst
        return headers

    def login(self, identifier: str, password: str) -> bool:
        data = json.dumps({'identifier': identifier, 'password': password})
        r = req.post(self.base_url+'/session',
                     headers=self.get_headers(version=2),
                     data=data)
        if r.ok:
            self.__security_token = r.headers['X-SECURITY-TOKEN']
            self.__cst = r.headers['CST']
            self._id = identifier
            return True
        return False

    def get_accounts(self) -> dict:
        return self.get('/accounts', version=1)

    @check_auth
    def get_positions(self) -> dict:
        return self.get('/positions')

    def get_positions_profitloss(self) -> dict:
        positions = self.get_positions()['positions']
        for position in positions:
            if position['market']['marketStatus'] == 'CLOSED':
                position['profitloss'] = '-'
            else:
                if position['position']['direction'] == 'BUY':
                    position['profitloss'] = position['market']['bid'] -\
                            position['position']['level']
                elif position['position']['direction'] == 'SELL':
                    position['profitloss'] = position['position']['level'] -\
                        position['market']['offer']
        return positions

    @check_auth
    def get_position(self, deal_id: str) -> dict:
        return self.get(f'/positions/{deal_id}')

    @check_auth
    def add_position(self,
                     direction: str,  # BUY/SELL
                     order_type: str,  # LIMIT/MARGIN
                     epic: str,
                     size: float,
                     currency_code: str,
                     level: Union[float, None] = None,
                     expiry: Union[datetime, None] = None,
                     deal_reference: Union[str, None] = None,
                     force_open: bool = True,
                     guaranteed_stop: bool = False,
                     limit_distance: Union[float, None] = None,
                     limit_level=None,
                     stop_distance=None,
                     stop_level=None,
                     trailing_stop=None,
                     trailing_stop_increment=None,
                     time_in_force='FILL_OR_KILL',
                     quote_id=None) -> dict:
        data = {"epic": epic,
                "expiry": expiry if expiry else '-',
                "direction": direction,
                "size": size,
                "orderType": order_type,
                "timeInForce": time_in_force,
                "level": level,
                "guaranteedStop": guaranteed_stop,
                "stopLevel": stop_level,
                "stopDistance": stop_distance,
                "trailingStop": trailing_stop,
                "trailingStopIncrement": trailing_stop_increment,
                "forceOpen": force_open,
                "limitLevel": limit_level,
                "limitDistance": limit_distance,
                "quoteId": quote_id,
                "currencyCode": currency_code}
        return self.post('/positions/otc', data=data)

    @check_auth
    def close_position(self, position_id, direction, size):
        data = {"dealId": position_id,
                "epic": None,
                "expiry": None,
                "direction": direction,
                "size": str(size),
                "level": None,
                "orderType": "MARKET",
                "timeInForce": None,
                "quoteId": None}
        return self.post('/positions/otc', data=data, version=1, extra_headers={'_method': 'DELETE'})

    @check_auth
    def get_activity(self) -> dict:
        return self.get('/history/activity')

    @check_auth
    def get_last_activity(self) -> dict:
        return self.get_activity()['activities'][0]

    @check_auth
    def get_transactions(self) -> dict:
        return self.get('/history/transactions')

    @check_auth
    def get_working_orders(self) -> dict:
        return self.get('/workingorders')

    @check_auth
    def add_working_order(self, direction, order_type, epic, size,
                          currency_code, level,
                          expiry='-', deal_reference=None,
                          force_open=True, guaranteed_stop=False,
                          limit_distance=None, limit_level=None,
                          stop_distance=None, stop_level=None,
                          time_in_force='GOOD_TILL_CANCELLED',
                          good_till_date=None,) -> dict:
        data = {"epic": epic,
                "expiry": expiry,
                "direction": direction,
                "size": size,
                "level": level,
                "forceOpen": force_open,
                "type": order_type,
                "currencyCode": currency_code,
                "timeInForce": time_in_force,
                "goodTillDate": good_till_date,
                "guaranteedStop": guaranteed_stop,
                "stopLevel": stop_level,
                "stopDistance": stop_distance,
                "limitLevel": limit_level,
                "limitDistance": limit_distance}
        return self.post('/workingorders/otc', data=data)

    @check_auth
    def edit_working_order(self, deal_id, order_type, order_level,
                           limit_distance=None, limit_level=None,
                           stop_distance=None, stop_level=None,
                           time_in_force='GOOD_TILL_CANCELLED',
                           good_till_date=None) -> dict:
        data = {"timeInForce": time_in_force,
                "goodTillDate": good_till_date,
                "stopLevel": stop_level,
                "stopDistance": stop_distance,
                "limitLevel": limit_level,
                "limitDistance": limit_distance,
                "type": order_type,
                "level": order_level}
        return self.put(f'/workingorders/otc/{deal_id}', data=data)

    @check_auth
    def delete_working_order(self, deal_id: str) -> dict:
        return self.delete(f'/workingorders/otc/{deal_id}')

    @check_auth
    def get_markets(self, *args: List[str]) -> dict:
        return self.get('/markets', params={'epics': ','.join(args)})

    @check_auth
    def get_market(self, epic: str) -> dict:
        return self.get(f'/markets/{epic}')

    @check_auth
    def search_market(self, term: str) -> dict:
        return self.get('/markets', params={'searchTerm': term}, version=1)

    @check_auth
    def get_prices(self, epic: str,
                   resolution: str = 'DAY',
                   num_points: int = 100) -> dict:
        return self.get(f'/prices/{epic}/{resolution}/{num_points}')

    @check_auth
    def get_prices_date(self, epic: str,
                        resolution: str = 'DAY',
                        start_date: datetime = None,
                        end_date: datetime = None) -> dict:
        now = datetime.utcnow()
        if not start_date:
            start_date = (now - timedelta(days=7)).strftime(self.STRF)
        if not end_date:
            end_date = now.strftime(self.STRF)

        if isinstance(start_date, datetime):
            start_date = start_date.strftime(self.STRF)
        if isinstance(end_date, datetime):
            end_date = end_date.strftime(self.STRF)
        return self.get(f'/prices/{epic}/{resolution}/{start_date}/{end_date}')

    @check_auth
    def get_client_sentiment(self, *args: List[str]) -> dict:
        params = {'marketIds': ",".join(args)}
        return self.get('/clientsentiment/', params=params)

    @check_auth
    def get_client_sentiment_related(self, market_id: str) -> dict:
        return self.get(f'/clientsentiment/related/{market_id}')

    @check_auth
    def get_application(self) -> dict:
        return self.get('/operations/application', version=1)
