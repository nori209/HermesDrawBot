#!/usr/bin/env bash
set -euo pipefail
umask 077
fail() { printf '%s\n' "$*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || fail 'Запустите от root.'
task_domain=${1:-}
task_email=${2:-}
[[ "$task_domain" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}$ ]] || fail 'Использование: bash deploy/publish-nginx.sh raffle.example.com email@example.com'
for tool in nginx curl python3 systemctl; do command -v "$tool" >/dev/null || fail "Требуется $tool. Существующие службы не изменены."; done
[[ -f /etc/shopen-raffle/env ]] || fail 'Сначала выполните deploy/install.sh.'
[[ -d /etc/nginx/sites-enabled ]] || fail 'Нет sites-enabled. Нужна адаптация под текущую конфигурацию nginx.'
systemctl is-active --quiet nginx || fail 'Скрипт рассчитан на уже работающий nginx. Нужна проверка веб-сервера.'
[[ "$(sed -n 's/^APP_URL=//p' /etc/shopen-raffle/env)" == "https://$task_domain" ]] || fail 'Домен отличается от APP_URL в настройках нового бота.'
task_conf=/etc/nginx/sites-available/shopen-raffle.conf
task_link=/etc/nginx/sites-enabled/shopen-raffle.conf
[[ ! -e "$task_conf" && ! -e "$task_link" && ! -L "$task_link" ]] || fail 'Конфигурация shopen-raffle уже существует. Автоматическая перезапись запрещена.'
task_dump=$(mktemp)
trap 'rm -f "$task_dump"' EXIT
nginx -T >"$task_dump" 2>/dev/null || fail 'Текущая конфигурация nginx содержит ошибки. Изменения не выполнены.'
python3 - "$task_dump" "$task_domain" <<'PY'
import re, sys
text = re.sub(r'#[^\n]*', '', open(sys.argv[1]).read())
for names in re.findall(r'\bserver_name\s+([^;]+);', text):
    if sys.argv[2] in names.split():
        sys.exit('Этот домен уже используется в nginx. Автоматическая настройка остановлена.')
PY
task_cert="/etc/letsencrypt/live/$task_domain"
if [[ ! -f "$task_cert/fullchain.pem" || ! -f "$task_cert/privkey.pem" ]]; then
    command -v certbot >/dev/null || fail 'Для сертификата требуется certbot. Существующая система не изменена.'
    [[ "$task_email" == *@*.* ]] || fail 'Укажите email для нового сертификата вторым аргументом.'
fi
curl --fail --silent http://127.0.0.1:18765/healthz >/dev/null || fail 'Новая web-служба недоступна.'
install -d -m 0755 /var/www/shopen-raffle-acme /etc/nginx/sites-available
task_committed=0
rollback() {
    task_code=$?
    rm -f "$task_dump"
    if [[ "$task_committed" -eq 0 ]]; then
        rm -f "$task_link" "$task_conf"
        if nginx -t; then systemctl reload nginx; fi
        printf 'Добавленная конфигурация нового сайта удалена. Проверьте причину ошибки выше.\n' >&2
    fi
    return "$task_code"
}
trap rollback EXIT
cat >"$task_conf" <<EOF
server {
    listen 80;
    server_name $task_domain;
    location /.well-known/acme-challenge/ { root /var/www/shopen-raffle-acme; }
    location / { return 503; }
}
EOF
chmod 0644 "$task_conf"
ln -s "$task_conf" "$task_link"
nginx -t
systemctl reload nginx
if [[ ! -f "$task_cert/fullchain.pem" || ! -f "$task_cert/privkey.pem" ]]; then
    certbot certonly --webroot -w /var/www/shopen-raffle-acme -d "$task_domain" --email "$task_email" --agree-tos --non-interactive
fi
cat >"$task_conf" <<EOF
server {
    listen 80;
    server_name $task_domain;
    location /.well-known/acme-challenge/ { root /var/www/shopen-raffle-acme; }
    location / { return 308 https://\$host\$request_uri; }
}
server {
    listen 443 ssl;
    server_name $task_domain;
    ssl_certificate $task_cert/fullchain.pem;
    ssl_certificate_key $task_cert/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size 16k;
    client_body_timeout 10s;
    large_client_header_buffers 4 16k;
    access_log /var/log/nginx/shopen-raffle-access.log;
    error_log /var/log/nginx/shopen-raffle-error.log;
    location / {
        proxy_pass http://127.0.0.1:18765;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_connect_timeout 5s;
        proxy_read_timeout 35s;
    }
}
EOF
nginx -t
systemctl reload nginx
curl --fail --silent --show-error --resolve "$task_domain:443:127.0.0.1" "https://$task_domain/healthz" | python3 -c 'import json,sys; r=json.load(sys.stdin); assert r.get("status")=="ok" and r.get("configured")'
# Keep the verified website even if Telegram is temporarily unavailable.
task_committed=1
systemctl enable --now shopen-raffle-bot.service
printf '\nHTTPS включён: https://%s\nПроверьте /start у НОВОГО бота и journalctl -u shopen-raffle-bot -n 30\n' "$task_domain"
printf 'Certbot webroot: /var/www/shopen-raffle-acme. Проверьте активный certbot.timer и продление сертификата.\n'
