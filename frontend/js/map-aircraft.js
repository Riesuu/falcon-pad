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

// ── Bullseye (range rings) ─────────────────────────────────────
var _bullMarker = null;
var _bullLat = null, _bullLon = null;
var _bullRings = [];       // L.circle layers
var _bullRadials = [];     // L.polyline layers
var _bullLabels = [];      // L.marker label layers
var _NM_TO_M = 1852;
var _BULL_RINGS_NM = [20, 40, 60, 80, 100];
var _BULL_BEARINGS = [0, 45, 90, 135, 180, 225, 270, 315];
var _BULL_BRG_LBL  = ['360','045','090','135','180','225','270','315'];

function _clearBullseye() {
  _bullRings.forEach(function(c){try{map.removeLayer(c)}catch(e){}});
  _bullRadials.forEach(function(l){try{map.removeLayer(l)}catch(e){}});
  _bullLabels.forEach(function(l){try{map.removeLayer(l)}catch(e){}});
  if(_bullMarker){try{map.removeLayer(_bullMarker)}catch(e){}}
  _bullRings=[]; _bullRadials=[]; _bullLabels=[]; _bullMarker=null;
}

function _buildBullseye(lat, lon) {
  _clearBullseye();
  var col = C_BULL;
  var w = S_BULL * 0.12;  // stroke weight (default 8 → ~1px)

  // Center cross
  _bullMarker = L.circleMarker([lat, lon], {
    radius: 2, color: col, fillColor: col, fillOpacity: 1, weight: 1, interactive: false
  }).addTo(map);

  // Range rings every 20 NM
  _BULL_RINGS_NM.forEach(function(nm) {
    var ring = L.circle([lat, lon], {
      radius: nm * _NM_TO_M, color: col, weight: w, fillOpacity: 0, opacity: 0.45,
      interactive: false, dashArray: '8 6'
    }).addTo(map);
    _bullRings.push(ring);

    // NM label below center (south side of each ring)
    var labelLat = lat - (nm * _NM_TO_M) / 111320;
    var label = L.marker([labelLat, lon], {
      icon: L.divIcon({
        html: '<span style="font:700 9px Consolas,monospace;color:'+col+';opacity:.5">'+nm+'</span>',
        className: '', iconSize: [28, 12], iconAnchor: [14, 0]
      }), interactive: false
    }).addTo(map);
    _bullLabels.push(label);
  });

  // 8 radial lines + bearing labels at outer ring
  var maxM = _BULL_RINGS_NM[_BULL_RINGS_NM.length - 1] * _NM_TO_M;
  var cosLat = Math.cos(lat * Math.PI / 180);
  _BULL_BEARINGS.forEach(function(brg, i) {
    var rad = brg * Math.PI / 180;
    var dLat = (maxM * Math.cos(rad)) / 111320;
    var dLon = (maxM * Math.sin(rad)) / (111320 * cosLat);
    var endLat = lat + dLat, endLon = lon + dLon;

    var line = L.polyline([[lat, lon], [endLat, endLon]], {
      color: col, weight: w, opacity: 0.35, interactive: false, dashArray: '4 8'
    }).addTo(map);
    _bullRadials.push(line);

    // Bearing label just outside outer ring
    var lblM = maxM * 1.06;
    var lblLat = lat + (lblM * Math.cos(rad)) / 111320;
    var lblLon = lon + (lblM * Math.sin(rad)) / (111320 * cosLat);
    var lbl = L.marker([lblLat, lblLon], {
      icon: L.divIcon({
        html: '<span style="font:700 10px Consolas,monospace;color:'+col+';opacity:.5">'+_BULL_BRG_LBL[i]+'</span>',
        className: '', iconSize: [30, 14], iconAnchor: [15, 7]
      }), interactive: false
    }).addTo(map);
    _bullLabels.push(lbl);
  });
}

function updateBullseye(lat, lon) {
  if (lat == null || lon == null) return;
  var moved = (_bullLat !== lat || _bullLon !== lon);
  _bullLat = lat; _bullLon = lon;
  var bullOn = document.getElementById('bullBtn')?.classList.contains('active') !== false;
  if (bullOn && (moved || _bullRings.length === 0)) {
    _buildBullseye(lat, lon);
  }
  var el = document.getElementById('gps-bull');
  if (el && _lastAircraftData) {
    var brg = bearingTo(_lastAircraftData.lat, _lastAircraftData.lon, lat, lon);
    var nm  = haversineNm(_lastAircraftData.lat, _lastAircraftData.lon, lat, lon);
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
