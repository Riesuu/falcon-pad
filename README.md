<p align="center">
  <img src="logo.png" alt="Falcon-Pad Logo" width="480"/>
</p>

<h1 align="center">Falcon-Pad</h1>

<p align="center">
  <strong>Tactical companion app for Falcon BMS — web-based, multi-device, no god mode.</strong><br/>
  by <a href="mailto:contact@falcon-charts.com">Riesu</a> · <a href="https://www.falcon-charts.com">falcon-charts.com</a>
</p>

<p align="center">
  <a href="https://www.python.org"><img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python" alt="Python"/></a>
  <a href="https://fastapi.tiangolo.com"><img src="https://img.shields.io/badge/FastAPI-0.100%2B-009688?style=flat-square&logo=fastapi" alt="FastAPI"/></a>
  <a href="https://www.benchmarksims.org"><img src="https://img.shields.io/badge/Falcon%20BMS-4.38-orange?style=flat-square" alt="BMS"/></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-GPL%20v3-green?style=flat-square" alt="License"/></a>
</p>

---

## 🇫🇷 Français

### Présentation

**Falcon-Pad** est une application web tactique conçue pour **Falcon BMS 4.38**, accessible depuis n'importe quel device sur votre réseau local — PC, tablette, smartphone. Elle lit directement la **Shared Memory BMS** pour afficher votre position, vos contacts radar/datalink, votre Bullseye, votre plan de vol et vos menaces PPT sur une carte Leaflet interactive.

L'objectif est simple : avoir un **kneeboard numérique** complet sur une tablette posée à côté de votre HOTAS, sans dépendre d'une application Windows tierce.

### Fonctionnalités

**Navigation & Carte**
- Carte Leaflet interactive — théâtre Corée (Korea)
- Position ownship en temps réel via Shared Memory BMS
- Marker **Bullseye** en temps réel (lecture FD2 `bullseyeX/Y`) avec bearing & distance depuis ownship
- Contacts radar/datalink BMS uniquement — **pas de mode dieu** (DrawingData uniquement)
- Cercles de menace PPT avec rayon NM configurable
- Chargement automatique du dernier fichier `.ini` BMS (steerpoints, PPT, flightplan)
- Popup aéroport compact : ICAO · TACAN · fréquence tour + chips ILS (RWY · freq · CRS)
- Outils de dessin : annotations, règle, flèches, notes collantes

