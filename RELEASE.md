# Release 1.2.0

## Novità

- Motore di gioco in `motore.py` (usabile senza UI).
- Modalità online browser (`/gioca`) e server HTTP (`server-web`).
- Regola: **colpito = stesso turno**, mancato = passa l’avversario.
- **App Android** in `android/` (Capacitor), stessa esperienza del sito con D-pad e layout mobile.

## Android APK

1. Scarica l’APK dalla [GitHub Release v1.2.0](https://github.com/Leo-Galli/battaglia-navale/releases/tag/v1.2.0) (workflow CI).
2. Oppure compila localmente: vedi `android/README.md`.
3. Avvia sul PC: `python3 battaglia_navale.py server-web 0.0.0.0 8080`.
4. Nell’app imposta l’URL API (LAN o `10.0.2.2` in emulatore).

## Sito

Deploy statico Astro in `website/` (Vercel, root directory `website`).
