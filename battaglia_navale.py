#!/usr/bin/env python3
# Battaglia navale: server, client e menu nel terminale.
from __future__ import annotations

import json
import os
import random
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import unicodedata
import re
import signal
import socket
import subprocess
import sys
import threading
import termios
import tty
import time
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.abspath(__file__)
CARTELLA_DATI = os.path.join(BASE, ".battaglia_navale")
PID_FILE = os.path.join(CARTELLA_DATI, "server.pid")
PID_WEB_FILE = os.path.join(CARTELLA_DATI, "server-web.pid")
LOG_FILE = os.path.join(CARTELLA_DATI, "server.log")
LOG_WEB_FILE = os.path.join(CARTELLA_DATI, "server-web.log")
CONFIG_FILE = os.path.join(CARTELLA_DATI, "server.json")

# --- Game engine (formerly motore.py) ---
ACQUA = "."
NAVE = "N"
COLPITO = "X"
MANCATO = "O"
DIMENSIONE_GRIGLIA = 10
COLONNE = "ABCDEFGHIJ"
LUNGHEZZE_NAVI = [4, 3, 3, 2, 2, 2, 1, 1, 1, 1]
POTERI_TIPI = ("radar", "salvo")


def parse_coordinata(testo):
    testo = testo.strip().upper().replace(" ", "")
    if len(testo) < 2:
        return None
    colonna = testo[0]
    if colonna not in COLONNE:
        return None
    try:
        riga = int(testo[1:])
    except ValueError:
        return None
    if riga < 1 or riga > DIMENSIONE_GRIGLIA:
        return None
    return riga - 1, COLONNE.index(colonna)


def coordinate_label(riga, colonna):
    return f"{COLONNE[colonna]}{riga + 1}"


class Tavola:
    def __init__(self):
        self.griglia = [[ACQUA for _ in range(DIMENSIONE_GRIGLIA)] for _ in range(DIMENSIONE_GRIGLIA)]
        self.colpi_ricevuti = [[False for _ in range(DIMENSIONE_GRIGLIA)] for _ in range(DIMENSIONE_GRIGLIA)]
        self.navi = []

    def dentro(self, riga, colonna):
        return 0 <= riga < DIMENSIONE_GRIGLIA and 0 <= colonna < DIMENSIONE_GRIGLIA

    def celle_nave(self, riga, colonna, lunghezza, orizzontale):
        celle = []
        for i in range(lunghezza):
            r = riga if orizzontale else riga + i
            c = colonna + i if orizzontale else colonna
            celle.append((r, c))
        return celle

    def posizione_valida(self, riga, colonna, lunghezza, orizzontale):
        celle = self.celle_nave(riga, colonna, lunghezza, orizzontale)
        for r, c in celle:
            if not self.dentro(r, c):
                return False
            if self.griglia[r][c] != ACQUA:
                return False
        return True

    def piazza_nave(self, riga, colonna, lunghezza, orizzontale):
        if not self.posizione_valida(riga, colonna, lunghezza, orizzontale):
            return False
        celle = self.celle_nave(riga, colonna, lunghezza, orizzontale)
        for r, c in celle:
            self.griglia[r][c] = NAVE
        self.navi.append(list(celle))
        return True

    def spara(self, riga, colonna):
        if not self.dentro(riga, colonna):
            return "invalido", False
        if self.colpi_ricevuti[riga][colonna]:
            return "già_colpito", False
        self.colpi_ricevuti[riga][colonna] = True
        if self.griglia[riga][colonna] == NAVE:
            self.griglia[riga][colonna] = COLPITO
            affondata = self.nave_affondata_in(riga, colonna)
            return "colpito", affondata
        self.griglia[riga][colonna] = MANCATO
        return "mancato", False

    def nave_affondata_in(self, riga, colonna):
        for segmento in self.navi:
            if (riga, colonna) in segmento:
                for r, c in segmento:
                    if self.griglia[r][c] != COLPITO:
                        return False
                return True
        return False

    def tutte_navi_affondate(self):
        for segmento in self.navi:
            for r, c in segmento:
                if self.griglia[r][c] != COLPITO:
                    return False
        return True

    def matrice(self, mostra_navi=True):
        out = []
        for r in range(DIMENSIONE_GRIGLIA):
            riga = []
            for c in range(DIMENSIONE_GRIGLIA):
                cella = self.griglia[r][c]
                if not mostra_navi and cella == NAVE:
                    riga.append(ACQUA)
                else:
                    riga.append(cella)
            out.append(riga)
        return out

    def righe_testo(self, mostra_navi=True):
        righe = ["   " + " ".join(COLONNE)]
        for i in range(DIMENSIONE_GRIGLIA):
            pezzi = []
            for j in range(DIMENSIONE_GRIGLIA):
                cella = self.griglia[i][j]
                if not mostra_navi and cella == NAVE:
                    pezzi.append(ACQUA)
                else:
                    pezzi.append(cella)
            righe.append(f"{i + 1:2d} " + " ".join(pezzi))
        return righe

    def disegna(self, titolo, mostra_navi=True):
        linee = [titolo] + self.righe_testo(mostra_navi)
        return "\n".join(linee)


class Partita:
    def __init__(self):
        self.lock = threading.Lock()
        self.tavole = {1: Tavola(), 2: Tavola()}
        self.indice_nave = {1: 0, 2: 0}
        self.fase = "posizionamento"
        self.turno = 1
        self.vincitore = None
        self.poteri = {1: {p: True for p in POTERI_TIPI}, 2: {p: True for p in POTERI_TIPI}}
        self.ultimo_radar = {1: None, 2: None}

    def prossima_lunghezza(self, giocatore):
        indice = self.indice_nave[giocatore]
        if indice >= len(LUNGHEZZE_NAVI):
            return None
        return LUNGHEZZE_NAVI[indice]

    def posizionamento_completo(self):
        return all(self.indice_nave[g] >= len(LUNGHEZZE_NAVI) for g in (1, 2))

    def piazza(self, giocatore, riga, colonna, orizzontale):
        with self.lock:
            if self.fase != "posizionamento":
                return False, "fase_errata"
            lunghezza = self.prossima_lunghezza(giocatore)
            if lunghezza is None:
                return False, "flotta_completa"
            tavola = self.tavole[giocatore]
            if not tavola.piazza_nave(riga, colonna, lunghezza, orizzontale):
                return False, "posizione_non_valida"
            self.indice_nave[giocatore] += 1
            if self.posizionamento_completo():
                self.fase = "battaglia"
            return True, lunghezza

    def _celle_radar(self, riga, colonna):
        out = []
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                r, c = riga + dr, colonna + dc
                if 0 <= r < DIMENSIONE_GRIGLIA and 0 <= c < DIMENSIONE_GRIGLIA:
                    out.append((r, c))
        return out

    def _celle_salvo(self, riga, colonna):
        celle = [(riga, colonna)]
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            r, c = riga + dr, colonna + dc
            if 0 <= r < DIMENSIONE_GRIGLIA and 0 <= c < DIMENSIONE_GRIGLIA:
                celle.append((r, c))
        return celle

    def usa_potere(self, giocatore, tipo, riga, colonna):
        with self.lock:
            if self.fase != "battaglia":
                return None
            if giocatore != self.turno:
                return {"ok": False, "motivo": "turno_errato"}
            if tipo not in POTERI_TIPI:
                return {"ok": False, "motivo": "potere_sconosciuto"}
            if not self.poteri[giocatore].get(tipo):
                return {"ok": False, "motivo": "potere_esaurito"}
            avversario = 2 if giocatore == 1 else 1
            tavola = self.tavole[avversario]
            if not tavola.dentro(riga, colonna):
                return {"ok": False, "motivo": "coordinata_invalida"}

            if tipo == "radar":
                self.poteri[giocatore]["radar"] = False
                celle = self._celle_radar(riga, colonna)
                rivelazione = []
                for r, c in celle:
                    ship = tavola.griglia[r][c] == NAVE
                    rivelazione.append({"riga": r, "colonna": c, "nave": ship})
                self.ultimo_radar[giocatore] = rivelazione
                self.turno = avversario
                return {
                    "ok": True,
                    "tipo": "radar",
                    "celle": rivelazione,
                    "prossimo_turno": self.turno,
                }

            self.poteri[giocatore]["salvo"] = False
            colpi = []
            any_hit = False
            for r, c in self._celle_salvo(riga, colonna):
                if tavola.colpi_ricevuti[r][c]:
                    colpi.append({"riga": r, "colonna": c, "esito": "già_colpito"})
                    continue
                esito, affondata = tavola.spara(r, c)
                colpi.append({"riga": r, "colonna": c, "esito": esito, "affondata": affondata})
                if esito == "colpito":
                    any_hit = True
            payload = {
                "ok": True,
                "tipo": "salvo",
                "colpi": colpi,
                "riga": riga,
                "colonna": colonna,
                "bersaglio": avversario,
            }
            if tavola.tutte_navi_affondate():
                self.vincitore = giocatore
                self.fase = "fine"
                payload["vittoria"] = giocatore
            elif not any_hit:
                self.turno = avversario
            payload["prossimo_turno"] = self.turno
            return payload

    def spara(self, giocatore, riga, colonna):
        with self.lock:
            if self.fase != "battaglia":
                return None
            if giocatore != self.turno:
                return {"esito": "turno_errato"}
            avversario = 2 if giocatore == 1 else 1
            tavola = self.tavole[avversario]
            risultato, affondata = tavola.spara(riga, colonna)
            if risultato == "invalido":
                return {"esito": "coordinata_invalida"}
            if risultato == "già_colpito":
                return {"esito": "già_colpito"}
            payload = {
                "esito": risultato,
                "affondata": affondata,
                "riga": riga,
                "colonna": colonna,
                "bersaglio": avversario,
            }
            if tavola.tutte_navi_affondate():
                self.vincitore = giocatore
                self.fase = "fine"
                payload["vittoria"] = giocatore
            elif risultato == "mancato":
                self.turno = avversario
            payload["prossimo_turno"] = self.turno
            return payload

    def snapshot_giocatore(self, giocatore):
        with self.lock:
            avversario = 2 if giocatore == 1 else 1
            return {
                "fase": self.fase,
                "turno": self.turno,
                "giocatore": giocatore,
                "vincitore": self.vincitore,
                "prossima_lunghezza": self.prossima_lunghezza(giocatore),
                "propria": self.tavole[giocatore].matrice(mostra_navi=True),
                "nemica": self.tavole[avversario].matrice(mostra_navi=False),
                "navi_piazzate": self.indice_nave[giocatore],
                "navi_totali": len(LUNGHEZZE_NAVI),
                "poteri": dict(self.poteri[giocatore]),
                "radar_ultimo": self.ultimo_radar.get(giocatore),
            }


def celle_nave(riga, colonna, lunghezza, orizzontale):
    out = []
    for i in range(lunghezza):
        r = riga if orizzontale else riga + i
        c = colonna + i if orizzontale else colonna
        if r < 0 or r >= DIMENSIONE_GRIGLIA or c < 0 or c >= DIMENSIONE_GRIGLIA:
            return None
        out.append((r, c))
    return out


def piazzamento_valido(griglia, riga, colonna, lunghezza, orizzontale):
    celle = celle_nave(riga, colonna, lunghezza, orizzontale)
    if celle is None:
        return False
    for r, c in celle:
        if griglia[r][c] != ACQUA:
            return False
    return True


