"""
============================================================================
MQTT SIMULATOR SENZORA PUMPE (ELKON demo projekat)
============================================================================

SVRHA:
Ovaj program NE ZAVISI od ESP32 hardvera. On generiše realistične
sintetičke podatke koji liče na signal sa vibracionog i strujnog senzora
pumpe, i šalje ih na ISTI MQTT topik i u ISTOM JSON formatu kao ESP32
firmver (esp32_scada_node.ino). Zahvaljujući tome, Node-RED dashboard i
Python AI skripta za detekciju anomalija ne prave nikakvu razliku između
"pravih" podataka sa ESP32-a i ovih simuliranih - potpuno su zamjenjivi.

ZAŠTO NAM TREBA:
1) TRENIRANJE AI MODELA zahtijeva stotine/hiljade uzoraka "normalnog" rada
   pumpe. Ručno okretanje potenciometra na ESP32-u satima je nerealno -
   zato ovaj simulator može da generiše veliku istorijsku bazu podataka
   za nekoliko sekundi (--mode bulk).
2) TESTIRANJE DASHBOARDA čak i kad ESP32 nije priključen ili nije pri
   ruci (--mode live).

DVA REŽIMA RADA:
  --mode live   -> šalje po jedan uzorak u sekundi (kao pravi ESP32),
                   koristan za live demo dashboarda bez hardvera
  --mode bulk   -> generiše N uzoraka odmah (bez čekanja) i upisuje ih
                   u CSV fajl - koristan za treniranje AI modela

MODEL PONAŠANJA PUMPE:
- Normalan rad: vibracija i struja osciluju oko baznih vrijednosti sa
  malim šumom (kao stvarna mehanička vibracija i mreža).
- Povremeno (konfigurabilna vjerovatnoća) simulator ulazi u "kvar" -
  postepeni porast vibracije (habanje ležaja) i/ili strujni udar
  (preopterećenje) - baš ono što AI model treba da nauči da prepozna.

POTREBNA BIBLIOTEKA:
  pip install paho-mqtt
============================================================================
"""

import argparse
import csv
import json
import math
import random
import time
from datetime import datetime

import paho.mqtt.client as mqtt

# ---------------------------------------------------------------------------
# KONFIGURACIJA - mora biti IDENTIČNA kao u ESP32 firmveru
# ---------------------------------------------------------------------------
MQTT_BROKER = "localhost"          # ako simulator radi na istom računaru kao Mosquitto
MQTT_PORT = 1883
MQTT_TOPIC = "elkon/pumpa1/senzori"
DEVICE_ID = "simulator_pumpa1"

# ---------------------------------------------------------------------------
# PARAMETRI NORMALNOG RADA PUMPE (podesivo prema tome kako želiš da "izgleda")
# ---------------------------------------------------------------------------
VIBRATION_BASELINE_MMS = 2.5   # tipična vibracija zdrave pumpe
VIBRATION_NOISE_STD = 0.3      # slučajni šum (standardna devijacija)

CURRENT_BASELINE_A = 4.0       # tipična radna struja motora
CURRENT_NOISE_STD = 0.2

# ---------------------------------------------------------------------------
# PARAMETRI SIMULIRANOG KVARA
# ---------------------------------------------------------------------------
FAULT_PROBABILITY_PER_SAMPLE = 0.003   # ~0.3% šanse po uzorku da počne kvar
FAULT_DURATION_SAMPLES = (60, 200)     # trajanje epizode kvara (u broju uzoraka)
FAULT_VIBRATION_EXTRA_MMS = 8.0        # koliko vibracija poraste tokom kvara
FAULT_CURRENT_EXTRA_A = 3.5            # koliko struja poraste tokom kvara


class PumpSimulator:
    """
    Drži unutrašnje stanje simulacije (da li je pumpa trenutno u kvaru,
    koliko dugo, itd.) i generiše jedan uzorak podataka po pozivu.
    """

    def __init__(self):
        self.sample_count = 0
        self.in_fault = False
        self.fault_samples_remaining = 0
        self.fault_progress = 0  # koristi se za postepen (ne nagli) porast

    def generate_sample(self):
        self.sample_count += 1

        # --- Odluka da li ulazimo u novu epizodu kvara ---
        if not self.in_fault and random.random() < FAULT_PROBABILITY_PER_SAMPLE:
            self.in_fault = True
            self.fault_samples_remaining = random.randint(*FAULT_DURATION_SAMPLES)
            self.fault_progress = 0
            print(f"[SIMULATOR] >>> Pocinje simulirani KVAR "
                  f"(trajanje ~{self.fault_samples_remaining} uzoraka)")

        # --- Bazne (zdrave) vrijednosti + slučajni šum ---
        vibration = random.gauss(VIBRATION_BASELINE_MMS, VIBRATION_NOISE_STD)
        current = random.gauss(CURRENT_BASELINE_A, CURRENT_NOISE_STD)

        # blaga periodična komponenta (imitira rotaciju osovine/harmoniku)
        vibration += 0.4 * math.sin(self.sample_count / 15.0)

        # --- Ako smo u kvaru, dodajemo postepeno rastući "fault signal" ---
        if self.in_fault:
            self.fault_progress += 1
            # trougaoni profil: raste pa opada, realističnije od naglog skoka
            severity = min(self.fault_progress, self.fault_samples_remaining - self.fault_progress)
            severity = max(severity, 0) / (self.fault_samples_remaining / 2)
            severity = min(severity, 1.0)

            vibration += FAULT_VIBRATION_EXTRA_MMS * severity
            current += FAULT_CURRENT_EXTRA_A * severity

            self.fault_samples_remaining -= 1
            if self.fault_samples_remaining <= 0:
                self.in_fault = False
                print("[SIMULATOR] <<< Kvar zavrsen, pumpa se vraca u normalan rad")

        # vrijednosti ne mogu biti negativne (fizički nemoguće)
        vibration = max(vibration, 0.0)
        current = max(current, 0.0)

        return {
            "device": DEVICE_ID,
            "ts_ms": int(time.time() * 1000),
            "vibration_mms": round(vibration, 2),
            "current_a": round(current, 2),
            "is_simulated_fault": self.in_fault,  # KORISNO za treniranje AI (label),
                                                     # ali NE šaljemo ovo polje na MQTT
                                                     # (pravi senzor to ne bi znao) -
                                                     # koristi se samo za CSV/trening
        }


