// ESP32: 4 soil moisture sensors -> server, and relay <- pump command
#include <WiFi.h>
#include <HTTPClient.h>
const char* SSID = "YOUR_WIFI";
const char* PASS = "YOUR_PASSWORD";
String SERVER = "http://192.168.1.10:5000";   // your laptop IP or ngrok URL
const int SENSOR[4] = {34, 35, 32, 33};       // analog pins
const int RELAY = 26;
const int DRY = 3200, WET = 1300;             // calibrate: raw value in air / in water

int pct(int raw) { return constrain(map(raw, DRY, WET, 0, 100), 0, 100); }

void setup() {
  Serial.begin(115200);
  pinMode(RELAY, OUTPUT); digitalWrite(RELAY, LOW);
  WiFi.begin(SSID, PASS);
  while (WiFi.status() != WL_CONNECTED) delay(500);
}

void loop() {
  HTTPClient h;
  String body = "{\"zones\":[";
  for (int i = 0; i < 4; i++) body += String(pct(analogRead(SENSOR[i]))) + (i < 3 ? "," : "");
  body += "]}";
  h.begin(SERVER + "/api/sensor"); h.addHeader("Content-Type", "application/json");
  h.POST(body); h.end();

  h.begin(SERVER + "/api/pump");
  if (h.GET() == 200) digitalWrite(RELAY, h.getString().indexOf("true") > 0 ? HIGH : LOW);
  h.end();
  delay(3000);
}