def piazzamento_casuale(griglia, lunghezza):
    opzioni = []
    for orizzontale in (True, False):
        for r in range(DIMENSIONE_GRIGLIA):
            for c in range(DIMENSIONE_GRIGLIA):
                celle = celle_nave(r, c, lunghezza, orizzontale)
                if celle and all(griglia[rr][cc] == ACQUA for rr, cc in celle):
                    opzioni.append((r, c, orizzontale))
    if not opzioni:
        return None
    return random.choice(opzioni)


# --- End game engine ---

PORTA_PREDEFINITA = 5555
PORTA_HTTP_PREDEFINITA = 8080
HOST_PREDEFINITO = "127.0.0.1"

PORTA_MIN = 1024
PORTA_MAX = 65535
TIMEOUT_PUBBLICO = 2.0


def normalizza_host_ascolto(scelta_locale):
    if scelta_locale:
        return "127.0.0.1"
    return "0.0.0.0"


def porta_valida(porta):
    return isinstance(porta, int) and PORTA_MIN <= porta <= PORTA_MAX


def porta_disponibile(host, porta):
    bind_host = "0.0.0.0" if host in ("0.0.0.0", "") else host
    prova = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        prova.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        prova.bind((bind_host, porta))
        return True
    except OSError:
        return False
    finally:
        prova.close()


def porta_raggiungibile(host, porta):
    bersaglio = host
    if bersaglio in ("0.0.0.0", ""):
        bersaglio = "127.0.0.1"
    try:
        with socket.create_connection((bersaglio, porta), timeout=0.5):
            return True
    except OSError:
        return False


def indirizzi_lan():
    trovati = set()
    try:
        nome = socket.gethostname()
        for info in socket.getaddrinfo(nome, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                trovati.add(ip)
    except OSError:
        pass
    try:
        uscita = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        uscita.connect(("8.8.8.8", 80))
        ip = uscita.getsockname()[0]
        uscita.close()
        if not ip.startswith("127."):
            trovati.add(ip)
    except OSError:
        pass
    return sorted(trovati)


def indirizzo_pubblico():
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=TIMEOUT_PUBBLICO) as risposta:
            testo = risposta.read().decode("utf-8").strip()
            if testo and "." in testo:
                return testo
    except OSError:
        pass
    try:
        with urllib.request.urlopen("https://ifconfig.me/ip", timeout=TIMEOUT_PUBBLICO) as risposta:
            testo = risposta.read().decode("utf-8").strip()
            if testo and "." in testo:
                return testo
    except OSError:
        pass
    return None


def formato_endpoint(host, porta):
    return f"{host}:{porta}"


def righe_endpoint(porta, host_ascolto="0.0.0.0"):
    righe = []
    righe.append(("locale", "127.0.0.1", porta))
    for ip in indirizzi_lan():
        righe.append(("lan", ip, porta))
    pubblico = indirizzo_pubblico()
    if pubblico:
        righe.append(("pubblico", pubblico, porta))
    if host_ascolto == "127.0.0.1":
        return [r for r in righe if r[0] == "locale"]
    return righe


def etichetta_tipo(tipo):
    if tipo == "locale":
        return "Locale (questo PC)"
    if tipo == "lan":
        return "Rete interna (LAN)"
    if tipo == "pubblico":
        return "Internet (IP pubblico)"
    return tipo


def _defaults_config():
    return {
        "host": "127.0.0.1",
        "porta": 5555,
        "porta_http": PORTA_HTTP_PREDEFINITA,
        "conferme_veloci": True,
    }


def carica_config(percorso):
    cfg = carica_config_completa(percorso)
    host = cfg.get("host")
    porta = cfg.get("porta")
    if host and porta_valida(porta):
        return host, porta
    return None


def carica_config_completa(percorso):
    base = _defaults_config()
    if not os.path.isfile(percorso):
        return dict(base)
    try:
        with open(percorso, "r", encoding="utf-8") as handle:
            dati = json.load(handle)
        if isinstance(dati, dict):
            base.update(dati)
        porta = int(base.get("porta", base["porta"]))
        base["porta"] = porta
        base["porta_http"] = int(base.get("porta_http", PORTA_HTTP_PREDEFINITA))
        base["conferme_veloci"] = bool(base.get("conferme_veloci", False))
    except (OSError, ValueError, TypeError):
        pass
    return base


def salva_config_completa(percorso, cfg):
    cartella = os.path.dirname(percorso)
    if cartella:
        os.makedirs(cartella, exist_ok=True)
    out = _defaults_config()
    out.update(cfg)
    with open(percorso, "w", encoding="utf-8") as handle:
        json.dump(out, handle, ensure_ascii=False, indent=2)


def invia(connessione, messaggio):
    dati = (json.dumps(messaggio, ensure_ascii=False) + "\n").encode("utf-8")
    connessione.sendall(dati)


class Ricevitore:
    def __init__(self, connessione):
        self.connessione = connessione
        self.buffer = ""

    def ricevi(self):
        while "\n" not in self.buffer:
            blocco = self.connessione.recv(4096)
            if not blocco:
                return None
            self.buffer += blocco.decode("utf-8")
        riga, self.buffer = self.buffer.split("\n", 1)
        return json.loads(riga)


RESET = "\033[0m"
GRIGIO = "\033[90m"
CIANO = "\033[96m"
VERDE = "\033[92m"
GIALLO = "\033[93m"
ROSSO = "\033[91m"
BLU = "\033[94m"
MAGENTA = "\033[95m"
BIANCO = "\033[97m"
GRASSETTO = "\033[1m"

LARGHEZZA_PANNELLO = 80

_ASCII_TITOLO = """    dBBBBb dBBBBBb  dBBBBBBP dBBBBBBP dBBBBBb     dBBBBb  dBP    dBP dBBBBBb
      dBP      BB                         BB                             BB
  dBBBK'   dBP BB   dBP      dBP      dBP BB   dBBBB   dBP    dBP    dBP BB
 dB' db   dBP  BB  dBP      dBP      dBP  BB  dB' BB  dBP    dBP    dBP  BB
dBBBBP'  dBBBBBBB dBP      dBP      dBBBBBBB dBBBBBB dBBBBP dBP    dBBBBBBB

    dBBBBb dBBBBBb   dBP dP dBBBBBb     dBP    dBBBP
       dBP      BB               BB
  dBP dBP   dBP BB dB .BP    dBP BB   dBP    dBBP
 dBP dBP   dBP  BB BB.BP    dBP  BB  dBP    dBP
dBP dBP   dBBBBBBB BBBP    dBBBBBBB dBBBBP dBBBBP"""


def supporta_colori():
    if os.environ.get("NO_COLOR"):
        return False
    if sys.platform == "win32":
        os.system("")
        return True
    return sys.stdout.isatty()


def stile(testo, sequenza):
    if supporta_colori():
        return f"{sequenza}{testo}{RESET}"
    return testo


def pulisci_schermo():
    if sys.platform == "win32":
        os.system("cls")
    else:
        os.system("clear")


