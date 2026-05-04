# Changelog

All notable changes to Falcon-Pad are documented here.

---

## [0.3.1] — 2026-05-04

A maintenance release driven mostly by community feedback from the BMS forum thread.
Big thanks to **oakdesign**, **sniper762**, **Skorp** and **hoover** for the detailed
bug reports and technical input — most of what's below comes straight from their messages.

### Fixed
- **Airports randomly vanishing** (sniper762) — the map sometimes lost all airfields
  and toggling the button wouldn't bring them back. Turns out we were nuking the
  markers *before* the API call returned, so any failed fetch left the map empty
  permanently. Now we only swap markers once we have valid data, and a WebSocket
  reconnect refreshes them automatically.
- **Duplicate ownship on the map** (Skorp) — your own jet was showing up twice:
  once as the proper green marker (from SharedMemory) and once as a weirdly-coloured
  ACMI contact from the Tacview stream. The TRTT feed now filters anything within
  ~200m of ownship.
- **TMERC projection drift** (oakdesign) — every theater is now projected with
  `FE=512000` (the actual 4.38 value, not whatever was previously hardcoded), and
  `lon0` / `FN` are taken straight from each theater's `Theater.txt`. Steerpoint,
  bullseye and PPT positions line up correctly across all theaters now.
- **Theater detection mixing up KTO and Hellas** — both share `FE=512000` and
  similar `FN` values, so projecting the same coordinates produced bbox hits for
  both. Detection now uses airport proximity as a tiebreaker (KTO coords match 9
  Korean airports, Hellas matches 0), so the right theater wins.
- **Theater name mismatches** — if BMS sent a slightly off-spec theater name,
  airports would silently fail to load. Theater names are now canonicalised, with
  fuzzy fallback matching as a safety net.
- **DOCX briefings** — headings weren't HTML-escaped. Crafted documents could
  inject markup; that's plugged.

### Added
- **Fog of war in single-player** (suggested by sniper762, design call by oakdesign) —
  Falcon-Pad was effectively god-mode in SP, showing every enemy in the sim.
  Now in SP the app hides everything except friendlies on the ACMI feed, mirroring
  what the Tacview stream itself filters out in MP TvT. PPT threats, datalink
  markpoints and HSD lines stay visible — they're pilot-side intel, not cheating.
  No toggle, fully automatic based on `pilots_online`.
- **Per-theater runway generator** (`tools/gen_runway_data.py`) — pulls runway
  thresholds from ACMI recordings, dimensions and magnetic course from WDP's
  `Airports.xml`, and true heading from BMS ATC `.dat` files. Output is the
  pre-computed `RUNWAY_DATA_BY_THEATER` blob in `runway-data.js`. Following
  oakdesign's recommendation, runways no longer rely on hardcoded ILS heading
  guesses — they come from BMS itself.

### Changed
- **4.38 only** — Aegean, Iberia and Nordic theaters were 4.37 add-ons and are
  no longer shipped. The four supported theaters are now Korea KTO, Balkans,
  Israel and Hellas.

### Improved
- **TCP listen port** is now configurable from the Settings dialog (no more
  hardcoded 8000 — was a long-standing complaint from hoover).
- IPv6 link-local and ULA addresses are now accepted by the LAN-only middleware.
- The Qt window does a clean `QApplication.quit()` instead of `sys.exit(0)`,
  so FastAPI gets to shut down properly.
- URL hover states on the tray window now clear when the mouse leaves it.
- CI pipeline: correct spec filename, dist folder zipped properly for release.
- Build pipeline cleaned up — single canonical PyInstaller spec, dead `assets/`
  folder removed (~5 MB), `.gitignore` simplified.

### Internal
- Refactored duplicated theater-info and STPT-parsing logic into shared helpers.
- TRTT timeouts and a few magic numbers moved out of inline code into `app_info`.
- Mission-change hash now considers every steerpoint, not just the first and last.
- `_try_float` helper retired — replaced by proper try/except in the parsers.

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
