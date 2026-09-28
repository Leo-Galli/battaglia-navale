<div align="center">

# Battaglia Navale

Due giocatori, terminale, rete TCP. Un file Python, niente dipendenze.

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)
[![Dependencies](https://img.shields.io/badge/Dipendenze-Zero-FF6B6B?style=for-the-badge)](battaglia_navale.py)
[![Platform](https://img.shields.io/badge/Linux%20%7C%20macOS%20%7C%20Windows-0078D4?style=for-the-badge&logo=windows&logoColor=white)](avvia.sh)

[Sito del progetto](website/) · deploy statico con [Astro](https://astro.build) (`vercel.json` in root)

</div>

Serve **Python 3.10+**. Il launcher (`battaglia_navale.py` o `avvia.sh` / `avvia.bat`) fa tutto: avvia il server in background, connetti, controlla lo stato, ferma. Menu con frecce e Invio; in **Esci** anche **Q**.

**In locale:** avvia il server (default `127.0.0.1:5555`), apri due terminali, **Connetti in rete** in entrambi, piazza le navi e gioca. A fine partita **Ferma server**.

```bash
./avvia.sh                    # Linux/macOS (chmod +x la prima volta)
python3 battaglia_navale.py   # stesso menu ovunque
```

Porta a scelta (1024–65535, controllata libera). **Solo questo PC** → `127.0.0.1`; **LAN/Internet** → `0.0.0.0` (in LAN sul client usa l’indirizzo interno che vedi in **Stato server**). Per giocare da fuori serve port forwarding sul router.

Senza menu, da terminale:

```bash
python3 battaglia_navale.py server
python3 battaglia_navale.py server 0.0.0.0 5555
python3 battaglia_navale.py client
python3 battaglia_navale.py client 127.0.0.1 5555
```

Runtime in `.battaglia_navale/` (`server.log`, `server.pid`, `server.json`).

**Regole:** griglia 10×10 (A–J, 1–10), flotta 4-3-3-2-2-2-1×4. Piazzamento: frecce, Invio sui due estremi (**R** per rifare il primo). Sparo: frecce sulla griglia avversaria, Invio. `.` acqua, `N` tua nave, `X` colpito, `O` mancato. Vince chi affonda tutto.

Tutto in `battaglia_navale.py`; `avvia.sh` e `avvia.bat` sono solo comodi da lanciare.

<div align="center">

MIT — Leonardo Galli, 2026 · [`LICENSE`](LICENSE)

</div>