def _centra_blocco_ascii(righe, larghezza):
    visibili = [r for r in righe if r]
    max_w = max((len(r) for r in visibili), default=0)
    margine = max(0, (larghezza - max_w) // 2)
    pad = " " * margine
    return [pad + r if r else "" for r in righe]


def _righe_intestazione_principale():
    righe = [r.rstrip() for r in _ASCII_TITOLO.split("\n")]
    return _centra_blocco_ascii(righe, LARGHEZZA_PANNELLO - 4)


def _intestazione_stilizzata():
    righe = _righe_intestazione_principale()
    out = []
    dopo_vuoto = False
    for riga in righe:
        if not riga:
            out.append("")
            dopo_vuoto = True
            continue
        col = GRASSETTO + (BIANCO if dopo_vuoto else CIANO)
        out.append(stile(riga, col))
    return out


def banner_principale():
    return riquadro_menu(None, [], intestazione=_intestazione_stilizzata())


def _riga_pannello_plain(contenuto, larghezza, allinea="sinistra"):
    interno = larghezza - 4
    plain = testo_piano(contenuto)
    vis = larghezza_visibile(plain)
    if not plain:
        return f"║ {' ' * interno} ║"
    if allinea == "centro":
        pad_sin = (interno - vis) // 2
        pad_des = interno - vis - pad_sin
        return f"║ {' ' * pad_sin}{plain}{' ' * pad_des} ║"
    return f"║ {plain}{' ' * (interno - vis)} ║"


def _linee_pannello_plain(titolo, righe_contenuto, larghezza=LARGHEZZA_PANNELLO, intestazione=None):
    b = "═" * (larghezza - 2)
    sep = f"╠{b}╣"
    linee = [f"╔{b}╗"]
    if intestazione:
        for riga in intestazione:
            linee.append(_riga_pannello_plain(riga, larghezza, allinea="sinistra"))
        if titolo or righe_contenuto:
            linee.append(sep)
    if titolo:
        linee.append(f"║ {titolo.center(larghezza - 4)} ║")
        if righe_contenuto:
            linee.append(sep)
    elif righe_contenuto and not intestazione:
        linee.append(sep)
    for riga in righe_contenuto:
        plain = testo_piano(riga)
        while plain and larghezza_visibile(plain) > larghezza - 4:
            plain = plain[:-1]
        linee.append(f"║ {plain}{' ' * (larghezza - 4 - larghezza_visibile(plain))} ║")
    linee.append(f"╚{b}╝")
    return linee


def linea_orizzontale(larghezza, caratteri=("╔", "═", "╗")):
    sinistra, ripetuto, destra = caratteri
    return sinistra + ripetuto * (larghezza - 2) + destra


def riga_pannello(contenuto, larghezza):
    interno = larghezza - 4
    return f"║ {riempi_visibile(contenuto, interno)} ║"


def riquadro_menu(titolo, righe, larghezza=LARGHEZZA_PANNELLO, intestazione=None):
    alto = linea_orizzontale(larghezza)
    separatore = linea_orizzontale(larghezza, ("╠", "═", "╣"))
    chiusura = linea_orizzontale(larghezza, ("╚", "═", "╝"))
    corpo = [alto]
    if intestazione:
        for riga in intestazione:
            if testo_piano(riga):
                corpo.append(riga_pannello(riempi_visibile(riga, larghezza - 4), larghezza))
            else:
                corpo.append(riga_pannello("", larghezza))
        if titolo or righe:
            corpo.append(separatore)
    if titolo:
        titolo_fmt = stile(titolo, GRASSETTO + BIANCO)
        corpo.append(riga_pannello(riempi_visibile(titolo_fmt, larghezza - 4, "centro"), larghezza))
        if righe:
            corpo.append(separatore)
    elif righe and not intestazione:
        corpo.append(separatore)
    for riga in righe:
        if larghezza_visibile(riga) > larghezza - 4:
            plain = riga
            while larghezza_visibile(plain) > larghezza - 4 and plain:
                plain = plain[:-1]
            riga = plain
        corpo.append(riga_pannello(riga, larghezza))
    corpo.append(chiusura)
    return "\n".join(corpo)


def riquadro(titolo, righe, larghezza=LARGHEZZA_PANNELLO):
    return riquadro_menu(titolo, righe, larghezza)


def menu_principale():
    opzioni = [
        "Avvia server (terminale TCP)",
        "Avvia server web (online browser)",
        "Connetti in rete (terminale)",
        "Stato server",
        "Ferma server",
        "Esci",
    ]
    return menu_a_frecce(opzioni, titolo="Menu principale", intestazione=True)


def pannello_endpoint(endpoints):
    righe = []
    for tipo, host, porta in endpoints:
        eti = etichetta_tipo(tipo)
        url = formato_endpoint(host, porta)
        if tipo == "locale":
            col = VERDE
        elif tipo == "lan":
            col = CIANO
        else:
            col = MAGENTA
        righe.append(stile(eti + ": ", GRASSETTO + col) + stile(url, GRASSETTO + BIANCO))
    if any(t == "pubblico" for t, _, _ in endpoints):
        righe.append("")
        righe.append(stile("Per giocare da fuori casa apri la stessa porta sul router.", GIALLO))
    print()
    print(riquadro("Indirizzi di connessione", righe))
    print()


def cornice_tavola(titolo, righe_griglia):
    larghezza = max(larghezza_visibile(titolo) + 4, 32)
    for riga in righe_griglia:
        larghezza = max(larghezza, larghezza_visibile(riga) + 4)
    alto = linea_orizzontale(larghezza, ("┏", "━", "┓"))
    chiusura = linea_orizzontale(larghezza, ("┗", "━", "┛"))
    titolo_fmt = stile(titolo, GRASSETTO + BLU)
    out = [alto, f"┃ {riempi_visibile(titolo_fmt, larghezza - 4, 'centro')} ┃"]
    out.append(linea_orizzontale(larghezza, ("┣", "━", "┫")))
    for riga in righe_griglia:
        out.append(f"┃ {riempi_visibile(riga, larghezza - 4)} ┃")
    out.append(chiusura)
    return "\n".join(out)


def colora_cella(simbolo):
    vis = simbolo_visivo(simbolo)
    if simbolo == "N":
        return stile(vis, VERDE + GRASSETTO)
    if simbolo == "X":
        return stile(vis, ROSSO + GRASSETTO)
    if simbolo == "O":
        return stile(vis, GIALLO)
    if simbolo == ".":
        return stile(vis, GRIGIO)
    return vis


def abbellisci_tavola_testo(testo_tavola):
    righe = testo_tavola.split("\n")
    if not righe:
        return testo_tavola
    titolo = righe[0]
    griglia = []
    for riga in righe[1:]:
        if not riga.strip():
            continue
        pezzi = []
        for carattere in riga:
            if carattere in "NXO.":
                pezzi.append(colora_cella(carattere))
            else:
                pezzi.append(carattere)
        griglia.append("".join(pezzi))
    return cornice_tavola(titolo, griglia)


def pannello_evento(titolo, messaggio):
    righe = messaggio.split("\n")
    print()
    print(riquadro(titolo, righe))
    print()


def pannello_legenda():
    righe = [
        stile(" . ", GRIGIO) + " acqua",
        stile(" # ", VERDE + GRASSETTO) + " tua nave",
        stile(" X ", ROSSO + GRASSETTO) + " colpito",
        stile(" o ", GIALLO) + " mancato",
    ]
    print(riquadro("Legenda", righe, larghezza=44))


def intestazione_fase(fase, turno, giocatore):
    if fase == "posizionamento":
        testo = "Stai posizionando la tua flotta"
    elif fase == "battaglia":
        if turno == giocatore:
            testo = stile("È il tuo turno: scegli dove sparare", VERDE + GRASSETTO)
        else:
            testo = stile(f"Turno del giocatore {turno}: attendi", GIALLO)
    else:
        testo = f"Fase: {fase}"
    print()
    print(riquadro("Situazione", [testo]))
    print()


def prompt(testo):
    return input(stile(testo, CIANO)).strip()


def messaggio_errore(testo):
    pannello_evento("Attenzione", stile(testo, ROSSO))


def messaggio_ok(testo):
    pannello_evento("Informazione", stile(testo, VERDE))


def schermata_client():
    pulisci_schermo()
    print(banner_principale())
    print()


def chiedi_modalita_ascolto():
    indice = scelta_a_frecce(
        [
            "Solo questo computer (127.0.0.1)",
            "Rete locale e Internet (0.0.0.0)",
        ],
        titolo="Modalità server",
    )
    return indice == 0


def chiedi_porta(predefinita):
    opzioni = ["5555", "5556", "7777", "8888", "9000", "Inserisci porta personalizzata"]
    indice = scelta_a_frecce(opzioni, titolo="Porta del server")
    if indice == len(opzioni) - 1:
        testo = prompt(f"Porta TCP [{predefinita}]: ") or str(predefinita)
        try:
            return int(testo)
        except ValueError:
            return None
    return int(opzioni[indice])


def chiedi_host_client(endpoints, predefinito="127.0.0.1"):
    if not endpoints:
        return prompt(f"Host del server [{predefinito}]: ") or predefinito
    pannello_endpoint(endpoints)
    etichette = []
    hosts = []
    for tipo, host, porta in endpoints:
        etichette.append(f"{etichetta_tipo(tipo)} — {formato_endpoint(host, porta)}")
        hosts.append(host)
    etichette.append("Inserisci host manualmente")
    indice = scelta_a_frecce(etichette, titolo="Dove ti connetti")
    if indice == len(etichette) - 1:
        return prompt(f"Host [{predefinito}]: ") or predefinito
    return hosts[indice]


_RE_ANSI = re.compile(r"\033\[[0-9;]*m")


def larghezza_visibile(testo):
    n = 0
    for ch in _RE_ANSI.sub("", testo or ""):
        if unicodedata.combining(ch):
            continue
        n += 2 if unicodedata.east_asian_width(ch) in "WF" else 1
    return n


def testo_piano(testo):
    return _RE_ANSI.sub("", testo or "")


def riempi_visibile(testo, larghezza, allinea="sinistra"):
    extra = larghezza - larghezza_visibile(testo)
    if extra <= 0:
        return testo
    if allinea == "centro":
        sin = extra // 2
        des = extra - sin
        return " " * sin + testo + " " * des
    return testo + " " * extra


def _prova_curses():
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return None
    try:
        import curses
        return curses
    except ImportError:
        return None


def _decodifica_tasto(b):
    if b in ("\r", "\n"):
        return "invio"
    low = b.lower()
    if low in ("q", "\x1b"):
        return "esci"
    if low == "r":
        return "ruota"
    if b in ("A", "0"):
        return "auto"
    if low in ("w", "8", "k"):
        return "su"
    if low in ("s", "2", "j"):
        return "giu"
    if low in ("a", "4", "h"):
        return "sinistra"
    if low in ("d", "6", "l"):
        return "destra"
    if b == " ":
        return "ruota"
    return "altro"


def _leggi_tasto_raw():
    if sys.platform == "win32":
        import msvcrt
        primo = msvcrt.getwch()
        if primo in ("\x00", "\xe0"):
            secondo = msvcrt.getwch()
            mappa = {"H": "su", "P": "giu", "K": "sinistra", "M": "destra"}
            return mappa.get(secondo, "altro")
        return _decodifica_tasto(primo)
    fd = sys.stdin.fileno()
    vecchio = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        b = sys.stdin.read(1)
        if b == "\x1b":
            resto = sys.stdin.read(2)
            if resto == "[A":
                return "su"
            if resto == "[B":
                return "giu"
            if resto == "[C":
                return "destra"
            if resto == "[D":
                return "sinistra"
            return "esci"
        return _decodifica_tasto(b)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, vecchio)


def _menu_fallback(opzioni, titolo="Menu principale", indice_iniziale=0, intestazione=False):
    indice = indice_iniziale
    while True:
        if sys.platform == "win32":
            os.system("cls")
        else:
            os.system("clear")
        print(_render_statico(opzioni, indice, titolo, intestazione=intestazione))
        sys.stdout.flush()
        tasto = _leggi_tasto_raw()
        if tasto == "su":
            indice = (indice - 1) % len(opzioni)
        elif tasto == "giu":
            indice = (indice + 1) % len(opzioni)
        elif tasto == "invio":
            return indice
        elif tasto == "esci":
            return len(opzioni) - 1


def _render_statico(opzioni, selezione, titolo="Menu principale", intestazione=False):
    righe = []
    for i, voce in enumerate(opzioni):
        if i == selezione:
            righe.append(stile(" > " + voce, GRASSETTO + CIANO))
        else:
            righe.append("   " + voce)
    head = _intestazione_stilizzata() if intestazione else None
    return riquadro_menu(titolo, righe, intestazione=head)


def _attr_riga_menu(curses, linea):
    if " > " in linea:
        return curses.color_pair(3) | curses.A_BOLD
    if linea[:1] in "╔╠╚":
        return curses.color_pair(5)
    return curses.color_pair(4)


