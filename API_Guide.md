# Документация API сервера телеметрии ПР200 (Systherm Multi-Cabinet API)

## 1. Базовые параметры подключения
* **Base URL:** `https://sslip.io`
* **Прямой TCP-порт для шкафов (HF2211):** `<SERVER_IP>:9000`
* **Формат данных:** `application/json; charset=utf-8`
* **Авторизация и разграничение прав:**
  Во все HTTP-запросы передается заголовок `X-API-Key`:
  ```http
  X-API-Key: <API_KEY>
  ```
  * **Ключ клиента** (значение `"api_key"` из файла `/opt/pr200_server/maps/<cab_id>.json`): открывает доступ **только к одному конкретному шкафу**.
  * **Мастер-ключ** (`<MASTER_API_KEY>`): открывает доступ **ко всем шкафам сразу**, а также позволяет загружать новые карты регистров через API.
* **Коды ответов:**
  * `200 OK` — запрос выполнен успешно.
  * `403 Forbidden` — неверный ключ или попытка доступа к чужому шкафу.
  * `503 Service Unavailable` — шкаф (`cab_id`) сейчас не в сети (`offline`), запись невозможна.

---

## 2. Методы (Endpoints)

### 2.1. Получение актуальных данных доступных шкафов (в реальном времени)
Рекомендуется опрашивать с интервалом `1–2 секунды` для обновления мнемосхемы и датчиков.

* **Запрос:** `GET /api/cabinets`
* **Пример ответа (`200 OK`):**
  ```json
  {
    "shkaf_01": {
      "online": true,
      "ts": 1794837829.4,
      "tags": {
        "Coils_1_N": 7296,
        "Coils_2_N": 256,
        "Tsup_N": 67,
        "Tret_N": 37,
        "Tout_N": -10.1,
        "InputPress_N": 4.79,
        "OutPress_N": 4.59
      }
    }
  }
  ```

---

### 2.2. Запись значения или команды в регистр ПР200
* **Запрос:** `POST /api/cabinets/{cab_id}/write`
* **Тело запроса (JSON):**
  ```json
  {
    "reg_addr": 552,
    "dtype": "float",
    "value": 1.5
  }
  ```
* **Параметры:** `reg_addr` (`int` — адрес регистра), `dtype` (`"word"` или `"float"`), `value` (`number`).
* **Ответ (`200 OK`):** `{"status": "ok"}`

---

### 2.3. Получение исторических данных (для графиков)
Данные пишутся в SQLite каждые `10 секунд` и хранятся `90 дней`.

* **Запрос:** `GET /api/cabinets/{cab_id}/history`
* **Query-параметры (необязательные):**
  * `tags` — имена параметров через запятую (например, `Tsup_N,Tout_N`). Если не указывать — вернутся все теги.
  * `from_ts` — начало периода (Unix timestamp в секундах, по умолчанию `текущее время - 3600`).
  * `to_ts` — конец периода (Unix timestamp в секундах, по умолчанию `текущее время`).
  * `limit` — лимит точек (по умолчанию `1000`).
* **Пример ответа (`200 OK`):**
  ```json
  {
    "cabinet_id": "shkaf_01",
    "from_ts": 1794830000.0,
    "to_ts": 1794840000.0,
    "series": {
      "Tsup_N": [[1794830010.2, 67.0], [1794830020.2, 68.0]],
      "Tout_N": [[1794830010.2, -10.1], [1794830020.2, -10.2]]
    }
  }
  ```

---

### 2.4. Получение карты регистров конкретного шкафа
Возвращает индивидуальную карту регистров, типов данных, адреса Modbus (`slave_id`) и комментариев для указанного шкафа.

* **Запрос:** `GET /api/cabinets/{cab_id}/map`
* **Пример ответа (`200 OK`):**
  ```json
  {
    "api_key": "u28Z4kZj9ejpa_0CIgmYouyN3u-z2KF-",
    "slave_id": 16,
    "start_reg": 512,
    "total_regs": 50,
    "tags": {
      "Tsup_N": {"reg": 514, "type": "word", "log": true, "comment": "Темп подачи отопления,С"},
      "InputPress_N": {"reg": 558, "type": "float", "log": false, "comment": "Даваление до насосов, бар"}
    }
  }
  ```