def run_live_mode(interval_s: float):
    """
    Šalje po jedan uzorak u sekundi preko MQTT-a - ponaša se kao ESP32.
    Koristan za testiranje dashboarda kad hardver nije pri ruci.
    """
    print(f"[MQTT] Povezivanje na broker {MQTT_BROKER}:{MQTT_PORT} ...")
    client = mqtt.Client(client_id=DEVICE_ID)
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.loop_start()
    print("[MQTT] Povezano. Pocinje slanje simuliranih podataka (Ctrl+C za prekid)")

    sim = PumpSimulator()

    try:
        while True:
            sample = sim.generate_sample()

            # Za MQTT payload uklanjamo interno "is_simulated_fault" polje -
            # pravi senzor/ESP32 ne bi znao tu informaciju, a format mora
            # ostati identičan onome iz esp32_scada_node.ino
            mqtt_payload = {
                "device": sample["device"],
                "ts_ms": sample["ts_ms"],
                "vibration_mms": sample["vibration_mms"],
                "current_a": sample["current_a"],
            }

            payload_json = json.dumps(mqtt_payload)
            result = client.publish(MQTT_TOPIC, payload_json)

            status = "OK" if result.rc == mqtt.MQTT_ERR_SUCCESS else "GRESKA"
            fault_marker = " [KVAR]" if sample["is_simulated_fault"] else ""
            print(f"[DATA] vibracija={sample['vibration_mms']:.2f} mm/s, "
                  f"struja={sample['current_a']:.2f} A  |  publish: {status}{fault_marker}")

            time.sleep(interval_s)

    except KeyboardInterrupt:
        print("\n[SIMULATOR] Prekinuto od strane korisnika. Zatvaram MQTT konekciju...")
        client.loop_stop()
        client.disconnect()


def run_bulk_mode(num_samples: int, output_csv: str):
    """
    Generise veliku kolicinu istorijskih podataka ODMAH (bez cekanja) i
    upisuje ih u CSV fajl - koristi se za treniranje AI modela za
    detekciju anomalija (Isolation Forest i sl.), jer je ucenju potrebno
    nekoliko stotina/hiljada uzoraka normalnog (i po koji anomalni) rada.
    """
    print(f"[BULK] Generisem {num_samples} uzoraka u fajl '{output_csv}' ...")

    sim = PumpSimulator()
    rows = []

    for i in range(num_samples):
        sample = sim.generate_sample()
        rows.append(sample)

        if (i + 1) % 500 == 0:
            print(f"[BULK] ... {i + 1}/{num_samples} uzoraka generisano")

    with open(output_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "device", "ts_ms", "vibration_mms", "current_a", "is_simulated_fault"
        ])
        writer.writeheader()
        writer.writerows(rows)

    fault_count = sum(1 for r in rows if r["is_simulated_fault"])
    print(f"[BULK] Zavrseno. Upisano {len(rows)} redova u '{output_csv}'.")
    print(f"[BULK] Od toga {fault_count} uzoraka je bilo tokom simuliranog kvara "
          f"({100 * fault_count / len(rows):.1f}%).")
    print("[BULK] Ovaj CSV mozes direktno koristiti za treniranje AI modela "
          "(kolona 'is_simulated_fault' ti sluzi za provjeru tacnosti modela, "
          "iako sam model ucenja NE treba da vidi tu kolonu tokom treniranja).")


def main():
    parser = argparse.ArgumentParser(
        description="Simulator senzora pumpe za ELKON demo projekat"
    )
    parser.add_argument(
        "--mode", choices=["live", "bulk"], default="live",
        help="'live' = salji preko MQTT-a u realnom vremenu, "
             "'bulk' = generisi CSV bazu za treniranje AI modela"
    )
    parser.add_argument(
        "--interval", type=float, default=1.0,
        help="Interval slanja u sekundama za 'live' rezim (podrazumijevano 1.0)"
    )
    parser.add_argument(
        "--samples", type=int, default=5000,
        help="Broj uzoraka za 'bulk' rezim (podrazumijevano 5000)"
    )
    parser.add_argument(
        "--output", type=str, default="pumpa_istorijski_podaci.csv",
        help="Naziv CSV fajla za 'bulk' rezim"
    )

    args = parser.parse_args()

    print("============================================================")
    print("  MQTT SIMULATOR SENZORA PUMPE - ELKON demo")
    print(f"  Pokrenuto: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("============================================================")

    if args.mode == "live":
        run_live_mode(args.interval)
    else:
        run_bulk_mode(args.samples, args.output)


if __name__ == "__main__":
    main()
