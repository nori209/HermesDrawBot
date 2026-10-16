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
const listBtn = $('listBtn');
const participantsModal = $('participantsModal');
const participantsList = $('participantsList');
const participantsClose = $('participantsClose');
const prevPage = $('prevPage');
const nextPage = $('nextPage');
const pageLabel = $('pageLabel');

let currentPage = 1;

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
    if (owner) {
    listBtn.hidden = false;
    listBtn.textContent = `Участники (${state.participant_count})`;
    listBtn.disabled = busy || fatal;
  } else {
    listBtn.hidden = true;
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


async function loadParticipants() {
  const data = await api(`/api/admin/participants?round_id=${state.round.id}&page=${currentPage}`);
  const editable = state.round.status === 'open';
  const rows = data.items.map(item => {
    const row = document.createElement('div');
    row.className = 'participant-row';

    const info = document.createElement('div');
    info.className = 'p-info';
    const name = document.createElement('div');
    name.className = 'p-name';
    name.textContent = item.username ? `@${item.username}` : item.display_name;
    const sub = document.createElement('div');
    sub.className = 'p-sub';
    sub.textContent = `ID ${item.telegram_id} · ${item.display_name}`;
    info.append(name, sub);

    const num = document.createElement('span');
    num.className = 'p-num';
    num.textContent = `№${pad(item.number)}`;

    row.append(info, num);

    if (editable) {
      const btn = document.createElement('button');
      btn.className = 'p-remove';
      btn.textContent = 'Удалить';
      btn.addEventListener('click', () => removeParticipant(item.number));
      row.append(btn);
    }
    return row;
  });
  if (!rows.length) {
    const empty = document.createElement('p');
    empty.style.color = 'var(--muted)';
    empty.style.textAlign = 'center';
    empty.style.padding = '30px 0';
    empty.textContent = 'Пока никого';
    participantsList.replaceChildren(empty);
  } else {
    participantsList.replaceChildren(...rows);
  }
  pageLabel.textContent = `${data.page} / ${Math.max(1, data.pages)}`;
  prevPage.disabled = currentPage <= 1;
  nextPage.disabled = currentPage >= data.pages;
}

async function removeParticipant(num) {
  if (busy || fatal) return;
  const ok = await confirmDialog(
    'Удалить участника?',
    `Билет №${pad(num)} будет удалён из розыгрыша. Действие необратимо.`
  );
  if (!ok) return;
  busy = true;
  try {
    await api('/api/admin/remove-participant', { round_id: state.round.id, number: num });
    await refresh();
    await loadParticipants();
    haptic('win');
  } catch (err) {
    if (tg?.showAlert) tg.showAlert(err.message || 'Ошибка').catch(() => {});
    else alert(err.message || 'Ошибка');
  } finally {
    busy = false;
  }
}

listBtn.addEventListener('click', () => action(async () => {
  currentPage = 1;
  await loadParticipants();
  participantsModal.hidden = false;
}));

participantsClose.addEventListener('click', () => { participantsModal.hidden = true; });
participantsModal.addEventListener('click', (e) => {
  if (e.target === participantsModal) participantsModal.hidden = true;
});

prevPage.addEventListener('click', () => action(async () => {
  if (currentPage > 1) { currentPage -= 1; await loadParticipants(); }
}));
nextPage.addEventListener('click', () => action(async () => {
  currentPage += 1; await loadParticipants();
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