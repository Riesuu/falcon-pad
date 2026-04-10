// Falcon-Pad — map-airports.js
// Airport loading, popups, runway data & rendering, calibration
// Copyright (C) 2024 Riesu — GNU GPL v3

var apData = [];
var _apNameVisible = false;
var apNameMarkers = [];
var apLabelMarkers= [];
var apIconMarkers = [];

function buildApPopup(ap) {
  const isEnemy = ap.side === 'red';
  const col  = isEnemy ? C_AP_RED : C_AP_BLUE;
  const parts = [`<span class="ap-l1-icao" style="color:${col}">${_esc(ap.icao)}</span>`];
  if (ap.tacan) { parts.push(`<span class="ap-l1-dot">·</span>`); parts.push(`<span class="ap-l1-tacan">${_esc(ap.tacan)}</span>`); }
  if (ap.freq)  { parts.push(`<span class="ap-l1-dot">·</span>`); parts.push(`<span class="ap-l1-freq">${_esc(ap.freq)}</span>`); }
  const line1 = `<div class="ap-l1">${parts.join('')}</div>`;
  let line2 = '';
  if (ap.ils && ap.ils.length) {
    const chips = ap.ils.map(i =>
      `<div class="ap-ils-chip">
        <span class="ap-ils-rwy">RWY ${_esc(i.rwy)}</span>
        <span class="ap-ils-freq">${_esc(i.freq)}</span>
        <span class="ap-ils-crs">${_esc(i.crs)}°</span>
      </div>`
    ).join('');
    line2 = `<div class="ap-l2">${chips}</div>`;
  }
  return `<div class="ap-popup">${line1}${line2}</div>`;
}

async function loadAirports() {
  [...apIconMarkers, ...apLabelMarkers].forEach(m => { try { map.removeLayer(m); } catch(e) {} });
  apIconMarkers.length = 0; apLabelMarkers.length = 0;
  airportMarkers.length = 0; apNameMarkers.length = 0; apData = [];
  try {
    const aps = await (await fetch('/api/airports')).json();
    apData = aps;
    const apNameOn = _apNameVisible;
    aps.forEach(ap => {
      const isEnemy = ap.side === 'red';
      const col = isEnemy ? C_AP_RED : C_AP_BLUE;
      const sz = 13;
      const sym = `<svg width="${sz}" height="${sz}" viewBox="0 0 13 13" style="cursor:pointer">
        <polygon points="6.5,1 12,6.5 6.5,12 1,6.5" fill="${col}" stroke="rgba(0,0,0,.7)" stroke-width="1.5"/>
      </svg>`;
      const mIcon = L.marker([ap.lat, ap.lon], {
        icon: L.divIcon({html: sym, className:'', iconSize:[sz,sz], iconAnchor:[sz/2,sz/2]}),
        zIndexOffset: 10
      }).addTo(map);
      mIcon.bindPopup(buildApPopup(ap), {className:'', maxWidth:320, closeButton:true, offset:L.point(0,-6)});
      apIconMarkers.push(mIcon);
      const apIcao = ap.icao.startsWith('KP-') || ap.icao.length > 5 ? ap.name : ap.icao;
      const labelHtml = `<div style="pointer-events:none;line-height:1.2">
        <div style="font-family:'Consolas','Courier New',monospace;font-size:11px;font-weight:700;
          color:${col};letter-spacing:.8px;text-shadow:0 1px 4px #000,0 0 8px rgba(0,0,0,.9);
          white-space:nowrap">${apIcao}</div>
      </div>`;
      const mLabel = L.marker([ap.lat, ap.lon], {
        icon: L.divIcon({html: labelHtml, className:'', iconSize:[160,26], iconAnchor:[-8,6]}),
        zIndexOffset: -100, interactive: true
      });
      if(apNameOn) mLabel.addTo(map);
      mLabel.on('click', e => {
        if(rulerActive) { L.DomEvent.stopPropagation(e); if(!rStart){rStart=L.latLng(ap.lat,ap.lon);rDot=L.circleMarker(rStart,{radius:4,color:'#fff',fillColor:activeColor,fillOpacity:1,weight:2}).addTo(map);}else{clearRuler();} }
        else { mIcon.openPopup(); }
      });
      mIcon.on('click', e => {
        if(rulerActive) { L.DomEvent.stopPropagation(e); if(!rStart){rStart=L.latLng(ap.lat,ap.lon);rDot=L.circleMarker(rStart,{radius:4,color:'#fff',fillColor:activeColor,fillOpacity:1,weight:2}).addTo(map);}else{clearRuler();} }
        else { mIcon.openPopup(); }
      });
      apLabelMarkers.push(mLabel);
      airportMarkers.push(mIcon, mLabel);
      apNameMarkers.push(mLabel);
    });
    if(!document.getElementById('airportBtn')?.classList.contains('active')) {
      apIconMarkers.forEach(m => { try { map.removeLayer(m); } catch(e) {} });
    }
    renderRunways();
  } catch(e) { console.warn('[airports] load failed:', e); }
}

