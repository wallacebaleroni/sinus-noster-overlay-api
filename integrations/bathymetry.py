from typing import Any, Dict, Optional

from .http import CoordinateCache, get_json


class OpenTopoDataBathymetry:
    """Consulta profundidade via OpenTopoData (dataset GEBCO 2020).

    A API retorna elevação em metros — valores negativos indicam profundidade
    abaixo do nível do mar. TTL alto por coordenada (batimetria é estática).
    """

    def __init__(
        self,
        session,
        base_url: str,
        timeout: float,
        cache_ttl_seconds: float,
        position_tolerance_deg: float,
        enabled: bool = True,
    ) -> None:
        self._session = session
        self._base_url = base_url
        self._timeout = timeout
        self._enabled = enabled
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

        params = {'locations': f'{latitude},{longitude}'}
        payload = get_json(self._session, self._base_url, params=params, timeout=self._timeout)
        if not payload:
            return {}

        elevation = self._extract_elevation(payload)
        depth = -elevation if elevation is not None and elevation < 0 else None
        result = {
            'depth': round(depth, 1) if depth is not None else None,
            'elevation': elevation,
        }
        self._cache.set(latitude, longitude, result)
        return result

    @staticmethod
    def _extract_elevation(payload: Dict[str, Any]) -> Optional[float]:
        results = payload.get('results') or []
        if not results:
            return None
        first = results[0] or {}
        elevation = first.get('elevation')
        try:
            return float(elevation) if elevation is not None else None
        except (TypeError, ValueError):
            return None
