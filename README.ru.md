<p align="center">
  <img src="https://raw.githubusercontent.com/hteppl/remnawave-cloudflare-nodes/master/.github/images/logo.png" alt="remnawave-cloudflare-nodes" width="800px">
</p>

## remnawave-cloudflare-nodes

<p align="left">
  <a href="https://github.com/hteppl/remnawave-cloudflare-nodes/releases/"><img src="https://img.shields.io/github/v/release/hteppl/remnawave-cloudflare-nodes.svg" alt="Release"></a>
  <a href="https://hub.docker.com/r/hteppl/remnawave-cloudflare-nodes/"><img src="https://img.shields.io/badge/DockerHub-remnawave--cloudflare--nodes-blue" alt="DockerHub"></a>
  <a href="https://github.com/hteppl/remnawave-cloudflare-nodes/actions"><img src="https://img.shields.io/github/actions/workflow/status/hteppl/remnawave-cloudflare-nodes/dockerhub-publish.yaml" alt="Build"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12-blue.svg" alt="Python 3.12"></a>
  <a href="https://opensource.org/licenses/GPL-3.0"><img src="https://img.shields.io/badge/license-GPLv3-green.svg" alt="License: GPL v3"></a>
</p>

[English](README.md) | Русский

Сервис для автоматического управления DNS-записями Cloudflare в зависимости от состояния нод Remnawave (https://docs.rw).

## Возможности

- **Мониторинг нод** - Отслеживание состояния нод через Remnawave API
- **Управление DNS** - Автоматическое добавление и удаление A-записей
- **Автоопределение зон** - Получение Zone ID по имени домена
- **Мультидоменность** - Поддержка нескольких доменов и зон
- **Telegram-уведомления** - Оповещения об изменении статуса нод, DNS и критических событиях
- **Гибкая настройка** - Настраиваемые интервалы проверок
- **Docker** - Готовый образ для быстрого развёртывания

## Требования

- **Remnawave Panel** с добавленными нодами
- **Remnawave API Token** - генерируется в настройках панели
- **Cloudflare** с настроенными DNS-зонами
- **Cloudflare API Token** - с правами на редактирование DNS

## Настройка

Скопируйте [`.env.example`](.env.example) в `.env`:

```env
# Remnawave
REMNAWAVE_API_URL=https://panel.example.com
REMNAWAVE_API_KEY=remnawave_api_key

# Cloudflare (токен с правами DNS Edit)
CLOUDFLARE_API_TOKEN=cloudflare_api_token

# Telegram (токен от @BotFather)
TELEGRAM_BOT_TOKEN=your_bot_token_here
# Chat ID (узнать через @username_to_id_bot)
TELEGRAM_CHAT_ID=123456789
# ID топика (для форумов, иначе оставить пустым)
TELEGRAM_TOPIC_ID=

# Часовой пояс и формат времени
TIMEZONE=UTC
TIME_FORMAT="%d.%m.%Y %H:%M:%S"
```

Скопируйте [`config.example.yml`](config.example.yml) в `config.yml`:

```yaml
remnawave:
  # Health check interval in seconds
  check-interval: 30

# Domains and DNS zones to manage
domains:
  - domain: example1.com
    zones:
      - name: s1          # Creates s1.example1.com
        ttl: 60           # Record TTL in seconds
        proxied: false    # Cloudflare proxy (orange cloud)
        ips:              # Node IPs to monitor
          - 1.2.3.4
          - 5.6.7.8

  - domain: example2.com
    zones:
      - name: s2
        ttl: 60
        proxied: false
        ips:
          - 13.14.15.16
          - 17.18.19.20

logging:
  level: INFO # DEBUG, INFO, WARNING, ERROR, CRITICAL

telegram:
  enabled: false
  locale: en  # en, ru
  notify:
    node_changes: true  # Node online/offline
    dns_changes: true   # DNS record changes
    errors: true        # Error alerts
    critical: true      # All nodes down alert
```

### Параметры

| Переменная             | Описание                                   | По умолчанию      | Обязательно |
|------------------------|--------------------------------------------|-------------------|-------------|
| `REMNAWAVE_API_URL`    | Адрес панели Remnawave                     | -                 | Да          |
| `REMNAWAVE_API_KEY`    | API токен Remnawave                        | -                 | Да          |
| `CLOUDFLARE_API_TOKEN` | API токен Cloudflare (DNS Edit)            | -                 | Да          |
| `TELEGRAM_BOT_TOKEN`   | Токен бота (@BotFather)                    | -                 | Нет         |
| `TELEGRAM_CHAT_ID`     | ID чата для уведомлений                    | -                 | Нет         |
| `TELEGRAM_TOPIC_ID`    | ID топика (для форумов)                    | -                 | Нет         |
| `TIMEZONE`             | Часовой пояс                               | UTC               | Нет         |
| `TIME_FORMAT`          | Формат времени                             | %d.%m.%Y %H:%M:%S | Нет         |
| `check-interval`       | Интервал проверки (сек)                    | 30                | Нет         |
| `logging.level`        | Уровень логов                              | INFO              | Нет         |

## Установка

### Docker (рекомендуется)

1. Создайте `docker-compose.yml`:

```yaml
services:
  remnawave-cloudflare-nodes:
    image: hteppl/remnawave-cloudflare-nodes:latest
    container_name: remnawave-cloudflare-nodes
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      - ./config.yml:/app/config.yml:ro
      - ./logs:/app/logs
    logging:
      driver: json-file
      options:
        max-size: "20m"
        max-file: "3"
```

2. Настройте `.env`:

```bash
cp .env.example .env
nano .env
```

3. Запустите:

```bash
docker compose up -d && docker compose logs -f
```

### Ручная установка

```bash
git clone https://github.com/hteppl/remnawave-cloudflare-nodes.git
cd remnawave-cloudflare-nodes

python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

pip install -r requirements.txt
cp .env.example .env
python -m src
```

## Принцип работы

1. **Запуск** - Сервис получает список нод из Remnawave и определяет Zone ID в Cloudflare

2. **Проверка состояния** - Нода считается рабочей, если:
   - `is_connected = true`
   - `is_disabled = false`
   - `xray_version` не пустой

3. **Синхронизация DNS**:
   - Добавляет A-записи для рабочих нод
   - Удаляет A-записи для нерабочих нод

4. **Цикл** - Проверка повторяется каждые `check-interval` секунд

## Telegram-уведомления

Сервис отправляет уведомления о событиях в Telegram.

### Подключение

1. Создайте бота через [@BotFather](https://t.me/BotFather)
2. Узнайте свой chat ID через [@username_to_id_bot](https://t.me/username_to_id_bot)
3. Добавьте бота в чат
4. Укажите токен и chat ID в `.env`
5. Включите уведомления в `config.yml`:

```yaml
telegram:
  enabled: true
  locale: ru
```

### Типы уведомлений

| Событие          | Описание            | Пример                                                                          |
|------------------|---------------------|---------------------------------------------------------------------------------|
| **Нода онлайн**  | Нода доступна       | ✅ Нода онлайн<br>node-1 (1.2.3.4) доступна.<br>📊 Ноды: 5/6 онлайн, 0 отключено |
| **Нода офлайн**  | Нода недоступна     | ❌ Нода офлайн<br>node-1 (1.2.3.4) недоступна.<br>Причина: disconnected          |
| **DNS добавлен** | Добавлена A-запись  | 📝 DNS обновлён<br>Добавлен 1.2.3.4 → s1.example.com                            |
| **DNS удалён**   | Удалена A-запись    | 🗑️ DNS удалён<br>Удалён 1.2.3.4 из s1.example.com                              |
| **Критическая**  | Все ноды недоступны | 🔴 КРИТИЧНО: Все ноды недоступны                                                |
| **Запуск**       | Сервис запущен      | 🚀 Сервис запущен                                                               |
| **Остановка**    | Сервис остановлен   | 🛑 Сервис остановлен                                                            |

### Фильтрация уведомлений

```yaml
telegram:
  enabled: true
  locale: ru
  notify:
    node_changes: true  # изменения статуса нод
    dns_changes: true   # изменения DNS
    errors: true        # ошибки
    critical: true      # критические события
```

### Логи

```bash
# Docker
docker compose logs -f

# Ручная установка
# stdout + logs/app.log
```

## Лицензия

[GNU General Public License v3.0](LICENSE)
