from typing import Any, Dict, Optional

from .http import CoordinateCache, get_json


class NominatimReverseGeocoder:
    """Reverse geocoding via Nominatim (OSM).

    Política de uso exige User-Agent identificável e no máximo 1 req/s no host
    público — o cache por coordenada aqui é intencionalmente grande (várias
    horas) para respeitar isso mesmo com sensor mandando dado a cada segundo.
    """

    def __init__(
        self,
        session,
        base_url: str,
        timeout: float,
        cache_ttl_seconds: float,
        position_tolerance_deg: float,
        user_agent: str,
        enabled: bool = True,
    ) -> None:
        self._session = session
        self._base_url = base_url
        self._timeout = timeout
        self._enabled = enabled
        self._user_agent = user_agent
        self._cache = CoordinateCache(cache_ttl_seconds, position_tolerance_deg)

    @property
    def enabled(self) -> bool:
        return self._enabled and bool(self._base_url)

    def fetch(self, latitude: float, longitude: float) -> Dict[str, Any]:
        if not self.enabled:
            return {}

        cached = self._cache.get(latitude, longitude)
        if cached is not None:
            return cached

        params = {
            'lat': latitude,
            'lon': longitude,
            'format': 'jsonv2',
            'zoom': 10,
            'accept-language': 'pt-BR,pt',
        }
        headers = {'User-Agent': self._user_agent}
        payload = get_json(
            self._session,
            self._base_url,
            params=params,
            timeout=self._timeout,
            headers=headers,
        )
        if not payload:
            return {}

        result = {
            'location_name': self._short_name(payload),
            'location_full': payload.get('display_name'),
        }
        self._cache.set(latitude, longitude, result)
        return result

    @staticmethod
    def _short_name(payload: Dict[str, Any]) -> Optional[str]:
        address = payload.get('address') or {}
        for key in ('city', 'town', 'village', 'municipality', 'county', 'state', 'ocean', 'sea', 'water', 'country'):
            value = address.get(key)
            if value:
                return value
        return payload.get('name') or payload.get('display_name')
