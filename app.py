from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import json
import os
import urllib.error
import urllib.parse
import urllib.request

app = Flask(__name__, template_folder='templates')
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
CORS(app)  # Allows OBS to access the script without CORS blocking

EXTERNAL_DATA_REFRESH_INTERVAL_SECONDS = int(os.getenv('EXTERNAL_DATA_REFRESH_INTERVAL_SECONDS', '60'))
OPEN_METEO_BASE_URL = os.getenv('OPEN_METEO_BASE_URL', 'https://marine-api.open-meteo.com/v1/marine')
OPEN_METEO_ENABLED = os.getenv('OPEN_METEO_ENABLED', '1') not in ('0', 'false', 'False')
DEPTH_API_URL = os.getenv('DEPTH_API_URL')
DEPTH_API_KEY = os.getenv('DEPTH_API_KEY')

sensor_data = {
    'speed': 0.0,
    'bearing': 0.0,
    'latitude': 0.0,
    'longitude': 0.0,
    'latitude_dms': '00°00\'00"N',
    'longitude_dms': '00°00\'00"E',
    'position_decimal': '0.000000, 0.000000',
    'vertical_acceleration': 0.0,
    'tide_height': None,
    'tide_state': 'unknown',
    'water_temperature': None,
    'wind_speed': None,
    'wind_direction': None,
    'depth': None,
    'last_update': None,
}

external_cache = {
    'updated_at': None,
    'latitude': None,
    'longitude': None,
    'marine_data': {},
}


