"use strict";
const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
  try { tg.setHeaderColor('#080205'); tg.setBackgroundColor('#080205'); } catch (_) {}
}

const $ = (id) => document.getElementById(id);
const numberEl = $('number');
const countEl = $('count');
const mainBtn = $('mainBtn');
const secondBtn = $('secondBtn');
const stage = $('stage');
const flash = $('flash');

let state = null;
let busy = false;
let fatal = false;
let shownValue = null;

const pad = (n) => String(n).padStart(3, '0');

function fitFont(value) {
  numberEl.classList.remove('small', 'tiny');
  const len = String(value).length;
  if (len > 6) numberEl.classList.add('tiny');
  else if (len > 3) numberEl.classList.add('small');
}

function haptic(type) {
  if (!tg?.HapticFeedback) return;
  if (type === 'light') tg.HapticFeedback.impactOccurred('light');
  if (type === 'heavy') tg.HapticFeedback.impactOccurred('heavy');
  if (type === 'win') tg.HapticFeedback.notificationOccurred('success');
}

function burstParticles() {
  const rect = $('displayBox').getBoundingClientRect();
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;
  const palette = ['#ffffff', '#ffccd5', '#ff2e4d', '#c91833', '#6b0015'];
  for (let i = 0; i < 30; i++) {
    const p = document.createElement('div');
    p.className = 'particle';
    const angle = (Math.PI * 2 * i) / 30 + Math.random() * 0.5;
    const dist = 130 + Math.random() * 200;
    const size = 4 + Math.random() * 7;
    const color = palette[i % palette.length];
    p.style.setProperty('--dx', Math.cos(angle) * dist + 'px');
    p.style.setProperty('--dy', Math.sin(angle) * dist + 'px');
    p.style.left = cx + 'px';
    p.style.top = cy + 'px';
    p.style.width = p.style.height = size + 'px';
    p.style.background = color;
    p.style.boxShadow = `0 0 12px ${color}, 0 0 24px ${color}`;
    document.body.appendChild(p);
    setTimeout(() => p.remove(), 1500);
  }
}

function setNumber(value, { winner = false, pop = false } = {}) {
  numberEl.textContent = value;
  fitFont(value);
  if (pop) {
    numberEl.style.animation = 'none';
    void numberEl.offsetWidth;
    numberEl.style.animation = 'numberPop .8s cubic-bezier(.2,.9,.3,1.4)';
  }
  if (winner) {
    numberEl.classList.add('winner');
    stage.classList.add('winner');
    flash.classList.remove('show');
    void flash.offsetWidth;
    flash.classList.add('show');
    burstParticles();
  } else {
    numberEl.classList.remove('winner');
    stage.classList.remove('winner');
  }
}

function desiredValue() {
  if (!state) return '?';
  if (state.winner) return pad(state.winner.number);
  if (state.my_entry) return pad(state.my_entry.number);
  return '?';
}

function render() {
  if (!state) {
    countEl.value = '0';
    return;
  }
  countEl.value = String(state.participant_count);

  const value = desiredValue();
  if (value !== shownValue) {
    const isWinner = Boolean(state.winner);
    setNumber(value, { winner: isWinner });
    shownValue = value;
  }

  const open = state.round.status === 'open';
  const owner = state.is_owner;
  const joined = Boolean(state.my_entry);

  mainBtn.disabled = busy || fatal || !open || joined;
  if (!tg?.initData) mainBtn.textContent = 'Откройте через Telegram';
  else if (busy) mainBtn.textContent = '…';
  else if (joined) mainBtn.textContent = 'Вы участвуете';
  else if (!open) mainBtn.textContent = 'Розыгрыш завершён';
  else mainBtn.textContent = 'Участвовать';

  if (!owner) {
    secondBtn.hidden = true;
  } else if (open && state.participant_count > 0) {
    secondBtn.hidden = false;
    secondBtn.textContent = 'Запустить';
    secondBtn.disabled = busy || fatal;
  } else if (!open) {
    secondBtn.hidden = false;
    secondBtn.textContent = 'Следующий';
    secondBtn.disabled = busy || fatal;
  } else {
    secondBtn.hidden = true;
  }
}

async function api(path, body) {
  const resp = await fetch(path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: {
      Authorization: `tma ${tg?.initData || ''}`,
      'Content-Type': 'application/json',
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: 'no-store',
    signal: AbortSignal.timeout(20000),
  });
  const data = await resp.json();
  if (!resp.ok) {
    if (resp.status === 401 || resp.status === 503) fatal = true;
    throw new Error(data.error || 'Ошибка запроса.');
  }
  return data;
}

async function refresh() {
  state = await api('/api/state');
  render();
}

async function action(task) {
  if (busy || fatal) return;
  busy = true;
  render();
  try { await task(); }
  catch (err) {
    haptic('heavy');
    const msg = err.message || 'Ошибка';
    if (tg?.showAlert) tg.showAlert(msg).catch(() => {});
    else alert(msg);
  } finally {
    busy = false;
    render();
  }
}

function confirmDialog(title, message) {
  if (tg?.showConfirm) return tg.showConfirm(message, { title }).catch(() => false);
  return Promise.resolve(window.confirm(message));
}

function fakeSpin(finalNumber, max) {
  return new Promise((resolve) => {
    const start = performance.now();
    const duration = 2200;
    let lastTick = 0;
    function frame(now) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      const ease = 1 - Math.pow(1 - progress, 3.2);
      if (progress < 1) {
        const interval = 38 + ease * 320;
        if (now - lastTick > interval) {
          const r = Math.max(1, Math.floor(Math.random() * Math.max(max, 1)) + 1);
          numberEl.textContent = pad(r);
          fitFont(pad(r));
          haptic('light');
          lastTick = now;
        }
        requestAnimationFrame(frame);
      } else {
        resolve();
      }
    }
    requestAnimationFrame(frame);
  });
}

mainBtn.addEventListener('click', () => action(async () => {
  if (!state || state.my_entry || state.round.status !== 'open') return;
  await api('/api/join', { round_id: state.round.id });
  haptic('win');
  await refresh();
}));

secondBtn.addEventListener('click', () => action(async () => {
  if (!state || !state.is_owner) return;

  if (state.round.status === 'open') {
    const ok = await confirmDialog(
      'Запустить розыгрыш?',
      `Участников: ${state.participant_count}. Регистрация закроется. Результат нельзя переиграть.`
    );
    if (!ok) return;

    stage.classList.add('rolling');
    document.body.classList.add('drawing');

    const result = await api('/api/admin/draw', { round_id: state.round.id });
    const winnerNumber = result.winner.number;
    await fakeSpin(winnerNumber, state.participant_count);

    stage.classList.remove('rolling');
    document.body.classList.remove('drawing');

    shownValue = null;
    await refresh();
    haptic('win');
  } else {
    const ok = await confirmDialog(
      'Новый розыгрыш?',
      'История сохранится. Каждый участник должен будет нажать «Участвовать» заново.'
    );
    if (!ok) return;
    await api('/api/admin/new-round', { round_id: state.round.id });
    shownValue = null;
    await refresh();
  }
}));

(async function start() {
  if (!tg?.initData) {
    mainBtn.textContent = 'Откройте через Telegram';
    mainBtn.disabled = true;
    return;
  }
  try {
    await refresh();
  } catch (err) {
    mainBtn.textContent = 'Ошибка';
    mainBtn.disabled = true;
    return;
  }
  setInterval(async () => {
    if (busy || document.hidden || fatal) return;
    try { await refresh(); } catch (_) { /* сеть моргнула — повторим */ }
  }, 5000);
})();