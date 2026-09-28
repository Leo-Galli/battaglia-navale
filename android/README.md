# App Android

Client **Capacitor** con la stessa UI/logica del sito (`/gioca`): griglie touch, D-pad, API HTTP verso `server_web.py`.

## Requisiti

- Node.js 22+
- JDK 17+
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

## CI

Push tag `v*` avvia `.github/workflows/android-apk.yml` e allega l’APK agli artifact / release GitHub.