def _menu_curses(curses, opzioni, titolo, intestazione=False):
    def _interno(stdscr):
        curses.curs_set(0)
        stdscr.keypad(True)
        _init_coppie_colori(curses)
        selezione = 0
        head = _righe_intestazione_principale() if intestazione else None
        while True:
            stdscr.erase()
            h, w = stdscr.getmaxyx()
            x0 = max(0, (w - LARGHEZZA_PANNELLO) // 2)
            y = 0
            voci = []
            for i, voce in enumerate(opzioni):
                if i == selezione:
                    voci.append(f" > {voce}")
                else:
                    voci.append(f"   {voce}")
            for linea in _linee_pannello_plain(titolo, voci, intestazione=head):
                if y >= h:
                    break
                try:
                    stdscr.addstr(y, x0, linea[: max(0, w - x0)], _attr_riga_menu(curses, linea))
                except curses.error:
                    pass
                y += 1
            stdscr.refresh()
            tasto = stdscr.getch()
            if tasto in (curses.KEY_UP, ord("k")):
                selezione = (selezione - 1) % len(opzioni)
            elif tasto in (curses.KEY_DOWN, ord("j")):
                selezione = (selezione + 1) % len(opzioni)
            elif tasto in (10, 13, curses.KEY_ENTER):
                return selezione
            elif tasto in (27, ord("q"), ord("Q")):
                return len(opzioni) - 1
    return curses.wrapper(_interno)


def menu_a_frecce(opzioni, titolo="Menu principale", intestazione=False):
    mod = _prova_curses()
    if mod is not None:
        try:
            return _menu_curses(mod, opzioni, titolo, intestazione=intestazione)
        except Exception:
            pass
    return _menu_fallback(opzioni, titolo=titolo, intestazione=intestazione)


def scelta_a_frecce(opzioni, titolo="Scegli"):
    return menu_a_frecce(opzioni, titolo=titolo)


def attesa_invio(messaggio=""):
    testo = (messaggio or "").strip()
    if not testo:
        if sys.stdin.isatty():
            try:
                sys.stdin.readline()
            except OSError:
                pass
        return
    mod = _prova_curses()
    if mod is not None:
        try:
            def _interno(stdscr):
                mod.curs_set(0)
                stdscr.erase()
                h, w = stdscr.getmaxyx()
                try:
                    for i, riga in enumerate(testo.split("\n")[:8]):
                        stdscr.addstr(2 + i, 2, riga[: max(10, w - 4)], mod.color_pair(4) if mod.has_colors() else mod.A_NORMAL)
                except mod.error:
                    pass
                stdscr.refresh()
                while True:
                    t = stdscr.getch()
                    if t in (10, 13, getattr(mod, "KEY_ENTER", 343)):
                        return
            if mod.has_colors():
                mod.use_default_colors()
                mod.init_pair(4, mod.COLOR_WHITE, -1)
            mod.wrapper(_interno)
            return
        except Exception:
            pass
    input(testo + " ")


def simbolo_visivo(ch, terminale=False):
    return {".": ".", "N": "#", "X": "X", "O": "o"}.get(ch, ch)


def _init_coppie_colori(curses):
    curses.use_default_colors()
    if not curses.has_colors():
        return
    curses.init_pair(1, curses.COLOR_CYAN, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(4, curses.COLOR_WHITE, -1)
    curses.init_pair(5, curses.COLOR_CYAN, -1)
    curses.init_pair(6, curses.COLOR_GREEN, -1)
    curses.init_pair(7, curses.COLOR_YELLOW, -1)
    curses.init_pair(8, curses.COLOR_RED, -1)
    curses.init_pair(9, curses.COLOR_YELLOW, -1)
    curses.init_pair(10, curses.COLOR_BLUE, -1)
    curses.init_pair(11, curses.COLOR_RED, -1)
    curses.init_pair(12, curses.COLOR_BLACK, curses.COLOR_WHITE)


def griglia_da_tavola(tavola, mostra_navi=True):
    matrice = []
    for r in range(DIMENSIONE_GRIGLIA):
        riga = []
        for c in range(DIMENSIONE_GRIGLIA):
            cella = tavola.griglia[r][c]
            if not mostra_navi and cella == NAVE:
                riga.append(ACQUA)
            else:
                riga.append(cella)
        matrice.append(riga)
    return matrice


def estrai_griglia(testo_tavola):
    matrice = []
    for linea in testo_tavola.split("\n")[1:]:
        if not linea.strip():
            continue
        pezzi = linea.split()
        if not pezzi or not pezzi[0].isdigit():
            continue
        celle = pezzi[1:]
        if len(celle) >= DIMENSIONE_GRIGLIA:
            matrice.append(celle[:DIMENSIONE_GRIGLIA])
    while len(matrice) < DIMENSIONE_GRIGLIA:
        matrice.append(["."] * DIMENSIONE_GRIGLIA)
    return matrice[:DIMENSIONE_GRIGLIA]


def celle_in_linea(r1, c1, r2, c2):
    if r1 == r2 and c1 != c2:
        c_min, c_max = sorted([c1, c2])
        return [(r1, c) for c in range(c_min, c_max + 1)]
    if c1 == c2 and r1 != r2:
        r_min, r_max = sorted([r1, r2])
        return [(r, c1) for r in range(r_min, r_max + 1)]
    if r1 == r2 and c1 == c2:
        return [(r1, c1)]
    return []


def piazzamento_da_estremi(r1, c1, r2, c2, lunghezza):
    celle = celle_in_linea(r1, c1, r2, c2)
    if len(celle) != lunghezza:
        return None
    if r1 == r2:
        return r1, min(c1, c2), True
    if c1 == c2:
        return min(r1, r2), c1, False
    return None


def celle_anteprima(r1, c1, r2, c2, lunghezza):
    celle = celle_in_linea(r1, c1, r2, c2)
    if len(celle) != lunghezza:
        return set()
    return set(celle)


def _valida_piazzamento(griglia, r1, c1, r2, c2, lunghezza):
    risultato = piazzamento_da_estremi(r1, c1, r2, c2, lunghezza)
    if risultato is None:
        return None, "Estremi non allineati o lunghezza errata."
    celle = celle_in_linea(r1, c1, r2, c2)
    for r, c in celle:
        if griglia[r][c] != ".":
            return None, "La nave copre caselle gia occupate."
    return risultato, None


def _larghezza_griglia():
    return 4 + DIMENSIONE_GRIGLIA * 3


def _disegna_legenda_curses(stdscr, curses, y, x):
    voci = [
        (10, ". acqua"),
        (2, "# nave"),
        (8, "X colpito"),
        (9, "o mancato"),
    ]
    try:
        stdscr.addstr(y, x, "Legenda", curses.color_pair(5) | curses.A_BOLD)
        for i, (pair, testo) in enumerate(voci):
            stdscr.addstr(y + 1 + i, x, testo, curses.color_pair(pair))
    except curses.error:
        pass


def _disegna_barra_progresso(stdscr, curses, y, x, completate, totali, larghezza=24):
    if totali <= 0:
        return
    pieni = int(larghezza * completate / totali)
    barra = "#" * pieni + "-" * (larghezza - pieni)
    try:
        stdscr.addstr(y, x, f"Flotta [{completate}/{totali}] ", curses.color_pair(5))
        stdscr.addstr(y, x + 18, barra[:larghezza], curses.color_pair(2 if completate >= totali else 6))
    except curses.error:
        pass


def _disegna_griglia_curses(stdscr, curses, griglia, offset_y, offset_x, cursore, evidenziata, estremo_a, estremo_b, anteprima, anteprima_invalida, bersaglio=False):
    ox = offset_x
    try:
        header = "    " + " ".join(COLONNE)
        stdscr.addstr(offset_y, ox, header, curses.color_pair(5) | curses.A_BOLD)
        stdscr.addstr(offset_y + 1, ox, "   ┌" + "──┬" * (DIMENSIONE_GRIGLIA - 1) + "──┐", curses.color_pair(5))
    except curses.error:
        pass
    for r in range(DIMENSIONE_GRIGLIA):
        y = offset_y + 2 + r * 2
        try:
            stdscr.addstr(y, ox, f"{r + 1:2d} │", curses.color_pair(5))
        except curses.error:
            pass
        for c in range(DIMENSIONE_GRIGLIA):
            x = ox + 4 + c * 3
            raw = griglia[r][c]
            simbolo = simbolo_visivo(raw, terminale=True)
            stile = curses.color_pair(4)
            if raw == ".":
                stile = curses.color_pair(10) | curses.A_DIM
            if (r, c) in anteprima_invalida:
                stile = curses.color_pair(11) | curses.A_BOLD
            elif (r, c) in anteprima:
                stile = curses.color_pair(6) | curses.A_BOLD
            elif (r, c) == estremo_a or (r, c) == estremo_b:
                stile = curses.color_pair(7) | curses.A_BOLD
            elif cursore[0] >= 0 and (r, c) == cursore:
                stile = curses.color_pair(3) | curses.A_BOLD
            elif raw == "N":
                stile = curses.color_pair(2) | curses.A_BOLD
            elif raw == "X":
                stile = curses.color_pair(8) | curses.A_BOLD
            elif raw == "O":
                stile = curses.color_pair(9)
            cella = f" {simbolo} "
            try:
                stdscr.addstr(y, x, cella, stile)
            except curses.error:
                pass
        sep_y = y + 1
        if r < DIMENSIONE_GRIGLIA - 1:
            try:
                stdscr.addstr(sep_y, ox + 3, "├" + "──┼" * (DIMENSIONE_GRIGLIA - 1) + "──┤", curses.color_pair(5))
            except curses.error:
                pass
    try:
        foot_y = offset_y + 2 + (DIMENSIONE_GRIGLIA - 1) * 2 + 1
        stdscr.addstr(foot_y, ox + 3, "└" + "──┴" * (DIMENSIONE_GRIGLIA - 1) + "──┘", curses.color_pair(5))
    except curses.error:
        pass


def _sessione_curses(curses, griglia_propria, griglia_nemica, modalita, lunghezza=None, meta=None):
    meta = meta or {}

    def _interno(stdscr):
        curses.curs_set(0)
        stdscr.keypad(True)
        _init_coppie_colori(curses)
        r, c = 0, 0
        orizzontale = True
        messaggio = ""
        while True:
            stdscr.erase()
            h, w = stdscr.getmaxyx()
            lw = _larghezza_griglia()
            affianca = griglia_nemica is not None and w >= 2 * lw + 8
            anteprima = set()
            anteprima_invalida = set()
            if modalita == "piazza":
                celle_prev = celle_nave(r, c, lunghezza, orizzontale)
                if celle_prev is None:
                    anteprima_invalida = set()
                elif piazzamento_valido(griglia_propria, r, c, lunghezza, orizzontale):
                    anteprima = set(celle_prev)
                else:
                    anteprima_invalida = set(celle_prev)
            try:
                stdscr.addstr(0, 2, "BATTAGLIA NAVALE", curses.color_pair(1) | curses.A_BOLD)
                if modalita == "piazza":
                    segno = "—" if orizzontale else "|"
                    stdscr.addstr(1, 2, f"Nave {lunghezza}  {coordinate_label(r, c)}  {segno}", curses.color_pair(4) | curses.A_BOLD)
                elif modalita == "spara":
                    stdscr.addstr(1, 2, coordinate_label(r, c), curses.color_pair(4) | curses.A_BOLD)
            except curses.error:
                pass
            if meta.get("navi_totali"):
                _disegna_barra_progresso(stdscr, curses, 3, 2, meta.get("navi_piazzate", 0), meta["navi_totali"])
            cursore_propria = (r, c) if modalita == "piazza" else (-1, -1)
            cursore_nemica = (r, c) if modalita == "spara" else (-1, -1)
            grid_top = 5 if meta.get("navi_totali") else 4
            ox_centro = max(1, (w - lw) // 2)
            if affianca:
                ox_pro, ox_nem = 2, 2 + lw + 3
                _disegna_griglia_curses(stdscr, curses, griglia_propria, grid_top, ox_pro, cursore_propria, modalita == "piazza", None, None, anteprima, anteprima_invalida, False)
                _disegna_griglia_curses(stdscr, curses, griglia_nemica, grid_top, ox_nem, cursore_nemica, modalita == "spara", None, None, set(), set(), True)
                try:
                    stdscr.addstr(grid_top - 1, ox_nem, "Nemico", curses.color_pair(5) | curses.A_BOLD)
                    stdscr.addstr(grid_top - 1, ox_pro, "Tuoi", curses.color_pair(5) | curses.A_BOLD)
                except curses.error:
                    pass
                leg_x = min(w - 18, ox_nem + lw + 2)
            elif modalita == "spara" and griglia_nemica is not None:
                _disegna_griglia_curses(stdscr, curses, griglia_nemica, grid_top, ox_centro, cursore_nemica, True, None, None, set(), set(), True)
                try:
                    stdscr.addstr(grid_top - 1, ox_centro, "Nemico", curses.color_pair(5) | curses.A_BOLD)
                except curses.error:
                    pass
                leg_x = min(w - 18, ox_centro + lw + 2)
            else:
                _disegna_griglia_curses(stdscr, curses, griglia_propria, grid_top, ox_centro, cursore_propria, modalita == "piazza", None, None, anteprima, anteprima_invalida, False)
                try:
                    stdscr.addstr(grid_top - 1, ox_centro, "Tuoi", curses.color_pair(5) | curses.A_BOLD)
                except curses.error:
                    pass
                leg_x = w - 2
            if messaggio:
                bar_y = min(h - 2, grid_top + 2 + DIMENSIONE_GRIGLIA * 2 + 2)
                try:
                    stdscr.addstr(bar_y, 2, messaggio[: max(10, w - 4)], curses.color_pair(8))
                except curses.error:
                    pass
            stdscr.refresh()
            tasto = stdscr.getch()
            if tasto in (ord("0"),) and modalita == "piazza":
                auto = piazzamento_casuale(griglia_propria, lunghezza)
                if auto is None:
                    messaggio = "Nessuno spazio libero per questa nave."
                    continue
                return ("piazza", auto[0], auto[1], auto[2])
            if tasto in (27, ord("q"), ord("Q")):
                return None
            if tasto in (curses.KEY_UP, ord("k"), ord("K"), ord("w"), ord("W"), ord("8")):
                r = max(0, r - 1)
            elif tasto in (curses.KEY_DOWN, ord("j"), ord("J"), ord("s"), ord("S"), ord("2")):
                r = min(DIMENSIONE_GRIGLIA - 1, r + 1)
            elif tasto in (curses.KEY_LEFT, ord("h"), ord("H"), ord("a"), ord("4")):
                c = max(0, c - 1)
            elif tasto in (curses.KEY_RIGHT, ord("l"), ord("L"), ord("d"), ord("6")):
                c = min(DIMENSIONE_GRIGLIA - 1, c + 1)
            elif tasto in (10, 13, curses.KEY_ENTER):
                if modalita == "spara":
                    bersaglio = griglia_nemica if griglia_nemica else griglia_propria
                    cella = bersaglio[r][c]
                    if cella in ("X", "O"):
                        messaggio = "Hai già sparato su questa casella."
                        continue
                    return ("spara", r, c)
                if modalita == "piazza":
                    if piazzamento_valido(griglia_propria, r, c, lunghezza, orizzontale):
                        return ("piazza", r, c, orizzontale)
                    messaggio = "Posizione non valida: fuori griglia o caselle occupate."
            elif tasto in (ord("r"), ord("R"), ord(" ")) and modalita == "piazza":
                orizzontale = not orizzontale

    return curses.wrapper(_interno)


def _sessione_fallback(griglia_propria, griglia_nemica, modalita, lunghezza=None):
    r, c = 0, 0
    orizzontale = True
    messaggio = ""
    while True:
        if sys.platform == "win32":
            os.system("cls")
        else:
            os.system("clear")
        if modalita == "piazza":
            segno = "—" if orizzontale else "|"
            print(f"Nave {lunghezza}  {coordinate_label(r, c)}  {segno}\n")
        elif modalita == "spara":
            print(f"{coordinate_label(r, c)}\n")
        gr = griglia_nemica if modalita == "spara" else griglia_propria
        print("   " + " ".join(COLONNE))
        prev_ok = set()
        prev_ko = set()
        if modalita == "piazza":
            celle_prev = celle_nave(r, c, lunghezza, orizzontale)
            if celle_prev:
                if piazzamento_valido(griglia_propria, r, c, lunghezza, orizzontale):
                    prev_ok = set(celle_prev)
                else:
                    prev_ko = set(celle_prev)
        for i, row in enumerate(gr):
            linea = f"{i + 1:2d} "
            for j, ch in enumerate(row):
                cell = row[j]
                if (i, j) in prev_ok:
                    cell = "+"
                elif (i, j) in prev_ko:
                    cell = "!"
                vis = simbolo_visivo(cell) if cell in "NXO." else cell
                if i == r and j == c:
                    linea += f"[{vis}]"
                else:
                    linea += f" {vis} "
            print(linea)
        if messaggio:
            print(messaggio)
        sys.stdout.flush()
        tasto = _leggi_tasto_raw()
        if tasto == "esci":
            return None
        if tasto == "auto" and modalita == "piazza":
            auto = piazzamento_casuale(griglia_propria, lunghezza)
            if auto:
                return ("piazza", auto[0], auto[1], auto[2])
            messaggio = "Nessuno spazio per piazzamento casuale."
            continue
        if tasto == "ruota" and modalita == "piazza":
            orizzontale = not orizzontale
            continue
        if tasto == "su":
            r = max(0, r - 1)
        elif tasto == "giu":
            r = min(DIMENSIONE_GRIGLIA - 1, r + 1)
        elif tasto == "sinistra":
            c = max(0, c - 1)
        elif tasto == "destra":
            c = min(DIMENSIONE_GRIGLIA - 1, c + 1)
        elif tasto == "invio":
            if modalita == "spara":
                if gr[r][c] in ("X", "O"):
                    messaggio = "Casella gia colpita."
                    continue
                return ("spara", r, c)
            if piazzamento_valido(griglia_propria, r, c, lunghezza, orizzontale):
                return ("piazza", r, c, orizzontale)
            messaggio = "Posizione non valida."


def seleziona_piazzamento_nave(testo_tavola_propria, lunghezza, testo_tavola_nemica=None, navi_piazzate=0, griglia=None):
    if griglia is None:
        griglia = estrai_griglia(testo_tavola_propria)
    else:
        griglia = [riga[:] for riga in griglia]
    nemica = estrai_griglia(testo_tavola_nemica) if testo_tavola_nemica else None
    meta = {"navi_totali": len(LUNGHEZZE_NAVI), "navi_piazzate": navi_piazzate}
    mod = _prova_curses()
    if mod is not None:
        try:
            risultato = _sessione_curses(mod, griglia, nemica, "piazza", lunghezza, meta=meta)
        except Exception:
            risultato = _sessione_fallback(griglia, nemica, "piazza", lunghezza)
    else:
        risultato = _sessione_fallback(griglia, nemica, "piazza", lunghezza)
    if risultato is None:
        return None
    _, riga, colonna, orizzontale = risultato
    return riga, colonna, orizzontale


def seleziona_sparo(testo_tavola_propria, testo_tavola_nemica, griglia_nemica=None):
    propria = estrai_griglia(testo_tavola_propria)
    nemica = griglia_nemica if griglia_nemica is not None else estrai_griglia(testo_tavola_nemica)
    mod = _prova_curses()
    if mod is not None:
        try:
            risultato = _sessione_curses(mod, propria, nemica, "spara", None)
        except Exception:
            risultato = _sessione_fallback(propria, nemica, "spara", None)
    else:
        risultato = _sessione_fallback(propria, nemica, "spara", None)
    if risultato is None:
        return None
    _, riga, colonna = risultato
    return riga, colonna


def overlay_messaggio(testo_propria, testo_nemica, titolo, dettaglio="", attendi=True):
    titolo = testo_piano(titolo)
    dettaglio = testo_piano(dettaglio)
    mod = _prova_curses()
    propria = estrai_griglia(testo_propria) if testo_propria else None
    nemica = estrai_griglia(testo_nemica) if testo_nemica else None
    if mod is None or propria is None:
        if propria and testo_propria:
            print(abbellisci_tavola_testo(testo_propria))
        pannello_evento(titolo, dettaglio or titolo)
        if attendi:
            attesa_invio()
        return

    def _interno(stdscr):
        curses_loc = mod
        curses_loc.curs_set(0)
        _init_coppie_colori(curses_loc)
        while True:
            stdscr.erase()
            h, w = stdscr.getmaxyx()
            lw = _larghezza_griglia()
            affianca = nemica is not None and w >= 2 * lw + 8
            ox_centro = max(1, (w - lw) // 2)
            try:
                stdscr.addstr(0, 2, titolo[: max(10, w - 4)], curses_loc.color_pair(1) | curses_loc.A_BOLD)
                if dettaglio:
                    for i, riga in enumerate(dettaglio.split("\n")[:3]):
                        stdscr.addstr(1 + i, 2, riga[: max(10, w - 4)], curses_loc.color_pair(4))
            except curses_loc.error:
                pass
            top = 5 + min(2, dettaglio.count("\n"))
            if affianca:
                _disegna_griglia_curses(stdscr, curses_loc, propria, top, 2, (-1, -1), False, None, None, set(), set(), False)
                _disegna_griglia_curses(stdscr, curses_loc, nemica, top, 2 + lw + 3, (-1, -1), False, None, None, set(), set(), True)
            elif nemica:
                _disegna_griglia_curses(stdscr, curses_loc, nemica, top, ox_centro, (-1, -1), False, None, None, set(), set(), True)
            else:
                _disegna_griglia_curses(stdscr, curses_loc, propria, top, ox_centro, (-1, -1), False, None, None, set(), set(), False)
            h, w = stdscr.getmaxyx()
            stdscr.refresh()
            if not attendi:
                return
            t = stdscr.getch()
            if t in (10, 13, curses_loc.KEY_ENTER, ord("q"), ord("Q"), 27):
                return

    try:
        mod.wrapper(_interno)
    except Exception:
        pannello_evento(titolo, dettaglio)
        if attendi:
            attesa_invio()


def run_server(host=HOST_PREDEFINITO, porta=PORTA_PREDEFINITA):
    partita = Partita()
    connessioni = {}
    lock_conn = threading.Lock()
    tutti_connessi = threading.Event()

    def invia_tutti(messaggio):
        with lock_conn:
            for conn in connessioni.values():
                invia(conn, messaggio)

    def gestisci_client(connessione, giocatore):
        tutti_connessi.wait()
        ricevitore = Ricevitore(connessione)
        invia(connessione, {
            "tipo": "benvenuto",
            "giocatore": giocatore,
            "totale_navi": len(LUNGHEZZE_NAVI),
        })
        while True:
            messaggio = ricevitore.ricevi()
            if messaggio is None:
                break
            tipo = messaggio.get("tipo")
            if tipo == "piazza":
                riga = messaggio.get("riga")
                colonna = messaggio.get("colonna")
                orizzontale = bool(messaggio.get("orizzontale"))
                ok, info = partita.piazza(giocatore, riga, colonna, orizzontale)
                if not ok:
                    invia(connessione, {"tipo": "errore_piazza", "motivo": info})
                else:
                    invia(connessione, {
                        "tipo": "nave_piazzata",
                        "lunghezza": info,
                        "prossima": partita.prossima_lunghezza(giocatore),
                        "restanti": len(LUNGHEZZE_NAVI) - partita.indice_nave[giocatore],
                    })
                    if partita.posizionamento_completo():
                        invia_tutti({"tipo": "inizio_battaglia", "turno": partita.turno})
            elif tipo == "spara":
                coord = messaggio.get("coordinata", "")
                parsed = parse_coordinata(coord)
                if parsed is None:
                    invia(connessione, {"tipo": "errore_sparo", "motivo": "coordinata_invalida"})
                    continue
                riga, colonna = parsed
                esito = partita.spara(giocatore, riga, colonna)
                if esito is None:
                    continue
                if esito.get("esito") == "turno_errato":
                    invia(connessione, {"tipo": "errore_sparo", "motivo": "turno_errato"})
                    continue
                if esito.get("esito") in ("coordinata_invalida", "già_colpito"):
                    invia(connessione, {"tipo": "errore_sparo", "motivo": esito["esito"]})
                    continue
                invia_tutti({"tipo": "esito_sparo", "attaccante": giocatore, **esito})
            elif tipo == "stato":
                tavola = partita.tavole[giocatore]
                avversario = 2 if giocatore == 1 else 1
                invia(connessione, {
                    "tipo": "stato_tavole",
                    "propria": tavola.disegna("Tua flotta"),
                    "nemica": partita.tavole[avversario].disegna("Avversario", mostra_navi=False),
                    "fase": partita.fase,
                    "turno": partita.turno,
                    "prossima_lunghezza": partita.prossima_lunghezza(giocatore),
                })
        connessione.close()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, porta))
    server.listen(2)
    print(f"Server in ascolto su {host}:{porta}")
    in_attesa = []
    for id_giocatore in (1, 2):
        conn, _ = server.accept()
        with lock_conn:
            connessioni[id_giocatore] = conn
        in_attesa.append((conn, id_giocatore))
        invia(conn, {"tipo": "attesa", "connessi": len(in_attesa), "richiesti": 2})
        threading.Thread(target=gestisci_client, args=(conn, id_giocatore), daemon=True).start()
    tutti_connessi.set()
    print("Entrambi i giocatori connessi")
    server.close()


def _preferenze():
    cfg = carica_config_completa(CONFIG_FILE)
    return cfg.get("conferme_veloci", False)


def _testo_esito_sparo(messaggio, giocatore):
    att = messaggio["attaccante"]
    esito = messaggio["esito"]
    coord = ""
    if "colonna" in messaggio and "riga" in messaggio:
        coord = f" su {COLONNE[messaggio['colonna']]}{messaggio['riga'] + 1}"
    if esito == "colpito":
        linea = stile(f"COLPITO{coord}!", GRASSETTO + ROSSO)
    elif esito == "mancato":
        linea = stile(f"Acqua{coord}.", GIALLO)
    else:
        linea = f"Esito: {esito}"
    righe = [linea]
    if messaggio.get("affondata"):
        righe.append("Affondata.")
    if messaggio.get("vittoria"):
        if messaggio["vittoria"] == giocatore:
            righe.append(stile("Vittoria.", GRASSETTO + VERDE))
        else:
            righe.append(stile("Sconfitta.", GRASSETTO + GIALLO))
    return "\n".join(righe)


def _ultime_tavole():
    return getattr(_ultime_tavole, "propria", None), getattr(_ultime_tavole, "nemica", None)


def _memorizza_tavole(propria, nemica):
    _ultime_tavole.propria = propria
    _ultime_tavole.nemica = nemica


def mostra_messaggio(messaggio, giocatore=None, tavole=None):
    tipo = messaggio.get("tipo")
    propria, nemica = tavole or _ultime_tavole()
    if tipo == "benvenuto":
        pass
    elif tipo == "attesa":
        overlay_messaggio(
            propria,
            nemica,
            f"Giocatore {messaggio.get('connessi', 1)}/{messaggio.get('richiesti', 2)}",
            "",
            attendi=False,
        )
    elif tipo == "errore_piazza":
        messaggio_errore(f"Piazzamento rifiutato: {messaggio['motivo']}")
    elif tipo == "nave_piazzata":
        pass
    elif tipo == "inizio_battaglia":
        pass
    elif tipo == "errore_sparo":
        messaggio_errore(f"Sparo non accettato: {messaggio['motivo']}")
    elif tipo == "esito_sparo":
        if messaggio.get("vittoria"):
            overlay_messaggio(
                propria,
                nemica,
                "Fine partita",
                _testo_esito_sparo(messaggio, giocatore),
                attendi=True,
            )


def richiedi_stato(connessione, ricevitore):
    invia(connessione, {"tipo": "stato"})
    stato = ricevitore.ricevi()
    if stato and stato.get("tipo") == "stato_tavole":
        _memorizza_tavole(stato.get("propria"), stato.get("nemica"))
    return stato


def fase_posizionamento(connessione, ricevitore, giocatore):
    navi_piazzate = 0
    while True:
        stato = richiedi_stato(connessione, ricevitore)
        if stato is None:
            return False
        if stato.get("tipo") == "inizio_battaglia":
            return stato
        if stato.get("tipo") != "stato_tavole":
            continue
        lunghezza = stato.get("prossima_lunghezza")
        if lunghezza is None:
            overlay_messaggio(stato["propria"], stato.get("nemica"), "…", "", attendi=False)
            while True:
                messaggio = ricevitore.ricevi()
                if messaggio is None:
                    return False
                mostra_messaggio(messaggio, giocatore)
                if messaggio.get("tipo") == "inizio_battaglia":
                    return messaggio
            continue
        gr = estrai_griglia(stato["propria"])
        piazzamento = seleziona_piazzamento_nave(
            stato["propria"],
            lunghezza,
            None,
            navi_piazzate=navi_piazzate,
            griglia=gr,
        )
        if piazzamento is None:
            messaggio_errore("Piazzamento annullato. Riprova.")
            continue
        riga, colonna, orizzontale = piazzamento
        invia(connessione, {
            "tipo": "piazza",
            "riga": riga,
            "colonna": colonna,
            "orizzontale": orizzontale,
        })
        while True:
            messaggio = ricevitore.ricevi()
            if messaggio is None:
                return False
            mostra_messaggio(messaggio, giocatore)
            if messaggio.get("tipo") == "inizio_battaglia":
                return messaggio
            if messaggio.get("tipo") == "errore_piazza":
                break
            if messaggio.get("tipo") == "nave_piazzata":
                navi_piazzate += 1
                break


def fase_battaglia(connessione, ricevitore, giocatore, primo_messaggio):
    turno = primo_messaggio.get("turno")
    while True:
        stato = richiedi_stato(connessione, ricevitore)
        if stato is None:
            return
        if turno == giocatore and stato.get("tipo") == "stato_tavole":
            bersaglio = seleziona_sparo(stato["propria"], stato["nemica"])
            if bersaglio is None:
                messaggio_errore("Sparo annullato.")
                continue
            riga, colonna = bersaglio
            colonna_lettera = COLONNE[colonna]
            invia(connessione, {"tipo": "spara", "coordinata": f"{colonna_lettera}{riga + 1}"})
        elif stato.get("tipo") == "stato_tavole" and turno != giocatore:
            overlay_messaggio(stato["propria"], stato["nemica"], "…", "", attendi=False)
        while True:
            messaggio = ricevitore.ricevi()
            if messaggio is None:
                return
            if messaggio.get("tipo") == "errore_sparo":
                mostra_messaggio(messaggio, giocatore)
                if turno == giocatore:
                    stato_agg = richiedi_stato(connessione, ricevitore)
                    if stato_agg and stato_agg.get("tipo") == "stato_tavole":
                        bersaglio = seleziona_sparo(stato_agg["propria"], stato_agg["nemica"])
                        if bersaglio:
                            riga, colonna = bersaglio
                            colonna_lettera = COLONNE[colonna]
                            invia(connessione, {"tipo": "spara", "coordinata": f"{colonna_lettera}{riga + 1}"})
                continue
            if messaggio.get("tipo") == "esito_sparo":
                richiedi_stato(connessione, ricevitore)
                mostra_messaggio(messaggio, giocatore)
                if messaggio.get("vittoria"):
                    return
                turno = messaggio.get("prossimo_turno", turno)
                break


def run_client(host=HOST_PREDEFINITO, porta=PORTA_PREDEFINITA):
    schermata_client()
    try:
        connessione = socket.create_connection((host, porta), timeout=10)
    except OSError:
        messaggio_errore(f"Impossibile connettersi a {host}:{porta}.")
        attesa_invio()
        return
    ricevitore = Ricevitore(connessione)
    giocatore = None
    while giocatore is None:
        messaggio = ricevitore.ricevi()
        if messaggio is None:
            return
        mostra_messaggio(messaggio)
        if messaggio.get("tipo") == "benvenuto":
            giocatore = messaggio["giocatore"]
    inizio = fase_posizionamento(connessione, ricevitore, giocatore)
    if not inizio:
        return
    mostra_messaggio(inizio, giocatore)
    fase_battaglia(connessione, ricevitore, giocatore, inizio)


def assicura_cartella():
    os.makedirs(CARTELLA_DATI, exist_ok=True)


def processo_attivo(pid):
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def leggi_pid():
    if not os.path.isfile(PID_FILE):
        return None
    try:
        with open(PID_FILE, "r", encoding="utf-8") as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return None


def scrivi_pid(pid):
    assicura_cartella()
    with open(PID_FILE, "w", encoding="utf-8") as handle:
        handle.write(str(pid))


def rimuovi_pid():
    if os.path.isfile(PID_FILE):
        os.remove(PID_FILE)


def leggi_pid_web():
    if not os.path.isfile(PID_WEB_FILE):
        return None
    try:
        with open(PID_WEB_FILE, "r", encoding="utf-8") as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return None


def scrivi_pid_web(pid):
    assicura_cartella()
    with open(PID_WEB_FILE, "w", encoding="utf-8") as handle:
        handle.write(str(pid))


def rimuovi_pid_web():
    if os.path.isfile(PID_WEB_FILE):
        os.remove(PID_WEB_FILE)


def _avvia_processo_background(comando, log_path, pid_path, scrivi):
    assicura_cartella()
    log_handle = open(log_path, "a", encoding="utf-8")
    kwargs = {
        "cwd": BASE,
        "stdout": log_handle,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    processo = subprocess.Popen(comando, **kwargs)
    scrivi(processo.pid)
    time.sleep(0.6)
    if processo.poll() is not None:
        if pid_path == PID_FILE:
            rimuovi_pid()
        else:
            rimuovi_pid_web()
        return False, "Il server non è partito. Controlla il file di log."
    return True, str(processo.pid)


def avvia_server_background(host, porta):
    pid_esistente = leggi_pid()
    if pid_esistente and processo_attivo(pid_esistente):
        return False, "Il server è già in esecuzione. Fermalo prima di riavviare."
    comando = [sys.executable, SCRIPT, "server", host, str(porta)]
    ok, msg = _avvia_processo_background(comando, LOG_FILE, PID_FILE, scrivi_pid)
    if not ok:
        return ok, msg
    cfg = carica_config_completa(CONFIG_FILE)
    cfg["host"] = host
    cfg["porta"] = porta
    salva_config_completa(CONFIG_FILE, cfg)
    return ok, msg


def avvia_server_web_background(host, porta):
    pid_esistente = leggi_pid_web()
    if pid_esistente and processo_attivo(pid_esistente):
        return False, "Il server web è già in esecuzione. Fermalo prima di riavviare."
    comando = [sys.executable, SCRIPT, "server-web", host, str(porta)]
    ok, msg = _avvia_processo_background(comando, LOG_WEB_FILE, PID_WEB_FILE, scrivi_pid_web)
    if not ok:
        return ok, msg
    cfg = carica_config_completa(CONFIG_FILE)
    cfg["host"] = host
    cfg["porta_http"] = porta
    salva_config_completa(CONFIG_FILE, cfg)
    return ok, msg


def _termina_pid(pid, rimuovi):
    if not processo_attivo(pid):
        rimuovi()
        return False
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=False, capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.4)
            if processo_attivo(pid):
                os.kill(pid, signal.SIGKILL)
    except OSError:
        return False
    rimuovi()
    return True


def ferma_server():
    fermati = 0
    pid = leggi_pid()
    if pid:
        if _termina_pid(pid, rimuovi_pid):
            fermati += 1
        elif pid:
            rimuovi_pid()
    pid_web = leggi_pid_web()
    if pid_web:
        if _termina_pid(pid_web, rimuovi_pid_web):
            fermati += 1
        elif pid_web:
            rimuovi_pid_web()
    if fermati == 0:
        return False, "Nessun server in background registrato."
    return True, f"Server fermati: {fermati}."


def porta_predefinita():
    config = carica_config_completa(CONFIG_FILE)
    return config.get("porta", PORTA_PREDEFINITA)


def configurazione_server(porta_predef):
    solo_locale = chiedi_modalita_ascolto()
    host = normalizza_host_ascolto(solo_locale)
    porta = chiedi_porta(porta_predef)
    if porta is None:
        messaggio_errore("Porta non valida: usa un numero tra 1024 e 65535.")
        return None
    if not porta_valida(porta):
        messaggio_errore("Porta non valida: usa un numero tra 1024 e 65535.")
        return None
    if not porta_disponibile(host, porta):
        messaggio_errore(f"La porta {porta} è già occupata. Scegli un'altra porta.")
        return None
    return host, porta


def avvia_server_ui(host, porta):
    ok, messaggio = avvia_server_background(host, porta)
    if not ok:
        messaggio_errore(messaggio)
        return
    pulisci_schermo()
    print(banner_principale())
    messaggio_ok(
        f"Server avviato in background.\n"
        f"PID: {messaggio}\n"
        f"Porta TCP: {porta}\n"
        f"Log: {LOG_FILE}"
    )
    pannello_endpoint(righe_endpoint(porta, host))


def avvia_server_web_ui(host, porta):
    ok, messaggio = avvia_server_web_background(host, porta)
    if not ok:
        messaggio_errore(messaggio)
        return
    pulisci_schermo()
    print(banner_principale())
    bind = "127.0.0.1" if host in ("127.0.0.1", "localhost") else host
    url = f"http://{bind}:{porta}/api/health"
    messaggio_ok(
        f"Server web avviato.\n"
        f"PID: {messaggio}\n"
        f"HTTP: http://{bind}:{porta}\n"
        f"Open http://{bind}:{porta}/ in a browser (UI is served by this file).\n"
        f"Log: {LOG_WEB_FILE}"
    )
    pannello_endpoint(righe_endpoint(porta, host))


def ferma_server_ui():
    ok, messaggio = ferma_server()
    if ok:
        messaggio_ok(messaggio)
    else:
        messaggio_errore(messaggio)


def stato_server():
    config = carica_config(CONFIG_FILE)
    if not config:
        messaggio_errore("Nessuna configurazione salvata. Avvia prima il server.")
        attesa_invio()
        return
    host, porta = config
    pid = leggi_pid()
    attivo = pid is not None and processo_attivo(pid)
    ascolto = porta_raggiungibile(host, porta)
    pubblico = indirizzo_pubblico()
    stato_proc = stile("[ON] IN ESECUZIONE", GRASSETTO + VERDE) if attivo else stile("[OFF] FERMO", ROSSO)
    stato_porta = stile("[ON] IN ASCOLTO", GRASSETTO + VERDE) if ascolto else stile("[OFF] NON RAGGIUNGIBILE", ROSSO)
    righe = [
        f"Processo: {stato_proc}  (PID {pid if pid else '—'})",
        f"Porta {porta}: {stato_porta}",
        f"Interfaccia di rete: {host}",
        f"IP pubblico: {pubblico if pubblico else 'non rilevato'}",
        f"Registro: {LOG_FILE}",
    ]
    pulisci_schermo()
    print(banner_principale())
    print()
    print(riquadro("Stato server", righe))
    pannello_endpoint(righe_endpoint(porta, host))
    attesa_invio()


def risolvi_porta_client(porta_predef):
    config = carica_config(CONFIG_FILE)
    if config:
        return config[1]
    porta = chiedi_porta(porta_predef)
    if porta is None or not porta_valida(porta):
        return None
    return porta


def connetti_client(porta_predef):
    porta = risolvi_porta_client(porta_predef)
    if porta is None:
        messaggio_errore("Porta non valida.")
        return porta_predef
    config = carica_config(CONFIG_FILE)
    host_ascolto = config[0] if config else "0.0.0.0"
    endpoints = righe_endpoint(porta, host_ascolto)
    host = chiedi_host_client(endpoints)
    pulisci_schermo()
    subprocess.run([sys.executable, SCRIPT, "client", host, str(porta)], cwd=BASE)
    return porta


def _web_cors(handler):
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")


def _web_json(handler, codice, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(codice)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    _web_cors(handler)
    handler.end_headers()
    handler.wfile.write(body)


def _web_html(handler, codice, html):
    body = html.encode("utf-8")
    handler.send_response(codice)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


WEB_GAME_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1"/>
<meta name="theme-color" content="#071322"/>
<title>Battleship</title>
<style>
:root{color-scheme:dark;font-family:system-ui,sans-serif}
body{margin:0;background:#020617;color:#e2e8f0}
.app{width:min(960px,calc(100% - 1.5rem));margin:0 auto;padding:1rem 0 3rem}
h1{margin:.5rem 0;font-size:clamp(1.4rem,4vw,2rem)}
.sub{color:#94a3b8;font-size:.9rem}
.card{margin:1rem 0;padding:1rem;border:1px solid #334155;border-radius:8px;background:#0f172a99}
label{display:grid;gap:.35rem;font-size:.875rem}
input{padding:.65rem;border-radius:6px;border:1px solid #334155;background:#020617;color:#e2e8f0;width:100%;box-sizing:border-box}
.btn{padding:.55rem 1rem;border-radius:6px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;font-weight:600;cursor:pointer;touch-action:manipulation}
.btn.primary{background:#0284c7;border-color:#0284c7;color:#f0f9ff}
.btn:disabled{opacity:.45;cursor:not-allowed}
.btn-row{display:flex;flex-wrap:wrap;gap:.5rem;margin-top:.5rem}
.status{min-height:1.25rem;color:#7dd3fc;font-size:.875rem;margin-top:.5rem}
.boards{display:grid;gap:1.25rem}
@media(min-width:720px){.boards{grid-template-columns:1fr 1fr}}
.board h2{font-size:.8rem;text-transform:uppercase;letter-spacing:.06em;color:#64748b;margin:0 0 .5rem}
.grid{display:grid;grid-template-columns:repeat(10,minmax(0,1fr));gap:2px;touch-action:manipulation}
.cell{aspect-ratio:1;display:flex;align-items:center;justify-content:center;font-family:ui-monospace,monospace;font-size:clamp(.65rem,2.8vw,.85rem);font-weight:600;border-radius:3px;background:#0c4a6e;color:#bae6fd;border:none;padding:0}
.cell.water{background:#082f49;color:#64748b}
.cell.ship{background:#14532d;color:#bbf7d0}
.cell.hit{background:#7f1d1d;color:#fecaca}
.cell.miss{background:#713f12;color:#fde68a}
.cell.cursor{outline:2px solid #22d3ee;outline-offset:-2px}
.cell.preview{background:#155e75}
.cell.bad{background:#991b1b}
.cell.radar-ship{background:#4c1d95;color:#e9d5ff}
.cell.radar-water{background:#1e3a5f}
.grid.target .cell{cursor:pointer}
.hint{font-size:.8rem;color:#64748b;margin:.5rem 0 0}
</style>
</head>
<body>
<div class="app">
<header><h1>Battleship</h1><p class="sub">Python engine · single-file server</p></header>
<section class="card" id="setup">
<label>API base URL<input id="api-base" type="url" placeholder="http://127.0.0.1:8080"/></label>
<button type="button" id="btn-join" class="btn primary">Join match</button>
<p id="status" class="status" role="status"></p>
</section>
<section class="card" id="panel-controls" hidden>
<p id="phase-text"></p>
<div class="btn-row">
<button type="button" id="btn-rotate" class="btn">Rotate (R)</button>
<button type="button" id="btn-auto" class="btn">Auto place (0)</button>
<button type="button" id="btn-radar" class="btn">Radar (3×3)</button>
<button type="button" id="btn-salvo" class="btn">Salvo (+)</button>
<button type="button" id="btn-fire" class="btn primary">Confirm</button>
<button type="button" id="btn-rematch" class="btn primary" hidden>New match</button>
</div>
<p class="hint">Arrows / WASD · Enter · click enemy grid · powers use your turn</p>
</section>
<div class="boards" id="boards" hidden>
<div class="board"><h2>Your fleet</h2><div id="grid-own" class="grid"></div></div>
<div class="board"><h2>Enemy</h2><div id="grid-enemy" class="grid target"></div></div>
</div>
</div>
<script>
const COLS='ABCDEFGHIJ'.split(''),SIZE=10;
let apiBase='',token='',giocatore=0,cursor={r:0,c:0},orizzontale=true,polling=null,lastState=null,powerMode=null;
const el=id=>document.getElementById(id);
function loadApiBase(){const s=location.origin;if(s.startsWith('http'))el('api-base').value=s;}
async function api(path,opts={}){const res=await fetch(`${apiBase.replace(/\/$/,'')}${path}`,{...opts,headers:{'Content-Type':'application/json',...(opts.headers||{})}});const data=await res.json().catch(()=>({}));if(!res.ok)throw new Error(data.motivo||data.errore||res.statusText);return data;}
function sym(ch){return{'.':'.',N:'#',X:'X',O:'o'}[ch]||ch;}
function radarOverlay(state){const m=new Map();if(!state?.radar_ultimo)return m;for(const c of state.radar_ultimo)m.set(`${c.riga},${c.colonna}`,c.nave?'ship':'water');return m;}
function paintGrid(container,matrix,opts={}){container.replaceChildren();const rad=opts.radar||new Map();for(let r=0;r<SIZE;r++)for(let c=0;c<SIZE;c++){const ch=matrix[r][c];const btn=document.createElement('button');btn.type='button';btn.className='cell';btn.dataset.r=String(r);btn.dataset.c=String(c);btn.textContent=sym(ch);if(ch==='.')btn.classList.add('water');if(ch==='N')btn.classList.add('ship');if(ch==='X')btn.classList.add('hit');if(ch==='O')btn.classList.add('miss');if(opts.cursor&&opts.cursor.r===r&&opts.cursor.c===c)btn.classList.add('cursor');if(opts.preview?.has(`${r},${c}`))btn.classList.add('preview');if(opts.bad?.has(`${r},${c}`))btn.classList.add('bad');const rk=`${r},${c}`;if(rad.has(rk))btn.classList.add(rad.get(rk)==='ship'?'radar-ship':'radar-water');container.appendChild(btn);}}
function previewCells(state){const set=new Set(),bad=new Set();if(state.fase!=='posizionamento'||!state.prossima_lunghezza)return{set,bad};const len=state.prossima_lunghezza;for(let i=0;i<len;i++){const r=cursor.r+(orizzontale?0:i),c=cursor.c+(orizzontale?i:0);if(r>=0&&r<SIZE&&c>=0&&c<SIZE){set.add(`${r},${c}`);if(state.propria[r][c]!=='.')bad.add(`${r},${c}`);}else bad.add(`${cursor.r},${cursor.c}`);}return{set,bad};}
function render(state){lastState=state;const placing=state.fase==='posizionamento'&&state.prossima_lunghezza;const myTurn=state.fase==='battaglia'&&state.turno===giocatore;const prev=placing?previewCells(state):{set:new Set(),bad:new Set()};const rad=radarOverlay(state);paintGrid(el('grid-own'),state.propria,{cursor:placing?cursor:null,preview:prev.set,bad:prev.bad});paintGrid(el('grid-enemy'),state.nemica,{cursor:myTurn&&!powerMode?cursor:null,radar:rad});const p=state.poteri||{};el('phase-text').textContent=state.attesa_avversario?`Player ${state.giocatore}: waiting for opponent…`:state.fase==='posizionamento'?`Place ship ${state.prossima_lunghezza||'-'} (${COLS[cursor.c]}${cursor.r+1})`:state.fase==='fine'?state.vincitore===giocatore?'You win.':'You lose.':powerMode?`Power: ${powerMode} at ${COLS[cursor.c]}${cursor.r+1}`:myTurn?'Your turn — hit = shoot again':'Opponent turn';el('btn-rotate').hidden=!placing;el('btn-auto').hidden=!placing;el('btn-radar').hidden=!myTurn;el('btn-salvo').hidden=!myTurn;el('btn-radar').disabled=!p.radar;el('btn-salvo').disabled=!p.salvo;el('btn-fire').textContent=placing?'Place':myTurn&&!powerMode?'Fire':'Confirm power';el('btn-fire').disabled=!placing&&!myTurn;el('btn-rematch').hidden=state.fase!=='fine';}
async function refresh(){const state=await api(`/api/stato?token=${encodeURIComponent(token)}`);render(state);if(state.fase==='fine'&&polling){clearInterval(polling);polling=null;}}
async function join(){apiBase=el('api-base').value.trim()||location.origin;el('status').textContent='Connecting…';const data=await api('/api/unisciti',{method:'POST',body:'{}'});token=data.token;giocatore=data.giocatore;powerMode=null;el('status').textContent=`Player ${giocatore} · ${data.connessi}/${data.richiesti}`;el('boards').hidden=false;el('panel-controls').hidden=false;await refresh();if(polling)clearInterval(polling);polling=setInterval(()=>refresh().catch(e=>el('status').textContent=e.message),1200);}
async function confirm(){if(!lastState)return;if(lastState.fase==='posizionamento'&&lastState.prossima_lunghezza){await api('/api/piazza',{method:'POST',body:JSON.stringify({token,riga:cursor.r,colonna:cursor.c,orizzontale})});}else if(powerMode&&lastState.turno===giocatore){await api('/api/potere',{method:'POST',body:JSON.stringify({token,tipo:powerMode,riga:cursor.r,colonna:cursor.c})});powerMode=null;}else if(lastState.turno===giocatore){const ch=lastState.nemica[cursor.r][cursor.c];if(ch==='X'||ch==='O'){el('status').textContent='Already fired here.';return;}await api('/api/spara',{method:'POST',body:JSON.stringify({token,riga:cursor.r,colonna:cursor.c})});}await refresh();}
function move(dr,dc){cursor.r=Math.max(0,Math.min(SIZE-1,cursor.r+dr));cursor.c=Math.max(0,Math.min(SIZE-1,cursor.c+dc));if(lastState)render(lastState);}
async function autoPlace(){if(!lastState?.prossima_lunghezza)return;const len=lastState.prossima_lunghezza;for(const horiz of[true,false])for(let r=0;r<SIZE;r++)for(let c=0;c<SIZE;c++){let ok=true;for(let i=0;i<len;i++){const rr=r+(horiz?0:i),cc=c+(horiz?i:0);if(rr>=SIZE||cc>=SIZE||lastState.propria[rr][cc]!=='.'){ok=false;break;}}if(ok){orizzontale=horiz;cursor={r,c};await api('/api/piazza',{method:'POST',body:JSON.stringify({token,riga:r,colonna:c,orizzontale:horiz})});await refresh();return;}}el('status').textContent='No space for auto placement.';}
async function rematch(){await api('/api/rematch',{method:'POST',body:JSON.stringify({token})});powerMode=null;await refresh();if(!polling)polling=setInterval(()=>refresh().catch(e=>el('status').textContent=e.message),1200);}
el('btn-join').addEventListener('click',()=>join().catch(e=>el('status').textContent=e.message));
el('btn-fire').addEventListener('click',()=>confirm().catch(e=>el('status').textContent=e.message));
el('btn-rotate').addEventListener('click',()=>{orizzontale=!orizzontale;if(lastState)render(lastState);});
el('btn-auto').addEventListener('click',()=>autoPlace().catch(e=>el('status').textContent=e.message));
el('btn-radar').addEventListener('click',()=>{powerMode=powerMode==='radar'?null:'radar';if(lastState)render(lastState);});
el('btn-salvo').addEventListener('click',()=>{powerMode=powerMode==='salvo'?null:'salvo';if(lastState)render(lastState);});
el('btn-rematch').addEventListener('click',()=>rematch().catch(e=>el('status').textContent=e.message));
el('grid-enemy').addEventListener('click',ev=>{const t=ev.target;if(!(t instanceof HTMLElement)||!t.dataset.r)return;cursor.r=Number(t.dataset.r);cursor.c=Number(t.dataset.c);if(lastState?.fase==='battaglia'&&lastState.turno===giocatore)confirm().catch(e=>el('status').textContent=e.message);else if(lastState)render(lastState);});
window.addEventListener('keydown',ev=>{const k=ev.key;if(['ArrowUp','w','W','k','K'].includes(k)){ev.preventDefault();move(-1,0);}else if(['ArrowDown','s','S','j','J'].includes(k)){ev.preventDefault();move(1,0);}else if(['ArrowLeft','a','A','h','H'].includes(k)){ev.preventDefault();move(0,-1);}else if(['ArrowRight','d','D','l','L'].includes(k)){ev.preventDefault();move(0,1);}else if(k==='r'||k==='R'||k===' '){ev.preventDefault();orizzontale=!orizzontale;if(lastState)render(lastState);}else if(k==='0'){ev.preventDefault();autoPlace().catch(e=>el('status').textContent=e.message);}else if(k==='Enter'){ev.preventDefault();confirm().catch(e=>el('status').textContent=e.message);}});
loadApiBase();
</script>
</body>
</html>"""


class StatoWeb:
    def __init__(self):
        self.lock = threading.Lock()
        self.partita = Partita()
        self.giocatori = {}
        self.token_giocatore = {}

    def unisciti(self):
        with self.lock:
            if self.partita.fase == "fine" and len(self.giocatori) >= 2:
                self.partita = Partita()
            if len(self.giocatori) >= 2:
                return None, "partita_piena"
            gid = len(self.giocatori) + 1
            token = secrets.token_urlsafe(16)
            self.giocatori[token] = gid
            self.token_giocatore[gid] = token
            return {
                "token": token,
                "giocatore": gid,
                "connessi": len(self.giocatori),
                "richiesti": 2,
            }, None

    def giocatore_da_token(self, token):
        return self.giocatori.get(token)

    def stato(self, giocatore):
        snap = self.partita.snapshot_giocatore(giocatore)
        snap["attesa_avversario"] = len(self.giocatori) < 2
        return snap

    def piazza(self, giocatore, riga, colonna, orizzontale):
        ok, info = self.partita.piazza(giocatore, riga, colonna, orizzontale)
        if not ok:
            return {"ok": False, "motivo": info}
        return {
            "ok": True,
            "lunghezza": info,
            "prossima": self.partita.prossima_lunghezza(giocatore),
            "inizio_battaglia": self.partita.fase == "battaglia",
        }

    def spara(self, giocatore, riga, colonna):
        esito = self.partita.spara(giocatore, riga, colonna)
        if esito is None:
            return {"ok": False, "motivo": "fase_errata"}
        if esito.get("esito") in ("turno_errato", "coordinata_invalida", "già_colpito"):
            return {"ok": False, "motivo": esito["esito"]}
        return {"ok": True, **esito}

    def potere(self, giocatore, tipo, riga, colonna):
        esito = self.partita.usa_potere(giocatore, tipo, riga, colonna)
        if esito is None:
            return {"ok": False, "motivo": "fase_errata"}
        return esito

    def rematch(self):
        with self.lock:
            if self.partita.fase != "fine":
                return {"ok": False, "motivo": "partita_in_corso"}
            self.partita = Partita()
            return {"ok": True}


class HandlerWeb(BaseHTTPRequestHandler):
    stato = StatoWeb()

    def log_message(self, format, *args):
        return

    def do_OPTIONS(self):
        self.send_response(204)
        _web_cors(self)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if parsed.path in ("/", "/gioca", "/play"):
            _web_html(self, 200, WEB_GAME_PAGE)
            return
        if parsed.path == "/api/stato":
            token = (qs.get("token") or [""])[0]
            g = self.stato.giocatore_da_token(token)
            if not g:
                _web_json(self, 401, {"errore": "token_invalido"})
                return
            _web_json(self, 200, self.stato.stato(g))
            return
        if parsed.path == "/api/health":
            _web_json(self, 200, {"ok": True, "motore": "python", "file": "battaglia_navale.py"})
            return
        _web_json(self, 404, {"errore": "non_trovato"})

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            dati = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            _web_json(self, 400, {"errore": "json_invalido"})
            return

        if parsed.path == "/api/unisciti":
            payload, err = self.stato.unisciti()
            if err:
                _web_json(self, 409, {"errore": err})
                return
            _web_json(self, 200, payload)
            return

        token = dati.get("token", "")

        if parsed.path == "/api/rematch":
            if not self.stato.giocatore_da_token(token):
                _web_json(self, 401, {"errore": "token_invalido"})
                return
            risp = self.stato.rematch()
            _web_json(self, 200 if risp.get("ok") else 400, risp)
            return

        giocatore = self.stato.giocatore_da_token(token)
        if not giocatore:
            _web_json(self, 401, {"errore": "token_invalido"})
            return

        if parsed.path == "/api/piazza":
            risp = self.stato.piazza(
                giocatore,
                int(dati["riga"]),
                int(dati["colonna"]),
                bool(dati.get("orizzontale", True)),
            )
            _web_json(self, 200 if risp.get("ok") else 400, risp)
            return

        if parsed.path == "/api/spara":
            if "coordinata" in dati:
                parsed_coord = parse_coordinata(str(dati["coordinata"]))
                if parsed_coord is None:
                    _web_json(self, 400, {"ok": False, "motivo": "coordinata_invalida"})
                    return
                riga, colonna = parsed_coord
            else:
                riga, colonna = int(dati["riga"]), int(dati["colonna"])
            risp = self.stato.spara(giocatore, riga, colonna)
            _web_json(self, 200 if risp.get("ok") else 400, risp)
            return

        if parsed.path == "/api/potere":
            tipo = str(dati.get("tipo", ""))
            risp = self.stato.potere(giocatore, tipo, int(dati["riga"]), int(dati["colonna"]))
            _web_json(self, 200 if risp.get("ok") else 400, risp)
            return

        _web_json(self, 404, {"errore": "non_trovato"})


def run_server_web(host="0.0.0.0", porta=PORTA_HTTP_PREDEFINITA):
    server = ThreadingHTTPServer((host, porta), HandlerWeb)
    print(f"Web server at http://{host}:{porta}/ (UI + API)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def loop_launcher():
    assicura_cartella()
    porta_predef = porta_predefinita() or PORTA_PREDEFINITA
    while True:
        scelta = menu_principale()
        if scelta == 0:
            rete = configurazione_server(porta_predef)
            if rete is not None:
                avvia_server_ui(rete[0], rete[1])
                porta_predef = rete[1]
            attesa_invio()
        elif scelta == 1:
            cfg = carica_config_completa(CONFIG_FILE)
            rete = configurazione_server(cfg.get("porta_http", PORTA_HTTP_PREDEFINITA))
            if rete is not None:
                avvia_server_web_ui(rete[0], rete[1])
            attesa_invio()
        elif scelta == 2:
            nuova = connetti_client(porta_predef)
            if nuova:
                porta_predef = nuova
            attesa_invio()
        elif scelta == 3:
            stato_server()
        elif scelta == 4:
            ferma_server_ui()
            attesa_invio()
        elif scelta == 5:
            pulisci_schermo()
            print(stile("A presto.", CIANO + GRASSETTO))
            return
        else:
            messaggio_errore("Opzione non valida.")
            attesa_invio()


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "server":
        host = sys.argv[2] if len(sys.argv) > 2 else HOST_PREDEFINITO
        porta = int(sys.argv[3]) if len(sys.argv) > 3 else PORTA_PREDEFINITA
        run_server(host, porta)
    elif len(sys.argv) >= 2 and sys.argv[1] == "client":
        host = sys.argv[2] if len(sys.argv) > 2 else HOST_PREDEFINITO
        porta = int(sys.argv[3]) if len(sys.argv) > 3 else PORTA_PREDEFINITA
        run_client(host, porta)
    elif len(sys.argv) >= 2 and sys.argv[1] == "server-web":
        host = sys.argv[2] if len(sys.argv) > 2 else "0.0.0.0"
        porta = int(sys.argv[3]) if len(sys.argv) > 3 else PORTA_HTTP_PREDEFINITA
        run_server_web(host, porta)
    else:
        loop_launcher()


if __name__ == "__main__":
    main()
