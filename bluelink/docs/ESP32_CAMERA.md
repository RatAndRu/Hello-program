# DIY-очки на ESP32: прошивка под BlueLink

Если делать очки (или шлем, или камеру-кулон) самому, удобнее всего ESP32-CAM: камера, BLE и
Wi-Fi в одной плате. Ниже — минимальная прошивка, которая отдаёт снимок **двумя способами**:

- **по BLE** — уведомлениями в характеристику `FFE2` (профиль «BLE-камера»);
- **по Wi-Fi/HTTP** — по адресу `http://192.168.4.1/capture` (профиль «Камера по Wi-Fi»).

Проверено на AI-Thinker ESP32-CAM; для других плат поменяйте распиновку.

## Что нужно

- Arduino IDE (или PlatformIO) + ядро ESP32;
- библиотека **NimBLE-Arduino**;
- Модуль ESP32-CAM + USB-TTL переходник для прошивки.

## Прошивка

```cpp
#include <NimBLEDevice.h>
#include <WiFi.h>
#include <WebServer.h>
#include "esp_camera.h"
#include "esp_timer.h"

// --- UUID совпадают с профилем «BLE-камера (шаблон)» в BlueLink ---
#define SERVICE_UUID "0000ffe0-0000-1000-8000-00805f9b34fb"
#define TRIGGER_UUID "0000ffe1-0000-1000-8000-00805f9b34fb"
#define DATA_UUID    "0000ffe2-0000-1000-8000-00805f9b34fb"

#define WIFI_SSID "GlassCam"
#define WIFI_PASS "12345678"

// Распиновка AI-Thinker ESP32-CAM
#define PWDN_GPIO_NUM 32
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM 0
#define SIOD_GPIO_NUM 26
#define SIOC_GPIO_NUM 27
#define Y9_GPIO_NUM 35
#define Y8_GPIO_NUM 34
#define Y7_GPIO_NUM 39
#define Y6_GPIO_NUM 36
#define Y5_GPIO_NUM 21
#define Y4_GPIO_NUM 19
#define Y3_GPIO_NUM 18
#define Y2_GPIO_NUM 5
#define VSYNC_GPIO_NUM 25
#define HREF_GPIO_NUM 23
#define PCLK_GPIO_NUM 22

NimBLECharacteristic *dataChar = nullptr;
WebServer server(80);

void setupCamera() {
  camera_config_t config = {};
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM; config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM; config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM; config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM; config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM; config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM; config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM; config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM; config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = FRAMESIZE_VGA;   // 640x480: быстрый старт, можно поднять до SVGA
  config.jpeg_quality = 12;
  config.fb_count = 2;
  if (esp_camera_init(&config) != ESP_OK) {
    Serial.println("Камера не найдена");
  }
}

camera_fb_t *takePhoto() {
  // Несколько попыток: после простоя первый кадр часто пустой
  for (int i = 0; i < 3; i++) {
    camera_fb_t *fb = esp_camera_fb_get();
    if (fb && fb->len > 1000) return fb;
    if (fb) esp_camera_fb_return(fb);
    delay(120);
  }
  return nullptr;
}

// Отправка JPEG уведомлениями, кусками по MTU-3
void sendPhotoOverBle() {
  camera_fb_t *fb = takePhoto();
  if (!fb) { Serial.println("Снимок не удался"); return; }
  uint16_t chunk = NimBLEDevice::getMTU() - 3;
  Serial.printf("JPEG %u байт, куски по %u\n", fb->len, chunk);
  for (size_t off = 0; off < fb->len; off += chunk) {
    size_t len = min((size_t)chunk, fb->len - off);
    dataChar->setValue(fb->buf + off, len);
    dataChar->notify();
    delay(8);                          // даём стеку BLE отправить пакет
  }
  esp_camera_fb_return(fb);
}

void handleCapture() {
  camera_fb_t *fb = takePhoto();
  if (!fb) { server.send(500, "text/plain", "capture failed"); return; }
  WiFiClient client = server.client();
  server.sendHeader("Content-Type", "image/jpeg");
  server.sendHeader("Content-Length", String(fb->len));
  server.setContentLength(fb->len);
  server.send(200, "image/jpeg", "");
  client.write(fb->buf, fb->len);
  esp_camera_fb_return(fb);
}

class TriggerCallback : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic *c) override {
    std::string value = c->getValue();
    if (!value.empty() && value[0] == 0x01) {
      Serial.println("Команда съёмки по BLE");
      sendPhotoOverBle();
    }
  }
};

void setup() {
  Serial.begin(115200);
  setupCamera();

  // Wi-Fi: очки поднимают свою точку доступа
  WiFi.softAP(WIFI_SSID, WIFI_PASS);
  Serial.print("AP: "); Serial.println(WiFi.softAPIP());  // обычно 192.168.4.1
  server.on("/capture", HTTP_GET, handleCapture);
  server.on("/photo.jpg", HTTP_GET, handleCapture);
  server.begin();

  // BLE
  NimBLEDevice::init("GlassCam");
  NimBLEDevice::setMTU(247);
  NimBLEServer *srv = NimBLEDevice::createServer();
  NimBLEService *svc = srv->createService(SERVICE_UUID);

  dataChar = svc->createCharacteristic(DATA_UUID, NIMBLE_PROPERTY::NOTIFY);
  NimBLECharacteristic *trigger =
      svc->createCharacteristic(TRIGGER_UUID, NIMBLE_PROPERTY::WRITE);
  trigger->setCallbacks(new TriggerCallback());

  svc->start();
  NimBLEAdvertising *adv = NimBLEDevice::getAdvertising();
  adv->addServiceUUID(SERVICE_UUID);
  adv->setName("GlassCam");
  adv->start();
}

void loop() {
  server.handleClient();
  delay(2);
}
```

## Как подключить к BlueLink

**Вариант 1 — BLE (без Wi-Fi):**

1. BlueLink → «Поиск» → «Сканировать» → подключиться к `GlassCam`.
2. «Профили» → профиль **«BLE-камера (шаблон)»** → «Выбрать».
3. «Камера» → «Снять фото». JPEG придёт уведомлениями и сохранится.

**Вариант 2 — Wi-Fi (быстрее и качественнее):**

1. «Профили» → **«Камера по Wi-Fi (шаблон)»** → «Изменить»: проверьте `wifiSsid = GlassCam`,
   пароль `12345678`, `httpUrl = http://192.168.4.1/capture`.
2. «Выбрать» → «Камера» → «Снять фото». Телефон сам подключится к точке доступа очков.

## Нюансы

- **BLE и Wi-Fi одновременно** на ESP32 работают, но Wi-Fi-точка заметно снижает скорость BLE.
  Для экономии энергии можно поднимать точку доступа только по команде.
- **Размер кадра.** VGA (640×480) по BLE — 3–8 секунд. SVGA/UXGA лучше отдавать по Wi-Fi.
- **MTU.** BlueLink запрашивает 247 байт; в прошивке тоже стоит `setMTU(247)`. Если кадр
  приходит рваными кусками, уменьшите `chunk` до 20 байт.
- **Яркий свет** и стабильное питание важнее мегапикселей: ESP32-CAM чувствителен к просадкам
  напряжения, при них кадры ломаются.
- Если хочется отдавать **заголовок с размером** (4 байта) перед JPEG, включите в профиле
  `"framing": "sizeHeader"` и отправьте эти 4 байта первым уведомлением.
