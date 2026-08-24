# AI-potpomognuti SCADA sistem za prediktivno održavanje pumpi

Demonstracioni projekat koji kombinuje klasičan SCADA nadzor sa AI slojem za ranu detekciju anomalija — razvijen kao praktičan dokaz sposobnosti uz prijavu za poziciju **Inženjer za automatizaciju i razvoj vještačke inteligencije** (ELKON d.o.o.).

Sistem nadzire rad pumpe (vibracija + struja motora) kroz dva paralelna mehanizma:

- **Klasični SCADA alarm** — fiksni granični pragovi (npr. vibracija > 8 mm/s), standardan industrijski pristup, prikazan uživo na Node-RED dashboardu.
- **AI rana detekcija** — Isolation Forest model uči normalan obrazac rada pumpe iz istorijskih podataka i prepoznaje neuobičajene *kombinacije* vibracije i struje, često i prije nego što se pređe klasičan prag.

## Arhitektura

```
ESP32 (senzori)                 
      │  MQTT (JSON)
      ▼
Mosquitto broker
      │
      ├──────────────► Node-RED  ──► SCADA dashboard (gauge, trend, klasični alarm)
      │
      ▼
Python AI (Isolation Forest)
      │  MQTT (AI alarm, poseban topik)
      ▼
Node-RED  ──► AI indikator na dashboardu
```

Protok podataka: `ESP32 → MQTT → Node-RED (SCADA prikaz) → Python AI model → MQTT (AI alarm) → Node-RED (AI indikator)`

## Napomena o hardveru

Za potrebe demonstracije, pravi vibracioni i strujni senzor (ADXL345, ACS712) zamijenjeni su sa dva potenciometra kao analognim ulazima na ESP32 (GPIO34, GPIO35) — identičan tip signala kao kod pravih senzora. Kod je namjerno strukturiran (`readVibrationRaw()` / `readCurrentRaw()`) tako da je prelazak na prave senzore izmjena od svega nekoliko linija.

## Sadržaj repozitorijuma

| Fajl | Opis |
|---|---|
| `esp32_scada_node.ino` | Firmver za ESP32 — čita senzore, šalje JSON preko MQTT-a |
| `mqtt_sensor_simulator.py` | Nezavisan simulator podataka pumpe (live i bulk režim) — za testiranje bez hardvera i generisanje trening baze |
| `train_ai_model.py` | Trening Isolation Forest modela na istorijskim podacima, sa evaluacijom |
| `live_ai_detection.py` | Live AI detekcija — sluša MQTT podatke uživo, šalje AI alarm |
| `node_red_scada_flow.json` | Node-RED flow — SCADA dashboard (gauge, trend grafikoni, klasični alarm) |
| `node_red_ai_alarm_nodes.json` | Dodatni Node-RED čvorovi — prikaz AI alarma na dashboardu |

## Pokretanje

### 1. MQTT broker (Mosquitto)

```bash
sudo apt install -y mosquitto mosquitto-clients
sudo systemctl enable --now mosquitto
```

Podesi broker da prihvata konekcije sa mreže (`/etc/mosquitto/conf.d/default.conf` ili ekvivalent):
```
listener 1883 0.0.0.0
allow_anonymous true
```

> Napomena: `allow_anonymous true` je u redu za lokalni demo, ne za produkciju bez dodatne autentifikacije.

### 2. ESP32 firmver

Otvori `esp32_scada_node.ino` u Arduino IDE-u (board: ESP32 Dev Module), popuni `WIFI_SSID`, `WIFI_PASSWORD` i `MQTT_BROKER` (IP adresa računara sa brokerom), uploaduj.

Hardver: potenciometar (10kΩ) na GPIO34 (vibracija-proxy) i GPIO35 (struja-proxy), napajanje **3.3V** (ne 5V).

Biblioteke: `PubSubClient`, `ArduinoJson`.

Alternativa bez hardvera — pokreni simulator:
```bash
pip install paho-mqtt --break-system-packages
python3 mqtt_sensor_simulator.py --mode live
```

### 3. Node-RED SCADA dashboard

```bash
npm install -g --unsafe-perm node-red
cd ~/.node-red && npm install node-red-dashboard
node-red
```

Otvori `http://localhost:1880`, uvezi `node_red_scada_flow.json` (Menu → Import), zatim `node_red_ai_alarm_nodes.json` (import u isti flow), **Deploy**.

Dashboard: `http://localhost:1880/ui`

### 4. Trening AI modela

```bash
pip install pandas scikit-learn joblib --break-system-packages

# generiši istorijsku bazu (bulk režim)
python3 mqtt_sensor_simulator.py --mode bulk --samples 5000 --output pumpa_istorijski_podaci.csv

# treniraj model (contamination = % anomalija iz ispisa prethodne komande)
python3 train_ai_model.py --input pumpa_istorijski_podaci.csv --contamination 0.018
```

### 5. Live AI detekcija

```bash
python3 live_ai_detection.py
```

Sluša `elkon/pumpa1/senzori`, šalje AI alarm na `elkon/pumpa1/ai_alarm` kad detektuje anomaliju.

## Korišćene tehnologije

ESP32 (Arduino/C++) · MQTT (Mosquitto) · Node-RED + Node-RED Dashboard · Python (pandas, scikit-learn, paho-mqtt, joblib) · Isolation Forest

## Status projekta

Demonstracioni projekat, razvijen u kratkom vremenskom roku kao praktičan dokaz sposobnosti — nije produkcioni sistem. Trening podaci su sintetički (generisani simulatorom), ne sa realnog pogona.

## Licenca

MIT
