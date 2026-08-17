# Sinus Noster API

Aplicação web em Python para receber, processar e exibir dados em tempo real de navegação e condições marítimas. A API foi pensada para funcionar como backend de um painel de monitoramento de embarcação, integrando informações de GPS, bússola, aceleração e dados meteorológicos/ambientais diretamente em uma interface web.

## Contexto

A ideia desta aplicação é centralizar dados vindos de sensores ou dispositivos embarcados e transformá-los em informações úteis para navegação, observação de maré, vento, profundidade e posição. Em um cenário real, o dashboard é usado como fonte visual para uma transmissão ao vivo em OBS (Open Broadcaster Software), onde as informações são exibidas em tela como parte de um livestream.

Isso é especialmente útil quando o objetivo é "popular" uma cena do OBS com dados de embarcação em tempo real, como:

- velocidade, rumo e localização em tempo real;
- estado da maré e condições ambientais;
- dados de vento, profundidade e temperatura da água;
- indicadores para uma tela de monitoramento em transmissão ao vivo;
- exibição contínua de status para streams, vídeos de navegação ou conteúdo de mar/obs.

A aplicação expõe um endpoint para receber dados em JSON e outro endpoint para fornecer os dados já processados para a interface, que foi pensada para ser facilmente consumida por uma cena do OBS.

---

## Como funciona

A lógica principal está em `app.py`:

1. A aplicação inicia um servidor Flask.
2. Um cliente externo envia um payload JSON para o endpoint `/data` via `POST`.
3. O backend extrai os valores de:
   - `location`
   - `accelerometer`
   - `compass`
4. Os dados são convertidos em informações mais legíveis:
   - velocidade em nós;
   - rumo em graus;
   - latitude e longitude em graus/minutos/segundos;
   - posição decimal formatada;
   - aceleração vertical;
5. Se a posição não for nula, o sistema busca dados externos de clima e mar:
   - temperatura da água;
   - altura da maré;
   - estado da maré (subindo/descendo);
   - velocidade do vento;
   - direção do vento;
   - profundidade.
6. A interface renderiza esses dados em `/`, consumindo `/live-data` em tempo real com `fetch()` no navegador.

A aplicação usa `Flask`, `flask-cors` e renderização de template HTML em `templates/index.html`. A estrutura visual foi pensada para ser legível, estável e com atualização em tempo real, para que o navegador da cena do OBS mostre esses dados de forma contínua durante a transmissão.

---

## Funcionalidades

### 1. Recebimento de sensores

Endpoint:

- `POST /data`

Esse endpoint aceita um JSON com estrutura semelhante a:

```json
{
  "payload": [
    {"name": "location", "values": {"latitude": -23.5, "longitude": -46.3, "speed": 3.5, "bearing": 120}},
    {"name": "accelerometer", "values": {"z": 0.75}},
    {"name": "compass", "values": {"magneticBearing": 118}}
  ]
}
```

A partir disso, a API calcula e salva os dados em `sensor_data`.

### 2. Dashboard em tempo real

Endpoint:

- `GET /live-data`

Retorna os dados digestados em formato JSON, prontos para atualização automática da interface.

### 3. Conversão de coordenadas

A aplicação converte coordenadas decimais em formato DMS, por exemplo:

- `23°12'00"S`
- `46°42'15"W`

Também mostra a posição em formato decimal.

### 4. Dados ambientais e marítimos

Ao receber uma localização válida, a API consulta serviços externos para complementar o painel com:

- temperatura da água;
- altura da maré;
- estado da maré (`rising`, `falling`, `steady`, `unknown`);
- direção e velocidade do vento;
- profundidade da água.

### 5. Interface visual para OBS e livestream

A página em `templates/index.html` foi desenhada para funcionar como uma tela de dados de transmissão ao vivo, exibindo:

- velocidade em nós;
- rumo em graus;
- direção cardeal (N, NE, E, etc.);
- latitude e longitude;
- posição decimal;
- vento e direção do vento;
- maré e profundidade;
- temperatura da água;
- horário da última atualização.

Como ela é atualizada automaticamente via `fetch()` em um intervalo de 1 segundo, ela se adapta bem ao uso em uma cena do OBS, onde a janela do navegador pode ser capturada diretamente como fonte de imagem da live.

---

## Estrutura do projeto

```text
API/
├── app.py
├── templates/
│   └── index.html
├── .gitignore
├── README.md
└── .venv/   # ambiente virtual local (se existir)
```

---

## Requisitos

- Python 3.9+
- Flask
- Flask-CORS

---

## Como rodar localmente

### 1. Crie um ambiente virtual

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
pip install flask flask-cors
```

### 3. Inicie a aplicação

```bash
python app.py
```

A aplicação ficará disponível em:

- `http://localhost:5000`

---

## Variáveis de ambiente

A aplicação aceita algumas variáveis de ambiente para configurar integrações externas:

```bash
EXTERNAL_DATA_REFRESH_INTERVAL_SECONDS=60
OPEN_METEO_BASE_URL=https://marine-api.open-meteo.com/v1/marine
OPEN_METEO_ENABLED=1
DEPTH_API_URL=
DEPTH_API_KEY=
STARTUP_API_URL=
STARTUP_API_METHOD=GET
STARTUP_API_BODY=
```

### O que cada uma faz

- `EXTERNAL_DATA_REFRESH_INTERVAL_SECONDS`: intervalo de atualização do cache dos dados externos.
- `OPEN_METEO_BASE_URL`: base da API de dados marítimos.
- `OPEN_METEO_ENABLED`: ativa ou desativa a consulta ao Open-Meteo.
- `DEPTH_API_URL`: endpoint para profundidade.
- `DEPTH_API_KEY`: chave opcional para a API de profundidade.
- `STARTUP_API_URL`: chamada opcional realizada na inicialização.
- `STARTUP_API_METHOD` e `STARTUP_API_BODY`: método e payload para a chamada de startup.

---

## Exemplo de uso

### Enviando dados para a API

```bash
curl -X POST http://localhost:5000/data \
  -H "Content-Type: application/json" \
  -d '{
    "payload": [
      {"name": "location", "values": {"latitude": -23.5, "longitude": -46.3, "speed": 3.2, "bearing": 120}},
      {"name": "accelerometer", "values": {"z": 0.7}},
      {"name": "compass", "values": {"magneticBearing": 118}}
    ]
  }'
```

### Consultando os dados finais

```bash
curl http://localhost:5000/live-data
```

---

## Observações

- O backend define headers de cache desabilitado para evitar stale data na tela.
- - A aplicação foi pensada para uso em painel de monitoramento e para composição visual em transmissões ao vivo.
- A interface está pronta para ser usada como dashboard em tela ampla, projeto visual de navegação ou fonte de captura do OBS em livestream.

---

## Licença

Este projeto não especifica licença no momento. Se for um projeto interno ou pessoal, a utilização pode ser ajustada conforme a necessidade do responsável.
