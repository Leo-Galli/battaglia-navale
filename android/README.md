# App Android

Capacitor shell for the same web app as the browser (`android/www/index.html`). Point it at `battaglia_navale.py server-web` (HTTP API + UI).

## Requisiti

- Node.js 22+
- JDK 21+
- Android SDK (Android Studio o `cmdline-tools`)

## Sviluppo

```bash
cd android
npm install
npx cap sync android
npx cap open android
```

In emulatore Android, l’host del PC è **`http://10.0.2.2:8080`**. Su dispositivo fisico usa l’IP LAN del PC (es. `http://192.168.1.10:8080`).

Avvia il motore sul PC:

```bash
python3 battaglia_navale.py server-web 0.0.0.0 8080
```

## Build APK (release)

```bash
cd android
npm ci
npx cap sync android
cd android
./gradlew assembleRelease
```

APK: `android/app/build/outputs/apk/release/app-release.apk`

## Aggiornamenti automatici (GitHub)

All’avvio l’app interroga  
`https://api.github.com/repos/Leo-Galli/battaglia-navale/releases/latest`  
e confronta la versione con quella installata. Se c’è un APK più recente nella release, propone **Scarica e installa** (DownloadManager + permesso `REQUEST_INSTALL_PACKAGES`).

Configurazione in `www/config.js`. Controllo manuale: pulsante in header.

## CI

Push tag `v*` avvia `.github/workflows/android-apk.yml` e allega l’APK agli artifact / release GitHub.
