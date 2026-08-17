from typing import Any, Dict, Optional, Tuple

MPS_TO_KNOTS = 1.94384


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_latest(payload: Dict[str, Any], name: str) -> Dict[str, Any]:
    readings = (payload or {}).get('payload') or []
    for reading in reversed(readings):
        if reading.get('name') == name:
            return reading.get('values') or {}
    return {}


def to_dms(value: float, is_latitude: bool = True) -> str:
    value = parse_float(value)
    abs_value = abs(value)
    degrees = int(abs_value)
    minutes = int((abs_value - degrees) * 60)
    seconds = round((abs_value - degrees - minutes / 60) * 3600)

    if seconds >= 60:
        seconds -= 60
        minutes += 1
    if minutes >= 60:
        minutes -= 60
        degrees += 1

    if is_latitude:
        direction = 'N' if value >= 0 else 'S'
    else:
        direction = 'E' if value >= 0 else 'W'

    return f"{degrees}°{minutes:02d}'{seconds:02d}\"{direction}"


def speed_in_knots(location_values: Dict[str, Any]) -> float:
    return round(parse_float(location_values.get('speed')) * MPS_TO_KNOTS, 1)


def resolve_bearing(location_values: Dict[str, Any], compass_values: Dict[str, Any]) -> float:
    location_bearing = parse_float(location_values.get('bearing'))
    if location_bearing != 0:
        return round(location_bearing, 0)
    return round(parse_float(compass_values.get('magneticBearing')), 0)


def coordinates(location_values: Dict[str, Any]) -> Tuple[float, float]:
    return parse_float(location_values.get('latitude')), parse_float(location_values.get('longitude'))


def vertical_acceleration(accelerometer_values: Dict[str, Any]) -> float:
    return round(parse_float(accelerometer_values.get('z')), 2)


def cardinal_direction(degrees: Optional[float]) -> str:
    if degrees is None:
        return '--'
    value = parse_float(degrees) % 360
    if value <= 22.5 or value > 337.5:
        return 'N'
    if value <= 67.5:
        return 'NE'
    if value <= 112.5:
        return 'E'
    if value <= 157.5:
        return 'SE'
    if value <= 202.5:
        return 'S'
    if value <= 247.5:
        return 'SW'
    if value <= 292.5:
        return 'W'
    return 'NW'


def has_valid_position(latitude: float, longitude: float) -> bool:
    return not (latitude == 0 and longitude == 0)
