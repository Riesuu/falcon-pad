#!/usr/bin/env python3
"""
Generate RUNWAY_DATA for map-airports.js from BMS data files.

Sources:
  - BMS ACMI recordings:  exact runway threshold lat/lon from BMS (best source)
  - Airport JSON files:   lat/lon fallback (ARP position)
  - ATC .dat files:       True Heading per runway
  - WDP Airports.xml:     runway Toda/Width, WDP Crs (magnetic fallback)

Position priority:
  1. ACMI runway thresholds (exact BMS positions, computed as pair midpoints)
  2. Airport JSON ARP (fallback, may be ~200-1000m from actual runway center)

Usage:
  python tools/gen_runway_data.py <theater_name>

  theater_name: korea | balkans | israel | hellas

The script expects BMS to be installed at the path configured below.
"""

import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

# ── Configuration ────────────────────────────────────────────────────────
BMS_ROOT = r"D:\Falcon BMS 4.38"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Theater definitions: paths to data sources + magnetic variation
# Magnetic variation: True = Magnetic + mag_var  (per OpenRadar / ATC verification)
THEATERS = {
    "korea": {
        "wdp_db": "Korea",
        "airport_json": os.path.join(PROJECT_ROOT, "data", "airports", "korea.json"),
        "atc_dir": os.path.join(BMS_ROOT, "Data", "TerrData", "ATC"),
        "mag_var": -7,  # OpenRadar: -7.5, ATC avg: -6.5
    },
    "balkans": {
        "wdp_db": "Balkans",
        "airport_json": os.path.join(PROJECT_ROOT, "data", "airports", "balkans.json"),
        "atc_dir": os.path.join(BMS_ROOT, "Data", "Add-On Balkans", "Terrdata", "ATC"),
        "mag_var": 2,   # ATC avg: +1.8
    },
    "israel": {
        "wdp_db": "Israel",
        "airport_json": os.path.join(PROJECT_ROOT, "data", "airports", "israel.json"),
        "atc_dir": os.path.join(BMS_ROOT, "Data", "Add-On Israel", "Terrdata", "ATC"),
        "mag_var": 5,   # ~5° East for Middle East region
    },
    "hellas": {
        "wdp_db": "Ikaros",
        "airport_json": os.path.join(PROJECT_ROOT, "data", "airports", "hto.json"),
        "atc_dir": os.path.join(BMS_ROOT, "Data", "Add-On Hellas", "TerrData", "ATC"),
        "mag_var": 3,   # ATC avg: +3.3
    },
}

FT_TO_M = 0.3048
ACMI_DIR = os.path.join(BMS_ROOT, "User", "Acmi")


# ── ACMI runway threshold parser ─────────────────────────────────────────

def parse_acmi_thresholds():
    """
    Parse all BMS ACMI recordings for runway threshold positions.
    Returns dict: { "ICAO": { "rwy_nr": (lat, lon), ... }, ... }
    and a dict of computed runway centers:
    { "ICAO": { norm_hdg: (center_lat, center_lon), ... }, ... }
    """
    thresholds = {}  # icao -> { thr_name: (lat, lon) }

    if not os.path.isdir(ACMI_DIR):
        return {}

    for fname in os.listdir(ACMI_DIR):
        if not fname.endswith(".acmi"):
            continue
        fpath = os.path.join(ACMI_DIR, fname)
        try:
            with zipfile.ZipFile(fpath) as z:
                zname = z.namelist()[0]
                with z.open(zname) as f:
                    for raw in f:
                        line = raw.decode("utf-8", errors="replace").strip()
                        if "Runway THR" not in line:
                            continue
                        m_name = re.search(
                            r"Name=(\w+)\s+Runway\s+THR\s+(\S+)", line
                        )
                        m_pos = re.search(
                            r"T=([\d.\-]+)\|([\d.\-]+)\|", line
                        )
                        if m_name and m_pos:
                            icao = m_name.group(1)
                            thr = m_name.group(2)
                            lon = float(m_pos.group(1))
                            lat = float(m_pos.group(2))
                            thresholds.setdefault(icao, {})[thr] = (lat, lon)
        except Exception:
            continue

    # Compute runway centers from threshold pairs
    centers = {}  # icao -> { qfu_low: (lat, lon) }
    for icao, thrs in thresholds.items():
        centers[icao] = {}
        paired = set()
        for thr_name, (lat1, lon1) in thrs.items():
            # Find reciprocal: "18L" <-> "36R", "09" <-> "27"
            nr_str = re.sub(r"[LRC]$", "", thr_name, flags=re.IGNORECASE)
            suffix = thr_name[len(nr_str):]
            try:
                nr = int(nr_str)
            except ValueError:
                continue
            recip_nr = (nr + 18) % 36 or 36
            # Swap L/R for reciprocal
            recip_suffix = {"L": "R", "R": "L", "C": "C"}.get(suffix, "")
            recip_name = f"{recip_nr:02d}{recip_suffix}"
            if recip_name in thrs and thr_name not in paired:
                lat2, lon2 = thrs[recip_name]
                c_lat = (lat1 + lat2) / 2
                c_lon = (lon1 + lon2) / 2
                low_qfu = min(nr, recip_nr)
                low_suffix = suffix if nr < recip_nr else recip_suffix
                key = f"{low_qfu:02d}{low_suffix}"
                centers[icao][key] = (c_lat, c_lon)
                paired.add(thr_name)
                paired.add(recip_name)

    return centers


