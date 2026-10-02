# PEHCHAAN Android app

A thin Android shell (Capacitor) that opens the hosted PEHCHAAN dashboard in
a full-screen web view. The app holds no copy of the dashboard: it loads the
address in `capacitor.config.json` (`server.url`), so it always shows the
version that is deployed there and signs in with the same session cookies as
a browser. If the server cannot be reached it shows `www/offline.html`.

| Setting | Value |
|---|---|
| Application id | `in.gov.pehchaan.app` |
| Server | `https://tumharipehchaan.vercel.app` |
| Permissions | Internet, camera (document capture and live photo) |
| Minimum Android | 7.0 (API 24) |

## Build

Needs Node 20+, JDK 21 and the Android SDK (platform 36). On Windows:

```bat
set JAVA_HOME=D:\Android\jdk-21.0.12.1+1
set ANDROID_HOME=D:\Android\sdk
cd mobile
npm install
npm run build
```

The APK is written to `android/app/build/outputs/apk/debug/app-debug.apk`.
It is a debug build signed with this machine's debug key; a phone that has an
APK signed on another machine must uninstall that one first.

## Change the server

Edit `server.url` in `capacitor.config.json` and the address in
`www/offline.html`, then run `npm run build` again.

## Change the icon

The launcher icons and splash screens in `android/app/src/main/res` are the
team's original artwork. `npm run icons` regenerates them from
`assets/logo.png` (1024 x 1024) and overwrites that artwork, so run it only
with a new source image.
