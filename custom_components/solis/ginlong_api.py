"""
Access to the Ginlong platform 2.0 API for PV monitoring.
Works for all Ginlong brands using the Ginlong Platform 2.0 portal API
Solis, Solarman, Sofar Solar and possibly MyEvolveCloud

For more information: https://github.com/hultenvp/solis-sensor/
"""
from __future__ import annotations

import asyncio
from http import HTTPStatus
import logging
from typing import Any
from aiohttp import ClientError, ClientSession
import async_timeout


from .ginlong_const import *

_LOGGER = logging.getLogger(__name__)

# VERSION
VERSION = '0.1.3'

# Response constants
SUCCESS = 'Success'
CONTENT = 'Content'
STATUS_CODE = 'StatusCode'
MESSAGE = 'Message'

VALUE_RECORD = '_from_record'
VALUE_ELEMENT = ''

#InverterDataType = dict[str, list[str | dict[str, list[str | type| int | None]]]]
InverterDataType = dict[str, list[Any]]

"""{payload subset key: [payload type, {key type, decimal precision}]}"""
INVERTER_DATA: InverterDataType = {
    'none': [
        VALUE_ELEMENT, {
            INVERTER_SERIAL:             ['sn', str, None],
            INVERTER_PLANT_ID:           ['plantId', str, None],
            INVERTER_LAT:                ['lat', float, 7],
            INVERTER_LON:                ['lon', float, 7],
            INVERTER_ADDRESS:            ['address', str, None],
            INVERTER_DEVICE_ID:          ['deviceId', str, None],
            INVERTER_DATALOGGER_SERIAL:  ['dataloggerSn', str, None],
            # Timestamp coming online?
            INVERTER_TIMESTAMP_ONLINE:   ['receiveTimestamps', int, None],
            # Timestamp of measurement
            INVERTER_TIMESTAMP_UPDATE:   ['updateDate', int, None],
            INVERTER_STATE:              ['state', int, None],
        }
    ],
    'realTimeDataImp': [
        VALUE_RECORD, {
            INVERTER_TEMPERATURE:       ['1df', float, 1],
        }
    ],
    'realTimeDataOther': [
        VALUE_RECORD, {
            INVERTER_POWER_LIMIT:       ['1rv', float, 2],
        }
    ],
    'realTimeDataState': [
        VALUE_RECORD, {
            INVERTER_POWER_STATE:       ['1fd', int, None],
        }
    ],
    'realTimeDataPower': [
        VALUE_RECORD, {
            INVERTER_ACPOWER:           ['1ao', float, 2],
            INVERTER_ACFREQUENCY:       ['1ar', float, 2],
            INVERTER_ENERGY_LAST_MONTH: ['1ru', float, 2],
            INVERTER_ENERGY_TODAY:      ['1bd', float, 2],
            INVERTER_ENERGY_THIS_MONTH: ['1be', float, 2],
            INVERTER_ENERGY_THIS_YEAR:  ['1bf', float, 2],
            INVERTER_ENERGY_TOTAL_LIFE: ['1bc', float, 2],
            STRING1_VOLTAGE: ['1a', float, 2],
            STRING2_VOLTAGE: ['1b', float, 2],
            STRING3_VOLTAGE: ['1c', float, 2],
            STRING4_VOLTAGE: ['1d', float, 2],
            STRING1_CURRENT: ['1j', float, 2],
            STRING2_CURRENT: ['1k', float, 2],
            STRING3_CURRENT: ['1l', float, 2],
            STRING4_CURRENT: ['1m', float, 2],
            STRING1_POWER:   ['1s', float, 2],
            STRING2_POWER:   ['1t', float, 2],
            STRING3_POWER:   ['1u', float, 2],
            STRING4_POWER:   ['1v', float, 2],
            PHASE1_VOLTAGE: ['1af', float, 2],
            PHASE2_VOLTAGE: ['1ag', float, 2],
            PHASE3_VOLTAGE: ['1ah', float, 2],
            PHASE1_CURRENT: ['1ai', float, 2],
            PHASE2_CURRENT: ['1aj', float, 2],
            PHASE3_CURRENT: ['1ak', float, 2],
        }
    ],
    'dataJSON': [
        VALUE_ELEMENT, {
            BAT_REMAINING_CAPACITY:      ['1cv', float, 2],
            BAT_TOTAL_ENERGY_CHARGED:    ['1cx', float, 2],
            BAT_TOTAL_ENERGY_DISCHARGED: ['1cy', float, 2],
            BAT_DAILY_ENERGY_CHARGED:    ['1cz', float, 2],
            BAT_DAILY_ENERGY_DISCHARGED: ['1da', float, 2],
            GRID_DAILY_ON_GRID_ENERGY:    ['1bw', float, 2],
            GRID_DAILY_ENERGY_PURCHASED:  ['1bx', float, 2],
            GRID_DAILY_ENERGY_USED:       ['1co', float, 2],
            GRID_MONTHLY_ENERGY_PURCHASED:['1bz', float, 2],
            GRID_MONTHLY_ENERGY_USED:     ['1cp', float, 2],
            GRID_YEARLY_ENERGY_PURCHASED: ['1cb', float, 2],
            GRID_YEARLY_ENERGY_USED:      ['1cq', float, 2],
            GRID_TOTAL_ON_GRID_ENERGY:    ['1bu', float, 2],
            GRID_TOTAL_CONSUMPTION_ENERGY:['1cn', float, 2],
            GRID_TOTAL_POWER:             ['1bq', float, 2],
            GRID_TOTAL_CONSUMPTION_POWER: ['1cj', float, 2],
            GRID_TOTAL_ENERGY_USED:       ['1bv', float, 2],

        }
    ]
}

