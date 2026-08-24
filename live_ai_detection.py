"""
Live AI detekcija anomalija (ELKON demo)

Sluša MQTT senzorske podatke, ocjenjuje ih istreniranim Isolation Forest
modelom, i pri promjeni stanja (normalno <-> anomalija) šalje alarm na
poseban topik (elkon/pumpa1/ai_alarm) - odvojeno od klasičnog SCADA
prag-alarma u Node-RED-u, da se na dashboardu vidi razlika između
klasičnog i AI pristupa.

Zavisnosti: paho-mqtt, joblib, scikit-learn
Potrebni fajlovi: isolation_forest_model.joblib, feature_scaler.joblib
"""

import argparse
import json
import time

import joblib
import numpy as np
import paho.mqtt.client as mqtt

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
TOPIC_SENZORI = "elkon/pumpa1/senzori"
TOPIC_AI_ALARM = "elkon/pumpa1/ai_alarm"
MODEL_PATH = "isolation_forest_model.joblib"
SCALER_PATH = "feature_scaler.joblib"


class AIDetektor:
    def __init__(self, model_path: str, scaler_path: str):
        self.model = joblib.load(model_path)
        self.scaler = joblib.load(scaler_path)
        self.trenutno_anomalija = False  # za edge-detection alarma

    def oceni_uzorak(self, vibration_mms: float, current_a: float):
        X = self.scaler.transform(np.array([[vibration_mms, current_a]]))
        je_anomalija = self.model.predict(X)[0] == -1
        score = float(self.model.decision_function(X)[0])  # nize = sigurnije anomalija
        return je_anomalija, score


def main():
    parser = argparse.ArgumentParser(description="Live AI detekcija anomalija - ELKON demo")
    parser.add_argument("--broker", default=MQTT_BROKER)
    parser.add_argument("--port", type=int, default=MQTT_PORT)
    parser.add_argument("--model", default=MODEL_PATH)
    parser.add_argument("--scaler", default=SCALER_PATH)
    args = parser.parse_args()

    detektor = AIDetektor(args.model, args.scaler)

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"[GRESKA] neispravan JSON: {e}")
            return

        vibration = payload.get("vibration_mms")
        current = payload.get("current_a")
        if vibration is None or current is None:
            return

        je_anomalija, score = detektor.oceni_uzorak(vibration, current)
        print(f"vib={vibration:.2f} cur={current:.2f} -> "
              f"{'ANOMALIJA' if je_anomalija else 'normalno'} (score={score:.3f})")

        if je_anomalija and not detektor.trenutno_anomalija:
            client.publish(TOPIC_AI_ALARM, json.dumps({
                "device": payload.get("device", "unknown"),
                "ts_ms": int(time.time() * 1000),
                "ai_anomaly": True,
                "anomaly_score": round(score, 3),
                "vibration_mms": vibration,
                "current_a": current,
            }))
        elif not je_anomalija and detektor.trenutno_anomalija:
            client.publish(TOPIC_AI_ALARM, json.dumps({
                "device": payload.get("device", "unknown"),
                "ts_ms": int(time.time() * 1000),
                "ai_anomaly": False,
            }))

        detektor.trenutno_anomalija = je_anomalija

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            client.subscribe(TOPIC_SENZORI)
            print(f"[MQTT] Povezano, pretplacen na {TOPIC_SENZORI}")
        else:
            print(f"[MQTT] Greska pri povezivanju: {rc}")

    client = mqtt.Client(client_id="ai_detektor_pumpa1")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.broker, args.port, keepalive=60)

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        client.disconnect()


if __name__ == "__main__":
    main()
