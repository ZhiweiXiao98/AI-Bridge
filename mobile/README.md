# Data Bridge Mobile

Data Bridge Mobile is now a lightweight companion PWA. It is not a Python APK.

The phone connects to the PC service over HTTP/WebSocket, then acts as a mobile control surface:

- log in to the desktop service
- view browser/API messages
- switch sessions
- send browser-mode or API-mode prompts
- inspect server status/log events

This matches the Marvis-style architecture: the computer remains the execution host; the phone is the companion, monitor, and remote control.

## Run

```powershell
C:\Data-Bridge\mobile\serve_mobile.ps1 -Port 8787
```

Open `http://<computer-ip>:8787` on the phone.

The Data Bridge service still needs to be running on the PC, usually at port `8765`.

## Why The Old Mobile Build Was Removed

The old mobile path embedded Python into an Android APK. That produced very large build directories and APKs, and it made every build depend on Android Python runtimes, engine artifacts, build caches, and ABI packaging.

For a companion client, that is the wrong weight class. A web/PWA client ships only static assets and uses the existing PC service for the heavy work.

## Test

```powershell
node C:\Data-Bridge\tests\mobile_web_core.test.mjs
```
