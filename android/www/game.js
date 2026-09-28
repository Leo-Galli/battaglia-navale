const COLS = 'ABCDEFGHIJ'.split('');
const SIZE = 10;

let apiBase = '';
let token = '';
let giocatore = 0;
let cursor = { r: 0, c: 0 };
let orizzontale = true;
let polling = null;
let lastState = null;

const el = (id) => document.getElementById(id);

function loadApiBase() {
  const saved = localStorage.getItem('bn_api_base');
  el('api-base').value = saved || 'http://10.0.2.2:8080';
}

async function api(path, opts = {}) {
  const res = await fetch(`${apiBase.replace(/\/$/, '')}${path}`, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.motivo || data.errore || res.statusText);
  return data;
}

function sym(ch) {
  return { '.': '.', N: '#', X: 'X', O: 'o' }[ch] || ch;
}

function paintGrid(container, matrix, opts = {}) {
  container.replaceChildren();
  for (let r = 0; r < SIZE; r++) {
    for (let c = 0; c < SIZE; c++) {
      const ch = matrix[r][c];
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'cell';
      btn.dataset.r = String(r);
      btn.dataset.c = String(c);
      btn.textContent = sym(ch);
      btn.setAttribute('aria-label', `${COLS[c]}${r + 1}`);
      if (ch === '.') btn.classList.add('water');
      if (ch === 'N') btn.classList.add('ship');
      if (ch === 'X') btn.classList.add('hit');
      if (ch === 'O') btn.classList.add('miss');
      if (opts.cursor && opts.cursor.r === r && opts.cursor.c === c) btn.classList.add('cursor');
      if (opts.preview?.has(`${r},${c}`)) btn.classList.add('preview');
      if (opts.bad?.has(`${r},${c}`)) btn.classList.add('bad');
      container.appendChild(btn);
    }
  }
}

function previewCells(state) {
  const set = new Set();
  const bad = new Set();
  if (state.fase !== 'posizionamento' || !state.prossima_lunghezza) return { set, bad };
  const len = state.prossima_lunghezza;
  for (let i = 0; i < len; i++) {
    const r = cursor.r + (orizzontale ? 0 : i);
    const c = cursor.c + (orizzontale ? i : 0);
    if (r >= 0 && r < SIZE && c >= 0 && c < SIZE) {
      set.add(`${r},${c}`);
      if (state.propria[r][c] !== '.') bad.add(`${r},${c}`);
    } else {
      bad.add(`${cursor.r},${cursor.c}`);
    }
  }
  return { set, bad };
}

function render(state) {
  lastState = state;
  const placing = state.fase === 'posizionamento' && state.prossima_lunghezza;
  const myTurn = state.fase === 'battaglia' && state.turno === giocatore;
  const prev = placing ? previewCells(state) : { set: new Set(), bad: new Set() };

  paintGrid(el('grid-own'), state.propria, {
    cursor: placing ? cursor : null,
    preview: prev.set,
    bad: prev.bad,
  });
  paintGrid(el('grid-enemy'), state.nemica, { cursor: myTurn ? cursor : null });

  el('phase-text').textContent = state.attesa_avversario
    ? `Giocatore ${state.giocatore}: in attesa del secondo giocatore`
    : state.fase === 'posizionamento'
      ? `Piazza nave ${state.prossima_lunghezza || '-'} (${COLS[cursor.c]}${cursor.r + 1})`
      : state.fase === 'fine'
        ? state.vincitore === giocatore
          ? 'Vittoria.'
          : 'Sconfitta.'
        : myTurn
          ? 'Tuo turno — colpito = giri ancora'
          : `Turno giocatore ${state.turno}`;

  el('btn-rotate').hidden = !placing;
  el('btn-auto').hidden = !placing;
  el('btn-fire').textContent = placing ? 'Piazza' : myTurn ? 'Spara' : 'Attendi';
  el('btn-fire').disabled = !placing && !myTurn;
}

async function refresh() {
  const state = await api(`/api/stato?token=${encodeURIComponent(token)}`);
  render(state);
  if (state.fase === 'fine' && polling) {
    clearInterval(polling);
    polling = null;
  }
}

async function join() {
  apiBase = el('api-base').value.trim();
  localStorage.setItem('bn_api_base', apiBase);
  el('status').textContent = 'Connessione…';
  const data = await api('/api/unisciti', { method: 'POST', body: '{}' });
  token = data.token;
  giocatore = data.giocatore;
  el('status').textContent = `Giocatore ${giocatore} — ${data.connessi}/${data.richiesti}`;
  el('boards').hidden = false;
  el('panel-controls').hidden = false;
  await refresh();
  if (polling) clearInterval(polling);
  polling = setInterval(refresh, 1000);
}

async function confirm() {
  if (!lastState) return;
  if (lastState.fase === 'posizionamento' && lastState.prossima_lunghezza) {
    await api('/api/piazza', {
      method: 'POST',
      body: JSON.stringify({ token, riga: cursor.r, colonna: cursor.c, orizzontale }),
    });
  } else if (lastState.turno === giocatore) {
    await api('/api/spara', {
      method: 'POST',
      body: JSON.stringify({ token, riga: cursor.r, colonna: cursor.c }),
    });
  }
  await refresh();
}

function move(dr, dc) {
  cursor.r = Math.max(0, Math.min(SIZE - 1, cursor.r + dr));
  cursor.c = Math.max(0, Math.min(SIZE - 1, cursor.c + dc));
  if (lastState) render(lastState);
}

async function autoPlace() {
  if (!lastState?.prossima_lunghezza) return;
  const len = lastState.prossima_lunghezza;
  for (const horiz of [true, false]) {
    for (let r = 0; r < SIZE; r++) {
      for (let c = 0; c < SIZE; c++) {
        let ok = true;
        for (let i = 0; i < len; i++) {
          const rr = r + (horiz ? 0 : i);
          const cc = c + (horiz ? i : 0);
          if (rr >= SIZE || cc >= SIZE || lastState.propria[rr][cc] !== '.') {
            ok = false;
            break;
          }
        }
        if (ok) {
          orizzontale = horiz;
          cursor = { r, c };
          await api('/api/piazza', {
            method: 'POST',
            body: JSON.stringify({ token, riga: r, colonna: c, orizzontale: horiz }),
          });
          await refresh();
          return;
        }
      }
    }
  }
  el('status').textContent = 'Nessuno spazio per auto-piazzamento.';
}

el('btn-join').addEventListener('click', () => join().catch((e) => (el('status').textContent = e.message)));
el('btn-fire').addEventListener('click', () => confirm().catch((e) => (el('status').textContent = e.message)));
el('btn-rotate').addEventListener('click', () => {
  orizzontale = !orizzontale;
  if (lastState) render(lastState);
});
el('btn-auto').addEventListener('click', () => autoPlace().catch((e) => (el('status').textContent = e.message)));

document.querySelectorAll('.pad').forEach((btn) => {
  btn.addEventListener('click', () => {
    const d = btn.dataset.dir;
    if (d === 'up') move(-1, 0);
    if (d === 'down') move(1, 0);
    if (d === 'left') move(0, -1);
    if (d === 'right') move(0, 1);
  });
});

el('grid-enemy').addEventListener('click', (ev) => {
  const t = ev.target;
  if (!(t instanceof HTMLElement) || !t.dataset.r) return;
  cursor.r = Number(t.dataset.r);
  cursor.c = Number(t.dataset.c);
  if (lastState?.fase === 'battaglia' && lastState.turno === giocatore) {
    confirm().catch((e) => (el('status').textContent = e.message));
  } else if (lastState) render(lastState);
});

loadApiBase();
