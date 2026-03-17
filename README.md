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

**Falcon-Pad** est une application web tactique conçue pour **Falcon BMS 4.38**, accessible depuis n'importe quel device sur votre réseau local — PC, tablette, smartphone. Elle lit directement la **Shared Memory BMS** pour afficher votre position, vos contacts radar/datalink, votre plan de vol, et vos menaces PPT sur une carte Leaflet interactive.

L'objectif est simple : avoir un **kneeboard numérique** complet sur une tablette posée à côté de votre HOTAS, sans dépendre d'une application Windows tierce.

### Fonctionnalités

**Navigation & Carte**
- Carte Leaflet interactive centrée sur le théâtre Corée
- Position ownship en temps réel (Shared Memory BMS)
- Contacts radar/datalink BMS uniquement — **pas de mode dieu**
- Cercles de menace PPT avec rayon configurable
- Chargement automatique du dernier fichier `.ini` BMS (steerpoints, PPT, flightplan)
- Outils de dessin : annotations, règle, flèches, notes

**Onglets tactiques**
- **GPS** — LAT/LON, cap, FL, KIAS, distance & bearing vers le steerpoint actif
- **Charts** — [falcon-charts.com](https://www.falcon-charts.com) intégré en plein écran
- **Briefing** — visionneuse PDF / image / Word (.docx converti en HTML), stockage persistant
- **Kneeboard** — brevity codes NATO, fréquences Korea BMS, notes libres

**Système**
- Heure simulée BMS (`currentTime` Shared Memory) — pas l'heure UTC
- Barre de statut : IP réseau cliquable, connexion BMS, horloge BMS
- Panneau Settings : port d'écoute, dossier briefing, intervalle broadcast, thème
- Config persistante JSON dans `config/`
- Logs rotatifs dans `logs/` (3 × 2 MB)
- Sécurité : middleware LAN uniquement (RFC-1918 + localhost)
- Multi-device : PC + tablette en simultané

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
  Sécurité : LAN uniquement (RFC-1918)
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
  ├── briefing/            ← PDF, images, Word (auto-créé)
  └── config/
        └── falcon_pad_config.json   ← settings (auto-créé)
```

### Compiler en Falcon-PAD.exe

```bash
pip install pyinstaller
pyinstaller falcon_pad.spec
# → dist/Falcon-PAD.exe
```

### Architecture

```
BMS 4.38
  └── Shared Memory
        ├── Position ownship  →  get_position()
        ├── currentTime       →  heure simulée BMS
        └── DrawingData       →  contacts radar/datalink

Falcon-Pad (Python / FastAPI)
  ├── broadcast_loop()     →  WebSocket push 200ms
  ├── /api/mission         →  steerpoints & PPT
  ├── /api/briefing/*      →  upload / serve fichiers
  ├── /api/settings        →  config persistante
  └── HTML (Leaflet + JS)  →  carte & UI tactique

Client (Navigateur)
  ├── Leaflet map           →  fond OSM + overlays
  ├── WebSocket             →  position & contacts temps réel
  └── Onglets               →  GPS · Charts · Briefing · Kneeboard
```

### Roadmap

- [ ] Support multi-théâtre (Balkans, Israel, Irak…)
- [ ] Détection automatique du théâtre via SharedMemory
- [ ] QR code de l'URL réseau pour connexion tablette rapide
- [ ] Mode offline (tuiles de carte en cache local)
- [ ] Affichage TACAN/ILS sur sélection base

---

## 🇬🇧 English

### Overview

**Falcon-Pad** is a web-based tactical companion for **Falcon BMS 4.38**, accessible from any device on your local network. It reads directly from **BMS Shared Memory** to display your position, radar/datalink contacts, flight plan, and PPT threat circles on an interactive Leaflet map.

The goal: a complete **digital kneeboard** on a tablet next to your HOTAS, no third-party Windows app required.

### Features

**Navigation & Map**
- Interactive Leaflet map — Korea theater
- Real-time ownship position (BMS Shared Memory)
- BMS radar/datalink contacts only — **no god mode**
- PPT threat circles with configurable radius
- Auto-loads latest BMS `.ini` file (steerpoints, PPT, flightplan)
- Drawing tools: annotations, ruler, arrows, sticky notes

**Tactical tabs**
- **GPS** — LAT/LON, heading, FL, KIAS, distance & bearing to active steerpoint
- **Charts** — [falcon-charts.com](https://www.falcon-charts.com) embedded full-screen
- **Briefing** — PDF / image / Word viewer (.docx → HTML), persistent disk storage
- **Kneeboard** — NATO brevity codes, Korea BMS frequencies, free notes

**System**
- BMS simulated time (`currentTime` Shared Memory) — not wall-clock UTC
- Status bar: clickable network IP, BMS connection dot, BMS clock
- Settings panel: port, briefing folder, broadcast interval, theme
- Persistent JSON config in `config/`
- Rotating logs in `logs/` (3 × 2 MB)
- LAN-only security middleware (RFC-1918 + localhost)
- Multi-device: PC + tablet simultaneously

### Installation

```bash
pip install -r requirements.txt
python falcon_pad.py
```

Or download `Falcon-PAD.exe` from [Releases](../../releases).

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

### Roadmap

- [ ] Multi-theater support (Balkans, Israel, Iraq…)
- [ ] Automatic theater detection via SharedMemory
- [ ] QR code for quick tablet connection
- [ ] Offline map tile caching
- [ ] TACAN/ILS overlay on airbase selection

---

## Falcon-Pad vs BMSNav

| | **Falcon-Pad** | **BMSNav** |
|---|---|---|
| Access | Any browser, any device | Windows app only |
| Map | OpenStreetMap | BMS terrain (exact) |
| Datalink | DrawingData (what you see) | BMS native |
| Briefing | PDF / Image / Word built-in | Not included |
| Charts | falcon-charts.com embedded | No |
| Multi-device | ✅ Simultaneous | ❌ Single instance |
| God mode | ❌ Disabled by design | Depends on config |
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
