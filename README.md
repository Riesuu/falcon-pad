<p align="center">
  <img src="logo.png" alt="Falcon-Pad Logo" width="480"/>
</p>

<h1 align="center">Falcon-Pad</h1>

<p align="center">
  <strong>Real-time tactical companion for Falcon BMS 4.38 — map, steerpoints, radio, checklists and contacts on your tablet.</strong><br/>
  by <a href="mailto:contact@falcon-charts.com">Riesu</a> · <a href="https://www.falcon-charts.com">falcon-charts.com</a>
</p>

<p align="center">
  <a href="https://github.com/Riesuu/falcon-pad/releases"><img src="https://img.shields.io/badge/Download-v0.3-brightgreen?style=flat-square" alt="Download"/></a>
  <a href="https://www.python.org"><img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python" alt="Python"/></a>
  <a href="https://fastapi.tiangolo.com"><img src="https://img.shields.io/badge/FastAPI-0.100%2B-009688?style=flat-square&logo=fastapi" alt="FastAPI"/></a>
  <a href="https://www.benchmarksims.org"><img src="https://img.shields.io/badge/Falcon%20BMS-4.38-orange?style=flat-square" alt="BMS"/></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-GPL%20v3-green?style=flat-square" alt="License"/></a>
</p>

---

## 🇫🇷 Français

### Présentation

**Falcon-Pad** est une application web tactique pour **Falcon BMS 4.38**, accessible depuis n'importe quel appareil sur votre réseau local — PC, tablette, smartphone. Elle lit la **Shared Memory BMS** et le flux **TRTT (Tacview Real-Time)** pour afficher votre position, vos contacts aériens, votre plan de vol, vos menaces PPT et plus encore sur une carte interactive.

L'objectif : un **kneeboard numérique complet** sur une tablette posée à côté de votre HOTAS, sans application Windows tierce.

### Fonctionnalités

**Carte & Navigation**
- Carte interactive multi-couches : sombre, satellite, terrain
- Position ownship en temps réel (cap, altitude, vitesse) via Shared Memory BMS
- Multi-théâtre : KTO, Israel, Balkans, HTO — détection automatique au démarrage
- Steerpoints & plan de vol chargés automatiquement depuis BMS ou vos fichiers DTC `.ini`
- **Bullseye** avec cercles de portée (20/40/60/80/100 NM), 8 radicaux et labels de bearing
- Menaces PPT avec cercles de portée, noms et type — distinction sol/aérien par altitude AGL

**Contacts ACMI**
- Tous les appareils de la mission via le flux TRTT : amis, ennemis, inconnus
- Code couleur : vert (allié), rouge (ennemi), ambre (inconnu)
- Labels : callsign, altitude, cap, vitesse

**Radio & COMMS**
- Presets UHF/VHF et TACAN chargés automatiquement depuis votre profil pilote
- Détection automatique de l'aéroport de départ

**Checklists**
- 246 items depuis la T.O. BMS1F-16CJ-1CL-1
- Codage couleur par phase de vol : sol, taxi, décollage, combat, atterrissage, extinction

**Briefing**
- Visionneuse PDF, images, DOCX et HTML
- Pinch-to-zoom sur tablette
- Upload via l'interface ou dépôt direct dans le dossier `personal/`
- Briefings BMS chargés automatiquement

**Système**
- Heure simulée BMS (Shared Memory) — pas l'heure UTC réelle
- Sécurité : LAN uniquement (RFC-1918 + localhost)
- Config persistante JSON, logs rotatifs (3 × 2 MB)
- Multi-device : PC + tablette + téléphone en simultané

### Installation rapide