**Onglets tactiques**
- **GPS** — LAT/LON, cap, FL, KIAS, distance & bearing vers le steerpoint actif, position Bullseye
- **Charts** — [falcon-charts.com](https://www.falcon-charts.com) intégré en plein écran
- **Briefing** — visionneuse PDF / image / Word (.docx converti en HTML), stockage persistant sur disque
- **Kneeboard** — brevity codes NATO, fréquences Korea BMS, notes libres persistantes

**Système**
- Heure simulée BMS (`currentTime` FD2 Shared Memory) — pas l'heure UTC réelle
- Barre de statut : IP réseau cliquable (copie l'URL), connexion BMS, horloge BMS
- Roue crantée **Settings** : port d'écoute, dossier briefing, intervalle broadcast, thème dark/light
- Config persistante JSON dans `config/`
- Logs rotatifs dans `logs/` — 3 fichiers × 2 MB max
- Sécurité : middleware LAN uniquement (RFC-1918 + localhost), accès refusé depuis internet
- Multi-device : PC + tablette + téléphone en simultané sur le même serveur

**Mobile & Tactile**
- Optimisé tablette : viewport meta, `user-scalable=no`, touch targets 44px min
- Layout adaptatif : toolbar horizontale, panels plein écran, GPS en grille sur portrait
- Feedback tactile sur tous les éléments interactifs
- `user-select: none` sur la carte pour éviter les sélections accidentelles

### Installation

```bash
# Prérequis Python
pip install -r requirements.txt

# Lancer
python falcon_pad.py
```

Ou télécharger directement `Falcon-PAD.exe` depuis les [Releases](../../releases).

```
  Local    : http://localhost:8000       ← PC
  Réseau   : http://192.168.x.x:8000    ← Tablette / Mobile
  Sécurité : LAN uniquement (RFC-1918 + localhost)
```

### Configuration BMS requise

Dans `User/config/Falcon BMS User.cfg` :
```
set g_bTacviewRealTime 1
```

### Structure des dossiers

```
falcon-pad/
  ├── falcon_pad.py        ← script principal
  ├── falcon_pad.spec      ← config PyInstaller (→ Falcon-PAD.exe)
  ├── requirements.txt
  ├── LICENSE              ← GNU GPL v3
  ├── logo.png
  ├── logs/                ← logs rotatifs (auto-créé)
  ├── briefing/            ← PDF, images, Word importés (auto-créé)
  └── config/
        └── falcon_pad_config.json   ← settings persistants (auto-créé)
```

### Compiler en Falcon-PAD.exe

```bash
pip install pyinstaller
pyinstaller falcon_pad.spec
# → dist/Falcon-PAD.exe
```

### Architecture

```
BMS 4.38 — Shared Memory
  ├── FalconSharedMemoryArea   → cap, vitesse, altitude, z
  └── FalconSharedMemoryArea2  → lat/lon WGS84, currentTime,
                                  bullseyeX/Y, DrawingData

Falcon-Pad  (Python / FastAPI)
  ├── broadcast_loop()    → WebSocket push toutes les N ms
  │     ├── type: aircraft  → position + heure BMS + bullseye
  │     └── type: radar     → contacts DrawingData (no god mode)
  ├── /api/mission        → steerpoints & PPT depuis .ini
  ├── /api/briefing/*     → upload PDF/image/docx, serve inline
  ├── /api/settings       → lecture/écriture config JSON
  └── HTML (Leaflet + JS) → carte + UI tactique complète

Client (Navigateur — PC, tablette, téléphone)
  ├── Leaflet map   → fond OSM, ownship, bullseye, contacts, PPT
  ├── WebSocket     → position & contacts temps réel
  └── Onglets       → GPS · Charts · Briefing · Kneeboard
```

### Shared Memory — Offsets utilisés

| Zone | Offset | Type | Champ |
|---|---|---|---|
| FD  | `0x034` | float | KIAS (knots) |
| FD  | `0x0BC` | float | Cap vrai HSI (°) |
| FD2 | `0x014` | float | Altitude baro (ft) |
| FD2 | `0x02C` | int   | `currentTime` (s depuis minuit) |
| FD2 | `0x408` | float | Latitude WGS84 (°) |
| FD2 | `0x40C` | float | Longitude WGS84 (°) |
| FD2 | `0x4B0` | float | `bullseyeX` North (ft BMS) |
| FD2 | `0x4B4` | float | `bullseyeY` East (ft BMS) |

### Roadmap

- [ ] Support multi-théâtre (Balkans, Israel, Irak…)
- [ ] Détection automatique du théâtre actif via SharedMemory
- [ ] QR code de l'URL réseau pour connexion tablette rapide
- [ ] Mode offline (tuiles de carte en cache local)
- [ ] Export briefing en PDF depuis l'onglet Briefing

---

## 🇬🇧 English

### Overview

**Falcon-Pad** is a web-based tactical companion for **Falcon BMS 4.38**, accessible from any device on your local network — PC, tablet, smartphone. It reads directly from **BMS Shared Memory** to display your position, radar/datalink contacts, Bullseye, flight plan, and PPT threat circles on an interactive Leaflet map.

The goal: a complete **digital kneeboard** on a tablet next to your HOTAS, no third-party Windows app required.

### Features

**Navigation & Map**
- Interactive Leaflet map — Korea theater
- Real-time ownship position via BMS Shared Memory
- Real-time **Bullseye** marker (FD2 `bullseyeX/Y`) with bearing & distance from ownship
- BMS radar/datalink contacts only — **no god mode** (DrawingData only)
- PPT threat circles with configurable NM radius
- Auto-loads latest BMS `.ini` file (steerpoints, PPT, flightplan)
- Compact airbase popup: ICAO · TACAN · tower freq + ILS chips (RWY · freq · CRS)
- Drawing tools: annotations, ruler, arrows, sticky notes

**Tactical tabs**
- **GPS** — LAT/LON, heading, FL, KIAS, distance & bearing to active steerpoint, Bullseye position
- **Charts** — [falcon-charts.com](https://www.falcon-charts.com) embedded full-screen
- **Briefing** — PDF / image / Word viewer (.docx → HTML), persistent disk storage
- **Kneeboard** — NATO brevity codes, Korea BMS frequencies, persistent free notes

**System**
- BMS simulated time (`currentTime` FD2 Shared Memory) — not wall-clock UTC
- Status bar: clickable network IP (copies URL to clipboard), BMS connection, BMS clock
- **Settings** gear panel: listen port, briefing folder, broadcast interval, dark/light theme
- Persistent JSON config in `config/`
- Rotating logs in `logs/` — 3 files × 2 MB max
- LAN-only security middleware (RFC-1918 + localhost) — internet access blocked
- Multi-device: PC + tablet + phone simultaneously on the same server

**Mobile & Touch**
- Tablet-optimized: viewport meta, `user-scalable=no`, 44px min touch targets
- Responsive layout: horizontal toolbar, full-height panels, GPS grid on portrait
- Touch feedback on all interactive elements
- `user-select: none` on map to prevent accidental text selection

### Installation

```bash
pip install -r requirements.txt
python falcon_pad.py
```

Or download `Falcon-PAD.exe` from [Releases](../../releases).

```
  Local    : http://localhost:8000       ← PC
  Network  : http://192.168.x.x:8000    ← Tablet / Mobile
  Security : LAN only (RFC-1918 + localhost)
```

### Required BMS config

In `User/config/Falcon BMS User.cfg`:
```
set g_bTacviewRealTime 1
```

### Build executable

```bash
pip install pyinstaller
pyinstaller falcon_pad.spec
# → dist/Falcon-PAD.exe
```

### Architecture

```
BMS 4.38 — Shared Memory
  ├── FalconSharedMemoryArea   → heading, speed, altitude, z
  └── FalconSharedMemoryArea2  → lat/lon WGS84, currentTime,
                                  bullseyeX/Y, DrawingData

Falcon-Pad  (Python / FastAPI)
  ├── broadcast_loop()    → WebSocket push every N ms
  │     ├── type: aircraft  → position + BMS time + bullseye
  │     └── type: radar     → DrawingData contacts (no god mode)
  ├── /api/mission        → steerpoints & PPT from .ini
  ├── /api/briefing/*     → upload PDF/image/docx, serve inline
  ├── /api/settings       → read/write persistent JSON config
  └── HTML (Leaflet + JS) → full tactical map & UI

Client (Browser — PC, tablet, phone)
  ├── Leaflet map   → OSM tiles, ownship, bullseye, contacts, PPT
  ├── WebSocket     → real-time position & contacts
  └── Tabs          → GPS · Charts · Briefing · Kneeboard
```

### Shared Memory — Offsets used

| Area | Offset | Type | Field |
|---|---|---|---|
| FD  | `0x034` | float | KIAS (knots) |
| FD  | `0x0BC` | float | True heading HSI (°) |
| FD2 | `0x014` | float | Baro altitude (ft) |
| FD2 | `0x02C` | int   | `currentTime` (s since midnight) |
| FD2 | `0x408` | float | Latitude WGS84 (°) |
| FD2 | `0x40C` | float | Longitude WGS84 (°) |
| FD2 | `0x4B0` | float | `bullseyeX` North (ft BMS) |
| FD2 | `0x4B4` | float | `bullseyeY` East (ft BMS) |

### Roadmap

- [ ] Multi-theater support (Balkans, Israel, Iraq…)
- [ ] Automatic theater detection via SharedMemory
- [ ] QR code for quick tablet connection
- [ ] Offline map tile caching
- [ ] Briefing PDF export

---

## Falcon-Pad vs BMSNav

| | **Falcon-Pad** | **BMSNav** |
|---|---|---|
| Access | Any browser, any device | Windows app only |
| Map | OpenStreetMap | BMS terrain (exact) |
| Datalink | DrawingData (what you see) | BMS native |
| Bullseye | ✅ Real-time marker + bearing | Depends |
| Briefing | PDF / Image / Word built-in | Not included |
| Charts | falcon-charts.com embedded | No |
| BMS time | ✅ SharedMemory currentTime | N/A |
| Multi-device | ✅ Simultaneous | ❌ Single instance |
| God mode | ❌ Disabled by design | Depends on config |
| Mobile | ✅ Tablet optimized | ❌ |
| Open source | ✅ GPL v3 | ❌ Closed |

---

## License

Falcon-Pad is free software released under the **GNU General Public License v3.0**.
See [LICENSE](LICENSE) for full terms.

---

## Credits

**Falcon-Pad** — built by [Riesu](mailto:contact@falcon-charts.com)  
Charts — [falcon-charts.com](https://www.falcon-charts.com)

*Falcon BMS is developed by the BMS Team. This project is not affiliated with or endorsed by the BMS Team.*
