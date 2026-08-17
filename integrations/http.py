import logging
import threading
import time
from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


def build_session(user_agent: str = 'sinus-noster-overlay/1.0') -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2,
        backoff_factor=0.4,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(['GET']),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    session.headers.update({'User-Agent': user_agent, 'Accept': 'application/json'})
    return session


def get_json(
    session: requests.Session,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    timeout: float = 8.0,
    headers: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, Any]]:
    try:
        response = session.get(url, params=params, timeout=timeout, headers=headers)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as err:
        logger.warning('falha ao carregar %s: %s', url, err)
        return None


class CoordinateCache:
    """Cache por coordenada arredondada com TTL.

    Rounding pela tolerância evita invalidar o cache a cada micro-oscilação do
    GPS, o que economiza chamadas em APIs com rate limit apertado (Nominatim,
    OpenTopoData público).
    """

    def __init__(self, ttl_seconds: float, tolerance_deg: float = 0.01) -> None:
        self._ttl = ttl_seconds
        self._tolerance = tolerance_deg
        self._store: Dict[tuple, tuple] = {}
        self._lock = threading.Lock()

    def _key(self, latitude: float, longitude: float) -> tuple:
        step = self._tolerance if self._tolerance > 0 else 0.01
        return (round(latitude / step), round(longitude / step))

    def get(self, latitude: float, longitude: float) -> Optional[Any]:
        key = self._key(latitude, longitude)
        with self._lock:
            entry = self._store.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if expires_at < time.monotonic():
            return None
        return value

    def set(self, latitude: float, longitude: float, value: Any) -> None:
        key = self._key(latitude, longitude)
        expires_at = time.monotonic() + self._ttl
        with self._lock:
            self._store[key] = (expires_at, value)

    def invalidate(self) -> None:
        with self._lock:
            self._store.clear()