@app.after_request
def no_cache(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


def parse_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_latest(payload, name):
    for reading in reversed(payload['payload']):
        if reading.get('name') == name:
            return reading.get('values', {})
    return {}


def to_dms(value, is_latitude=True):
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

    direction = 'N' if value >= 0 else 'S' if is_latitude else 'E' if value >= 0 else 'W'
    if not is_latitude:
        direction = 'E' if value >= 0 else 'W'

    return f"{degrees}°{minutes}'{seconds}\"{direction}"


def get_speed(values):
    return round(parse_float(values.get('speed')) * 1.94384, 1)


def get_bearing(location_values, compass_values):
    location_bearing = parse_float(location_values.get('bearing'))
    if location_bearing != 0:
        return round(location_bearing, 0)
    return round(parse_float(compass_values.get('magneticBearing')), 0)


def get_coordinates(values):
    latitude = parse_float(values.get('latitude'))
    longitude = parse_float(values.get('longitude'))
    return latitude, longitude


def get_vertical_acceleration(accelerometer_values):
    return round(parse_float(accelerometer_values.get('z')), 2)


def get_cardinal_direction(degrees):
    degrees = parse_float(degrees) % 360
    if degrees <= 22.5 or degrees > 337.5:
        return 'N'
    if degrees <= 67.5:
        return 'NE'
    if degrees <= 112.5:
        return 'E'
    if degrees <= 157.5:
        return 'SE'
    if degrees <= 202.5:
        return 'S'
    if degrees <= 247.5:
        return 'SW'
    if degrees <= 292.5:
        return 'W'
    return 'NW'


def make_url(base_url, params):
    query = urllib.parse.urlencode(params)
    return f"{base_url}?{query}"


def load_json_url(url, timeout=10):
    request = urllib.request.Request(url, method='GET')
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode('utf-8', errors='ignore')
            return json.loads(payload)
    except (urllib.error.URLError, json.JSONDecodeError) as err:
        print(f'[external] falha ao carregar URL {url}: {err}')
        return None


def find_nearest_index(times):
    if not times:
        return 0

    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    nearest_index = 0
    smallest_delta = timedelta(days=365)

    for index, timestamp in enumerate(times):
        try:
            candidate = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        except ValueError:
            try:
                candidate = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M')
            except ValueError:
                continue
        delta = abs(candidate - now)
        if delta < smallest_delta:
            smallest_delta = delta
            nearest_index = index

    return nearest_index


def compute_tide_state(tide_heights, index):
    if not tide_heights or index < 0 or index >= len(tide_heights):
        return 'unknown'
    current = parse_float(tide_heights[index])
    if index + 1 < len(tide_heights):
        next_height = parse_float(tide_heights[index + 1])
        return 'rising' if next_height > current else 'falling'
    if index - 1 >= 0:
        previous_height = parse_float(tide_heights[index - 1])
        return 'rising' if current > previous_height else 'falling'
    return 'steady'


def fetch_marine_weather(latitude, longitude):
    if not OPEN_METEO_ENABLED or not OPEN_METEO_BASE_URL:
        return {}

    params = {
        'latitude': latitude,
        'longitude': longitude,
        'hourly': 'water_temperature,tide_height,wind_speed,wind_direction',
        'timezone': 'UTC',
    }
    url = make_url(OPEN_METEO_BASE_URL, params)
    data = load_json_url(url)
    if not data:
        return {}

    hourly = data.get('hourly', {})
    times = hourly.get('time', [])
    index = find_nearest_index(times)

    return {
        'water_temperature': parse_float(hourly.get('water_temperature', [None])[index] if index < len(hourly.get('water_temperature', [])) else None),
        'tide_height': parse_float(hourly.get('tide_height', [None])[index] if index < len(hourly.get('tide_height', [])) else None),
        'tide_state': compute_tide_state(hourly.get('tide_height', []), index),
        'wind_speed': parse_float(hourly.get('wind_speed', [None])[index] if index < len(hourly.get('wind_speed', [])) else None),
        'wind_direction': parse_float(hourly.get('wind_direction', [None])[index] if index < len(hourly.get('wind_direction', [])) else None),
    }


def fetch_depth_data(latitude, longitude):
    if not DEPTH_API_URL:
        return None

    params = {
        'lat': latitude,
        'lon': longitude,
    }
    if DEPTH_API_KEY:
        params['key'] = DEPTH_API_KEY

    url = make_url(DEPTH_API_URL, params)
    data = load_json_url(url)
    if not data:
        return None

    return data.get('depth') or data.get('water_depth') or data.get('depth_meters')


def update_external_data(latitude, longitude):
    now = datetime.utcnow()
    cache_valid = False

    if external_cache['updated_at'] is not None:
        age = now - external_cache['updated_at']
        cache_valid = (
            age < timedelta(seconds=EXTERNAL_DATA_REFRESH_INTERVAL_SECONDS)
            and external_cache['latitude'] == latitude
            and external_cache['longitude'] == longitude
        )

    if cache_valid and external_cache['marine_data']:
        marine_data = external_cache['marine_data']
    else:
        marine_data = fetch_marine_weather(latitude, longitude)
        external_cache.update({
            'updated_at': now,
            'latitude': latitude,
            'longitude': longitude,
            'marine_data': marine_data,
        })

    sensor_data['water_temperature'] = marine_data.get('water_temperature')
    sensor_data['tide_height'] = marine_data.get('tide_height')
    sensor_data['tide_state'] = marine_data.get('tide_state', 'unknown')
    sensor_data['wind_speed'] = marine_data.get('wind_speed')
    sensor_data['wind_direction'] = marine_data.get('wind_direction')
    sensor_data['depth'] = fetch_depth_data(latitude, longitude)


@app.route('/data', methods=['POST'])
def receive_sensor_data():
    global sensor_data
    payload = request.json

    if payload is not None and 'payload' in payload:
        location_values = get_latest(payload, 'location')
        accelerometer_values = get_latest(payload, 'accelerometer')
        compass_values = get_latest(payload, 'compass')

        latitude, longitude = get_coordinates(location_values)
        sensor_data['speed'] = get_speed(location_values)
        sensor_data['bearing'] = get_bearing(location_values, compass_values)
        sensor_data['latitude'] = latitude
        sensor_data['longitude'] = longitude
        sensor_data['latitude_dms'] = to_dms(latitude, is_latitude=True)
        sensor_data['longitude_dms'] = to_dms(longitude, is_latitude=False)
        sensor_data['position_decimal'] = f'{latitude:.6f}, {longitude:.6f}'
        sensor_data['vertical_acceleration'] = get_vertical_acceleration(accelerometer_values)

        if latitude != 0 or longitude != 0:
            update_external_data(latitude, longitude)

        sensor_data['last_update'] = datetime.utcnow().isoformat() + 'Z'

    return jsonify({'status': 'ok'}), 200


@app.route('/live-data', methods=['GET'])
def send_digested_data():
    return jsonify(sensor_data)


def call_startup_api():
    startup_url = os.getenv('STARTUP_API_URL')
    if not startup_url:
        print('[startup] STARTUP_API_URL não definido, pulando chamada de API')
        return

    method = os.getenv('STARTUP_API_METHOD', 'GET').upper()
    payload = os.getenv('STARTUP_API_BODY')
    data = payload.encode('utf-8') if payload else None
    headers = {'Content-Type': 'application/json'} if payload else {}

    request = urllib.request.Request(startup_url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read().decode('utf-8', errors='ignore')
            print(f'[startup] chamada {method} para {startup_url} retornou {response.status}')
            return body
    except urllib.error.URLError as err:
        print(f'[startup] falha na chamada de API: {err}')


@app.route('/')
def index():
    return render_template('index.html')


if __name__ == '__main__':
    call_startup_api()
    app.run(host='0.0.0.0', port=5000, debug=True)
