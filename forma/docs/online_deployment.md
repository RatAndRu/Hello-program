# Постоянный статический стенд Forma с автоматическим деплоем

## Целевая конфигурация

- **Постоянный адрес:** <https://forma3d-ratandru.fly.dev>.
- **Назначение:** версии, их изменения и готовые модели; полный Web UI здесь не публикуется.
- **Платформа:** Fly.io, двухстадийный Docker-образ со статическим Nginx.
- **Регион:** Амстердам (`ams`).
- **Ресурсы:** 1 shared CPU, 512 MB RAM, ровно одна машина.
- **Постоянная работа:** `min_machines_running = 1`, `auto_stop_machines = 'off'`.
- **Health-check:** <https://forma3d-ratandru.fly.dev/healthz>.
- **CI:** `.github/workflows/deploy-forma-online.yml`.

Always-on машина является платной конфигурацией Fly.io. Статический стенд не требует volume, серверной сборки или Python в конечном контейнере.

## Состав решения

| Файл | Назначение |
|---|---|
| `forma/showcase/catalog.source.json` | Версии, нововведения, описания и исходники моделей |
| `forma/showcase/build_showcase.py` | Offline-сборка `.forma`, полного/preview GLB, WebP, каталога и gzip |
| `forma/showcase/static/` | Лёгкий каталог и 3D-viewer, загружаемый по требованию |
| `forma/showcase/Dockerfile` | Сборка assets в Python и production на непривилегированном Nginx |
| `forma/showcase/nginx.conf` | Кеширование, precompressed gzip, healthz и запрет editor API |
| `forma/showcase/acceptance.py` | Одинаковая внешняя приёмка контейнера и публичного адреса |
| `forma/tests/test_showcase.py` | Регрессии ленивой загрузки, геометрии и production-конфигурации |
| `fly.toml` | HTTPS, регион, 512 MB и постоянная машина |
| `.github/workflows/deploy-forma-online.yml` | Тесты, Docker, деплой и внешняя приёмка |

Подробности генератора и оптимизации описаны в [`forma/showcase/README.md`](../showcase/README.md).

## Что видит посетитель

- список конкретных версий и их изменений;
- готовые WebP-превью и понятные параметры каждой модели;
- скачивание исходника `.forma` и полного `.glb` с отдельными деталями;
- интерактивный просмотр только по явной кнопке;
- после закрытия просмотра — освобождение WebGL и скрытых ресурсов.

Three.js не загружается на первом экране. Сервер не выполняет пользовательские сценарии и не пересобирает модели. `/api/*` возвращает `410 Gone`; это проверяется автоматически.

## Автоматический процесс после push

При изменении `forma/**`, `fly.toml`, `.dockerignore` или workflow на ветке `arena/4e4defc4-hello-program`:

1. Запускаются `test_showcase`, `test_train_carriage`, `test_living_room_052`.
2. Собирается статический production-образ с полным SHA текущего commit.
3. Внутри build stage заранее строятся обе модели, проверяются GLB round-trip, создаются WebP и gzip.
4. Контейнер запускается в CI. `acceptance.py` проверяет healthz, версии, файлы, SHA-256, GLB2, узлы, треугольники, gzip и `410` у editor API.
5. При наличии `FLY_API_TOKEN` приложение Fly создаётся, если его ещё нет.
6. `flyctl deploy --local-only` публикует образ без отдельного remote-builder.
7. `flyctl scale count 1` оставляет одну машину.
8. Публичный `/healthz?revision=SHA` обязан подтвердить новый commit.
9. Та же внешняя приёмка выполняется через HTTPS против постоянного адреса с `--allow-proxy-decode`: proxy может раскодировать транспорт, но все raw bytes, хеши и структурные проверки остаются обязательными. При ошибке workflow считается неуспешным.

Токен полного Web UI больше не нужен: публичный стенд не содержит editor API. `FLY_API_TOKEN` по-прежнему хранится только в GitHub Actions Secrets и не выводится в журнал или чат.

## Локальная проверка

Быстрый статический просмотр:

```bash
python -m pip install -r forma/requirements.txt Pillow
PYTHONPATH=forma python forma/showcase/build_showcase.py \
  --repo-root "$PWD" --output /tmp/forma-showcase-site --revision local
python -m http.server 8000 --bind 0.0.0.0 --directory /tmp/forma-showcase-site
```

Полная production-проверка:

```bash
docker build --build-arg FORMA_REVISION=local \
  -t forma3d-showcase -f forma/showcase/Dockerfile .
docker run --rm -p 8000:8000 forma3d-showcase
python forma/showcase/acceptance.py \
  --base http://127.0.0.1:8000 --revision local
```

## Обновление и откат

- **Обновление:** обычный push в рабочую ветку; assets пересобираются в CI, не на запросах посетителей.
- **Проверка версии:** открыть `/healthz` и сравнить `revision` с SHA commit.
- **Внешняя приёмка вручную:** `python forma/showcase/acceptance.py --base https://forma3d-ratandru.fly.dev --revision SHA --allow-proxy-decode`.
- **Откат:** выбрать предыдущий успешный release в панели Fly.io либо повторно опубликовать предыдущий проверенный commit.
- **После переноса в `main`:** изменить список веток в `on.push.branches` workflow на стабильную ветку.

Локальный полный редактор остаётся частью Forma, но не является production-конфигурацией этого адреса.