class PortalConfig:
    """ Portal configuration data """

    def __init__(self,
        portal_domain: str,
        portal_username: str,
        portal_password: str,
        portal_plantid: int
    ) -> None:
        self._domain: str = portal_domain
        self._username: str = portal_username
        self._password: str = portal_password
        self._plantid: int = portal_plantid

    @property
    def domain(self) -> str:
        """ Configured portal domain name."""
        return self._domain

    @property
    def username(self) -> str:
        """ Configured username."""
        return self._username

    @property
    def password(self) -> str:
        """ Configured password."""
        return self._password

    @property
    def plantid(self) -> int:
        """ Configured plant ID."""
        return self._plantid

class GinlongData():
    """ Representing data measurement for one inverter from Ginlong API """

    def __init__(self, data: dict[str, str | int | float]) -> None:
        """ Initialize the data object """
        self._data = data


    def get_inverter_data(self) -> dict[str, str | int | float]:
        """Return all available measurements in a dict."""
        return self._data

    def keys(self) -> list[str]:
        """Return keys of all measurements in a list, ensure state is first."""
        available_measurements: list[str] = list(self._data.keys())
        # Move state to beginning of list to avoid race conditions for the
        # energy today fix.
        available_measurements.remove(INVERTER_STATE)
        available_measurements.insert(0, INVERTER_STATE)
        return available_measurements

    def __getattr__(self, name):
        """Each measurement is represented as property."""
        try:
            return self._data[name]
        except KeyError as key_error:
            _LOGGER.debug("AttributeError, %s does not exist", name)
            raise AttributeError(name) from key_error

