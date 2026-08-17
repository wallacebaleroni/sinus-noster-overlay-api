# Sinus Noster Overlay

Overlay web em tempo real para navegação de embarcação, pensado para ser capturado por uma cena do OBS em livestream. Recebe telemetria do sensor (GPS, bússola, acelerômetro) via HTTP, agrega dados meteorológicos, oceanográficos, batimétricos e de localização de APIs públicas e renderiza tudo em uma tela 1920×1080 pronta pra transmissão.

Internamente o projeto tem três camadas: uma API HTTP (`POST /data`, `GET /live-data`), um worker de agregação em background e a página do overlay (`GET /`). O produto final é o overlay — os dois primeiros existem pra alimentá-lo.

## Contexto

A ideia é centralizar dados vindos de sensores/dispositivos embarcados e transformá-los em informação útil para navegação, observação de maré, vento, ondas, profundidade e posição. Em uso real, o dashboard vira fonte visual de uma transmissão ao vivo em OBS, exibindo em tela:

- velocidade, rumo e localização em tempo real;
- estado da maré e nível do mar;
- vento (velocidade, direção, rajada), pressão e temperatura do ar;
- ondas (altura, período, direção) e correntes marítimas;
- profundidade batimétrica e temperatura da água;
- localização (cidade/costa mais próxima);
- nascer e pôr do sol.

O sensor envia dados via `POST /data`, o backend consulta um conjunto de APIs externas em background e o overlay em `/` consome `GET /live-data` de segundo em segundo.

---

## APIs externas integradas

Todas as integrações são gratuitas e sem chave. As respostas são cacheadas por coordenada para respeitar rate limits.

| Fonte | Endpoint | Dados |
|---|---|---|
| Open-Meteo Forecast | `https://api.open-meteo.com/v1/forecast` | Vento (velocidade em nós, direção, rajada), temperatura do ar, pressão, precipitação, cobertura de nuvens, sunrise/sunset |
| Open-Meteo Marine | `https://marine-api.open-meteo.com/v1/marine` | Altura/direção/período de onda, temperatura da água (SST), nível do mar (`sea_level_height_msl`, base da maré), velocidade/direção de corrente |
| OpenTopoData GEBCO 2020 | `https://api.opentopodata.org/v1/gebco2020` | Batimetria (profundidade em metros derivada da elevação) |
| Nominatim OSM | `https://nominatim.openstreetmap.org/reverse` | Reverse geocoding — nome da cidade/costa/oceano próximo |

Notas de uso:

- **Open-Meteo**: não exige chave, forecast horário. Se rodar muitas instâncias, avalie subir uma cópia self-hosted.
- **OpenTopoData público**: 1 req/s e 1000 req/dia. Para embarcação em movimento, o cache por coordenada arredondada (~1 km) já resolve na prática.
- **Nominatim público**: exige `User-Agent` identificável (configure `NOMINATIM_USER_AGENT` no `.env`) e limite de 1 req/s. Use responsavelmente.

Estado da maré é derivado da série `sea_level_height_msl`: comparando a hora atual com a próxima, classificamos em `rising`, `falling` ou `steady`.

---

## Endpoints da aplicação

### `POST /data`

Recebe payload do sensor:

```json
{
  "payload": [
    {"name": "location", "values": {"latitude": -23.5, "longitude": -46.3, "speed": 3.5, "bearing": 120}},
    {"name": "accelerometer", "values": {"z": 0.75}},
    {"name": "compass", "values": {"magneticBearing": 118}}
  ]
}
```

A resposta é imediata (`200 OK`); as consultas externas rodam em thread separada, disparadas pela última posição válida recebida.

### `GET /live-data`

Retorna o estado consolidado em JSON:

```json
{
  "speed": 6.8,
  "bearing": 120,
  "latitude": -23.501,
  "longitude": -46.302,
  "latitude_dms": "23°30'03\"S",
  "longitude_dms": "46°18'07\"W",
  "position_decimal": "-23.501000, -46.302000",
  "vertical_acceleration": 0.75,
  "water_temperature": 22.4,
  "tide_height": 0.42,
  "tide_state": "rising",
  "wind_speed": 8.2,
  "wind_gust": 12.1,
  "wind_direction": 145,
  "wave_height": 1.1,
  "wave_period": 7,
  "wave_direction": 170,
  "current_speed": 0.2,
  "current_direction": 90,
  "air_temperature": 24.1,
  "pressure": 1015,
  "precipitation": 0.0,
  "cloud_cover": 40,
  "sunrise": "2026-08-17T09:12",
  "sunset": "2026-08-17T20:41",
  "depth": 34.7,
  "location_name": "Santos",
  "location_full": "Santos, São Paulo, Brasil",
  "last_update": "2026-08-17T17:08:00+00:00",
  "last_external_update": "2026-08-17T17:07:12+00:00"
}
```

