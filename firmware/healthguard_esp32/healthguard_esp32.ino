// Academic integration prototype; measurements are not clinically validated.
#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <MAX30105.h> // SparkFun's class also supports MAX30102.
#include <spo2_algorithm.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <math.h>

#if defined(HEALTHGUARD_COMPILE_CHECK)
#include "secrets.h.example"
#elif __has_include("secrets.h")
#include "secrets.h"
#else
#error "Copy secrets.h.example to ignored secrets.h and configure it locally."
#endif

static_assert(HEALTHGUARD_STAGE >= 1 && HEALTHGUARD_STAGE <= 3, "Stage must be 1, 2 or 3");
static_assert(HEALTHGUARD_PATIENT_ID > 0 && HEALTHGUARD_PATIENT_ID <= INT64_MAX, "Invalid patient ID");
static_assert(HEALTHGUARD_MAX_ACCEPTED >= 0, "Invalid accepted-post limit");

constexpr uint8_t SDA_PIN = 21, SCL_PIN = 22, TEMPERATURE_PIN = 4;
// Match the library Maxim algorithm: 100 Hz acquisition averaged by 4 = 25 Hz.
constexpr size_t WINDOW = 100, STEP = 25;
constexpr uint32_t POST_INTERVAL_MS = 2000, MAX_SNAPSHOT_AGE_MS = 1500;
MAX30105 optical;
OneWire oneWire(TEMPERATURE_PIN);
DallasTemperature temperatures(&oneWire);
DeviceAddress temperatureAddress;
uint32_t redSamples[WINDOW], irSamples[WINDOW];
size_t sampleCount = 0;
float latestTemperature = NAN;
uint32_t temperatureStarted = 0, temperatureAt = 0, lastService = 0, lastSample = 0;
struct Snapshot { int32_t heartRate, spo2; float temperature; uint32_t sampledAt; };
QueueHandle_t snapshots;

void halt(const char *reason) {
    Serial.println(reason);
    Serial.println("Stopped. Check hardware/configuration, then reset; no HTTP submissions.");
    while (true) delay(1000);
}

void resetOpticalWindow() {
    sampleCount = 0;
    optical.clearFIFO();
    while (optical.available()) optical.nextSample();
    xQueueReset(snapshots);
}

void updateTemperature() {
    if (millis() - temperatureStarted < 750) return; // Async 12-bit conversion.
    latestTemperature = NAN;
    if (temperatures.isConversionComplete()) {
        float value = temperatures.getTempC(temperatureAddress);
        // Disconnected (-127), startup (85), non-finite and API-invalid values are rejected.
        if (value != DEVICE_DISCONNECTED_C && value != 85.0f && isfinite(value) && value >= 20 && value <= 50) {
            latestTemperature = value;
            temperatureAt = millis();
        }
    }
    if (!isfinite(latestTemperature)) {
        Serial.println("DS18B20 conversion invalid/disconnected/outside API bounds; skipping snapshot.");
        xQueueReset(snapshots);
    }
    temperatures.requestTemperaturesByAddress(temperatureAddress);
    temperatureStarted = millis();
}

void evaluateWindow() {
    int32_t oxygen = 0, pulse = 0;
    int8_t oxygenValid = 0, pulseValid = 0;
    maxim_heart_rate_and_oxygen_saturation(irSamples, WINDOW, redSamples,
                                         &oxygen, &oxygenValid, &pulse, &pulseValid);
    Serial.printf("PPG red=%lu IR=%lu HRvalid=%d SpO2valid=%d\n",
                  (unsigned long)redSamples[WINDOW - 1], (unsigned long)irSamples[WINDOW - 1],
                  pulseValid, oxygenValid);
    // Input sanity bounds only. Demo alert rules remain exclusively on FastAPI.
    if (pulseValid && oxygenValid && pulse > 0 && pulse <= 300 && oxygen >= 0 && oxygen <= 100 &&
        isfinite(latestTemperature) && millis() - temperatureAt <= 2000) {
        Snapshot sample{pulse, oxygen, latestTemperature, millis()};
        Serial.printf("Sensor HR=%ld bpm SpO2=%ld %% Temp=%.2f C\n", (long)pulse, (long)oxygen, latestTemperature);
        xQueueOverwrite(snapshots, &sample); // Latest-only mailbox, not an offline delivery queue.
    } else {
        Serial.println("Unusable sensor result; check contact/motion/temperature. No fabricated values.");
        xQueueReset(snapshots);
    }
    memmove(redSamples, redSamples + STEP, (WINDOW - STEP) * sizeof(uint32_t));
    memmove(irSamples, irSamples + STEP, (WINDOW - STEP) * sizeof(uint32_t));
    sampleCount = WINDOW - STEP;
}