---

### 2.5. Загрузка / обновление карты нового шкафа (только для мастер-ключа)
Позволяет добавить новый шкаф (`shkaf_02`, `shkaf_03`...) без подключения по SSH.

* **Запрос:** `POST /api/cabinets/{cab_id}/map`
* **Тело запроса:** содержимое сгенерированного JSON-файла карты.
* **Ответ (`200 OK`):** `{"status": "saved", "cabinet_id": "shkaf_02"}`

---

## 3. Готовый класс-сервис для Flutter (Dart)

Требуется пакет `http` (`flutter pub add http`):

```dart
import 'dart:convert';
import 'package:http/http.dart' as http;

class Pr200ApiService {
  final String baseUrl;
  final String apiKey; // Ключ конкретного шкафа или мастер-ключ

  Pr200ApiService({
    this.baseUrl = 'https://sslip.io',
    required this.apiKey,
  });

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        'X-API-Key': apiKey,
      };

  /// 1. Получить актуальные данные по всем доступным шкафам
  Future<Map<String, dynamic>> getCabinets() async {
    final response = await http.get(
      Uri.parse('\$baseUrl/api/cabinets'),
      headers: _headers,
    );
    if (response.statusCode == 200) {
      return jsonDecode(utf8.decode(response.bodyBytes));
    }
    throw Exception('Ошибка получения данных: \${response.statusCode}');
  }

  /// 2. Записать новое значение в регистр ПР200
  Future<bool> writeRegister({
    required String cabinetId,
    required int regAddr,
    required String dtype, // 'word' или 'float'
    required num value,
  }) async {
    final response = await http.post(
      Uri.parse('baseUrl/api/cabinets/cabinetId/write'),
      headers: _headers,
      body: jsonEncode({
        'reg_addr': regAddr,
        'dtype': dtype,
        'value': value,
      }),
    );
    return response.statusCode == 200;
  }

  /// 3. Получить историю параметров для графиков
  Future<Map<String, List<dynamic>>> getHistory({
    required String cabinetId,
    List<String>? tags,
    DateTime? from,
    DateTime? to,
    int limit = 1000,
  }) async {
    final queryParams = <String, String>{
      'limit': limit.toString(),
    };
    if (tags != null && tags.isNotEmpty) {
      queryParams['tags'] = tags.join(',');
    }
    if (from != null) {
      queryParams['from_ts'] = (from.millisecondsSinceEpoch / 1000).toString();
    }
    if (to != null) {
      queryParams['to_ts'] = (to.millisecondsSinceEpoch / 1000).toString();
    }

    final uri = Uri.parse('baseUrl/api/cabinets/cabinetId/history')
        .replace(queryParameters: queryParams);

    final response = await http.get(uri, headers: _headers);
    if (response.statusCode == 200) {
      final data = jsonDecode(utf8.decode(response.bodyBytes));
      return Map<String, List<dynamic>>.from(data['series']);
    }
    throw Exception('Ошибка загрузки истории: \${response.statusCode}');
  }

  /// 4. Получить индивидуальную карту регистров шкафа
  Future<Map<String, dynamic>> getCabinetMap(String cabinetId) async {
    final response = await http.get(
      Uri.parse('baseUrl/api/cabinets/cabinetId/map'),
      headers: _headers,
    );
    if (response.statusCode == 200) {
      return jsonDecode(utf8.decode(response.bodyBytes));
    }
    throw Exception('Ошибка загрузки карты: \${response.statusCode}');
  }
}
```

### Проверка битов из масок (`Coils_1_N`, `Coils_2_N`) во Flutter
```dart
bool isBitSet(int wordValue, int bitIndex) => (wordValue & (1 << bitIndex)) != 0;

// Проверка 8-го бита в Coils_2_N (значение 256 = 1 << 8 -> true):
bool alarmActive = isBitSet(tags['Coils_2_N'] ?? 0, 8);
```
