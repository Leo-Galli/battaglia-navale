#!/usr/bin/env python3
import random
import sys

if sys.platform == "win32":
    import ctypes


def _configura_console_windows():
    if sys.platform != "win32":
        return
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleCP(65001)
        kernel32.SetConsoleOutputCP(65001)
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        for handle_id in (-11, -12):
            handle = kernel32.GetStdHandle(handle_id)
            modo = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(modo)):
                kernel32.SetConsoleMode(handle, modo.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
        for flusso in (sys.stdout, sys.stderr):
            try:
                flusso.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass
    except Exception:
        pass


_configura_console_windows()

ACQUA, NAVE, COLPITO, MANCATO = ".", "N", "X", "O"
DIMENSIONE_GRIGLIA = 10
COLONNE = "ABCDEFGHIJ"
LUNGHEZZE_NAVI = [4, 3, 3, 2, 2, 2, 1, 1, 1, 1]


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


def celle_nave(riga, colonna, lunghezza, orizzontale):
    celle = []
    for i in range(lunghezza):
        r = riga if orizzontale else riga + i
        c = colonna + i if orizzontale else colonna
        if r < 0 or r >= DIMENSIONE_GRIGLIA or c < 0 or c >= DIMENSIONE_GRIGLIA:
            return None
        celle.append((r, c))
    return celle


class Tavola:
    def __init__(self):
        self.griglia = [[ACQUA] * DIMENSIONE_GRIGLIA for _ in range(DIMENSIONE_GRIGLIA)]
        self.colpi_ricevuti = [[False] * DIMENSIONE_GRIGLIA for _ in range(DIMENSIONE_GRIGLIA)]
        self.navi = []

    def posizione_valida(self, riga, colonna, lunghezza, orizzontale):
        celle = celle_nave(riga, colonna, lunghezza, orizzontale)
        if celle is None:
            return False
        for r, c in celle:
            if self.griglia[r][c] != ACQUA:
                return False
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    rr, cc = r + dr, c + dc
                    if 0 <= rr < DIMENSIONE_GRIGLIA and 0 <= cc < DIMENSIONE_GRIGLIA and self.griglia[rr][cc] == NAVE:
                        return False
        return True

    def piazza_nave(self, riga, colonna, lunghezza, orizzontale):
        if not self.posizione_valida(riga, colonna, lunghezza, orizzontale):
            return False
        celle = celle_nave(riga, colonna, lunghezza, orizzontale)
        for r, c in celle:
            self.griglia[r][c] = NAVE
        self.navi.append(celle)
        return True

    def piazzamento_casuale(self, lunghezza):
        opzioni = []
        for orizzontale in (True, False):
            for r in range(DIMENSIONE_GRIGLIA):
                for c in range(DIMENSIONE_GRIGLIA):
                    if self.posizione_valida(r, c, lunghezza, orizzontale):
                        opzioni.append((r, c, orizzontale))
        return random.choice(opzioni) if opzioni else None

    def spara(self, riga, colonna):
        if self.colpi_ricevuti[riga][colonna]:
            return "già_colpito", False
        self.colpi_ricevuti[riga][colonna] = True
        if self.griglia[riga][colonna] == NAVE:
            self.griglia[riga][colonna] = COLPITO
            segmento = next(s for s in self.navi if (riga, colonna) in s)
            affondata = all(self.griglia[r][c] == COLPITO for r, c in segmento)
            return "colpito", affondata
        self.griglia[riga][colonna] = MANCATO
        return "mancato", False

    def tutte_navi_affondate(self):
        return all(self.griglia[r][c] == COLPITO for s in self.navi for r, c in s)


RESET, GRASSETTO = "\033[0m", "\033[1m"
GRIGIO, CIANO, VERDE, GIALLO, ROSSO, BLU = (
    "\033[90m", "\033[96m", "\033[92m", "\033[93m", "\033[91m", "\033[94m",
)

_SUPPORTA_COLORI = None


def supporta_colori():
    global _SUPPORTA_COLORI
    if _SUPPORTA_COLORI is None:
        import os
        _SUPPORTA_COLORI = not os.environ.get("NO_COLOR") and sys.stdout.isatty()
    return _SUPPORTA_COLORI


def stile(testo, sequenza):
    return f"{sequenza}{testo}{RESET}" if supporta_colori() else testo


def pulisci_schermo():
    sys.stdout.write("\033[H\033[2J\033[3J")
    sys.stdout.flush()


def colora_cella(cella):
    if cella == NAVE:
        return stile(NAVE, CIANO)
    if cella == COLPITO:
        return stile(COLPITO, ROSSO + GRASSETTO)
    if cella == MANCATO:
        return stile(MANCATO, BLU)
    return stile(ACQUA, GRIGIO)


def disegna_griglia(tavola, titolo, mostra_navi):
    righe = [stile(titolo, GRASSETTO + GIALLO), stile("   " + " ".join(COLONNE), GRASSETTO)]
    for r in range(DIMENSIONE_GRIGLIA):
        pezzi = []
        for c in range(DIMENSIONE_GRIGLIA):
            cella = tavola.griglia[r][c]
            if not mostra_navi and cella == NAVE:
                cella = ACQUA
            pezzi.append(colora_cella(cella))
        righe.append(f"{r + 1:2d} " + " ".join(pezzi))
    return "\n".join(righe)


def esci_se_richiesto(testo):
    if testo.strip().lower() in ("q", "esci"):
        pulisci_schermo()
        print(stile("Partita interrotta.", GIALLO))
        sys.exit(0)


def piazza_flotta(tavola, nome):
    indice = 0
    while indice < len(LUNGHEZZE_NAVI):
        lunghezza = LUNGHEZZE_NAVI[indice]
        pulisci_schermo()
        print(stile(f"=== Piazzamento flotta - {nome} ===", GRASSETTO + CIANO))
        print("Formato: <coordinata> <o|v>  es. 'A1 o' orizzontale, 'C5 v' verticale.")
        print("Nel formato orizzontale, la coordinata è verso destra,")
        print("Nel formato verticale, la coordinata è verso il basso.")
        print("La coordinata inserita è quella del primo estremo della nave.")
        print("Scrivi 'auto' per piazzare da sola/o tutta la flotta restante, 'q' per uscire.\n")
        print(disegna_griglia(tavola, "La tua flotta", mostra_navi=True))
        print(f"\nProssima nave: lunghezza {lunghezza}  ({len(LUNGHEZZE_NAVI) - indice} rimanenti)")
        scelta = input("> ")
        esci_se_richiesto(scelta)
        if scelta.strip().lower() == "auto":
            while indice < len(LUNGHEZZE_NAVI):
                posizione = tavola.piazzamento_casuale(LUNGHEZZE_NAVI[indice])
                if posizione is None:
                    break
                r, c, orizzontale = posizione
                tavola.piazza_nave(r, c, LUNGHEZZE_NAVI[indice], orizzontale)
                indice += 1
            continue
        parti = scelta.split()
        coord = parse_coordinata(parti[0]) if parti else None
        orientamento = parti[1].lower() if len(parti) == 2 else None
        if coord is None or orientamento not in ("o", "v"):
            print(stile("Formato non valido.", ROSSO))
            input("Premi invio per riprovare...")
            continue
        riga, colonna = coord
        if not tavola.piazza_nave(riga, colonna, lunghezza, orientamento == "o"):
            print(stile("Posizione non valida: fuori griglia o sovrapposta a un'altra nave.", ROSSO))
            input("Premi invio per riprovare...")
            continue
        indice += 1
    pulisci_schermo()
    print(disegna_griglia(tavola, f"Flotta di {nome} pronta", True))
    input("\nPremi invio per continuare...")


def turno_tiro(tavola_propria, tavola_nemica, nome):
    while True:
        pulisci_schermo()
        print(stile(f"=== Turno di {nome} ===", GRASSETTO + GIALLO))
        print(disegna_griglia(tavola_propria, "La tua flotta", True))
        print()
        print(disegna_griglia(tavola_nemica, "Mare nemico", False))
        scelta = input("\nCoordinata da colpire (q per uscire): ")
        esci_se_richiesto(scelta)
        coord = parse_coordinata(scelta)
        if coord is None:
            input(stile("Coordinata non valida. Premi invio...", ROSSO))
            continue
        riga, colonna = coord
        esito, affondata = tavola_nemica.spara(riga, colonna)
        if esito == "già_colpito":
            input(stile("Avevi già colpito questa casella. Premi invio...", ROSSO))
            continue
        pulisci_schermo()
        print(disegna_griglia(tavola_nemica, "Mare nemico", False))
        if esito == "colpito":
            print(stile("Affondato!" if affondata else "Colpito!", VERDE + GRASSETTO))
        else:
            print(stile("Mancato.", BLU))
        if tavola_nemica.tutte_navi_affondate():
            return True
        input("\nPremi invio per continuare...")
        if esito == "mancato":
            return False


def main():
    try:
        pulisci_schermo()
        print(stile("BATTAGLIA NAVALE - versione offline", GRASSETTO + CIANO))
        print("Due giocatori, stesso terminale, niente rete. Griglia 10x10, flotta 4-3-3-2-2-2-1x4.")
        print("Colpito = tiri ancora, mancato = turno avversario. 'q' per uscire in ogni momento.\n")
        input("Premi invio per iniziare il piazzamento di Giocatore 1...")

        tavola1, tavola2 = Tavola(), Tavola()
        piazza_flotta(tavola1, "Giocatore 1")
        pulisci_schermo()
        input("Passa il dispositivo a Giocatore 2, poi premi invio...")
        piazza_flotta(tavola2, "Giocatore 2")

        giocatori = {1: (tavola1, tavola2, "Giocatore 1"), 2: (tavola2, tavola1, "Giocatore 2")}
        turno = 1
        pulisci_schermo()
        input("Inizia la battaglia! Passa il dispositivo a Giocatore 1, poi premi invio...")

        while True:
            propria, nemica, nome = giocatori[turno]
            vittoria = turno_tiro(propria, nemica, nome)
            if vittoria:
                pulisci_schermo()
                print(stile(f"*** {nome} vince! Flotta avversaria affondata. ***", VERDE + GRASSETTO))
                return
            turno = 2 if turno == 1 else 1
            prossimo = giocatori[turno][2]
            pulisci_schermo()
            input(f"Passa il dispositivo a {prossimo}, poi premi invio...")
    except KeyboardInterrupt:
        pulisci_schermo()
        print(stile("\nPartita interrotta.", GIALLO))


if __name__ == "__main__":
    main()
