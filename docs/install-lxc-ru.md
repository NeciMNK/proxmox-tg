# Установка proxmox-tg в LXC-контейнер Proxmox

Пошаговая инструкция: контейнер на Proxmox VE, в нём панель (PegaProx с русским интерфейсом
и разделом «Пользователи Proxmox»), Telegram-бот, подключение кластера и Proxmox Backup
Server. Время: 20-30 минут.

Что получится:

| Что | Где |
|---|---|
| Веб-панель | `https://IP-контейнера:5000` (консоли VNC и SSH на 5001 и 5002) |
| Файлы панели | `/opt/PegaProx`, данные в `/opt/PegaProx/config`, ключ шифрования `/etc/pegaprox/secret.key` |
| Служба панели | `pegaprox` |
| Telegram-бот | `/opt/proxmox-tg-bot`, настройки `/etc/proxmox-tg-bot.env`, служба `proxmox-tg-bot` |
| Исходники для обновлений | `/opt/proxmox-tg-src` |

## 1. Контейнер

Всё в этом разделе выполняется в консоли ноды Proxmox (Shell ноды в веб-интерфейсе или SSH)
от root.

Скачайте шаблон Debian 12:

```bash
pveam update
pveam available --section system | grep debian-12
pveam download local debian-12-standard_12.12-1_amd64.tar.zst   # имя возьмите из вывода строкой выше
```

Создайте контейнер. Подставьте свободный номер (здесь `200`), хранилище диска (`local-lvm`),
мост (`vmbr0`) и адрес. Статический IP лучше DHCP: по этому адресу вы будете открывать
панель, а бот будет к ней обращаться.

```bash
pct create 200 local:vztmpl/debian-12-standard_12.12-1_amd64.tar.zst \
  --hostname proxmox-tg \
  --cores 2 --memory 2048 --swap 512 \
  --rootfs local-lvm:16 \
  --net0 name=eth0,bridge=vmbr0,ip=192.168.1.50/24,gw=192.168.1.1 \
  --nameserver 1.1.1.1 \
  --unprivileged 1 --features nesting=1,keyctl=1 \
  --onboot 1 \
  --password
pct start 200
pct enter 200
```

`--password` спросит пароль root контейнера. Дальше все команды выполняются уже внутри
контейнера (после `pct enter 200`).

Почему так:
- 2 ядра, 2 ГБ памяти и 16 ГБ диска хватает на один кластер с запасом. История метрик и
  журнал растут со временем, при десятках нод добавьте память и диск.
- `nesting=1` нужен systemd внутри непривилегированного контейнера, без него службы
  запускаются с ошибками.
- `--onboot 1` поднимает панель вместе с нодой.

## 2. Панель

Репозиторий `NeciMNK/proxmox-tg` закрытый, поэтому для `git clone` нужен токен GitHub:
GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens →
доступ только к репозиторию `proxmox-tg`, право `Contents: Read-only`. При запросе пароля
вставьте токен.

```bash
apt-get update && apt-get -y upgrade && apt-get -y install git curl sudo
git clone https://github.com/NeciMNK/proxmox-tg.git /opt/proxmox-tg-src
cd /opt/proxmox-tg-src
bash deploy.sh --port=5000 --no-interactive
```

`deploy.sh`, запущенный из клона, берёт файлы из него (а не из оригинального PegaProx):
ставит зависимости, создаёт пользователя `pegaprox`, venv, ключ шифрования и службу
`pegaprox`. В конце он печатает адрес панели.

Проверка:

```bash
systemctl status pegaprox
journalctl -u pegaprox -f       # логи, выход Ctrl+C
```

Откройте `https://192.168.1.50:5000`. Сертификат самоподписанный, браузер предупредит:
это ожидаемо, примите его. Первый вход открывает мастер настройки: создайте администратора
(это пользователь панели, не Proxmox). Язык переключается флажком **RU** вверху.

## 3. Подключение кластера Proxmox VE

Панели нужен доступ к API Proxmox (порт 8006 нод) и, для части функций (консоль ноды,
обновления нод, некоторые проверки), SSH к нодам (порт 22).

Самый простой вариант: `root@pam` и его пароль. Работает всё.

Вариант аккуратнее: отдельный пользователь с ролью ровно под панель. Готовый набор команд
панель показывает сама: «Добавить кластер» → вкладка Proxmox VE → «Роль с минимальными
правами для API (учётная запись или токен)». Подробно, какая привилегия для чего, в [proxmox-permissions.md](proxmox-permissions.md).
Учтите, что раздел «Пользователи Proxmox» меняет пользователей и права кластера, поэтому
учётной записи панели для него нужны ещё `User.Modify` и `Permissions.Modify` на `/`
и `Sys.Modify` на `/access` (для своих ролей). У `root@pam` всё это есть.

В панели: кнопка «Добавить кластер» → адрес любой ноды (например `192.168.1.10`), порт 8006,
пользователь и пароль (или API-токен).

## 4. Proxmox Backup Server

В левой колонке: «Добавить сервер резервного копирования» → адрес PBS, порт 8007,
пользователь и пароль (например `root@pam`) или API-токен PBS. После этого панель
показывает хранилища, задачи и снимки PBS.

Если бэкапы с нод Proxmox VE ещё не идут в PBS, PBS нужно добавить и как хранилище
в самом кластере: в панели «Датацентр → Хранилище», добавить хранилище типа Proxmox Backup Server
(или в Proxmox VE: Датацентр → Хранилище). Для этого нужен fingerprint PBS: он на
главной странице PBS (Dashboard → Show Fingerprint).