# ── ATC True Heading parser ─────────────────────────────────────────────

def parse_atc_headings(atc_dir):
    """
    Parse all ATC .dat files in a directory.
    Returns dict: { "base_name_lower": { qfu: true_heading, ... }, ... }
    """
    result = {}
    if not os.path.isdir(atc_dir):
        return result

    for fname in os.listdir(atc_dir):
        if not fname.endswith(".dat"):
            continue
        base_name = fname[:-4].lower()
        fpath = os.path.join(atc_dir, fname)
        try:
            with open(fpath, "rb") as f:
                text = f.read().decode("utf-8", errors="replace")
        except OSError:
            continue

        headings = {}
        for m in re.finditer(
            r"# RUNWAY:\s*(\d+)\s+HDG:\d+\s+QFU:(\d+)", text
        ):
            qfu = int(m.group(2))
            pos = m.end()
            th_match = re.search(
                r"Runway axis \(True Heading\)\s*[\r\n]+(\d+)", text[pos:]
            )
            if th_match:
                true_hdg = int(th_match.group(1))
                headings[qfu] = true_hdg

        if headings:
            result[base_name] = headings

    return result


# ── Runway corner computation ────────────────────────────────────────────

def compute_corners(lat, lon, hdg_deg, length_ft, width_ft):
    """Compute 4 runway corners from center + heading + dimensions."""
    length_m = length_ft * FT_TO_M
    width_m = max(width_ft * FT_TO_M, 45)  # minimum 45m visual width
    hdg = math.radians(hdg_deg)

    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat))

    half_len = length_m / 2
    half_wid = width_m / 2

    dx_len = math.sin(hdg)
    dy_len = math.cos(hdg)
    dx_wid = math.cos(hdg)
    dy_wid = -math.sin(hdg)

    corners = []
    for sl, sw in [(-1, -1), (-1, 1), (1, 1), (1, -1)]:
        mx = sl * half_len * dx_len + sw * half_wid * dx_wid
        my = sl * half_len * dy_len + sw * half_wid * dy_wid
        c_lat = lat + my / m_per_deg_lat
        c_lon = lon + mx / m_per_deg_lon
        corners.append([round(c_lat, 6), round(c_lon, 6)])

    return corners


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2 or sys.argv[1].lower() not in THEATERS:
        print(f"Usage: {sys.argv[0]} <{'|'.join(THEATERS.keys())}>")
        sys.exit(1)

    theater_key = sys.argv[1].lower()
    th = THEATERS[theater_key]

    # Load airport positions from JSON (same coords as map markers)
    if not os.path.isfile(th["airport_json"]):
        print(f"ERROR: airport JSON not found at {th['airport_json']}", file=sys.stderr)
        sys.exit(1)
    with open(th["airport_json"]) as f:
        ap_json = json.load(f)
    ap_pos = {}  # icao -> (lat, lon, name_from_json)
    for ap in ap_json:
        icao = ap.get("icao", "").strip()
        if icao and icao != "----":
            ap_pos[icao] = (ap["lat"], ap["lon"], ap.get("name", ""))

    # Locate WDP Airports.xml (for runway dimensions and heading)
    wdp_base = os.path.join(
        BMS_ROOT, "Tools", "Weapon_Delivery_Planner_3.7.24.232",
        "Database", th["wdp_db"], "Airports.xml"
    )
    if not os.path.isfile(wdp_base):
        print(f"ERROR: WDP Airports.xml not found at {wdp_base}", file=sys.stderr)
        sys.exit(1)

    # Parse ACMI runway positions (exact BMS positions)
    acmi_centers = parse_acmi_thresholds()
    acmi_hits = 0
    print(f"// ACMI runway centers loaded for {len(acmi_centers)} airports", file=sys.stderr)

    # Parse ATC True Headings
    atc_hdg = parse_atc_headings(th["atc_dir"])
    print(f"// ATC True Headings loaded for {len(atc_hdg)} bases", file=sys.stderr)

    # Parse WDP for runway parameters
    tree = ET.parse(wdp_base)
    root = tree.getroot()

    entries = []
    seen_keys = set()
    atc_used = 0
    atc_miss = 0

    for airport in root.findall("Airport"):
        wdp_name = airport.findtext("Name", "").strip()
        icao = airport.findtext("ICAO", "----").strip()

        # Only process airports we have positions for (from JSON)
        if icao not in ap_pos:
            continue

        lat, lon, json_name = ap_pos[icao]
        display_name = json_name or wdp_name

        # Try to find ATC True Heading for this airport
        atc_key = wdp_name.lower()
        atc_entry = atc_hdg.get(atc_key, {})

        # Collect all valid runways for this airport (low-heading only)
        ap_rwys = []
        for i in range(4):
            rwy_nr = airport.findtext(f"Rwy_{i}_Nr", "0").strip()
            crs = int(airport.findtext(f"Rwy_{i}_Crs", "0"))
            toda = float(airport.findtext(f"Rwy_{i}_Toda", "0"))
            width = float(airport.findtext(f"Rwy_{i}_Width", "0"))

            if not rwy_nr or rwy_nr == "0" or toda == 0:
                continue
            if crs >= 180:
                continue

            dedup_key = f"{icao}_{rwy_nr}_{crs}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            # Resolve heading
            qfu_str = re.sub(r"[LRC]$", "", rwy_nr, flags=re.IGNORECASE)
            qfu = int(qfu_str) if qfu_str.isdigit() else 0
            if qfu in atc_entry:
                hdg = atc_entry[qfu]
                atc_used += 1
            else:
                hdg = (crs + th.get("mag_var", 0)) % 360
                atc_miss += 1

            ap_rwys.append({
                "rwy": i, "nr": rwy_nr, "hdg": hdg,
                "toda": toda, "width": width,
            })

        # Group parallel runways (same heading) and offset perpendicular
        PARALLEL_OFFSET_M = 250  # perpendicular offset between parallel rwys
        by_hdg = {}
        for r in ap_rwys:
            by_hdg.setdefault(r["hdg"], []).append(r)

        # Check ACMI for exact runway center positions
        acmi_ap = acmi_centers.get(icao, {})

        for hdg_val, group in by_hdg.items():
            n = len(group)
            for idx, r in enumerate(group):
                # Try ACMI position: exact match, then without L/R/C suffix
                acmi_pos = acmi_ap.get(r["nr"])
                if not acmi_pos:
                    bare = re.sub(r"[LRC]$", "", r["nr"], flags=re.IGNORECASE)
                    if bare.isdigit():
                        acmi_pos = acmi_ap.get(f"{int(bare):02d}")

                if acmi_pos:
                    rwy_lat, rwy_lon = acmi_pos
                    acmi_hits += 1
                else:
                    rwy_lat, rwy_lon = lat, lon
                    if n > 1:
                        # Offset perpendicular to runway heading
                        perp = math.radians(r["hdg"] + 90)
                        offset_m = (idx - (n - 1) / 2) * PARALLEL_OFFSET_M
                        rwy_lat += (offset_m * math.cos(perp)) / 111320.0
                        rwy_lon += (offset_m * math.sin(perp)) / (
                            111320.0 * math.cos(math.radians(lat))
                        )

                corners = compute_corners(rwy_lat, rwy_lon, r["hdg"],
                                          r["toda"], r["width"])
                entries.append({
                    "icao": icao,
                    "name": display_name,
                    "rwy": r["rwy"],
                    "hdg": r["hdg"],
                    "len": round(r["toda"] * FT_TO_M),
                    "c": corners,
                })

    print(f"// Positions: {acmi_hits} from ACMI (exact), {len(entries)-acmi_hits} from JSON (ARP fallback)",
          file=sys.stderr)
    print(f"// Headings: {atc_used} from ATC (True), {atc_miss} from WDP Crs+magvar (fallback)",
          file=sys.stderr)

    # Output JavaScript
    print(f"// Auto-generated from BMS 4.38 data ({theater_key})")
    print(f"// {len(entries)} runways — positions from airport JSON, headings from ATC/WDP")
    print(f"var RUNWAY_DATA_{theater_key.upper()} = [")
    for e in entries:
        c = e["c"]
        print(f"  {{icao:'{e['icao']}',name:'{e['name']}',rwy:{e['rwy']},"
              f"hdg:{e['hdg']},len:{e['len']},"
              f"c:[[{c[0][0]},{c[0][1]}],[{c[1][0]},{c[1][1]}],"
              f"[{c[2][0]},{c[2][1]}],[{c[3][0]},{c[3][1]}]]}},")
    print("];")


if __name__ == "__main__":
    main()
