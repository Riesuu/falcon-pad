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

**Falcon-Pad** est une application web tactique conçue pour **Falcon BMS 4.38**, accessible depuis n'importe quel device sur votre réseau local  PC, tablette, smartphone. Elle lit directement la **Shared Memory BMS** pour afficher votre position, vos contacts radar/datalink, votre Bullseye, votre plan de vol et vos menaces PPT sur une carte  interactive.

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

télécharger directement `Falcon-PAD.exe` depuis les [Releases](../../releases).

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

download `Falcon-PAD.exe` from [Releases](../../releases).

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

## License

Falcon-Pad is free software released under the **GNU General Public License v3.0**.
See [LICENSE](LICENSE) for full terms.

---

## Credits

**Falcon-Pad** — built by [Riesu](mailto:contact@falcon-charts.com)  
Charts — [falcon-charts.com](https://www.falcon-charts.com)

*Falcon BMS is developed by the BMS Team. This project is not affiliated with or endorsed by the BMS Team.*