### `GET /`

Renderiza `templates/index.html`, o overlay 1920×1080 pensado pra ser capturado no OBS.

---

## Estrutura do projeto

```text
sinus-noster-overlay/
├── app.py                  # Flask, rotas, thread de refresh em background
├── sensors.py              # Parsing do payload + conversões (nós, DMS, cardeal)
├── integrations/
│   ├── __init__.py
│   ├── http.py             # Session requests com retry + cache por coordenada
│   ├── openmeteo.py        # Forecast + Marine
│   ├── bathymetry.py       # OpenTopoData GEBCO 2020
│   └── geocoding.py        # Nominatim reverse
├── templates/
│   └── index.html          # Overlay do OBS
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## Requisitos

- Python 3.9+
- Dependências em `requirements.txt` (Flask, Flask-CORS, requests)

---

## Como rodar localmente

### 1. Ambiente virtual

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Instale as dependências

```bash
pip install -r requirements.txt
```

### 3. Configure as variáveis

```bash
cp .env.example .env
```

Ajuste pelo menos `NOMINATIM_USER_AGENT` com um contato real (política do Nominatim).

### 4. Rode

```bash
python app.py
```

Overlay em `http://localhost:5000`.

---

## Variáveis de ambiente

| Variável | Padrão | Descrição |
|---|---|---|
| `EXTERNAL_DATA_REFRESH_INTERVAL_SECONDS` | `60` | Intervalo do refresh em background das APIs externas |
| `POSITION_CACHE_TOLERANCE_DEG` | `0.01` | Tolerância (em graus) para invalidar cache por posição (~1 km) |
| `EXTERNAL_HTTP_TIMEOUT_SECONDS` | `8` | Timeout global das requisições HTTP |
| `OPEN_METEO_FORECAST_URL` | Open-Meteo | URL base do endpoint Forecast |
| `OPEN_METEO_FORECAST_ENABLED` | `1` | Liga/desliga a integração |
| `OPEN_METEO_MARINE_URL` | Open-Meteo Marine | URL base do endpoint Marine |
| `OPEN_METEO_MARINE_ENABLED` | `1` | Liga/desliga a integração |
| `OPENTOPODATA_URL` | GEBCO 2020 | URL base para batimetria |
| `OPENTOPODATA_ENABLED` | `1` | Liga/desliga a integração |
| `NOMINATIM_URL` | Nominatim OSM | URL base do reverse geocoding |
| `NOMINATIM_ENABLED` | `1` | Liga/desliga a integração |
| `NOMINATIM_USER_AGENT` | placeholder | User-Agent obrigatório para Nominatim — coloque um contato real |
| `PORT` | `5000` | Porta HTTP do Flask |
| `FLASK_DEBUG` | `0` | Ativa modo debug do Flask |

---

## Exemplo de uso

Enviando dados:

```bash
curl -X POST http://localhost:5000/data \
  -H "Content-Type: application/json" \
  -d '{
    "payload": [
      {"name": "location", "values": {"latitude": -23.98, "longitude": -46.30, "speed": 3.2, "bearing": 120}},
      {"name": "accelerometer", "values": {"z": 0.7}},
      {"name": "compass", "values": {"magneticBearing": 118}}
    ]
  }'
```

Consultando o estado consolidado:

```bash
curl http://localhost:5000/live-data
```

---

## Observações

- O `POST /data` **não** aguarda respostas externas. Ele apenas registra a última posição e sinaliza a thread de refresh, que atualiza o estado global respeitando o intervalo configurado. Isso evita que uma API lenta atrase a atualização de GPS/rumo no overlay.
- Todo o estado compartilhado passa por `state_lock` (`threading.Lock`) — Flask em modo dev usa múltiplas threads e o refresh também roda paralelo.
- As respostas incluem headers de cache desabilitado, para que o navegador do OBS nunca segure dado velho.
- Se rodar atrás de um proxy/gateway, garanta que ele não bufferize a resposta do `/live-data`.

---

## Licença

Este projeto não especifica licença no momento.
