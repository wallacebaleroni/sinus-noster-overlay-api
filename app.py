import logging
import os
import threading
from datetime import datetime, timezone
from typing import Optional, Tuple

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

import sensors
from integrations.bathymetry import OpenTopoDataBathymetry
from integrations.geocoding import NominatimReverseGeocoder
from integrations.http import build_session
from integrations.openmeteo import OpenMeteoForecast, OpenMeteoMarine

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')


def env_flag(name: str, default: str = '1') -> bool:
    return os.getenv(name, default) not in ('0', 'false', 'False', '')


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


REFRESH_INTERVAL = int(env_float('EXTERNAL_DATA_REFRESH_INTERVAL_SECONDS', 60))
POSITION_TOLERANCE = env_float('POSITION_CACHE_TOLERANCE_DEG', 0.01)
HTTP_TIMEOUT = env_float('EXTERNAL_HTTP_TIMEOUT_SECONDS', 8.0)

_NOMINATIM_USER_AGENT = os.getenv(
    'NOMINATIM_USER_AGENT',
    'sinus-noster-overlay/1.0 (contato@example.com)',
)

session = build_session(user_agent=_NOMINATIM_USER_AGENT)

forecast_client = OpenMeteoForecast(
    session=session,
    base_url=os.getenv('OPEN_METEO_FORECAST_URL', 'https://api.open-meteo.com/v1/forecast'),
    timeout=HTTP_TIMEOUT,
    cache_ttl_seconds=REFRESH_INTERVAL * 5,
    position_tolerance_deg=POSITION_TOLERANCE,
    enabled=env_flag('OPEN_METEO_FORECAST_ENABLED'),
)

marine_client = OpenMeteoMarine(
    session=session,
    base_url=os.getenv('OPEN_METEO_MARINE_URL', 'https://marine-api.open-meteo.com/v1/marine'),
    timeout=HTTP_TIMEOUT,
    cache_ttl_seconds=REFRESH_INTERVAL * 5,
    position_tolerance_deg=POSITION_TOLERANCE,
    enabled=env_flag('OPEN_METEO_MARINE_ENABLED'),
)

bathymetry_client = OpenTopoDataBathymetry(
    session=session,
    base_url=os.getenv('OPENTOPODATA_URL', 'https://api.opentopodata.org/v1/gebco2020'),
    timeout=HTTP_TIMEOUT,
    cache_ttl_seconds=24 * 3600,
    position_tolerance_deg=POSITION_TOLERANCE,
    enabled=env_flag('OPENTOPODATA_ENABLED'),
)

geocoder_client = NominatimReverseGeocoder(
    session=session,
    base_url=os.getenv('NOMINATIM_URL', 'https://nominatim.openstreetmap.org/reverse'),
    timeout=HTTP_TIMEOUT,
    cache_ttl_seconds=6 * 3600,
    position_tolerance_deg=max(POSITION_TOLERANCE, 0.05),
    user_agent=_NOMINATIM_USER_AGENT,
    enabled=env_flag('NOMINATIM_ENABLED'),
)


app = Flask(__name__, template_folder='templates')
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
CORS(app)

state_lock = threading.Lock()
sensor_data = {
    'speed': 0.0,
    'bearing': 0.0,
    'latitude': 0.0,
    'longitude': 0.0,
    'latitude_dms': '00°00\'00"N',
    'longitude_dms': '00°00\'00"E',
    'position_decimal': '0.000000, 0.000000',
    'vertical_acceleration': 0.0,
    'water_temperature': None,
    'tide_height': None,
    'tide_state': 'unknown',
    'wind_speed': None,
    'wind_gust': None,
    'wind_direction': None,
    'wave_height': None,
    'wave_period': None,
    'wave_direction': None,
    'current_speed': None,
    'current_direction': None,
    'air_temperature': None,
    'pressure': None,
    'precipitation': None,
    'cloud_cover': None,
    'sunrise': None,
    'sunset': None,
    'depth': None,
    'location_name': None,
    'location_full': None,
    'last_update': None,
    'last_external_update': None,
}

_last_position: Optional[Tuple[float, float]] = None
_position_event = threading.Event()
_stop_event = threading.Event()