class GinlongAPI():
    """Class with functions for reading data from the Ginlong Portal 2.0."""

    def __init__(self, config: PortalConfig) -> None:
        self._config: PortalConfig = config
        self._session: ClientSession | None = None
        self._data: dict[str, str | int | float] = {}
        self._online: bool = False
        self._inverter_list: dict[str, str] | None = None
        # Default english
        self._language = 2

    @property
    def config(self) -> PortalConfig:
        """ Config this for this API instance."""
        return self._config

    @property
    def is_online(self) -> bool:
        """ Returns if we are logged in."""
        return self._online

    @property
    def inverters(self) -> dict[str, str] | None:
        """ Return the list of inverters for plant ID when logged in."""
        return self._inverter_list

    async def login(self, session: ClientSession) -> bool:
        """Login to the portal."""
        self._session = session
        self._inverter_list = None
        # Building url & params
        url = 'https://'+self._config.domain+'/cpro/login/validateLogin.json'
        params = {
            "userName": self._config.username,
            "password": self._config.password,
            "lan": self._language,
            "domain": self._config.domain,
            "userType": "C"
        }

        # Login call
        result = await self._post_data(url, params)
        if result[SUCCESS] is True:
            result_json = result[CONTENT]
            try:
                if result_json['result'].get('isAccept') == 1:
                    self._online = True
                    _LOGGER.info('Login Successful!')
                    self._inverter_list = await self.fetch_inverter_list(
                        self.config.plantid)
            except KeyError:
                _LOGGER.error(
                    'Unable to login to %s, are username and password correct?',
                    self.config.domain)
                self._online = False
        else:
            self._online = False
        return self._online

    async def logout(self) -> None:
        """ Logout from portal."""
        self._session = None
        self._online = False
        self._inverter_list = None

    async def fetch_inverter_list(self, plant_id: int) -> dict[str, str]:
        """
        Fetch return list of inverters { inverter serial : device_id }
        """

        device_ids = None

        url = 'http://'+self._config.domain+'/cpro/epc/plantDevice/inverterListAjax.json'
        params = {
            'orderBy': 'updateDate',
            'orderType': 2,
            'pageIndex': 1,
            'plantId': int(plant_id),
            'sequenceNum': 9,
            'showAddFlg': 1
        }

        result = await self._get_data(url, params)

        if result[SUCCESS] is True:
            device_ids = {}
            result_json: dict = result[CONTENT]
            for record in result_json['result']['paginationAjax']['data']:
                serial = record.get('sn')
                device_id = record.get('deviceId')
                device_ids[serial] = device_id
        else:
            self._online = False

        return device_ids

    async def fetch_inverter_data(self, inverter_serial: str) -> GinlongData | None:
        """
        Fetch data for given inverter. Backend data is optimized for frontend.
        Collect available data from payload and store as GinlongData object
        """

        _LOGGER.info("Fetching data for serial: %s", inverter_serial)
        self._data = {}
        if self.is_online:
            if self._inverter_list is not None and inverter_serial in self._inverter_list:
                device_id = self._inverter_list[inverter_serial]
                payload = await self._get_inverter_details(device_id)
                if payload is not None:
                    _LOGGER.debug("Payload = %s", payload)
                    self._collect_inverter_data(payload)
                    self._post_process()
                    _LOGGER.debug("Collected data: %s", GinlongData(self._data))
                    return GinlongData(self._data)
        return None


    async def _get_inverter_details(self, device_id: str) -> dict[str, Any] | None:
        """
        Update inverter details
        """

        # Get inverter details
        url = 'http://'+self._config.domain+'/cpro/device/inverter/goDetailAjax.json'
        params = {
            'deviceId': device_id
        }

        result = await self._get_data(url, params)

        jsondata = None
        if result[SUCCESS] is True:
            jsondata = result[CONTENT]
        else:
            _LOGGER.info('Unable to fetch details for device with ID: %s', device_id)
        return jsondata

    def _collect_inverter_data(self, payload: dict[str, Any]) -> None:
        """ Fetch dynamic properties """
        for subkey in INVERTER_DATA:
            jsondata = payload['result']['deviceWapper']
            if subkey != 'none':
                jsondata = jsondata[subkey]
            attributes = INVERTER_DATA[subkey][1]
            for dictkey in attributes:
                key = attributes[dictkey][0]
                type_ = attributes[dictkey][1]
                precision = attributes[dictkey][2]
                methodname = '_get_value' + INVERTER_DATA[subkey][0]
                if key is not None:
                    value = getattr(self, methodname)(jsondata, key, type_, precision)
                    if value is not None:
                        self._data[dictkey] = value

    def _post_process(self) -> None:
        """ Cleanup received data. """
        if self._data:
            # Fix timestamps
            if self._data.__contains__(INVERTER_TIMESTAMP_ONLINE):
                self._data[INVERTER_TIMESTAMP_ONLINE] = float(self._data[INVERTER_TIMESTAMP_ONLINE])/1000
            if self._data.__contains__(INVERTER_TIMESTAMP_UPDATE):
                self._data[INVERTER_TIMESTAMP_UPDATE] = float(self._data[INVERTER_TIMESTAMP_UPDATE])/1000
            # Unused phases are still in JSON payload as 0.0, remove them
            self._purge_if_unused(0.0, PHASE1_CURRENT, PHASE1_VOLTAGE)
            self._purge_if_unused(0.0, PHASE2_CURRENT, PHASE2_VOLTAGE)
            self._purge_if_unused(0.0, PHASE3_CURRENT, PHASE3_VOLTAGE)

    def _purge_if_unused(self, value: Any, *elements: str) -> None:
        for element in elements:
            try:
                if self._data[element] != value:
                    return
            except KeyError:
                return
        for element in elements:
            self._data.pop(element)

    def _get_value_from_record(self,
        data: list[dict[str, str]], key: str, type_: type, precision: int = 2
    ) -> str | int | float | None:
        result = None
        for record in data:
            key_value = record.get('key')
            if key_value == key:
                data_raw = record.get('value')
                if data_raw is not None:
                    result = type_(data_raw)
                    # Round to specified precision
                    if type_ is float:
                        result = round(result, precision)
        return result

    def _get_value(self,
        data: dict[str, Any], key: str, type_: type, precision: int = 2
    ) -> str | int | float | None:
        """ Retrieve 'key' from 'data' as type 'type_' with precision 'precision' """
        result = None

        data_raw = data.get(key)
        if data_raw is not None:
            result = type_(data_raw)
            # Round to specified precision
            if type_ is float:
                result = round(result, precision)
        return result

    async def _get_data(self,
            url: str,
            params: dict[str, Any]
        ) -> dict[str, Any]:
        """ Http-get data from specified url. """

        result: dict[str, Any] = {SUCCESS: False, MESSAGE: None, STATUS_CODE: None}
        resp = None
        if self._session is None:
            return result
        try:
            with async_timeout.timeout(10):
                resp = await self._session.get(url, params=params)

                result[STATUS_CODE] = resp.status
                result[CONTENT] = await resp.json()
                if resp.status == HTTPStatus.OK:
                    result[SUCCESS] = True
                    result[MESSAGE] = "OK"
                else:
                    result[MESSAGE] = "Got http statuscode: %d" % (resp.status)
                return result
        except (asyncio.TimeoutError, ClientError) as err:
            result[MESSAGE] = "Exception: %s" % err.__class__
            _LOGGER.debug("Error: %s", result[MESSAGE])
            return result
        finally:
            if resp is not None:
                await resp.release()

    async def _post_data(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """ Http-post data to specified url. """

        result: dict[str, Any] = {SUCCESS: False, MESSAGE: None}
        resp = None
        if self._session is None:
            return result
        try:
            with async_timeout.timeout(10):
                resp = await self._session.post(url, params=params)

                result[STATUS_CODE] = resp.status
                result[CONTENT] = await resp.json()
                if resp.status == HTTPStatus.OK:
                    result[SUCCESS] = True
                    result[MESSAGE] = "OK"
                else:
                    result[MESSAGE] = "Got http statuscode: %d" % (resp.status)

                return result
        except (asyncio.TimeoutError, ClientError) as err:
            result[MESSAGE] = "%s" % err
            _LOGGER.debug("Error: %s", result[MESSAGE])
            return result
        finally:
            if resp is not None:
                await resp.release()
