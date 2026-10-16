"use strict";

const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
  try {
    tg.setHeaderColor('#080205');
    tg.setBackgroundColor('#080205');
  } catch (_) {}
}

const $ = (id) => document.getElementById(id);

const numberEl = $('number');
const mainBtn = $('mainBtn');
const secondBtn = $('secondBtn');
const listBtn = $('listBtn');
const stage = $('stage');
const flash = $('flash');
const winnerLine = $('winnerLine');
const winnerLineText = $('winnerLineText');
const winnerCountRow = $('winnerCountRow');
const winnerCountInput = $('winnerCount');

const participantsModal = $('participantsModal');
const participantsList = $('participantsList');
const participantsClose = $('participantsClose');
const prevPage = $('prevPage');
const nextPage = $('nextPage');
const pageLabel = $('pageLabel');

const confirmModal = $('confirmModal');
const confirmTitle = $('confirmTitle');
const confirmText = $('confirmText');
const confirmYes = $('confirmYes');
const confirmNo = $('confirmNo');

const REVEAL_DELAY_MS = 4500;
const POLL_INTERVAL_MS = 2000;

let state = null;
let busy = false;
let fatal = false;
let shownValue = null;
let currentPage = 1;
let confirmResolver = null;

const spinState = { active: false, revealAt: 0 };

const pad = (n) => String(n).padStart(3, '0');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function fitFont(value) {
  numberEl.classList.remove('small', 'tiny');
  const len = String(value).length;
  if (len > 6) numberEl.classList.add('tiny');
  else if (len > 3) numberEl.classList.add('small');
}

function haptic(type) {
  if (!tg?.HapticFeedback) return;
  try {
    if (type === 'light') tg.HapticFeedback.impactOccurred('light');
    if (type === 'medium') tg.HapticFeedback.impactOccurred('medium');
    if (type === 'heavy') tg.HapticFeedback.impactOccurred('heavy');
    if (type === 'win') tg.HapticFeedback.notificationOccurred('success');
  } catch (_) {}
}