// Network operations have their own task; HTTP timeouts cannot block optical acquisition.
void networkTask(void *) {
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.println("Wi-Fi connecting...");
    uint32_t reconnectAt = millis(), nextPost = 0, accepted = 0, failures = 0;
    bool wasConnected = false;
    for (;;) {
        if (WiFi.status() != WL_CONNECTED) {
            if (wasConnected) Serial.println("Wi-Fi disconnected; sampling continues.");
            wasConnected = false;
            if (millis() - reconnectAt >= 10000) {
                Serial.println("Wi-Fi reconnecting...");
                WiFi.reconnect();
                reconnectAt = millis();
            }
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }
        if (!wasConnected) {
            Serial.print("Wi-Fi connected. IP: "); Serial.println(WiFi.localIP());
            wasConnected = true;
        }
        Snapshot sample;
        if ((int32_t)(millis() - nextPost) < 0 || xQueueReceive(snapshots, &sample, 0) != pdTRUE) {
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }
        if (millis() - sample.sampledAt > MAX_SNAPSHOT_AGE_MS) continue;
        char payload[160];
        int length = snprintf(payload, sizeof(payload),
            "{\"patient_id\":%lld,\"heart_rate\":%ld,\"spo2\":%ld,\"temperature_c\":%.2f}",
            (long long)HEALTHGUARD_PATIENT_ID, (long)sample.heartRate, (long)sample.spo2, sample.temperature);
        if (length < 0 || (size_t)length >= sizeof(payload)) {
            Serial.println("JSON buffer error; HTTP stopped."); vTaskDelete(nullptr);
        }
        WiFiClient client;
        HTTPClient http;
        http.setConnectTimeout(2000);
        http.setTimeout(2000);
        http.setReuse(false);
        if (!http.begin(client, HEALTHGUARD_SERVER_URL)) {
            Serial.println("Invalid server URL; HTTP stopped."); vTaskDelete(nullptr);
        }
        http.addHeader("Content-Type", "application/json");
        Serial.print("POST /api/readings payload: "); Serial.println(payload);
        int status = http.POST((uint8_t *)payload, length);
        Serial.printf("HTTP %d\n", status);
        http.end();
        if (status == 201) {
            failures = 0;
            Serial.printf("Reading accepted (%lu)\n", (unsigned long)++accepted);
            if (HEALTHGUARD_MAX_ACCEPTED && accepted >= HEALTHGUARD_MAX_ACCEPTED) {
                Serial.println("Accepted-post limit reached. Submissions stopped; reset to resume.");
                vTaskDelete(nullptr);
            }
            nextPost = millis() + POST_INTERVAL_MS;
        } else if (status >= 300 && status < 500) {
            Serial.println("Request/configuration rejected. Check URL/patient/payload; reset after correction.");
            vTaskDelete(nullptr);
        } else {
            Serial.println("Server/network failure; outcome may be unknown. No replay of this snapshot.");
            if (++failures >= 3) {
                Serial.println("Three submission failures; HTTP stopped. Check server, then reset.");
                vTaskDelete(nullptr);
            }
            nextPost = millis() + (5000UL << (failures - 1));
        }
    }
}

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("ESP32 booted — HealthGuard academic prototype");
    snapshots = xQueueCreate(1, sizeof(Snapshot));
    if (!snapshots) halt("Snapshot mailbox allocation failed");
    Wire.begin(SDA_PIN, SCL_PIN);
    Wire.setTimeOut(50);
    if (!optical.begin(Wire, I2C_SPEED_FAST)) halt("MAX30102 initialization failed");
    Serial.println("MAX30102-compatible device found (confirm actual module marking)");
    temperatures.begin();
    if (!temperatures.getAddress(temperatureAddress, 0) || temperatureAddress[0] != 0x28 ||
        !temperatures.isConnected(temperatureAddress)) halt("DS18B20 initialization failed");
    if (temperatures.isParasitePowerMode()) halt("Use externally powered DS18B20; parasite power is unsupported here");
    Serial.println("DS18B20 found");
    if (HEALTHGUARD_STAGE == 1) halt("Detection stage passed. Physically verify wiring before stage 2");
    temperatures.setResolution(temperatureAddress, 12);
    temperatures.setWaitForConversion(false);
    temperatures.requestTemperaturesByAddress(temperatureAddress);
    temperatureStarted = millis();
    optical.setup(60, 4, 2, 100, 411, 4096); // red + IR only, library algorithm acquisition settings.
    resetOpticalWindow();
    lastService = lastSample = millis();
    if (HEALTHGUARD_STAGE == 3) {
        String url(HEALTHGUARD_SERVER_URL);
        if (!url.startsWith("http://") || !url.endsWith("/api/readings") ||
            url.indexOf("localhost") >= 0 || url.indexOf("127.0.0.1") >= 0 ||
            url.indexOf("0.0.0.0") >= 0 || url.indexOf("YOUR_") >= 0 ||
            String(WIFI_SSID).startsWith("YOUR_")) halt("Configure trusted LAN URL and Wi-Fi in secrets.h");
        if (xTaskCreatePinnedToCore(networkTask, "healthguard-http", 8192, nullptr, 1, nullptr, 0) != pdPASS)
            halt("Network task allocation failed");
    } else Serial.println("Serial-only measurement stage: Wi-Fi/HTTP disabled.");
}

void loop() {
    // Library software FIFO is small. Discard a window if servicing was delayed;
    // never calculate across lost samples or silently treat gaps as uniform data.
    if (millis() - lastService > 100 || millis() - lastSample > 500) {
        resetOpticalWindow();
        lastSample = millis();
        Serial.println("Optical sample gap; collecting a new complete window.");
    }
    lastService = millis();
    if (optical.check() >= STORAGE_SIZE) {
        resetOpticalWindow();
        Serial.println("Optical driver FIFO overrun; discarding incomplete window.");
        return;
    }
    while (optical.available()) {
        redSamples[sampleCount] = optical.getFIFORed();
        irSamples[sampleCount] = optical.getFIFOIR();
        optical.nextSample();
        lastSample = millis();
        if (++sampleCount == WINDOW) evaluateWindow();
    }
    updateTemperature();
    delay(1); // Yield to RTOS, not a fixed multi-second sampling delay.
}
