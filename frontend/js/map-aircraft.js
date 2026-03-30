// Falcon-Pad — map-aircraft.js
// Aircraft icon, follow mode, compass (North Up / Track Up), bullseye
// Copyright (C) 2024 Riesu — GNU GPL v3

function makeAircraftIcon(hdg,alt,kias,realHdg){
  const displayHdg = realHdg != null ? realHdg : hdg;
  const hdgStr=String(Math.round(displayHdg)).padStart(3,'0')+'°';
  const altFL=alt!=null?'FL'+String(Math.round(Math.abs(alt)/100)).padStart(3,'0'):'';
  const spdStr=kias!=null&&kias>5?String(Math.round(kias))+'kt':'';
  const sz=48,cx=sz/2,sq=4,lineLen=20;
  const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="${sz}" height="${sz}" viewBox="0 0 ${sz} ${sz}">
    <rect x="${cx-sq}" y="${cx-sq}" width="${sq*2}" height="${sq*2}"
      fill="#5eead4" stroke="#5eead4" stroke-width="1"/>
    <line x1="${cx}" y1="${cx}" x2="${cx}" y2="${cx-lineLen}"
      stroke="#5eead4" stroke-width="1.5" transform="rotate(${hdg},${cx},${cx})"/>
  </svg>`;
  const label=`<div style="
    position:absolute;left:${sz-4}px;top:-4px;
    white-space:nowrap;pointer-events:none;
    font-family:'Consolas','Courier New',monospace;font-size:13px;font-weight:700;
    letter-spacing:.8px;line-height:1.5;color:#5eead4;
    text-shadow:0 0 6px rgba(94,234,212,.4),0 1px 3px #000;
  "><div>${hdgStr} ${spdStr}</div>${altFL?`<div>${altFL}</div>`:''}</div>`;
  return L.divIcon({html:`<div style="position:relative;width:${sz}px;height:${sz}px">${svg}${label}</div>`,className:'',iconSize:[sz,sz],iconAnchor:[cx,cx]});
}

var followAircraft = true;
var _trackUp = false;

// ── Compass: North Up / Track Up ───────────────────────────────
const _compassBtn = document.getElementById('compassBtn');
_compassBtn.classList.add('north-up');

_compassBtn.addEventListener('click', function(e){
  e.stopPropagation();
  _trackUp = !_trackUp;
  if(_trackUp){
    this.classList.remove('north-up');
    this.classList.add('track-up');
    this.title = 'Track Up (click for North Up)';
    if(!followAircraft){
      followAircraft = true;
      document.getElementById('followBtn').classList.add('active');
    }
  } else {
    this.classList.remove('track-up');
    this.classList.add('north-up');
    this.title = 'North Up (click for Track Up)';
    if(typeof map.setBearing==='function') map.setBearing(0);
  }
});

document.getElementById('followBtn')?.addEventListener('click', function() {
  followAircraft = !followAircraft;
  this.classList.toggle('active', followAircraft);
  this.title = followAircraft ? "Center on aircraft (active)" : "Center on aircraft (off)";
  if (followAircraft && aircraftMarker) map.setView(aircraftMarker.getLatLng(), map.getZoom());
});
map.on('dragstart', () => {
  if (followAircraft) {
    followAircraft = false;
    document.getElementById('followBtn').classList.remove('active');
    document.getElementById('followBtn').title = "Center on aircraft (off)";
  }
  if (_trackUp) {
    _trackUp = false;
    if(typeof map.setBearing==='function') map.setBearing(0);
    _compassBtn.classList.remove('track-up');
    _compassBtn.classList.add('north-up');
    _compassBtn.title = 'North Up (click for Track Up)';
  }
});

// ── Bullseye ───────────────────────────────────────────────────
var _bullMarker = null;
var _bullLat = null, _bullLon = null;

function _bullIcon() {
  const col = C_BULL;
  const sz = Math.round(S_BULL * 3.5);
  return L.divIcon({
    html: `<svg width="${sz}" height="${sz}" viewBox="0 0 28 28" style="overflow:visible">
      <circle cx="14" cy="14" r="11" fill="none" stroke="${col}" stroke-width="1.8" opacity=".85"/>
      <circle cx="14" cy="14" r="6"  fill="none" stroke="${col}" stroke-width="1.4" opacity=".7"/>
      <circle cx="14" cy="14" r="2"  fill="${col}" opacity=".9"/>
      <line x1="14" y1="0"  x2="14" y2="7"  stroke="${col}" stroke-width="1.4" opacity=".7"/>
      <line x1="14" y1="21" x2="14" y2="28" stroke="${col}" stroke-width="1.4" opacity=".7"/>
      <line x1="0"  y1="14" x2="7"  y2="14" stroke="${col}" stroke-width="1.4" opacity=".7"/>
      <line x1="21" y1="14" x2="28" y2="14" stroke="${col}" stroke-width="1.4" opacity=".7"/>
      <text x="14" y="-4" text-anchor="middle"
        style="font-family:'Consolas','Courier New',monospace;font-size:9px;fill:${col};letter-spacing:1px;font-weight:700">BULL</text>
    </svg>`,
    className:'', iconSize:[sz,sz], iconAnchor:[sz/2,sz/2]
  });
}

function updateBullseye(lat, lon) {
  if (lat == null || lon == null) return;
  _bullLat = lat; _bullLon = lon;
  var bullOn = document.getElementById('bullBtn')?.classList.contains('active') !== false;
  if (_bullMarker) { _bullMarker.setLatLng([lat, lon]); _bullMarker.setIcon(_bullIcon()); }
  else if (bullOn) { _bullMarker = L.marker([lat, lon], { icon: _bullIcon(), zIndexOffset: 500, interactive: false }).addTo(map); }
  const el = document.getElementById('gps-bull');
  if (el && _lastAircraftData) {
    const brg = bearingTo(_lastAircraftData.lat, _lastAircraftData.lon, lat, lon);
    const nm  = haversineNm(_lastAircraftData.lat, _lastAircraftData.lon, lat, lon);
    el.textContent = String(Math.round(brg)).padStart(3,'0') + '° / ' + nm.toFixed(1) + ' NM';
  }
}

function updateAircraft(d){
  window._hasAircraftPos = true;
  if(!d||d.lat===undefined||d.lon===undefined)return;
  if(d.lat===0&&d.lon===0)return;
  const hdg = d.heading||0;
  const iconHdg = _trackUp ? 0 : hdg;
  const icon=makeAircraftIcon(iconHdg,d.altitude,d.kias,hdg);
  if(aircraftMarker){aircraftMarker.setLatLng([d.lat,d.lon]);aircraftMarker.setIcon(icon);}
  else{aircraftMarker=L.marker([d.lat,d.lon],{icon,zIndexOffset:1000}).addTo(map);}
  if(followAircraft){
    const now=Date.now();
    if(!updateAircraft._lastPan||now-updateAircraft._lastPan>500){
      map.panTo([d.lat,d.lon],{animate:true,duration:0.4});
      updateAircraft._lastPan=now;
    }
  }
  if(_trackUp && typeof map.setBearing==='function') map.setBearing(hdg);
  if (d.bull_lat != null && d.bull_lon != null) updateBullseye(d.bull_lat, d.bull_lon);
}
