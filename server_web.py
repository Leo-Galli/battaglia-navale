# Server HTTP per client browser (motore senza grafica).
from __future__ import annotations

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from motore import Partita, parse_coordinata

PORTA_HTTP_PREDEFINITA = 8080


class StatoWeb:
    def __init__(self):
        self.lock = threading.Lock()
        self.partita = Partita()
        self.token_giocatore = {}
        self.giocatori = {}
        self.evento = threading.Event()

    def unisciti(self):
        with self.lock:
            if len(self.giocatori) >= 2:
                return None, "partita_piena"
            gid = len(self.giocatori) + 1
            token = secrets.token_urlsafe(16)
            self.giocatori[token] = gid
            self.token_giocatore[gid] = token
            if len(self.giocatori) == 2:
                self.evento.set()
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


def _cors(handler):
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")


def _json_response(handler, codice, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(codice)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    _cors(handler)
    handler.end_headers()
    handler.wfile.write(body)


class HandlerWeb(BaseHTTPRequestHandler):
    stato = StatoWeb()

    def log_message(self, format, *args):
        return

    def do_OPTIONS(self):
        self.send_response(204)
        _cors(self)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if parsed.path == "/api/stato":
            token = (qs.get("token") or [""])[0]
            g = self.stato.giocatore_da_token(token)
            if not g:
                _json_response(self, 401, {"errore": "token_invalido"})
                return
            _json_response(self, 200, self.stato.stato(g))
            return
        if parsed.path == "/api/health":
            _json_response(self, 200, {"ok": True, "motore": "python"})
            return
        _json_response(self, 404, {"errore": "non_trovato"})

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            dati = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            _json_response(self, 400, {"errore": "json_invalido"})
            return

        if parsed.path == "/api/unisciti":
            payload, err = self.stato.unisciti()
            if err:
                _json_response(self, 409, {"errore": err})
                return
            _json_response(self, 200, payload)
            return

        token = dati.get("token", "")
        giocatore = self.stato.giocatore_da_token(token)
        if not giocatore:
            _json_response(self, 401, {"errore": "token_invalido"})
            return

        if parsed.path == "/api/piazza":
            risp = self.stato.piazza(
                giocatore,
                int(dati["riga"]),
                int(dati["colonna"]),
                bool(dati.get("orizzontale", True)),
            )
            _json_response(self, 200 if risp.get("ok") else 400, risp)
            return

        if parsed.path == "/api/spara":
            if "coordinata" in dati:
                parsed_coord = parse_coordinata(str(dati["coordinata"]))
                if parsed_coord is None:
                    _json_response(self, 400, {"ok": False, "motivo": "coordinata_invalida"})
                    return
                riga, colonna = parsed_coord
            else:
                riga, colonna = int(dati["riga"]), int(dati["colonna"])
            risp = self.stato.spara(giocatore, riga, colonna)
            _json_response(self, 200 if risp.get("ok") else 400, risp)
            return

        _json_response(self, 404, {"errore": "non_trovato"})


def run_server_web(host="0.0.0.0", porta=PORTA_HTTP_PREDEFINITA):
    server = ThreadingHTTPServer((host, porta), HandlerWeb)
    print(f"Server web in ascolto su http://{host}:{porta}")
    print("API: POST /api/unisciti, GET /api/stato?token=..., POST /api/piazza, POST /api/spara")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
