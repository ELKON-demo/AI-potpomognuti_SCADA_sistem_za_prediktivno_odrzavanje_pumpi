/*
  ESP32 SCADA cvor - nadzor pumpe (ELKON demo projekat)

  Cita dva potenciometra (proxy za vibracioni i strujni senzor - fizicki
  senzor nije bio dostupan u roku) i salje podatke preko MQTT-a u JSON
  formatu. readVibrationRaw()/readCurrentRaw() su izdvojene namjerno -
  zamjena potenciometra pravim senzorom (ADXL345 / ACS712) ide samo kroz
  te dvije funkcije, ostatak koda se ne dira.

  Pinovi: GPIO34 (vibracija), GPIO35 (struja) - oba ADC1, input-only,
  bez konflikta sa WiFi radiom (ADC2 bi imao problem).

  Biblioteke: PubSubClient, ArduinoJson
*/

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// --- Konfiguracija ---
const char* WIFI_SSID     = "WIFI_IME";
const char* WIFI_PASSWORD = "WIFI_PASSWORD";

const char* MQTT_BROKER = "192.168.1.100";  // IP racunara sa Mosquitto brokerom
const int   MQTT_PORT   = 1883;
const char* MQTT_TOPIC  = "elkon/pumpa1/senzori";
const char* DEVICE_ID   = "esp32_pumpa1";

const unsigned long PUBLISH_INTERVAL_MS = 1000;

const int PIN_VIBRATION_PROXY = 34;
const int PIN_CURRENT_PROXY   = 35;

// Mapiranje ADC (0-4095) u realne jedinice - opsezi tipicni za manju pumpu
const float VIBRATION_MIN_MMS = 0.0, VIBRATION_MAX_MMS = 20.0;
const float CURRENT_MIN_A = 0.0, CURRENT_MAX_A = 15.0;

WiFiClient   wifiClient;
PubSubClient mqttClient(wifiClient);
unsigned long lastPublishTime = 0;

// --- Citanje senzora (apstrahovano zbog buduce zamjene hardvera) ---
int readVibrationRaw() {
  return analogRead(PIN_VIBRATION_PROXY);
  // Real sensor (ADXL345, I2C): magnituda ubrzanja umjesto analogRead()
}

int readCurrentRaw() {
  return analogRead(PIN_CURRENT_PROXY);
  // Real senzor (ACS712): isti analogni pristup, samo drugi mapping (mV/A)
}

float mapValue(int rawAdc, float outMin, float outMax) {
  return outMin + (outMax - outMin) * (rawAdc / 4095.0);
}

void connectWiFi() {
  Serial.print("[WiFi] Povezivanje na: ");
  Serial.println(WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 40) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println();
    Serial.print("[WiFi] Povezan, IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\n[WiFi] Neuspjelo povezivanje, restart");
    ESP.restart();
  }
}

void connectMQTT() {
  while (!mqttClient.connected()) {
    Serial.print("[MQTT] Konekcija na broker... ");
    if (mqttClient.connect(DEVICE_ID)) {
      Serial.println("OK");
    } else {
      Serial.print("greska rc=");
      Serial.println(mqttClient.state());
      delay(3000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  analogReadResolution(12);

  connectWiFi();
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  connectMQTT();
}

void loop() {
  if (!mqttClient.connected()) connectMQTT();
  mqttClient.loop();

  unsigned long now = millis();
  if (now - lastPublishTime >= PUBLISH_INTERVAL_MS) {
    lastPublishTime = now;

    int vibRaw = readVibrationRaw();
    int curRaw = readCurrentRaw();
    float vibrationMms = mapValue(vibRaw, VIBRATION_MIN_MMS, VIBRATION_MAX_MMS);
    float currentA      = mapValue(curRaw, CURRENT_MIN_A, CURRENT_MAX_A);

    // Format identican Python simulatoru - Node-RED/AI ne prave razliku izmedju izvora
    StaticJsonDocument<200> doc;
    doc["device"]        = DEVICE_ID;
    doc["ts_ms"]          = now;
    doc["vibration_mms"] = round(vibrationMms * 100) / 100.0;
    doc["current_a"]     = round(currentA * 100) / 100.0;

    char jsonBuffer[200];
    serializeJson(doc, jsonBuffer);
    bool sent = mqttClient.publish(MQTT_TOPIC, jsonBuffer);

    Serial.printf("vib=%.2f mm/s  cur=%.2f A  publish=%s\n",
                  vibrationMms, currentA, sent ? "OK" : "FAIL");
  }
}
