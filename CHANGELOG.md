# Changelog

All notable changes to Falcon-Pad are documented here.

---

## [0.3] — 2026-04-07

### Added
- **Multi-theater support** — KTO, Israel, Balkans, Aegean, Hellas, Iberia, Nordic — auto-detected at runtime from BMS SharedMemory
- **ACMI live contacts** — all mission aircraft via Tacview Real-Time stream (TRTT), color-coded by coalition (green/red/amber) with callsign, altitude, heading and speed labels
- **Radio & COMMS** — UHF/VHF presets and TACAN auto-loaded from BMS pilot profile, departure airport detected automatically
- **F-16 checklist** — 246-item T.O. BMS1F-16CJ-1CL-1, color-coded by flight phase (ground, taxi, takeoff, combat, landing, shutdown)
- **Bullseye rings** — range circles at 20/40/60/80/100 NM with 8 radials and bearing labels, auto-loaded from SharedMemory
- **Briefing viewer** — PDF, images, DOCX and HTML support with pinch-to-zoom; BMS campaign briefings auto-loaded
- **Map layers** — dark, satellite and terrain

### Improved
- PPT threat rings distinguish ground vs airborne units by AGL altitude
- Steerpoints display altitude, index and flight plan lines
- Settings panel: listen port, broadcast interval, dark/light theme

### Fixed
- Theater projection now switches automatically when BMS loads a new theater

---

## [0.2] — 2026-01-15

### Added
- Real-time ownship position, heading, altitude and speed via BMS SharedMemory
- Interactive Leaflet map (Korea theater)
- Steerpoints and PPT threat rings auto-loaded from DTC `.ini` files
- Bullseye marker with bearing and distance from ownship
- Briefing viewer (PDF and images)
- LAN-only security middleware (RFC-1918 + localhost)
- PySide6 tray window with local and network URL display
- Rotating logs (3 × 2 MB)

---

## [0.1] — 2025-11-20

### Added
- Initial release — proof of concept
- Basic map with ownship position
- Korea theater only
- Manual `.ini` file upload for steerpoints