## 5. Telegram-бот

Боту нужен выход на `api.telegram.org` и доступ к панели. Ставится в тот же контейнер:

```bash
cd /opt/proxmox-tg-src
bash tgbot/deploy/install.sh
nano /etc/proxmox-tg-bot.env     # впишите TG_BOT_TOKEN от @BotFather
systemctl restart proxmox-tg-bot
journalctl -u proxmox-tg-bot -f
```

Рекомендую сразу вписать в `TG_ALLOWED_IDS` свой id Telegram (узнать можно у
@userinfobot), тогда посторонние не смогут даже начать работу с ботом.

Привязка аккаунта: в панели «Мой профиль → API-токены» создайте токен, затем в личном
чате с ботом отправьте `/login pgx_...`. Все настройки и команды: [tgbot/README.md](../tgbot/README.md).

## 6. Сеть и firewall

Если в Proxmox включён firewall, разрешите:

| Откуда | Куда | Порт | Зачем |
|---|---|---|---|
| ваша сеть | контейнер | 5000-5002/tcp | панель и консоли |
| контейнер | ноды PVE | 8006/tcp | API |
| контейнер | ноды PVE | 22/tcp | функции через SSH |
| контейнер | PBS | 8007/tcp | API PBS |
| контейнер | интернет | 443/tcp | Telegram (`api.telegram.org`), GitHub для обновлений |

Панель не стоит публиковать в интернет напрямую. Для доступа извне лучше VPN
(WireGuard, Tailscale) или хотя бы обратный прокси с ограничением по IP; управление
с телефона закрывает Telegram-бот.

## 7. Обновление

Обновление в этом форке берёт код только из репозитория `NeciMNK/proxmox-tg` (оригинальный
PegaProx и его зеркало отключены, они затёрли бы русский перевод, раздел «Пользователи
Proxmox» и связку с ботом). Есть два способа.

**Из панели** (в настройках PegaProx кнопка «Проверить обновления», затем обновить) или `bash /opt/PegaProx/update.sh`.
Работает при двух условиях:
- репозиторий публичный: закрытый GitHub отдаёт без токена ошибку 404, и панель покажет
  «Update server returned 404»;
- в новой версии поднят номер `version` в `version.json` и `PEGAPROX_VERSION` в
  `pegaprox/constants.py` (например `1.4.1` → `1.4.2`): панель сравнивает только номер версии.

**Из клона** (работает и с закрытым репозиторием):

```bash
cd /opt/proxmox-tg-src
git pull
bash deploy.sh --port=5000 --no-interactive    # данные и настройки в config/ сохраняются
```

Бот обновляется отдельно, в обоих случаях: `cd /opt/proxmox-tg-src && git pull && bash tgbot/deploy/install.sh`
(настройки бота не трогает).

Перед обновлением удобно сделать снапшот контейнера в Proxmox (`pct snapshot 200 before-update`),
тогда откат занимает секунды.

## 8. Резервная копия и переезд на отдельный сервер

Всё состояние панели в двух местах: `/opt/PegaProx/config` (база с кластерами,
пользователями, настройками) и `/etc/pegaprox/secret.key` (ключ, которым база
зашифрована; без него база бесполезна). У бота: `/var/lib/proxmox-tg-bot` и
`/etc/proxmox-tg-bot.env`.

Самое простое: включите бэкап контейнера в PBS по расписанию.

Переезд на отдельный сервер (Debian 12/13 или Ubuntu 22.04/24.04):

1. На новом сервере выполните раздел 2 (клон и `deploy.sh`), но не проходите мастер настройки.
2. Остановите панель на обоих: `systemctl stop pegaprox`.
3. Скопируйте `/opt/PegaProx/config/` и `/etc/pegaprox/secret.key` со старого на новый,
   с теми же правами (`chown -R pegaprox:pegaprox /opt/PegaProx/config`,
   `chown root:pegaprox /etc/pegaprox/secret.key && chmod 640 /etc/pegaprox/secret.key`).
4. `systemctl start pegaprox` на новом. Для бота повторите раздел 5 и скопируйте его
   два пути; если адрес панели изменился, поправьте `PEGAPROX_URL` в `/etc/proxmox-tg-bot.env`.

## Если что-то не работает

| Симптом | Что проверить |
|---|---|
| Страница не открывается | `systemctl status pegaprox`, `journalctl -u pegaprox -n 100`; firewall на порт 5000 |
| Службы в контейнере не стартуют | у контейнера включён `nesting=1` (Параметры → Возможности) |
| Кластер «не подключён» | с контейнера `curl -k https://IP-ноды:8006` отвечает; логин и пароль верны; время в контейнере и на нодах совпадает |
| В «Пользователи Proxmox» ошибка про учётные данные | учётной записи панели в Proxmox не хватает `User.Modify`, `Permissions.Modify` или `Sys.Modify` (см. раздел 3) |
| Бот молчит | `journalctl -u proxmox-tg-bot -n 50`; с контейнера открывается `https://api.telegram.org`; верный `TG_BOT_TOKEN` |
| Бот пишет «PegaProx недоступен» | `PEGAPROX_URL` в `/etc/proxmox-tg-bot.env` (по умолчанию `https://127.0.0.1:5000`) |