document.getElementById('runwayBtn')?.addEventListener('click',function(){
  runwaysVisible=!runwaysVisible;
  this.classList.toggle('active',runwaysVisible);
  runwayLayers.forEach(l=>{try{runwaysVisible?l.addTo(map):map.removeLayer(l);}catch(e){}});
  saveUiPref({runways_visible:runwaysVisible});
});

document.getElementById('apNameBtn')?.addEventListener('click',function(){
  _apNameVisible=!_apNameVisible;
  this.classList.toggle('active',_apNameVisible);
  apLabelMarkers.forEach(m=>{try{_apNameVisible?m.addTo(map):map.removeLayer(m);}catch(e){}});
  saveUiPref({ap_name_visible:_apNameVisible});
});

// ── Runway data (loaded from runway-data.js) ──────────────────
// RUNWAY_DATA_BY_THEATER is defined in runway-data.js (auto-generated from BMS WDP + ATC data)
function _getRunwayData() {
  if (typeof RUNWAY_DATA_BY_THEATER === 'undefined' || !_currentTheater) return [];
  const key = _currentTheater.toLowerCase();
  if (RUNWAY_DATA_BY_THEATER[key]) return RUNWAY_DATA_BY_THEATER[key];
  for (const k of Object.keys(RUNWAY_DATA_BY_THEATER)) {
    if (key.includes(k) || k.includes(key)) return RUNWAY_DATA_BY_THEATER[k];
  }
  return [];
}

// ── Runway rendering ──────────────────────────────────────────
var runwayLayers = [], runwaysVisible = true;

function _computeRwyCorners(lat, lon, hdg_deg, len_m, wid_m) {
  const rad = hdg_deg * Math.PI / 180;
  const cosLat = Math.cos(lat * Math.PI / 180);
  const mLat = 1 / 111320;
  const mLon = 1 / (111320 * cosLat);
  const hl = len_m / 2, hw = wid_m / 2;
  const aLat = Math.cos(rad) * mLat, aLon = Math.sin(rad) * mLon;
  const pLat = -Math.sin(rad) * mLat, pLon = Math.cos(rad) * mLon;
  return [
    [lat - aLat*hl + pLat*hw, lon - aLon*hl + pLon*hw],
    [lat - aLat*hl - pLat*hw, lon - aLon*hl - pLon*hw],
    [lat + aLat*hl - pLat*hw, lon + aLon*hl - pLon*hw],
    [lat + aLat*hl + pLat*hw, lon + aLon*hl + pLon*hw],
  ];
}

function renderRunways() {
  runwayLayers.forEach(l => { try { map.removeLayer(l); } catch(e){} });
  runwayLayers = [];
  function _drawRwyPoly(corners, col, fillCol) {
    const poly = L.polygon(corners, {color:col,fillColor:fillCol,fillOpacity:1,weight:2,interactive:false});
    if (runwaysVisible) poly.addTo(map);
    runwayLayers.push(poly);
    const midA = [(corners[0][0]+corners[1][0])/2, (corners[0][1]+corners[1][1])/2];
    const midB = [(corners[2][0]+corners[3][0])/2, (corners[2][1]+corners[3][1])/2];
    const axis = L.polyline([midA, midB], {color:col,weight:1.5,opacity:0.6,dashArray:'8 5',interactive:false});
    if (runwaysVisible) axis.addTo(map);
    runwayLayers.push(axis);
  }
  const rwyData = _getRunwayData();
  const rwyIcaos = new Set(rwyData.map(r => r.icao));
  rwyData.forEach(r => {
    const apMatch = (apData || []).find(a => a.icao === r.icao);
    const isEnemy = apMatch ? apMatch.side === 'red' : false;
    const col     = isEnemy ? 'rgba(248,113,113,.75)' : 'rgba(148,185,220,.8)';
    const fillCol = isEnemy ? 'rgba(220,60,60,.18)'   : 'rgba(120,160,200,.15)';
    _drawRwyPoly(r.c, col, fillCol);
  });
  // Fallback: airports not in runway data — derive from ILS heading
  const seenKeys = new Set();
  (apData || []).forEach(ap => {
    if (rwyIcaos.has(ap.icao) || !ap.ils || ap.ils.length === 0) return;
    const isEnemy = ap.side === 'red';
    const col     = isEnemy ? 'rgba(248,113,113,.75)' : 'rgba(148,185,220,.8)';
    const fillCol = isEnemy ? 'rgba(220,60,60,.18)'   : 'rgba(120,160,200,.15)';
    ap.ils.forEach(ils => {
      const crs = parseFloat(ils.crs);
      if (isNaN(crs)) return;
      const normHdg = crs >= 180 ? crs - 180 : crs;
      const key = `${ap.icao}:${normHdg.toFixed(0)}`;
      if (seenKeys.has(key)) return;
      seenKeys.add(key);
      _drawRwyPoly(_computeRwyCorners(ap.lat, ap.lon, crs, 2500, 45), col, fillCol);
    });
  });
}
renderRunways();