1. Téléchargez `FalconPad.exe` depuis les [Releases](https://github.com/Riesuu/falcon-pad/releases) et placez-le dans le dossier `Tools` de BMS.
2. Ajoutez cette ligne dans `User/Config/Falcon BMS User.cfg` :
   ```
   set g_bTacviewRealTime 1
   ```
3. Ouvrez le port 8000 dans le pare-feu Windows (en tant qu'Administrateur) :
   ```
   netsh advfirewall firewall add rule name="Falcon-Pad" dir=in action=allow protocol=TCP localport=8000
   ```
4. Lancez `FalconPad.exe`. L'URL réseau est affichée dans la fenêtre système.
5. Sur votre tablette, ouvrez l'URL réseau dans un navigateur (ex. `http://192.168.0.x:8000`).

---

## 🇬🇧 English

### Overview

**Falcon-Pad** is a web-based tactical companion for **Falcon BMS 4.38**, accessible from any device on your local network — PC, tablet, smartphone. It reads **BMS Shared Memory** and the **TRTT (Tacview Real-Time)** stream to display your position, aircraft contacts, flight plan, PPT threats and more on an interactive map.

The goal: a complete **digital kneeboard** on a tablet next to your HOTAS, no third-party Windows app required.

### Features

**Map & Navigation**
- Interactive multi-layer map: dark, satellite, terrain
- Real-time ownship position (heading, altitude, speed) via BMS Shared Memory
- Multi-theater: KTO, Israel, Balkans, HTO — auto-detected at runtime
- Steerpoints & flight plan auto-loaded from BMS or your DTC `.ini` files
- **Bullseye** with range rings (20/40/60/80/100 NM), 8 radials and bearing labels
- PPT threat rings with range circles, names and threat type — ground vs airborne by AGL altitude

**ACMI Contacts**
- All mission aircraft via TRTT stream: friendly, enemy, unknown
- Color-coded blips: green (ally), red (enemy), amber (unknown)
- Labels: callsign, altitude, heading, speed

**Radio & COMMS**
- UHF/VHF presets and TACAN auto-loaded from your pilot profile
- Departure airport detected automatically

**Checklists**
- 246-item F-16 checklist from T.O. BMS1F-16CJ-1CL-1
- Color-coded by flight phase: ground, taxi, takeoff, combat, landing, shutdown

**Briefing**
- PDF, image, DOCX and HTML viewer
- Pinch-to-zoom on tablets
- Upload via the interface or drop files directly in the `personal/` folder
- BMS briefings auto-loaded

**System**
- BMS simulated time (Shared Memory) — not wall-clock UTC
- LAN-only security (RFC-1918 + localhost)
- Persistent JSON config, rotating logs (3 × 2 MB)
- Multi-device: PC + tablet + phone simultaneously

### Quick Setup

1. Download `FalconPad.exe` from [Releases](https://github.com/Riesuu/falcon-pad/releases) and place it in the BMS `Tools` folder.
2. Add this line to `User/Config/Falcon BMS User.cfg`:
   ```
   set g_bTacviewRealTime 1
   ```
3. Open port 8000 in Windows Firewall (as Administrator):
   ```
   netsh advfirewall firewall add rule name="Falcon-Pad" dir=in action=allow protocol=TCP localport=8000
   ```
4. Run `FalconPad.exe`. The network URL is shown in the tray window.
5. On your tablet, open the network URL in a browser (e.g. `http://192.168.0.x:8000`).

---

## Development

### Project structure

```
falcon-pad/
├── falcon_pad.py        # Entry point — FastAPI app, WebSocket, lifespan
├── app_info.py          # Single source of truth for version, URLs, constants
├── config.py            # Persistent JSON settings (port, theme, broadcast interval…)
├── core/
│   ├── sharedmem.py     # BMS Shared Memory reader (Windows ctypes)
│   ├── broadcast.py     # Main loop — reads SharedMem, pushes WebSocket frames
│   ├── trtt.py          # TRTT client — Tacview real-time aircraft contacts
│   ├── mission.py       # DTC .ini parser (steerpoints, PPT, radio presets)
│   ├── theaters.py      # Theater definitions and auto-detection
│   ├── airports.py      # Airport/TACAN database
│   └── stringdata.py    # BMS StringData Shared Memory reader
├── server/
│   └── routes.py        # FastAPI REST routes (config, briefing upload…)
├── ui/
│   ├── ui_prefs.py      # PySide6 tray window
│   └── ui_theme.py      # Qt theme helpers
├── frontend/            # Static web app (HTML/CSS/JS)
│   └── images/
├── data/
│   └── checklists/      # F-16 checklist JSON
└── tests/               # pytest test suite
```

### Setup

```bash
git clone https://github.com/Riesuu/falcon-pad.git
cd falcon-pad
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
```

### Run in dev mode

```bash
python falcon_pad.py
```

The server starts on `http://localhost:8000`. BMS does not need to be running — the app handles missing SharedMemory gracefully.

### Tests

```bash
pytest
```

Tests cover SharedMemory parsing, theater detection, DTC `.ini` parsing, TRTT, config, and HTTP routes. The test suite runs without BMS or any Windows-specific dependency.

### Build (Windows executable)

```bash
pip install pyinstaller>=6.0.0
pyinstaller FalconPad.spec
```

Output: `dist/FalconPad/FalconPad.exe` — self-contained, no Python install required.

### Contributing

Pull requests are welcome. A few guidelines:
- Keep `app_info.py` as the single source of truth for any version or URL constant.
- New features should come with tests in `tests/`.
- The frontend is plain HTML/CSS/JS — no build step, no bundler.

---

## License

Falcon-Pad is free software released under the **GNU General Public License v3.0**.  
See [LICENSE](LICENSE) for full terms.

---

## Credits

**Falcon-Pad** — built by [Riesu](mailto:contact@falcon-charts.com)  
Charts — [falcon-charts.com](https://www.falcon-charts.com)

*Falcon BMS is developed by the BMS Team. This project is not affiliated with or endorsed by the BMS Team.*
