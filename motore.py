# Motore di gioco Battaglia Navale (senza UI né rete).
from __future__ import annotations

import random
import threading

DIMENSIONE_GRIGLIA = 10
COLONNE = "ABCDEFGHIJ"
LUNGHEZZE_NAVI = [4, 3, 3, 2, 2, 2, 1, 1, 1, 1]

ACQUA = "."
NAVE = "N"
COLPITO = "X"
MANCATO = "O"


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