@app.after_request
def no_cache(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


def _update_state(**fields) -> None:
    with state_lock:
        sensor_data.update(fields)


def refresh_external_data(latitude: float, longitude: float) -> None:
    """Chama todas as integrações e mescla o resultado no estado global.

    Roda na thread de background — nunca no caminho do POST /data, pra não
    fazer a app do sensor esperar chamadas externas.
    """
    try:
        forecast = forecast_client.fetch(latitude, longitude)
        marine = marine_client.fetch(latitude, longitude)
        bathymetry = bathymetry_client.fetch(latitude, longitude)
        geocoding = geocoder_client.fetch(latitude, longitude)
    except Exception:
        logger.exception('erro ao atualizar dados externos')
        return

    merged = {
        'water_temperature': marine.get('water_temperature'),
        'tide_height': marine.get('tide_height'),
        'tide_state': marine.get('tide_state', 'unknown'),
        'wave_height': marine.get('wave_height'),
        'wave_period': marine.get('wave_period'),
        'wave_direction': marine.get('wave_direction'),
        'current_speed': marine.get('current_speed'),
        'current_direction': marine.get('current_direction'),
        'wind_speed': forecast.get('wind_speed'),
        'wind_gust': forecast.get('wind_gust'),
        'wind_direction': forecast.get('wind_direction'),
        'air_temperature': forecast.get('air_temperature'),
        'pressure': forecast.get('pressure'),
        'precipitation': forecast.get('precipitation'),
        'cloud_cover': forecast.get('cloud_cover'),
        'sunrise': forecast.get('sunrise'),
        'sunset': forecast.get('sunset'),
        'depth': bathymetry.get('depth'),
        'location_name': geocoding.get('location_name'),
        'location_full': geocoding.get('location_full'),
        'last_external_update': datetime.now(timezone.utc).isoformat(),
    }
    _update_state(**merged)


def _background_refresh_loop() -> None:
    logger.info('thread de refresh externo iniciada (interval=%ss)', REFRESH_INTERVAL)
    while not _stop_event.is_set():
        _position_event.wait(timeout=REFRESH_INTERVAL)
        _position_event.clear()
        if _stop_event.is_set():
            break
        with state_lock:
            position = _last_position
        if position is None:
            continue
        latitude, longitude = position
        if not sensors.has_valid_position(latitude, longitude):
            continue
        refresh_external_data(latitude, longitude)


refresh_thread = threading.Thread(target=_background_refresh_loop, name='external-refresh', daemon=True)


@app.route('/data', methods=['POST'])
def receive_sensor_data():
    global _last_position

    payload = request.get_json(silent=True)
    if not payload:
        # Não é JSON válido ou Content-Type está errado — logamos o corpo cru
        # pra ajudar a diagnosticar sensores mal configurados.
        raw = request.get_data(as_text=True)[:500]
        logger.warning(
            'POST /data sem JSON. ip=%s content-type=%s body=%r',
            request.remote_addr,
            request.headers.get('Content-Type'),
            raw,
        )
        return jsonify({'status': 'no-payload'}), 400

    readings = [r.get('name') for r in (payload.get('payload') or []) if isinstance(r, dict)]
    logger.info('POST /data ip=%s readings=%s', request.remote_addr, readings)

    location_values = sensors.get_latest(payload, 'location')
    accelerometer_values = sensors.get_latest(payload, 'accelerometer')
    compass_values = sensors.get_latest(payload, 'compass')

    latitude, longitude = sensors.coordinates(location_values)

    updates = {
        'speed': sensors.speed_in_knots(location_values),
        'bearing': sensors.resolve_bearing(location_values, compass_values),
        'latitude': latitude,
        'longitude': longitude,
        'latitude_dms': sensors.to_dms(latitude, is_latitude=True),
        'longitude_dms': sensors.to_dms(longitude, is_latitude=False),
        'position_decimal': f'{latitude:.6f}, {longitude:.6f}',
        'vertical_acceleration': sensors.vertical_acceleration(accelerometer_values),
        'last_update': datetime.now(timezone.utc).isoformat(),
    }
    _update_state(**updates)

    if sensors.has_valid_position(latitude, longitude):
        with state_lock:
            _last_position = (latitude, longitude)
        _position_event.set()

    return jsonify({'status': 'ok'}), 200


@app.route('/live-data', methods=['GET'])
def send_digested_data():
    with state_lock:
        snapshot = dict(sensor_data)
    return jsonify(snapshot)


@app.route('/')
def index():
    return render_template('index.html')


def start_background_workers() -> None:
    if not refresh_thread.is_alive():
        refresh_thread.start()


start_background_workers()


if __name__ == '__main__':
    # debug=True liga o reloader do Flask; use FLASK_DEBUG=0 pra produção.
    debug = env_flag('FLASK_DEBUG', default='0')
    app.run(host='0.0.0.0', port=int(env_float('PORT', 5000)), debug=debug, use_reloader=False)
