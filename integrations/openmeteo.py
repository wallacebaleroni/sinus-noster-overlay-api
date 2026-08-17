from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .http import CoordinateCache, get_json

FORECAST_HOURLY = (
    'wind_speed_10m',
    'wind_direction_10m',
    'wind_gusts_10m',
    'temperature_2m',
    'surface_pressure',
    'precipitation',
    'cloud_cover',
)

FORECAST_DAILY = ('sunrise', 'sunset')

MARINE_HOURLY = (
    'wave_height',
    'wave_direction',
    'wave_period',
    'sea_surface_temperature',
    'sea_level_height_msl',
    'ocean_current_velocity',
    'ocean_current_direction',
)


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_iso(timestamp: str) -> Optional[datetime]:
    if not timestamp:
        return None
    for candidate in (timestamp.replace('Z', '+00:00'), timestamp):
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            continue
    try:
        return datetime.strptime(timestamp, '%Y-%m-%dT%H:%M').replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _nearest_hourly_index(times: List[str]) -> int:
    if not times:
        return 0

    now = datetime.now(timezone.utc)
    best_index = 0
    best_delta = None

    for index, raw in enumerate(times):
        parsed = _parse_iso(raw)
        if parsed is None:
            continue
        delta = abs(parsed - now)
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best_index = index

    return best_index


def _pick(hourly: Dict[str, Any], key: str, index: int) -> Optional[float]:
    series = hourly.get(key) or []
    if not series or index >= len(series):
        return None
    return _to_float(series[index])


def _next_daily(daily: Dict[str, Any], key: str) -> Optional[str]:
    values = daily.get(key) or []
    now = datetime.now(timezone.utc)
    for raw in values:
        parsed = _parse_iso(raw)
        if parsed and parsed >= now:
            return raw
    return values[-1] if values else None


def _tide_state_from_series(series: List[Any], index: int) -> str:
    if not series or index >= len(series):
        return 'unknown'
    current = _to_float(series[index])
    if current is None:
        return 'unknown'
    if index + 1 < len(series):
        nxt = _to_float(series[index + 1])
        if nxt is not None:
            if nxt > current + 0.01:
                return 'rising'
            if nxt < current - 0.01:
                return 'falling'
            return 'steady'
    if index - 1 >= 0:
        prev = _to_float(series[index - 1])
        if prev is not None:
            if current > prev + 0.01:
                return 'rising'
            if current < prev - 0.01:
                return 'falling'
    return 'steady'


class OpenMeteoForecast:
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

        params = {
            'latitude': latitude,
            'longitude': longitude,
            'hourly': ','.join(FORECAST_HOURLY),
            'daily': ','.join(FORECAST_DAILY),
            'wind_speed_unit': 'kn',
            'timezone': 'UTC',
            'forecast_days': 2,
        }
        payload = get_json(self._session, self._base_url, params=params, timeout=self._timeout)
        if not payload:
            return {}

        hourly = payload.get('hourly') or {}
        daily = payload.get('daily') or {}
        index = _nearest_hourly_index(hourly.get('time') or [])

        result = {
            'wind_speed': _pick(hourly, 'wind_speed_10m', index),
            'wind_gust': _pick(hourly, 'wind_gusts_10m', index),
            'wind_direction': _pick(hourly, 'wind_direction_10m', index),
            'air_temperature': _pick(hourly, 'temperature_2m', index),
            'pressure': _pick(hourly, 'surface_pressure', index),
            'precipitation': _pick(hourly, 'precipitation', index),
            'cloud_cover': _pick(hourly, 'cloud_cover', index),
            'sunrise': _next_daily(daily, 'sunrise'),
            'sunset': _next_daily(daily, 'sunset'),
        }
        self._cache.set(latitude, longitude, result)
        return result


class OpenMeteoMarine:
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

        params = {
            'latitude': latitude,
            'longitude': longitude,
            'hourly': ','.join(MARINE_HOURLY),
            'timezone': 'UTC',
        }
        payload = get_json(self._session, self._base_url, params=params, timeout=self._timeout)
        if not payload:
            return {}

        hourly = payload.get('hourly') or {}
        index = _nearest_hourly_index(hourly.get('time') or [])

        result = {
            'wave_height': _pick(hourly, 'wave_height', index),
            'wave_direction': _pick(hourly, 'wave_direction', index),
            'wave_period': _pick(hourly, 'wave_period', index),
            'water_temperature': _pick(hourly, 'sea_surface_temperature', index),
            'tide_height': _pick(hourly, 'sea_level_height_msl', index),
            'tide_state': _tide_state_from_series(hourly.get('sea_level_height_msl') or [], index),
            'current_speed': _pick(hourly, 'ocean_current_velocity', index),
            'current_direction': _pick(hourly, 'ocean_current_direction', index),
        }
        self._cache.set(latitude, longitude, result)
        return result