function burstParticles() {
  const rect = $('displayBox').getBoundingClientRect();
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;
  const palette = ['#ffffff', '#ffccd5', '#ff2e4d', '#c91833', '#6b0015'];
  for (let i = 0; i < 36; i++) {
    const p = document.createElement('div');
    p.className = 'particle';
    const angle = (Math.PI * 2 * i) / 36 + Math.random() * 0.5;
    const dist = 140 + Math.random() * 220;
    const size = 4 + Math.random() * 8;
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

function setNumber(value, { winner = false } = {}) {
  numberEl.textContent = value;
  fitFont(value);
  if (winner) {
    numberEl.classList.remove('winner');
    void numberEl.offsetWidth;
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

function personName(entry) {
  if (!entry) return '';
  return entry.username ? `@${entry.username}` : entry.display_name;
}

function mainWinner() {
  return state?.winners?.[0] || null;
}

function desiredValue() {
  if (!state) return '?';
  if (spinState.active) return null;
  const w = mainWinner();
  if (w) return pad(w.number);
  if (state.my_entry) return pad(state.my_entry.number);
  return '?';
}

function medals(i) {
  return ['🏆', '🥈', '🥉'][i] || `${i + 1}.`;
}

function render() {
  if (!state) return;

  const value = desiredValue();
  if (value !== null && value !== shownValue) {
    setNumber(value, { winner: Boolean(mainWinner()) && !spinState.active });
    shownValue = value;
  }

  const winners = state.winners || [];
  if (winners.length && state.round.status === 'finished' && !spinState.active) {
    winnerLineText.replaceChildren(...winners.map((w, i) => {
      const row = document.createElement('span');
      row.className = 'w-row';
      row.textContent = `${medals(i)} ${personName(w)} · билет №${pad(w.number)}`;
      return row;
    }));
    winnerLine.hidden = false;
  } else {
    winnerLine.hidden = true;
  }

  const open = state.round.status === 'open';
  const owner = state.is_owner;
  const joined = Boolean(state.my_entry);
  const locked = busy || fatal || spinState.active;

  mainBtn.disabled = locked || !open || joined || !tg?.initData;
  if (!tg?.initData) mainBtn.textContent = 'Откройте через Telegram';
  else if (busy) mainBtn.textContent = '…';
  else if (joined) mainBtn.textContent = 'Вы участвуете';
  else if (!open) mainBtn.textContent = 'Розыгрыш завершён';
  else mainBtn.textContent = 'Участвовать';

  if (owner) {
    listBtn.hidden = false;
    listBtn.textContent = 'Участники';
    listBtn.disabled = locked;
  } else {
    listBtn.hidden = true;
  }

  const showCount = owner && open && state.participant_count > 0;
  winnerCountRow.hidden = !showCount;
  if (showCount) {
    const max = Math.min(10, state.participant_count);
    winnerCountInput.max = String(max);
    const cur = parseInt(winnerCountInput.value, 10) || 1;
    if (cur > max) winnerCountInput.value = String(max);
  }

  if (!owner) {
    secondBtn.hidden = true;
  } else if (open && state.participant_count > 0) {
    secondBtn.hidden = false;
    secondBtn.textContent = 'Запустить';
    secondBtn.disabled = locked;
  } else if (!open) {
    secondBtn.hidden = false;
    secondBtn.textContent = 'Следующий';
    secondBtn.disabled = locked;
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

function syncSpinState() {
  if (!state?.round?.drawn_at) return;
  if (state.round.status !== 'finished') return;
  if (!state.winners?.length) return;
  if (spinState.active) return;

  const revealAt = Date.parse(state.round.drawn_at) + REVEAL_DELAY_MS;
  const remaining = revealAt - Date.now();
  if (remaining <= 0) return;

  spinState.active = true;
  spinState.revealAt = revealAt;
  render();

  spinFor(remaining, state.winners[0].number).then(() => {
    spinState.active = false;
    shownValue = null;
    render();
  });
}

// === НОВАЯ АНИМАЦИЯ ===
// Кривая скорости: разгон → бешенство → замедление → ложный финал →
// снова разгон → финальная остановка.
// На высокой скорости — усиленное свечение и мелкая тряска.
async function spinFor(durationMs, finalNumber) {
  stage.classList.add('rolling');
  document.body.classList.add('drawing');

  const top = Math.max(state.participant_count, 1);
  const start = performance.now();
  let lastHapticAt = 0;

  function rand() {
    return pad(Math.max(1, Math.floor(Math.random() * top) + 1));
  }

  function paint(text, shake) {
    numberEl.textContent = text;
    fitFont(text);
    if (shake) {
      numberEl.classList.remove('tick');
      void numberEl.offsetWidth;
      numberEl.classList.add('tick');
    }
  }

  while (true) {
    const elapsed = performance.now() - start;
    if (elapsed >= durationMs) break;
    const p = elapsed / durationMs;

    let interval;
    let shake = false;
    let glow = 'normal'; // normal | hot

    if (p < 0.15) {
      // 1. Разгон: 120 → 45 мс
      interval = 120 - (p / 0.15) * 75;
    } else if (p < 0.5) {
      // 2. Бешенство: 40 мс
      interval = 40;
      glow = 'hot';
    } else if (p < 0.7) {
      // 3. Первое замедление: 60 → 340 мс
      const q = (p - 0.5) / 0.2;
      interval = 60 + Math.pow(q, 1.8) * 280;
      shake = q > 0.55;
    } else if (p < 0.78) {
      // 4. Ложный финал: 480 мс, тряска
      interval = 480;
      shake = true;
    } else if (p < 0.84) {
      // 5. Резкий разгон обратно: 480 → 60 мс
      const q = (p - 0.78) / 0.06;
      interval = 480 - q * 420;
      glow = 'hot';
    } else {
      // 6. Финальная остановка: 80 → 780 мс
      const q = (p - 0.84) / 0.16;
      interval = 80 + Math.pow(q, 2.4) * 700;
      shake = q > 0.35;
    }

    paint(rand(), shake);

    // Свечение зависит от скорости
    if (glow === 'hot') {
      numberEl.style.textShadow = '0 0 18px #fff, 0 0 40px var(--neon), 0 0 90px var(--crimson), 0 0 150px var(--blood)';
    } else {
      numberEl.style.textShadow = '';
    }

    // Вибрация по интервалу
    const minGap = Math.max(60, interval * 0.85);
    if (elapsed - lastHapticAt > minGap) {
      haptic(interval > 280 ? 'heavy' : interval < 60 ? 'medium' : 'light');
      lastHapticAt = elapsed;
    }

    await sleep(interval);
  }

  // Короткая пауза "затишья" перед победителем
  await sleep(140);

  numberEl.style.textShadow = '';
  numberEl.classList.remove('tick');
  stage.classList.remove('rolling');
  document.body.classList.remove('drawing');

  setNumber(pad(finalNumber), { winner: true });
  haptic('win');
}

async function refresh() {
  state = await api('/api/state');
  syncSpinState();
  render();
}

async function action(task) {
  if (busy || fatal) return;
  busy = true;
  render();
  try { await task(); }
  catch (err) { haptic('heavy'); await showAlert(err.message || 'Ошибка'); }
  finally { busy = false; render(); }
}

function askConfirm(title, text, yesLabel = 'Подтвердить') {
  confirmTitle.textContent = title;
  confirmText.textContent = text;
  confirmYes.textContent = yesLabel;
  confirmNo.hidden = false;
  confirmModal.hidden = false;
  return new Promise((resolve) => {
    confirmResolver = (value) => {
      confirmModal.hidden = true;
      confirmResolver = null;
      resolve(value);
    };
  });
}

function showAlert(msg) {
  confirmTitle.textContent = 'Ошибка';
  confirmText.textContent = msg;
  confirmYes.textContent = 'ОК';
  confirmNo.hidden = true;
  confirmModal.hidden = false;
  return new Promise((resolve) => {
    confirmResolver = () => {
      confirmModal.hidden = true;
      confirmResolver = null;
      resolve();
    };
  });
}

confirmYes.addEventListener('click', () => { if (confirmResolver) confirmResolver(true); });
confirmNo.addEventListener('click', () => { if (confirmResolver) confirmResolver(false); });

winnerCountInput.addEventListener('input', () => {
  let v = winnerCountInput.value.replace(/[^0-9]/g, '');
  if (v === '') { winnerCountInput.value = '1'; return; }
  const n = Math.max(1, Math.min(10, parseInt(v, 10)));
  winnerCountInput.value = String(n);
});

mainBtn.addEventListener('click', () => action(async () => {
  if (!state || state.my_entry || state.round.status !== 'open') return;
  await api('/api/join', { round_id: state.round.id });
  haptic('win');
  shownValue = null;
  await refresh();
}));

secondBtn.addEventListener('click', () => action(async () => {
  if (!state || !state.is_owner) return;

  if (state.round.status === 'open') {
    const winnerCount = Math.max(1, Math.min(10, parseInt(winnerCountInput.value, 10) || 1));
    const ok = await askConfirm(
      'Запустить розыгрыш?',
      `Победителей: ${winnerCount}. Регистрация закроется. Результат нельзя переиграть.`,
      'Запустить'
    );
    if (!ok) return;

    await api('/api/admin/draw', { round_id: state.round.id, winner_count: winnerCount });
    shownValue = null;
    await refresh();
    return;
  }

  const ok = await askConfirm(
    'Новый розыгрыш?',
    'История сохранится. Каждый участник должен будет нажать «Участвовать» заново.',
    'Открыть'
  );
  if (!ok) return;
  await api('/api/admin/new-round', { round_id: state.round.id });
  shownValue = null;
  await refresh();
}));

async function loadParticipants() {
  const data = await api(`/api/admin/participants?round_id=${state.round.id}&page=${currentPage}`);
  const editable = state.round.status === 'open';
  const rows = data.items.map((item) => {
    const row = document.createElement('div');
    row.className = 'participant-row';

    const info = document.createElement('div');
    info.className = 'p-info';
    const name = document.createElement('div');
    name.className = 'p-name';
    const placeTag = item.place ? medals(item.place - 1) + ' ' : '';
    name.textContent = placeTag + (item.username ? `@${item.username}` : item.display_name);
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
  prevPage.disabled = data.page <= 1;
  nextPage.disabled = data.page >= data.pages;
  currentPage = data.page;
}

async function removeParticipant(num) {
  const ok = await askConfirm(
    'Удалить участника?',
    `Билет №${pad(num)} будет удалён. Действие необратимо.`,
    'Удалить'
  );
  if (!ok) return;
  try {
    await api('/api/admin/remove-participant', { round_id: state.round.id, number: num });
    shownValue = null;
    await refresh();
    await loadParticipants();
    haptic('win');
  } catch (err) {
    await showAlert(err.message || 'Ошибка');
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
    try { await refresh(); } catch (_) {}
  }, POLL_INTERVAL_MS);
})();