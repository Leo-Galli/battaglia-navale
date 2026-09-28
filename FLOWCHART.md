# Battaglia Navale — Flowchart di sistema

Diagrammi del sistema completo: motore, rete, client e deploy. Per dettagli testuali vedi [`DATASHEET.md`](DATASHEET.md) e [`README.md`](README.md).

---

## Indice diagrammi

1. [Vista d’insieme](#1-vista-dinsieme)
2. [Entry point e processi](#2-entry-point-e-processi)
3. [Motore di gioco (`motore.py`)](#3-motore-di-gioco-motorepy)
4. [Server TCP terminale](#4-server-tcp-terminale)
5. [Server HTTP online](#5-server-http-online)
6. [Client terminale](#6-client-terminale)
7. [Client browser e Android](#7-client-browser-e-android)
8. [Regole turno in battaglia](#8-regole-turno-in-battaglia)
9. [Launcher e lifecycle server](#9-launcher-e-lifecycle-server)
10. [Build e distribuzione](#10-build-e-distribuzione)

---

## 1. Vista d’insieme

```mermaid
flowchart TB
    subgraph Utenti
        U1[Giocatore 1]
        U2[Giocatore 2]
    end

    subgraph ClientLayer["Client (presentazione)"]
        T1[Terminale TUI<br/>battaglia_navale.py client]
        T2[Terminale TUI]
        WEB[Sito /gioca<br/>website Astro]
        APP[App Android<br/>android/ Capacitor]
    end

    subgraph NetworkLayer["Rete applicativa"]
        TCP[Server TCP :5555<br/>run_server]
        HTTP[Server HTTP :8080<br/>server_web.py]
    end

    subgraph Domain["Dominio (autoritativo)"]
        MOT[motore.py<br/>Partita · Tavola · regole]
    end

    subgraph Ops["Operazioni"]
        LAUNCH[Launcher menu<br/>loop_launcher]
        CFG[.battaglia_navale/<br/>pid · log · json]
    end

    U1 --> T1
    U2 --> T2
    U1 --> WEB
    U2 --> APP

    T1 <-->|JSON + newline| TCP
    T2 <-->|JSON + newline| TCP
    WEB <-->|REST JSON| HTTP
    APP <-->|REST JSON| HTTP

    TCP --> MOT
    HTTP --> MOT

    LAUNCH -->|Popen server| TCP
    LAUNCH -->|Popen server-web| HTTP
    LAUNCH -->|subprocess client| T1
    LAUNCH --> CFG
    TCP --> CFG
    HTTP --> CFG
```

**Regola centrale:** solo `Partita` in memoria sul server (TCP o HTTP) decide stato, turno e esito colpi. I client mostrano e inviano comandi.

---

## 2. Entry point e processi

```mermaid
flowchart LR
    subgraph CLI["python3 battaglia_navale.py"]
        A[nessun arg] --> LAUNCH[loop_launcher]
        B[server host porta] --> SRV[run_server]
        C[client host porta] --> CLT[run_client]
        D[server-web host porta] --> WEBSRV[run_server_web]
    end

    subgraph Altri
        SH[./avvia.sh] --> LAUNCH
        SW[server_web.py] -.-> WEBSRV
    end

    LAUNCH --> M1[Menu scelta]
    M1 --> M2[Avvia TCP]
    M1 --> M3[Avvia HTTP]
    M1 --> M4[Connetti client]
    M1 --> M5[Stato / Stop]
```

| Comando | Processo | Porta tipica |
|---------|----------|--------------|
| `(default)` | Launcher interattivo | — |
| `server` | TCP + 2 thread client | 5555 |
| `server-web` | HTTP ThreadingHTTPServer | 8080 |
| `client` | TUI + socket | verso server |

---

## 3. Motore di gioco (`motore.py`)

```mermaid
flowchart TB
    subgraph Partita
        F{fase?}
        F -->|posizionamento| PIA[piazza nave]
        F -->|battaglia| SPA[spara]
        F -->|fine| END[immobile]

        PIA --> V1{valido?}
        V1 -->|no| EP[errore]
        V1 -->|sì| INC[indice_nave++]
        INC --> PC{flotte complete?}
        PC -->|sì| F2[fase = battaglia]
        PC -->|no| F

        SPA --> T0{turno == giocatore?}
        T0 -->|no| ET[turno_errato]
        T0 -->|sì| TV[Tavola.spara avversario]
        TV --> VIC{tutte affondate?}
        VIC -->|sì| WIN[vincitore · fase fine]
        VIC -->|no| ES{esito?}
        ES -->|mancato| SW[turno = avversario]
        ES -->|colpito| KEEP[turno invariato]
        SW --> F
        KEEP --> F
    end

    subgraph Tavola["Tavola (×2)"]
        G[griglia . N X O]
        CR[colpi_ricevuti]
        NV[navi segmenti]
    end

    Partita --> Tavola
```

---

## 4. Server TCP terminale

```mermaid
sequenceDiagram
    autonumber
    participant G1 as Client 1 TCP
    participant G2 as Client 2 TCP
    participant Main as Main thread
    participant TH1 as Thread G1
    participant TH2 as Thread G2
    participant P as Partita motore

    Main->>Main: bind listen
    G1->>Main: connect
    Main->>G1: attesa 1/2
    Main->>TH1: start gestisci_client
    G2->>Main: connect
    Main->>G2: attesa 2/2
    Main->>TH2: start gestisci_client
    Main->>Main: tutti_connessi.set()
    Main->>Main: close listener

    par Benvenuto
        TH1->>G1: benvenuto giocatore=1
        TH2->>G2: benvenuto giocatore=2
    end

    loop Partita
        G1->>TH1: piazza / spara / stato
        TH1->>P: lock mutate
        TH1->>G1: risposta
        Note over TH1,P: esito_sparo broadcast invia_tutti
        TH1->>G1: esito_sparo
        TH1->>G2: esito_sparo
    end
```

```mermaid
flowchart LR
    subgraph Threading
        L[Lock Partita]
        LC[Lock connessioni]
        E[Event tutti_connessi]
    end

    MSG[Ricevitore.ricevi] --> DISPATCH{tipo}
    DISPATCH -->|piazza| L
    DISPATCH -->|spara| L
    DISPATCH -->|stato| SNAP[snapshot tavole testo]
    DISPATCH -->|piazza OK + flotte ok| BCAST[inizio_battaglia]
    DISPATCH -->|spara OK| BCAST2[esito_sparo]
    BCAST --> LC
    BCAST2 --> LC
```

---

## 5. Server HTTP online

```mermaid
flowchart TB
    subgraph HTTP["server_web.py"]
        H[ThreadingHTTPServer]
        H --> R{path method}

        R -->|POST /api/unisciti| JOIN[token giocatore 1|2]
        R -->|GET /api/stato?token| ST[snapshot_giocatore JSON]
        R -->|POST /api/piazza| PL[piazza]
        R -->|POST /api/spara| SH[spara]
        R -->|GET /api/health| OK[ok motore python]

        JOIN --> SW[StatoWeb.partita]
        ST --> SW
        PL --> SW
        SH --> SW
    end

    SW --> MOT[Partita motore.py]

    CORS[CORS *] --> R
```

```mermaid
sequenceDiagram
    participant A as Browser / App
    participant S as server_web
    participant P as Partita

    A->>S: POST /api/unisciti
    S->>A: token, giocatore, connessi
    A->>S: GET /api/stato?token
    S->>P: snapshot
    S->>A: propria, nemica, fase, turno

    loop Piazzamento
        A->>S: POST /api/piazza
        S->>P: piazza
        S->>A: ok / motivo
    end

    loop Battaglia
        A->>S: POST /api/spara
        S->>P: spara
        S->>A: esito, prossimo_turno, vittoria?
        A->>S: GET /api/stato poll
    end
```

---

## 6. Client terminale

```mermaid
flowchart TD
    START[run_client] --> CONN[TCP connect]
    CONN --> BEN[attendi benvenuto]
    BEN --> FP[fase_posizionamento]

    FP --> RS1[richiedi_stato]
    RS1 --> PL{prossima_lunghezza?}
    PL -->|numero| UI1[seleziona_piazzamento_nave<br/>curses o fallback]
    UI1 --> SND1[invia piazza]
    SND1 --> FP
    PL -->|null| WAIT[inizio_battaglia]

    WAIT --> FB[fase_battaglia]
    FB --> RS2[richiedi_stato]
    RS2 --> TU{turno == io?}
    TU -->|sì| UI2[seleziona_sparo]
    UI2 --> SND2[invia spara]
    TU -->|no| OV[overlay attesa]
    SND2 --> RX[ricevi esito_sparo]
    OV --> RX
    RX --> VIT{vittoria?}
    VIT -->|no| FB
    VIT -->|sì| STOP[Fine]
```

---

## 7. Client browser e Android

```mermaid
flowchart LR
    subgraph Web["website /gioca"]
        WUI[HTML CSS game.js]
    end

    subgraph Android["android/www"]
        AUI[index.html game.js<br/>+ D-pad touch]
        UPD[update.js<br/>GitHub releases/latest]
    end

    subgraph Cap["Capacitor WebView"]
        WV[MainActivity]
    end

    WUI -->|fetch REST| HTTP[(server-web :8080)]
    AUI --> WV
    UPD -->|api.github.com| GH[(GitHub Releases)]
    UPD -->|DownloadManager| APKINST[InstallApk plugin]
    WV -->|fetch REST| HTTP

    WUI -. stessa logica .- AUI
```

| Client | Default API (sviluppo) | Input |
|--------|------------------------|--------|
| Browser | host:8080 o Vercel + server LAN | WASD, touch nemico |
| Android | 10.0.2.2:8080 emulatore / IP LAN | D-pad, touch |

---

## 8. Regole turno in battaglia

```mermaid
flowchart TD
    SHOT[Sparo valido accettato] --> H{Cella avversario}
    H -->|N → X colpito| C1[Segna colpito]
    H -->|acqua| C2[Segna O mancato]

    C1 --> AF{Affondata?}
    AF -->|info in payload| V{Tutta flotta affondata?}
    C2 --> V

    V -->|sì| WIN[fase fine · vincitore]
    V -->|no| E{esito}
    E -->|colpito| SAME[prossimo_turno = stesso giocatore]
    E -->|mancato| SWAP[prossimo_turno = avversario]
```

---

## 9. Launcher e lifecycle server

```mermaid
flowchart TD
    MENU[menu_principale] --> O0[Avvia server TCP]
    MENU --> O1[Avvia server web]
    MENU --> O2[Connetti terminale]
    MENU --> O3[Stato server]
    MENU --> O4[Ferma server]
    MENU --> O5[Esci]

    O0 --> CFG1[host porta probe]
    CFG1 --> POP[Popen server]
    POP --> PID1[server.pid + server.log]

    O1 --> CFG2[host porta]
    CFG2 --> POP2[Popen server-web]
    POP2 --> PID2[server-web.pid + server-web.log]

    O2 --> SUB[subprocess client]

    O4 --> KILL[SIGTERM / taskkill]
    KILL --> PID1
    KILL --> PID2

    O3 --> CHK[PID attivo + porta_raggiungibile]
```

---

## 10. Build e distribuzione

```mermaid
flowchart TB
    subgraph Repo["GitHub Leo-Galli/battaglia-navale"]
        PY[motore.py · battaglia_navale.py · server_web.py]
        WEBDIR[website/ Astro]
        AND[android/ Capacitor]
        WF[.github/workflows/android-apk.yml]
    end

    subgraph Deploy
        VER[Vercel root=website]
        TAG[tag v* push]
    end

    subgraph Output
        SITE[battaglia-navale.vercel.app]
        APK[app-release.apk Release]
    end

    WEBDIR --> VER --> SITE
    AND --> WF
    TAG --> WF --> APK

    PY -->|server-web LAN| SITE
    PY -->|server-web LAN| APK
```

---

## Mappa file → ruolo

```mermaid
flowchart LR
    motore[motore.py] --> logic[Regole + Partita]
    bn[battaglia_navale.py] --> logic
    bn --> tui[TUI + TCP server/client]
    bn --> launch[Launcher]
    sw[server_web.py] --> logic
    sw --> http[REST API]
    web[website/] --> static[Marketing + /gioca]
    and[android/] --> apk[APK WebView client]
```

---

MIT — Leonardo Galli
