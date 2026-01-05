import json

# import requests
# from requests import RequestException
import httpx as requests
from httpx import HTTPStatusError as RequestException
from typing import Union
from collections.abc import Callable
from logging import getLogger


class RESTfulJson:
    """A simple RESTful JSON client using requests library."""

    json_headers = {"Content-Type": "application/json"}

    @classmethod
    def get_logger(cls):
        return getLogger(cls.__name__)

    @staticmethod
    def send_get_request(
        url: str, headers: dict
    ) -> Union[requests.Response, RequestException]:
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return response
        except RequestException as e:
            return e

    @classmethod
    def _send(
        cls,
        url: str,
        payload: dict,
        func: Callable[..., requests.Response],
        timeout: int = 1,
    ) -> Union[dict, str]:
        response = func(
            url, headers=cls.json_headers, data=json.dumps(payload), timeout=timeout
        )
        if response.status_code == 200:
            try:
                return json.loads(response.text)
            except json.JSONDecodeError:
                return response.text
        else:
            return False

    @classmethod
    def put(cls, url: str, payload: dict, timeout=1) -> Union[dict, str]:
        return cls._send(url, payload, requests.put, timeout)

    @classmethod
    def post(cls, url: str, payload: dict, timeout=1) -> Union[dict, str]:
        return cls._send(url, payload, requests.post, timeout)

    @classmethod
    def get(cls, url: str, timeout=1) -> dict:
        try:
            response = requests.get(url, headers=cls.json_headers, timeout=timeout)
            get_data = json.loads(response.text)
        except Exception as e:
            return None
        return get_data
