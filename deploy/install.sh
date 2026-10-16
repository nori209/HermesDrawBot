#!/usr/bin/env bash
set -euo pipefail
umask 077

fail() { printf '%s\n' "$*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || fail 'Запустите установку от root на целевом сервере.'
task_source=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
for tool in python3 systemctl ss curl tar; do command -v "$tool" >/dev/null || fail "Требуется $tool. Установка остановлена."; done
python3 -c 'import sys; assert sys.version_info >= (3, 10)' || fail 'Требуется Python 3.10+.'
[[ -d /run/systemd/system ]] || fail 'Требуется systemd.'
for path in /opt/shopen-raffle /etc/shopen-raffle /var/lib/shopen-raffle /etc/systemd/system/shopen-raffle-web.service /etc/systemd/system/shopen-raffle-bot.service; do
    [[ ! -e "$path" ]] || fail "Уже существует $path. Для защиты данных установка остановлена."
done
if id shopen-raffle >/dev/null 2>&1 || getent group shopen-raffle >/dev/null; then fail 'Пользователь или группа shopen-raffle уже существуют.'; fi
if ss -H -ltn 'sport = :18765' | read -r _; then fail 'Порт 18765 занят. Установка остановлена.'; fi
printf 'Проверка текущих служб (только чтение):\n'
systemctl list-units --type=service --state=running --no-pager
printf '\nНовый бот получит /opt/shopen-raffle, /var/lib/shopen-raffle и порт 127.0.0.1:18765.\n'
IFS= read -r -s -p 'Токен НОВОГО бота: ' task_token
printf '\n'
IFS= read -r -p 'Telegram ID владельца: ' task_owner
IFS= read -r -p 'Отдельный поддомен (например raffle.example.com): ' task_domain
[[ "$task_token" =~ ^[0-9]+:[A-Za-z0-9_-]{30,}$ ]] || fail 'Неверный формат токена.'
[[ "$task_owner" =~ ^[1-9][0-9]{0,15}$ ]] || fail 'Укажите числовой ID владельца.'
[[ "$task_domain" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}$ ]] || fail 'Нужен домен без протокола и пути.'

# Build the virtualenv before creating the runtime account or starting services.
mkdir -m 0755 /opt/shopen-raffle
cp -R "$task_source/raffle" /opt/shopen-raffle/
cp "$task_source/requirements.txt" /opt/shopen-raffle/
cp "$task_source/deploy/backup.py" /opt/shopen-raffle/backup.py
if ! python3 -m venv /opt/shopen-raffle/.venv; then
    fail 'Не удалось создать venv. Проверьте python3-venv. Службы не запущены; созданный /opt/shopen-raffle сохранён для проверки.'
fi
/opt/shopen-raffle/.venv/bin/python -m pip install --disable-pip-version-check -r /opt/shopen-raffle/requirements.txt
useradd --system --user-group --home-dir /var/lib/shopen-raffle --no-create-home --shell /usr/sbin/nologin shopen-raffle
install -d -m 0750 -o root -g shopen-raffle /etc/shopen-raffle
install -d -m 0700 -o shopen-raffle -g shopen-raffle /var/lib/shopen-raffle
{
    printf 'BOT_TOKEN=%s\n' "$task_token"
    printf 'OWNER_ID=%s\nAPP_URL=https://%s\n' "$task_owner" "$task_domain"
    printf 'DATABASE_PATH=/var/lib/shopen-raffle/raffle.sqlite3\nINIT_DATA_TTL=86400\n'
} > /etc/shopen-raffle/env
unset task_token
chown root:shopen-raffle /etc/shopen-raffle/env
chmod 0640 /etc/shopen-raffle/env
chmod -R a+rX,go-w /opt/shopen-raffle
install -m 0644 "$task_source/deploy/shopen-raffle-web.service" /etc/systemd/system/
install -m 0644 "$task_source/deploy/shopen-raffle-bot.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now shopen-raffle-web.service
task_healthy=0
for task_attempt in {1..10}; do
    if curl --fail --silent http://127.0.0.1:18765/healthz >/dev/null; then task_healthy=1; break; fi
    sleep 1
done
[[ "$task_healthy" -eq 1 ]] || fail 'Новая web-служба не прошла проверку. journalctl -u shopen-raffle-web -n 40'
printf '\nПриложение установлено. Теперь настройте HTTPS:\nbash %s/deploy/publish-nginx.sh %s EMAIL_ДЛЯ_СЕРТИФИКАТА\n' "$task_source" "$task_domain"
printf 'Telegram polling пока не запущен: его включает publish-nginx.sh после проверки HTTPS.\n'
