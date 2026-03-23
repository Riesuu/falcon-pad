// Falcon-Pad — map.js
// Leaflet map, tiles, aircraft rendering, compass, bullseye,
// ruler/arrow tools, annotations, mission overlay, airports, 
// IDM markpoints, ACMI contacts
// Copyright (C) 2024 Riesu — GNU GPL v3
// Loaded BEFORE panels.js and websocket.js


// ── Shared: toast notification ──────────────────────────────
function showToast(msg, duration) {
  duration = duration || 3000;
  var n = document.createElement('div');
  n.className = 'bms-toast';
  n.textContent = msg;
  document.body.appendChild(n);
  setTimeout(function(){ n.remove(); }, duration);
}

// ── Shared: cross-file state variables ──────────────────────
// These are declared here (map.js loads first) and accessed from panels.js + websocket.js
var _bmsTimeSec = null;   // BMS seconds since midnight (from WS)
var _bmsTimeTs  = 0;      // JS timestamp of last BMS time receipt
var _lastAircraftData = null;  // last ownship data (for GPS panel)

// ── Shared: GPS/nav utility functions (used by map.js + panels.js) ──────
// ── GPS Panel data ───────────────────────────────────────────────
var _activeSteerIdx = 0;

function fmtLL(v, isLon) {
  if (v === undefined || v === null) return '—';
  const dir = isLon ? (v >= 0 ? 'E' : 'W') : (v >= 0 ? 'N' : 'S');
  const abs = Math.abs(v);
  const deg = Math.floor(abs);
  const min = ((abs - deg) * 60).toFixed(3);
  return `${dir} ${String(deg).padStart(isLon?3:2,'0')}° ${min}'`;
}

function haversineNm(lat1, lon1, lat2, lon2) {
  const R = 3440.065; // NM
  const φ1 = lat1*Math.PI/180, φ2 = lat2*Math.PI/180;
  const dφ = (lat2-lat1)*Math.PI/180;
  const dλ = (lon2-lon1)*Math.PI/180;
  const a = Math.sin(dφ/2)**2 + Math.cos(φ1)*Math.cos(φ2)*Math.sin(dλ/2)**2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
}

function bearingTo(lat1, lon1, lat2, lon2) {
  const φ1 = lat1*Math.PI/180, φ2 = lat2*Math.PI/180;
  const dλ = (lon2-lon1)*Math.PI/180;
  const y = Math.sin(dλ)*Math.cos(φ2);
  const x = Math.cos(φ1)*Math.sin(φ2) - Math.sin(φ1)*Math.cos(φ2)*Math.cos(dλ);
  return ((Math.atan2(y,x)*180/Math.PI) + 360) % 360;
}


const map = L.map('map',{preferCanvas:true,zoomControl:true,rotate:true,rotateControl:false,bearing:0,touchRotate:false,shiftKeyRotate:false,compassBearing:false}).setView([37.5,127.5],7);
// Disable any user-triggered rotation (only programmatic setBearing allowed)
if(map.touchRotate) map.touchRotate.disable();
if(map.compassBearing) map.compassBearing.disable();
if(map.shiftKeyRotate) map.shiftKeyRotate.disable();
const layers = {
  osm:       L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:''}),
  osmfr:     L.tileLayer('https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png',{maxZoom:20,subdomains:'abc',attribution:''}),
  dark:      L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{maxZoom:20,subdomains:'abcd',attribution:''}),
  satellite: L.tileLayer('https://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',{maxZoom:20,subdomains:['mt0','mt1','mt2','mt3'],attribution:''}),
  terrain:   L.tileLayer('https://{s}.google.com/vt/lyrs=p&x={x}&y={y}&z={z}',{maxZoom:20,subdomains:['mt0','mt1','mt2','mt3'],attribution:''})
};
let _activeTileKey = 'dark';
function switchLayer(key) {
  Object.values(layers).forEach(l => { try { map.removeLayer(l); } catch(e){} });
  if(layers[key]) layers[key].addTo(map);
  _activeTileKey = key;
  // Sync radio buttons
  document.querySelectorAll('input[name="layer"]').forEach(r => r.checked = (r.value === key));
}
// Démarrer sur Dark, fallback OSM si inaccessible
layers.dark.addTo(map);
let _darkFallbackDone = false;
layers.dark.on('tileerror', function(){
  if(_darkFallbackDone) return;
  _darkFallbackDone = true;
  console.warn('Dark tiles indisponibles, fallback OSM');
  map.removeLayer(layers.dark);
  layers.osm.addTo(map);
  _activeTileKey = 'osm';
  document.getElementById('lDark').checked = false;
  document.getElementById('lOsm').checked  = true;
});
map.attributionControl.setPrefix('');

// DMZ — 38ème parallèle Corée (coordonnées corrigées)
const _dmzLine = L.polyline([
  [38.31,125.10],[38.27,125.40],[38.25,125.68],[38.27,126.00],
  [38.25,126.35],[38.18,126.65],[38.12,126.95],[38.05,127.18],
  [38.00,127.45],[37.97,127.75],[38.00,128.02],[38.10,128.30],
  [38.20,128.55],[38.35,128.75],[38.45,129.00],[38.55,129.20]],
  {color:'#dc2626',weight:2,opacity:.7,dashArray:'10 5'}).addTo(map);
document.getElementById('chkDMZ')?.addEventListener('change',function(){
  this.checked ? _dmzLine.addTo(map) : map.removeLayer(_dmzLine);
});

const COLORS=['#ef4444','#f97316','#f59e0b','#eab308','#10b981','#4ade80','#3b82f6','#8b5cf6','#ec4899','#ffffff','#94a3b8','#1e293b'];
let activeColor='#3b82f6';

// ── Couleurs & tailles configurables (chargées depuis ui_prefs) ──
let C_DRAW  = '#3b82f6'; let S_DRAW  = 2;    // dessin/règle/flèches
let C_STPT  = '#e2e8f0'; let S_STPT  = 5;    // steerpoints
let C_FPLAN = '#f59e0b'; let S_FPLAN = 4;    // flight plan
let C_PPT   = '#ef4444'; let S_PPT   = 1.2;  // PPT cercles
let C_BULL  = '#fbbf24'; let S_BULL  = 8;    // bullseye
let C_MK    = '#fbbf24'; let S_MK    = 2.5;  // MK markpoints

function applyUiPrefs(p) {
  if(p.color_draw)  C_DRAW  = p.color_draw;
  if(p.size_draw)   S_DRAW  = p.size_draw;
  if(p.color_stpt)  C_STPT  = p.color_stpt;
  if(p.size_stpt)   S_STPT  = p.size_stpt;
  if(p.color_fplan) C_FPLAN = p.color_fplan;
  if(p.size_fplan)  S_FPLAN = p.size_fplan;
  if(p.color_ppt)   C_PPT   = p.color_ppt;
  if(p.size_ppt)    S_PPT   = p.size_ppt;
  if(p.color_bull)  C_BULL  = p.color_bull;
  if(p.size_bull)   S_BULL  = p.size_bull;
  if(p.color_mk)    C_MK    = p.color_mk;
  if(p.size_mk)     S_MK    = p.size_mk;
  if(p.active_color && COLORS.includes(p.active_color)) {
    activeColor = p.active_color;
    C_DRAW = p.active_color;
  }
}

// ── UI Prefs persistence ──────────────────────────────────────
async function saveUiPref(patch){
  try{
    const r=await fetch('/api/ui-prefs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(patch)});
    if(!r.ok) console.warn('[ui-prefs] save failed:',r.status,await r.text());
  }catch(e){ console.error('[ui-prefs] save error:',e); }
}

async function loadUiPrefs(){
  console.log('[ui-prefs] chargement...');
  try{
    const resp=await fetch('/api/ui-prefs');
    if(!resp.ok){ console.error('[ui-prefs] GET failed:',resp.status); return; }
    const p=await resp.json();
    console.log('[ui-prefs] reçu:',p);
    applyUiPrefs(p);
    if(p.active_color&&COLORS.includes(p.active_color)){
      activeColor=p.active_color;
      document.querySelectorAll('.c-swatch').forEach(s=>s.classList.toggle('sel',s.dataset.color===activeColor));
    }
    if(p.layer){
      switchLayer(p.layer);
      const r=document.querySelector(`input[name="layer"][value="${p.layer}"]`);
      if(r) r.checked=true;
    }
    const chkPPT=document.getElementById('chkPPT');
    const chkAP=document.getElementById('chkAirports');
    const chkRW=document.getElementById('chkRunways');
    const chkApN=document.getElementById('chkApName');
    if(chkPPT&&p.ppt_visible===false){chkPPT.checked=false;pptCircles.forEach(c=>{try{map.removeLayer(c)}catch(e){}});document.getElementById('pptBtn').classList.remove('active');}
    if(chkAP&&p.airports_visible===false){chkAP.checked=false;airportMarkers.forEach(m=>{try{map.removeLayer(m)}catch(e){}});document.getElementById('airportBtn').classList.remove('active');}
    if(chkRW&&p.runways_visible===false){chkRW.checked=false;runwayLayers.forEach(l=>{try{map.removeLayer(l)}catch(e){}});}
    if(chkApN&&p.ap_name_visible===true){chkApN.checked=true;apNameMarkers.forEach(m=>{try{m.addTo(map)}catch(e){}});}
    console.log('[ui-prefs] restauration terminée');
  }catch(e){ console.error('[ui-prefs] erreur:',e); }
}
let rulerActive=false,arrowActive=false;
let drawMarkers=[],missionMarkers=[],aircraftMarker=null;
var pptCircles=[],pptLabelMarkers=[],pptLabelsVisible=true,airportMarkers=[];

function makeAircraftIcon(hdg,alt,kias,realHdg){
  const displayHdg = realHdg != null ? realHdg : hdg;
  const hdgStr=String(Math.round(displayHdg)).padStart(3,'0')+'°';
  const altFL=alt!=null?'FL'+String(Math.round(Math.abs(alt)/100)).padStart(3,'0'):'';
  const spdStr=kias!=null&&kias>5?String(Math.round(kias))+'kt':'';
  const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="34" height="34" viewBox="0 0 34 34">
    <g transform="rotate(${hdg},17,17)">
      <polygon points="17,3 25,30 17,24 9,30"
        fill="#3b82f6" fill-opacity="0.95"
        stroke="#0c1a2e" stroke-width="1.5" stroke-linejoin="round"/>
      <line x1="17" y1="24" x2="17" y2="30" stroke="#93c5fd" stroke-width="1" opacity=".5"/>
    </g>
  </svg>`;
  const parts=[
    `<span style="color:#60a5fa;font-weight:700">${hdgStr}</span>`,
    altFL?`<span style="color:#bfdbfe">${altFL}</span>`:'',
    spdStr?`<span style="color:#93c5fd">${spdStr}</span>`:'',
  ].filter(Boolean).join('<span style="color:#1e3a5f;margin:0 3px">·</span>');
  const label=`<div style="
    position:absolute;left:50%;transform:translateX(-50%);top:36px;
    white-space:nowrap;background:rgba(3,8,20,.92);
    border:1px solid rgba(59,130,246,.5);border-radius:2px;
    padding:2px 8px;font-family:system-ui,sans-serif;font-weight:700;
    font-size:13px;pointer-events:none;letter-spacing:.5px;
    box-shadow:0 2px 10px rgba(0,0,0,.7),0 0 12px rgba(59,130,246,.12);
  ">${parts}</div>`;
  return L.divIcon({html:`<div style="position:relative;width:34px;height:34px">${svg}${label}</div>`,className:'',iconSize:[34,34],iconAnchor:[17,17]});
}


var followAircraft = true;
var _trackUp = false;

// ── Compass: North Up / Track Up ────────────────────────────────
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
  if (followAircraft && aircraftMarker) {
    map.setView(aircraftMarker.getLatLng(), map.getZoom());
  }
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

// ── Bullseye ─────────────────────────────────────────────────────
var _bullMarker = null;
var _bullLat = null, _bullLon = null;

function _bullIcon() {
  const col = C_BULL;
  const sz = Math.round(S_BULL * 3.5); // 8→28, 4→14, 16→56
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
  if (_bullMarker) {
    _bullMarker.setLatLng([lat, lon]);
  } else {
    _bullMarker = L.marker([lat, lon], {
      icon: _bullIcon(), zIndexOffset: 500, interactive: false
    }).addTo(map);
  }
  // Mettre à jour le champ BULL dans le panel GPS
  const el = document.getElementById('gps-bull');
  if (el && _lastAircraftData) {
    const brg = bearingTo(_lastAircraftData.lat, _lastAircraftData.lon, lat, lon);
    const nm  = haversineNm(_lastAircraftData.lat, _lastAircraftData.lon, lat, lon);
    el.textContent = String(Math.round(brg)).padStart(3,'0') + '° / ' + nm.toFixed(1) + ' NM';
  }
}

function updateAircraft(d){
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
  // Track Up: rotate map bearing
  if(_trackUp && typeof map.setBearing==='function') map.setBearing(hdg);
  // Bullseye
  if (d.bull_lat != null && d.bull_lon != null) {
    updateBullseye(d.bull_lat, d.bull_lon);
  }
}

let rStart=null,rLine=null,rLabel=null,rDot=null;

function updateRuler(to){
  if(!rStart)return;
  if(rLine)map.removeLayer(rLine);
  if(rLabel)map.removeLayer(rLabel);
  rLine=L.polyline([rStart,to],{color:activeColor,weight:S_DRAW,opacity:.8,dashArray:'8 4'}).addTo(map);
  const dist=map.distance(rStart,to);
  const nm=dist/1852,km=dist/1000;
  const φ1=rStart.lat*Math.PI/180,φ2=to.lat*Math.PI/180;
  const dλ=(to.lng-rStart.lng)*Math.PI/180;
  const y=Math.sin(dλ)*Math.cos(φ2);
  const x=Math.cos(φ1)*Math.sin(φ2)-Math.sin(φ1)*Math.cos(φ2)*Math.cos(dλ);
  const hdg=((Math.atan2(y,x)*180/Math.PI)+360)%360;
  const mid=L.latLng((rStart.lat+to.lat)/2,(rStart.lng+to.lng)/2);
  rLabel=L.marker(mid,{icon:L.divIcon({
    className:'',iconSize:[220,26],iconAnchor:[110,13],
    html:`<div class="ruler-label">
      <div class="ruler-line">${String(Math.round(hdg)).padStart(3,'0')}° / ${String(Math.round((hdg+180)%360)).padStart(3,'0')}° &nbsp;&#9658;&nbsp; <span style="color:${activeColor}">${nm.toFixed(1)} NM</span></div>
    </div>`
  })}).addTo(map);
}
function clearRuler(){[rLine,rLabel,rDot].forEach(l=>{if(l)map.removeLayer(l)});rLine=rLabel=rDot=rStart=null;}
document.getElementById('rulerBtn')?.addEventListener('click',function(){
  rulerActive=!rulerActive;arrowActive=false;
  this.classList.toggle('active',rulerActive);
  document.getElementById('arrowBtn').classList.remove('active');
  if(!rulerActive)clearRuler();
  map.getContainer().style.cursor=rulerActive?'crosshair':'';
});
map.on('click',e=>{
  if(!rulerActive||arrowActive)return;
  if(!rStart){rStart=e.latlng;rDot=L.circleMarker(rStart,{radius:4,color:'#fff',fillColor:activeColor,fillOpacity:1,weight:2}).addTo(map);}
  else{clearRuler();}
});
map.on('mousemove',e=>{if(rulerActive&&rStart)updateRuler(e.latlng);});

let aStart=null,aLine=null,aHead=null,aDot=null;

function arrowHeadPts(from,to,zoom){
  const fp = map.latLngToLayerPoint(from);
  const tp = map.latLngToLayerPoint(to);
  const ang = Math.atan2(tp.y-fp.y, tp.x-fp.x);
  const A = Math.PI/5.5;
  const L2 = Math.max(14, Math.min(32, map.distance(from,to)/60));  // px, proportionnel dist
  const sz = L2 / Math.pow(2, zoom-7) * 0.00015;  // retour en degrés approx
  const cosLat = Math.cos(to.lat*Math.PI/180);
  return [
    L.latLng(to.lat - sz*Math.cos(ang-A),          to.lng - sz*Math.sin(ang-A)/cosLat),
    L.latLng(to.lat - sz*Math.cos(ang+A),          to.lng - sz*Math.sin(ang+A)/cosLat)
  ];
}

function updateArrow(to){
  if(!aStart)return;
  if(aLine)map.removeLayer(aLine);
  if(aHead)map.removeLayer(aHead);
  aLine=L.polyline([aStart,to],{color:activeColor,weight:S_DRAW,opacity:.85}).addTo(map);
  const [p1,p2]=arrowHeadPts(aStart,to,map.getZoom());
  aHead=L.polygon([to,p1,p2],{color:activeColor,fillColor:activeColor,fillOpacity:.9,weight:1.5}).addTo(map);
}
function clearArrow(){[aLine,aHead,aDot].forEach(l=>{if(l)map.removeLayer(l)});aLine=aHead=aDot=aStart=null;}

document.getElementById('arrowBtn')?.addEventListener('click',function(){
  arrowActive=!arrowActive;rulerActive=false;
  this.classList.toggle('active',arrowActive);
  document.getElementById('rulerBtn').classList.remove('active');
  if(!arrowActive)clearArrow();
  map.getContainer().style.cursor=arrowActive?'crosshair':'';
});
map.on('click',e=>{
  if(!arrowActive||rulerActive)return;
  if(!aStart){
    aStart=e.latlng;
    aDot=L.circleMarker(aStart,{radius:4,color:'#fff',fillColor:activeColor,fillOpacity:1,weight:2}).addTo(map);
  } else {
    const fLine=L.polyline([aStart,e.latlng],{color:activeColor,weight:S_DRAW,opacity:.9}).addTo(map);
    drawMarkers.push(fLine);
    const [p1,p2]=arrowHeadPts(aStart,e.latlng,map.getZoom());
    const fHead=L.polygon([e.latlng,p1,p2],{color:activeColor,fillColor:activeColor,fillOpacity:1,weight:1.5}).addTo(map);
    drawMarkers.push(fHead);
    const dist=map.distance(aStart,e.latlng)/1852;
    if(dist>0.05){
      const mid=L.latLng((aStart.lat+e.latlng.lat)/2,(aStart.lng+e.latlng.lng)/2);
      const lm=L.marker(mid,{icon:L.divIcon({html:`<div class="arrow-label" style="color:${activeColor}">${dist.toFixed(1)} NM</div>`,className:'',iconSize:[70,20],iconAnchor:[35,20]})}).addTo(map);
      drawMarkers.push(lm);
    }
    clearArrow();
  }
});
map.on('mousemove',e=>{if(arrowActive&&aStart)updateArrow(e.latlng);});
// Touch ruler/arrow on tablet
(function(){
  const mc=map.getContainer();
  function _enDT(){map.dragging.disable();map.touchZoom.disable();}
  function _diDT(){map.dragging.enable();map.touchZoom.enable();}
  const _mo=new MutationObserver(()=>{if(rulerActive||arrowActive)_enDT();else _diDT();});
  _mo.observe(document.getElementById('rulerBtn'),{attributes:true,attributeFilter:['class']});
  _mo.observe(document.getElementById('arrowBtn'),{attributes:true,attributeFilter:['class']});
  mc.addEventListener('touchstart',function(e){
    if(!rulerActive&&!arrowActive)return;if(e.touches.length!==1)return;
    const t=e.touches[0],rect=mc.getBoundingClientRect();
    const pt=map.containerPointToLatLng(L.point(t.clientX-rect.left,t.clientY-rect.top));
    if(rulerActive&&!arrowActive){if(!rStart){rStart=pt;rDot=L.circleMarker(rStart,{radius:5,color:'#fff',fillColor:activeColor,fillOpacity:1,weight:2}).addTo(map);}else{clearRuler();}e.preventDefault();}
    if(arrowActive&&!rulerActive){if(!aStart){aStart=pt;aDot=L.circleMarker(aStart,{radius:5,color:'#fff',fillColor:activeColor,fillOpacity:1,weight:2}).addTo(map);}else{const fL=L.polyline([aStart,pt],{color:activeColor,weight:S_DRAW,opacity:.9}).addTo(map);drawMarkers.push(fL);const[p1,p2]=arrowHeadPts(aStart,pt,map.getZoom());const fH=L.polygon([pt,p1,p2],{color:activeColor,fillColor:activeColor,fillOpacity:1,weight:1.5}).addTo(map);drawMarkers.push(fH);const d=map.distance(aStart,pt)/1852;if(d>0.05){const mid=L.latLng((aStart.lat+pt.lat)/2,(aStart.lng+pt.lng)/2);const lm=L.marker(mid,{icon:L.divIcon({html:'<div class="arrow-label" style="color:'+activeColor+'">'+d.toFixed(1)+' NM</div>',className:'',iconSize:[70,20],iconAnchor:[35,20]})}).addTo(map);drawMarkers.push(lm);}clearArrow();}e.preventDefault();}
  },{passive:false});
  mc.addEventListener('touchmove',function(e){if(e.touches.length!==1)return;const t=e.touches[0],rect=mc.getBoundingClientRect();const pt=map.containerPointToLatLng(L.point(t.clientX-rect.left,t.clientY-rect.top));if(rulerActive&&rStart){updateRuler(pt);e.preventDefault();}if(arrowActive&&aStart){updateArrow(pt);e.preventDefault();}},{passive:false});
})();

document.getElementById('clearArrowsBtn')?.addEventListener('click',()=>{
  drawMarkers.forEach(m=>{try{map.removeLayer(m)}catch(e){}});drawMarkers=[];clearArrow();
});

let _noteCount=0;
function createNote(){
  let bgColor='#0f172a',textColor='#94a3b8';
  const wrapper=document.createElement('div');
  wrapper.className='note-wrapper';
  const _no=_noteCount%8;_noteCount++;
  wrapper.style.left=(300+_no*28)+'px';wrapper.style.top=(200+_no*28)+'px';
  wrapper.style.background=bgColor;wrapper.style.border='1px solid rgba(74,222,128,.2)';
  const header=document.createElement('div');header.className='note-header';
  const bgPicker=document.createElement('div');bgPicker.className='note-mini-picker';bgPicker.title='Fond';
  const bgSwatch=document.createElement('div');bgSwatch.className='swatch';bgSwatch.style.background=bgColor;
  const bgInput=document.createElement('input');bgInput.type='color';bgInput.value='#0f172a';
  bgInput.addEventListener('input',()=>{bgColor=bgInput.value;bgSwatch.style.background=bgColor;wrapper.style.background=bgColor;});
  bgPicker.appendChild(bgSwatch);bgPicker.appendChild(bgInput);
  const txPicker=document.createElement('div');txPicker.className='note-mini-picker';txPicker.title='Texte';
  const txSwatch=document.createElement('div');txSwatch.className='swatch';txSwatch.style.background=textColor;
  const txInput=document.createElement('input');txInput.type='color';txInput.value='#94a3b8';
  txInput.addEventListener('input',()=>{textColor=txInput.value;txSwatch.style.background=textColor;body.style.color=textColor;});
  txPicker.appendChild(txSwatch);txPicker.appendChild(txInput);
  const txLabel=document.createElement('span');txLabel.textContent='T';txLabel.style.cssText='font-size:9px;color:rgba(255,255,255,.3);margin-right:1px;font-family:system-ui,sans-serif';
  const colors=document.createElement('div');colors.className='note-header-colors';
  colors.appendChild(bgPicker);colors.appendChild(txLabel);colors.appendChild(txPicker);
  const closeBtn=document.createElement('button');closeBtn.className='note-close';closeBtn.innerHTML='×';closeBtn.title='Delete';
  closeBtn.addEventListener('click',()=>wrapper.remove());
  header.appendChild(colors);header.appendChild(closeBtn);
  const body=document.createElement('textarea');body.className='note-body';
  body.placeholder='Note…';body.style.color=textColor;
  wrapper.appendChild(header);wrapper.appendChild(body);
  let drag=false,ox=0,oy=0;
  header.addEventListener('mousedown',e=>{if(e.target===closeBtn||e.target===bgInput||e.target===txInput)return;drag=true;ox=e.clientX-wrapper.offsetLeft;oy=e.clientY-wrapper.offsetTop;e.preventDefault();});
  document.addEventListener('mousemove',e=>{if(drag){wrapper.style.left=(e.clientX-ox)+'px';wrapper.style.top=(e.clientY-oy)+'px';}});
  document.addEventListener('mouseup',()=>{drag=false;});
  // Touch drag (tablet)
  header.addEventListener('touchstart',e=>{
    if(e.target===closeBtn||e.target===bgInput||e.target===txInput)return;
    const t=e.touches[0];drag=true;ox=t.clientX-wrapper.offsetLeft;oy=t.clientY-wrapper.offsetTop;e.preventDefault();
  },{passive:false});
  document.addEventListener('touchmove',e=>{
    if(drag&&e.touches.length){wrapper.style.left=(e.touches[0].clientX-ox)+'px';wrapper.style.top=(e.touches[0].clientY-oy)+'px';e.preventDefault();}
  },{passive:false});
  document.addEventListener('touchend',()=>{drag=false;});
  document.body.appendChild(wrapper);body.focus();
}
document.getElementById('annotationBtn')?.addEventListener('click',createNote);

const cGrid=document.getElementById('cGrid');
COLORS.forEach(c=>{
  const s=document.createElement('div');
  s.className='c-swatch'+(c===activeColor?' sel':'');
  s.style.background=c;
  s.dataset.color=c;s.onclick=()=>{activeColor=c;document.querySelectorAll('.c-swatch').forEach(x=>x.classList.remove('sel'));s.classList.add('sel');saveUiPref({active_color:c});};
  cGrid.appendChild(s);
});
document.getElementById('colorBtn')?.addEventListener('click',()=>document.getElementById('colorPanel').classList.toggle('open'));

document.getElementById('layerBtn')?.addEventListener('click',()=>document.getElementById('layerPanel').classList.toggle('open'));
document.querySelectorAll('input[name="layer"]').forEach(r=>r.addEventListener('change',e=>{
  switchLayer(e.target.value);
  saveUiPref({layer:e.target.value});
}));

document.getElementById('pptLabelBtn')?.addEventListener('click',function(){
  pptLabelsVisible=!pptLabelsVisible;
  this.classList.toggle('active',pptLabelsVisible);
  pptLabelMarkers.forEach(m=>{try{pptLabelsVisible?m.addTo(map):map.removeLayer(m);}catch(e){}});
});

document.getElementById('pptBtn')?.addEventListener('click',function(){
  const v=this.classList.toggle('active');
  pptCircles.forEach(c=>v?c.addTo(map):map.removeLayer(c));
  const chk=document.getElementById('chkPPT');if(chk)chk.checked=v;
  saveUiPref({ppt_visible:v});
});
// chkPPT: géré uniquement via le bouton toolbar pptBtn

document.getElementById('airportBtn')?.addEventListener('click',function(){
  const v=this.classList.toggle('active');
  const apNameOn=document.getElementById('chkApName').checked;
  airportMarkers.forEach(m=>{
    if(!v){try{map.removeLayer(m)}catch(e){}}
    else if(apNameMarkers.includes(m)){if(apNameOn)try{m.addTo(map)}catch(e){}}
    else{try{m.addTo(map)}catch(e){}}
  });
  const chk=document.getElementById('chkAirports');if(chk)chk.checked=v;
  runwaysVisible=v;
  runwayLayers.forEach(l=>{try{v?l.addTo(map):map.removeLayer(l);}catch(e){}});
  const chkR=document.getElementById('chkRunways');if(chkR)chkR.checked=v;
  saveUiPref({airports_visible:v});
});
// chkAirports: géré uniquement via le bouton toolbar airportBtn

document.getElementById('uploadBtn')?.addEventListener('click',()=>document.getElementById('fileInput').click());
document.getElementById('fileInput')?.addEventListener('change',async e=>{
  const file=e.target.files[0];if(!file)return;
  const fd=new FormData();fd.append('file',file);
  const r=await fetch('/api/upload',{method:'POST',body:fd});
  if(r.ok)loadMission();
});

var _lastIniFile=null;
var _lastIniMtime=0;
setInterval(async()=>{
  try{
    const s=await(await fetch('/api/ini/status')).json();
    if(s.loaded&&s.mtime&&s.mtime!==_lastIniMtime){
      _lastIniFile=s.file;_lastIniMtime=s.mtime;
      loadMission();
      console.log('[INI] Auto-loaded:',s.file,'mtime:',s.mtime);
      const n=document.createElement('div');n.className='bms-toast';
      n.textContent='✦ MISSION LOADED — '+s.file;
      document.body.appendChild(n);setTimeout(()=>n.remove(),3000);
    }
  }catch(e){}
},3000);

function loadMission(){
  missionMarkers.forEach(m=>{try{map.removeLayer(m)}catch(e){}});missionMarkers=[];pptLabelMarkers=[];
  pptCircles.forEach(p=>{try{map.removeLayer(p)}catch(e){}});pptCircles=[];
  fetch('/api/mission').then(r=>r.json()).then(d=>{
    if(d.flightplan?.length){
      const c=C_FPLAN;
      missionMarkers.push(L.polyline(d.flightplan.map(p=>[p.lat,p.lon]),{color:c,weight:S_DRAW,opacity:.8}).addTo(map));
      d.flightplan.forEach((p,i)=>{
        missionMarkers.push(L.circleMarker([p.lat,p.lon],{radius:S_FPLAN,color:c,fillColor:c,fillOpacity:.85,weight:2}).addTo(map));
        missionMarkers.push(L.marker([p.lat,p.lon],{icon:L.divIcon({
          html:`<div style="font-family:'Consolas','Courier New',monospace;color:${c};font-size:9px;font-weight:700;text-shadow:0 1px 4px #000">${i+1}</div>`,
          className:'',iconSize:[16,12],iconAnchor:[-5,6]
        })}).addTo(map));
      });
    }
    if(d.route?.length){
      const c=C_STPT;
      for(let i=0;i<d.route.length-1;i++)
        missionMarkers.push(L.polyline([[d.route[i].lat,d.route[i].lon],[d.route[i+1].lat,d.route[i+1].lon]],{color:c,weight:S_DRAW}).addTo(map));
      d.route.forEach((p,i)=>{
        missionMarkers.push(L.circleMarker([p.lat,p.lon],{radius:S_STPT,color:c,fillColor:c,fillOpacity:.9,weight:2}).addTo(map));
        missionMarkers.push(L.marker([p.lat,p.lon],{icon:L.divIcon({
          html:`<div style="font-family:'Consolas','Courier New',monospace;color:${C_STPT};font-size:9px;font-weight:700;text-shadow:0 1px 4px #000">${i+1}</div>`,
          className:'',iconSize:[16,12],iconAnchor:[-5,6]
        })}).addTo(map));
      });
      map.setView([d.route[0].lat,d.route[0].lon],9);
    }
    if(d.threats?.length){
      const c=C_PPT;
      d.threats.forEach(t=>{
        const circ=L.circle([t.lat,t.lon],{radius:(t.range_m||t.range_nm*1852),color:c,fillColor:c,fillOpacity:.05,weight:S_PPT,dashArray:'5 4'});
        if(document.getElementById('pptBtn')?.classList.contains('active'))circ.addTo(map);
        pptCircles.push(circ);
        missionMarkers.push(L.circleMarker([t.lat,t.lon],{radius:5,color:'#fff',fillColor:c,fillOpacity:1,weight:2}).addTo(map));
        const nm=t.name?t.name.trim():'';
        const rng=t.range_nm>0?t.range_nm+'NM':'';
        const pptNum=(t.num!==undefined)?t.num:t.index;
        const parts2=[
          `<span style="color:#f87171;font-size:9px;letter-spacing:1px;font-weight:700">PPT\u00a0${pptNum}</span>`,
          nm?`<span style="color:#fca5a5;font-size:10px;font-weight:700;letter-spacing:.3px">${nm}</span>`:'',
          rng?`<span style="color:#ef4444;font-size:9px;font-family:'Consolas','Courier New',monospace">${rng}</span>`:'',
        ].filter(Boolean).join('<span style="color:rgba(239,68,68,.25);margin:0 3px;font-size:7px">▸</span>');
        const pptLbl=L.marker([t.lat,t.lon],{icon:L.divIcon({
          html:`<div style="background:rgba(8,2,2,.9);border:1px solid rgba(239,68,68,.22);border-left:2px solid rgba(239,68,68,.65);border-radius:2px;padding:2px 7px;white-space:nowrap;pointer-events:none;font-family:system-ui,sans-serif;display:inline-flex;align-items:center;gap:0;box-shadow:0 2px 8px rgba(0,0,0,.5)">${parts2}</div>`,
          className:'',iconSize:[110,16],iconAnchor:[-6,8]
        }),zIndexOffset:50});
        if(pptLabelsVisible) pptLbl.addTo(map);
        pptLabelMarkers.push(pptLbl);
        missionMarkers.push(pptLbl);
      });
    }
  });
}

var apData = [];        // cache des données
var apNameMarkers = []; // markers "nom complet" séparés
var apLabelMarkers= []; // markers TACAN/ICAO
var apIconMarkers = []; // markers losange

function buildApPopup(ap) {
  const isNK = ap.icao.startsWith('KP-') || ap.icao.startsWith('ZK');
  const col  = isNK ? '#f87171' : '#60a5fa';

  // Ligne 1 : ICAO · TACAN · TOUR
  const parts = [`<span class="ap-l1-icao" style="color:${col}">${ap.icao}</span>`];
  if (ap.tacan) {
    parts.push(`<span class="ap-l1-dot">·</span>`);
    parts.push(`<span class="ap-l1-tacan">${ap.tacan}</span>`);
  }
  if (ap.freq) {
    parts.push(`<span class="ap-l1-dot">·</span>`);
    parts.push(`<span class="ap-l1-freq">${ap.freq}</span>`);
  }
  const line1 = `<div class="ap-l1">${parts.join('')}</div>`;

  // Ligne 2 : chips ILS (RWY · freq · CRS)
  let line2 = '';
  if (ap.ils && ap.ils.length) {
    const chips = ap.ils.map(i =>
      `<div class="ap-ils-chip">
        <span class="ap-ils-rwy">RWY ${i.rwy}</span>
        <span class="ap-ils-freq">${i.freq}</span>
        <span class="ap-ils-crs">${i.crs}°</span>
      </div>`
    ).join('');
    line2 = `<div class="ap-l2">${chips}</div>`;
  }

  return `<div class="ap-popup">${line1}${line2}</div>`;
}

fetch('/api/airports').then(r=>r.json()).then(aps=>{
  apData = aps;
  aps.forEach(ap=>{
    const isNK=ap.icao.startsWith('KP-')||ap.icao.startsWith('ZK');
    const col=isNK?'rgba(248,113,113,.85)':'rgba(96,165,250,.85)';
    const sz = 13;
    const sym=`<svg width="${sz}" height="${sz}" viewBox="0 0 13 13" style="cursor:pointer">
      <polygon points="6.5,1 12,6.5 6.5,12 1,6.5" fill="${col}" stroke="rgba(0,0,0,.7)" stroke-width="1.5"/>
    </svg>`;
    const mIcon=L.marker([ap.lat,ap.lon],{
      icon:L.divIcon({html:sym,className:'',iconSize:[sz,sz],iconAnchor:[sz/2,sz/2]}),
      zIndexOffset:10
    }).addTo(map);
    mIcon.bindPopup(buildApPopup(ap),{
      className:'',maxWidth:320,closeButton:true,
      offset:L.point(0,-6)
    });
    apIconMarkers.push(mIcon);

    const apIcao = ap.icao.startsWith('KP-') ? ap.name : ap.icao;
    const labelHtml = `<div style="pointer-events:none;line-height:1.2">
      <div style="font-family:'Consolas','Courier New',monospace;font-size:11px;font-weight:700;
        color:${col};letter-spacing:.8px;text-shadow:0 1px 4px #000,0 0 8px rgba(0,0,0,.9);
        white-space:nowrap">${apIcao}</div>
    </div>`;
    const mLabel=L.marker([ap.lat,ap.lon],{
      icon:L.divIcon({html:labelHtml,className:'',iconSize:[160,26],iconAnchor:[-8,6]}),
      zIndexOffset:-100,interactive:true
    }).addTo(map);
    mLabel.on('click',e=>{
      if(rulerActive){
        L.DomEvent.stopPropagation(e);
        if(!rStart){
          rStart=L.latLng(ap.lat,ap.lon);
          rDot=L.circleMarker(rStart,{radius:4,color:'#fff',fillColor:activeColor,fillOpacity:1,weight:2}).addTo(map);
        } else { clearRuler(); }
      } else { mIcon.openPopup(); }
    });
    mIcon.on('click',e=>{
      if(rulerActive){
        L.DomEvent.stopPropagation(e);
        if(!rStart){
          rStart=L.latLng(ap.lat,ap.lon);
          rDot=L.circleMarker(rStart,{radius:4,color:'#fff',fillColor:activeColor,fillOpacity:1,weight:2}).addTo(map);
        } else { clearRuler(); }
      } else { mIcon.openPopup(); }
    });
    apLabelMarkers.push(mLabel);
    airportMarkers.push(mIcon,mLabel);
    apNameMarkers.push(mLabel);
  });

  document.getElementById('chkRunways')?.addEventListener('change',function(){
    runwaysVisible=this.checked;
    runwayLayers.forEach(l=>{try{runwaysVisible?l.addTo(map):map.removeLayer(l);}catch(e){}});
    saveUiPref({runways_visible:this.checked});
  });

  // chkApName — afficher/masquer les labels ICAO des aéroports
  document.getElementById('chkApName')?.addEventListener('change',function(){
    apLabelMarkers.forEach(m=>{
      try{ this.checked ? m.addTo(map) : map.removeLayer(m); }catch(e){}
    });
    saveUiPref({ap_name_visible:this.checked});
  });
  // Etat initial : labels visibles si coché
  if(!document.getElementById('chkApName').checked){
    apLabelMarkers.forEach(m=>{try{map.removeLayer(m);}catch(e){}});
  }

  // Charger les prefs UI après que tout est prêt
  loadUiPrefs();
});

const RUNWAY_DATA = [
  {icao:'RKTN',name:'Daegu AB',rwy:0,hdg:327.5,len:2743,c:[[35.883663,128.667015],[35.883885,128.66744],[35.904457,128.650634],[35.904229,128.650212]]},
  {icao:'RKTN',name:'Daegu AB',rwy:1,hdg:327.5,len:2754,c:[[35.882936,128.66592],[35.883162,128.666342],[35.903814,128.64947],[35.903585,128.649048]]},
  {icao:'RKJB',name:'Muan Apt',rwy:0,hdg:90.8,len:2794,c:[[34.988282,126.355991],[34.987878,126.355991],[34.987922,126.38666],[34.988327,126.386664]]},
  {icao:'RKSO',name:'Osan AB',rwy:0,hdg:186.6,len:2745,c:[[37.107717,127.046449],[37.107756,127.045939],[37.083195,127.042867],[37.08316,127.043375]]},
  {icao:'RKSO',name:'Osan AB',rwy:1,hdg:186.6,len:2745,c:[[37.107918,127.04392],[37.107955,127.043411],[37.083402,127.040337],[37.083361,127.040848]]},
  {icao:'RKTY',name:'Yecheon AB',rwy:0,hdg:182.6,len:2746,c:[[36.655298,128.355143],[36.655313,128.354636],[36.630626,128.353722],[36.630617,128.354233]]},
  {icao:'ZKTS',name:'Toksan AB',rwy:0,hdg:52.1,len:2484,c:[[39.27708,127.346012],[39.276736,127.34637],[39.290795,127.3688],[39.291138,127.368442]]},
  {icao:'RKPS',name:'Sacheon AB',rwy:0,hdg:215.6,len:2750,c:[[35.100714,128.087058],[35.100941,128.086671],[35.080615,128.069441],[35.080387,128.069827]]},
  {icao:'RKPS',name:'Sacheon AB',rwy:1,hdg:215.7,len:2751,c:[[35.102998,128.085936],[35.10322,128.085545],[35.082896,128.068315],[35.082675,128.068707]]},
  {icao:'ZKUJ',name:'Uiju AB',rwy:0,hdg:49.0,len:2493,c:[[40.040129,124.517393],[40.039743,124.517854],[40.054846,124.539484],[40.055233,124.539023]]},
  {icao:'RKSM',name:'Seoul AB',rwy:0,hdg:82.8,len:2957,c:[[37.446373,127.093555],[37.445966,127.093628],[37.449713,127.126783],[37.45012,127.12671]]},
  {icao:'RKSM',name:'Seoul AB',rwy:1,hdg:89.2,len:2744,c:[[37.449879,127.095767],[37.449469,127.095784],[37.450244,127.126841],[37.450655,127.126825]]},
  {icao:'RKTI',name:'Jungwon AB',rwy:0,hdg:275.6,len:2750,c:[[36.634671,127.516339],[36.635081,127.51638],[36.637084,127.485666],[36.636674,127.485625]]},
  {icao:'RKTI',name:'Jungwon AB',rwy:1,hdg:275.4,len:2852,c:[[36.632599,127.516742],[36.632916,127.516774],[36.634993,127.484914],[36.634675,127.484881]]},
  {icao:'RJOI',name:'Iwakuni AB',rwy:0,hdg:265.0,len:2441,c:[[34.15313,132.248972],[34.153664,132.248894],[34.151218,132.222548],[34.150685,132.22262]]},
  {icao:'RKPK',name:'Gimhae Apt',rwy:0,hdg:277.7,len:2749,c:[[35.182237,128.951059],[35.182636,128.951114],[35.185564,128.921087],[35.185165,128.921027]]},
  {icao:'RKPK',name:'Gimhae Apt',rwy:1,hdg:277.9,len:3206,c:[[35.180288,128.950746],[35.180819,128.950825],[35.184232,128.915799],[35.183701,128.915723]]},
  {icao:'RKJJ',name:'Gwangju AB',rwy:0,hdg:240.6,len:2835,c:[[35.134226,126.816195],[35.134576,126.815945],[35.121713,126.789037],[35.121362,126.789277]]},
  {icao:'RKJJ',name:'Gwangju AB',rwy:1,hdg:240.6,len:2835,c:[[35.135725,126.815124],[35.136075,126.814874],[35.123212,126.78796],[35.122862,126.78821]]},
  {icao:'KP-0005',name:'Taetan AB (G)',rwy:0,hdg:357.4,len:2503,c:[[38.238811,126.650634],[38.238835,126.651157],[38.261302,126.649337],[38.261276,126.648815]]},
  {icao:'KP-0030',name:'Panghyon AB',rwy:0,hdg:147.6,len:2597,c:[[39.910465,124.924693],[39.910198,124.924173],[39.890739,124.940999],[39.891009,124.941506]]},
  {icao:'RJOW',name:'Iwami Apt',rwy:0,hdg:168.6,len:2001,c:[[34.684957,131.787578],[34.684868,131.787097],[34.667321,131.791906],[34.66741,131.792387]]},
  {icao:'RKNY',name:'Yangyang Apt',rwy:0,hdg:310.8,len:2500,c:[[38.055058,128.676352],[38.05537,128.67668],[38.069756,128.654739],[38.069444,128.65441]]},
  {icao:'RKSI',name:'Incheon Apt *',rwy:0,hdg:305.8,len:3750,c:[[37.460193,126.463405],[37.460637,126.463789],[37.479929,126.428947],[37.479487,126.428556]]},
  {icao:'RKSI',name:'Incheon Apt *',rwy:1,hdg:305.8,len:3751,c:[[37.457142,126.460724],[37.457584,126.461112],[37.476881,126.426262],[37.476438,126.425875]]},
  {icao:'KP-0023',name:'Onchon AB',rwy:0,hdg:83.7,len:2502,c:[[39.815001,124.919894],[39.815409,124.919843],[39.817488,124.949006],[39.817083,124.949046]]},
  {icao:'RJOA',name:'Hiroshima Apt',rwy:0,hdg:1.2,len:3000,c:[[34.432547,132.910191],[34.432548,132.910845],[34.459516,132.910858],[34.459517,132.910204]]},
  {icao:'KP-0008',name:'Sondok AB',rwy:0,hdg:263.4,len:2502,c:[[39.750682,127.48869],[39.751087,127.488621],[39.748112,127.459616],[39.747707,127.459685]]},
  {icao:'RKSS',name:'Gimpo Apt',rwy:0,hdg:315.6,len:3573,c:[[37.545249,126.811295],[37.545627,126.811769],[37.568189,126.782909],[37.567809,126.782435]]},
  {icao:'RKSS',name:'Gimpo Apt',rwy:1,hdg:315.7,len:3172,c:[[37.542991,126.808384],[37.543371,126.808858],[37.563396,126.783243],[37.563015,126.782768]]},
  {icao:'KP-0020',name:'Hwangju AB',rwy:0,hdg:152.5,len:2504,c:[[38.682744,125.777293],[38.682925,125.77776],[38.662777,125.790628],[38.662601,125.790156]]},
  {icao:'RKSW',name:'Suwon AB',rwy:0,hdg:306.3,len:2743,c:[[37.22823,127.028906],[37.228566,127.029207],[37.242818,127.003916],[37.242484,127.00362]]},
  {icao:'RKSW',name:'Suwon AB',rwy:1,hdg:306.3,len:2743,c:[[37.227119,127.027862],[37.227454,127.028163],[37.241708,127.002872],[37.241373,127.002572]]},
  {icao:'KP-0011',name:'Mirim Airport',rwy:0,hdg:5.5,len:1251,c:[[39.06162,125.599413],[39.061595,125.59994],[39.072823,125.600799],[39.072847,125.600273]]},
  {icao:'RKJK',name:'Gunsan AB',rwy:0,hdg:101.3,len:2749,c:[[35.90714,126.599591],[35.906742,126.599495],[35.902279,126.629517],[35.902678,126.629607]]},
  {icao:'RKNN',name:'Gangneung AB',rwy:0,hdg:203.3,len:2761,c:[[37.765804,128.949017],[37.765963,128.948534],[37.743008,128.93657],[37.742853,128.937048]]},
  {icao:'RKNW',name:'Wonju AB',rwy:0,hdg:64.6,len:2738,c:[[37.427754,127.941412],[37.427386,127.941644],[37.438331,127.969412],[37.438699,127.969181]]},
  {icao:'RKSG',name:'Pyeongtaek AB',rwy:0,hdg:319.2,len:2309,c:[[36.952564,127.038492],[36.952839,127.038876],[36.968295,127.021521],[36.968019,127.021136]]},
  {icao:'RKTH',name:'Pohang AB',rwy:0,hdg:183.2,len:2133,c:[[35.997509,129.423488],[35.997524,129.422978],[35.978354,129.422152],[35.978339,129.42266]]},
  {icao:'RKTP',name:'Seosan AB',rwy:0,hdg:245.6,len:2744,c:[[36.706605,126.49829],[36.706977,126.49807],[36.696412,126.470264],[36.69604,126.470483]]},
  {icao:'RKTP',name:'Seosan AB',rwy:1,hdg:245.6,len:2744,c:[[36.708337,126.49727],[36.708708,126.497051],[36.698143,126.469244],[36.697771,126.469464]]},
  {icao:'RKTU',name:'Cheongju Apt',rwy:0,hdg:218.9,len:2744,c:[[36.732248,127.513095],[36.732577,127.512563],[36.713041,127.493765],[36.712711,127.494298]]},
  {icao:'RKTU',name:'Cheongju Apt',rwy:1,hdg:218.6,len:2744,c:[[36.732914,127.510383],[36.733161,127.509982],[36.713625,127.491185],[36.713378,127.491585]]},
  {icao:'KP-0035',name:'Hwangsuwon AB',rwy:0,hdg:325.0,len:2901,c:[[38.672715,125.376188],[38.672957,125.376617],[38.694085,125.357024],[38.693842,125.356594]]},
  {icao:'KP-0019',name:'Hyon-ni AB',rwy:0,hdg:79.4,len:2702,c:[[39.147695,125.867532],[39.147337,125.867634],[39.152173,125.898328],[39.152534,125.898236]]},
  {icao:'KP-0059',name:'Iwon AB',rwy:0,hdg:171.2,len:2509,c:[[40.327783,128.631085],[40.327712,128.630548],[40.305483,128.635634],[40.305556,128.636167]]},
  {icao:'KP-0018',name:'Kaechon AB',rwy:0,hdg:46.3,len:2503,c:[[39.79407,125.893871],[39.79378,125.894246],[39.809632,125.915044],[39.809923,125.914672]]},
  {icao:'KP-0015',name:'Koksan AB',rwy:0,hdg:32.3,len:2503,c:[[38.807253,126.392391],[38.807041,126.392836],[38.826276,126.407847],[38.826488,126.407401]]},
  {icao:'KP-0039',name:'Kwail AB',rwy:0,hdg:125.4,len:2499,c:[[38.70657,125.538208],[38.706245,125.53793],[38.69355,125.561675],[38.693864,125.561955]]},
  {icao:'KP-0053',name:'Manpo AB',rwy:0,hdg:72.4,len:1117,c:[[41.563091,126.252673],[41.562834,126.252808],[41.566123,126.265472],[41.566374,126.265345]]},
  {icao:'KP-0032',name:'Orang AB',rwy:0,hdg:58.8,len:2515,c:[[41.377494,129.437117],[41.377032,129.437509],[41.3892,129.462916],[41.389662,129.462523]]},
  {icao:'KP-0029',name:'Samjiyon AB',rwy:0,hdg:31.6,len:3308,c:[[42.053663,128.389224],[42.053384,128.389858],[42.079001,128.410225],[42.079278,128.40959]]},
  {icao:'KP-0021',name:'Sunchon AB',rwy:0,hdg:125.3,len:2504,c:[[39.440112,125.92096],[39.439773,125.920663],[39.427087,125.94474],[39.427426,125.945037]]},
  {icao:'KP-0006',name:'Taechon AB',rwy:0,hdg:164.1,len:2010,c:[[39.791475,124.713719],[39.79131,124.713039],[39.774091,124.720148],[39.774257,124.720826]]},
];

var runwayLayers = [], runwaysVisible = true;

var rwyOffsets = {};
try { rwyOffsets = JSON.parse(sessionStorage.getItem('bms_rwy_offsets')||'{}'); } catch(e){}

function saveRwyOffsets(){ sessionStorage.setItem('bms_rwy_offsets', JSON.stringify(rwyOffsets)); }

function applyOffset(latlon, icao) {
  const o = rwyOffsets[icao] || {dlat:0,dlon:0};
  return [latlon[0]+o.dlat, latlon[1]+o.dlon];
}

function renderRunways() {
  runwayLayers.forEach(l => { try { map.removeLayer(l); } catch(e){} });
  runwayLayers = [];

  RUNWAY_DATA.forEach(r => {
    const isNK = r.icao.startsWith('KP-') || r.icao.startsWith('ZK');
    const col     = isNK ? 'rgba(248,113,113,.75)' : 'rgba(148,185,220,.8)';
    const fillCol = isNK ? 'rgba(220,60,60,.18)'   : 'rgba(120,160,200,.15)';

    const corners = r.c.map(pt => applyOffset(pt, r.icao));

    const poly = L.polygon(corners, {
      color: col, fillColor: fillCol, fillOpacity: 1,
      weight: 2, interactive: false,
    });
    if (runwaysVisible) poly.addTo(map);
    runwayLayers.push(poly);

    const midA = [(corners[0][0]+corners[1][0])/2, (corners[0][1]+corners[1][1])/2];
    const midB = [(corners[2][0]+corners[3][0])/2, (corners[2][1]+corners[3][1])/2];
    const axis = L.polyline([midA, midB], {
      color: col, weight: 1.5, opacity: 0.6,
      dashArray: '8 5', interactive: false,
    });
    if (runwaysVisible) axis.addTo(map);
    runwayLayers.push(axis);
  });
}

var _calMode = false;
var _calIcao = null;
var _calAnchorPt = null;  // point théorique (avant offset) du premier coin

function openCalPanel() {
  document.getElementById('calPanel').style.display = 'block';
  const sel = document.getElementById('calIcaoSel');
  sel.innerHTML = '';
  const icaos = [...new Set(RUNWAY_DATA.map(r=>r.icao))].sort();
  icaos.forEach(ic => {
    const o = document.createElement('option');
    o.value = ic;
    const off = rwyOffsets[ic];
    o.textContent = ic + (off ? ` (${(off.dlat*111000).toFixed(0)}m N, ${(off.dlon*111000).toFixed(0)}m E)` : '');
    sel.appendChild(o);
  });
}

function startCalibration() {
  _calIcao = document.getElementById('calIcaoSel').value;
  if (!_calIcao) return;
  _calMode = true;
  document.getElementById('calPanel').style.display = 'none';
  document.getElementById('calStatus').textContent = `CALIB ${_calIcao} — Click on actual runway threshold`;
  document.getElementById('calStatus').style.display = 'block';
  map.getContainer().style.cursor = 'crosshair';

  const rwy0 = RUNWAY_DATA.find(r => r.icao === _calIcao);
  if (rwy0) {
    const cur = rwyOffsets[_calIcao] || {dlat:0,dlon:0};
    _calAnchorPt = [rwy0.c[0][0]+cur.dlat, rwy0.c[0][1]+cur.dlon];
    if (window._calTmpMarker) { try{map.removeLayer(window._calTmpMarker);}catch(e){} }
    window._calTmpMarker = L.circleMarker(_calAnchorPt, {
      radius:S_BULL, color:C_BULL, fillColor:C_BULL+'44',
      fillOpacity:1, weight:2, interactive:false
    }).addTo(map);
  }
}

map.on('click', function(e) {
  if (!_calMode) return;
  _calMode = false;
  map.getContainer().style.cursor = '';
  document.getElementById('calStatus').style.display = 'none';
  if (window._calTmpMarker) { try{map.removeLayer(window._calTmpMarker);}catch(e){} }

  if (!_calAnchorPt) return;
  const dlat = e.latlng.lat - _calAnchorPt[0];
  const dlon = e.latlng.lng - _calAnchorPt[1];

  const cur = rwyOffsets[_calIcao] || {dlat:0,dlon:0};
  rwyOffsets[_calIcao] = { dlat: cur.dlat+dlat, dlon: cur.dlon+dlon };
  saveRwyOffsets();
  renderRunways();

  const dn = ((cur.dlat+dlat)*111000).toFixed(0);
  const de = ((cur.dlon+dlon)*111000*Math.cos(_calAnchorPt[0]*Math.PI/180)).toFixed(0);
  showToast(`${_calIcao} recalibrated: ${dn>0?'+':''}${dn}m N, ${de>0?'+':''}${de}m E`);
});

function resetCalibration() {
  const ic = document.getElementById('calIcaoSel').value;
  if (ic) { delete rwyOffsets[ic]; saveRwyOffsets(); renderRunways(); openCalPanel(); }
}
function resetAllCalibration() {
  rwyOffsets = {}; saveRwyOffsets(); renderRunways(); openCalPanel();
}
renderRunways();


// ── Touch listeners passifs — améliore le scroll sur mobile ──────
try {
  const _passiveTest = Object.defineProperty({}, 'passive', {get: function(){ return true; }});
  window.addEventListener('testPassive', null, _passiveTest);
  window.removeEventListener('testPassive', null, _passiveTest);
  // Appliquer le passive aux events tactiles de la carte
  const _mapEl = document.getElementById('map');
  if (_mapEl) {
    _mapEl.addEventListener('touchstart', function(){}, {passive:true});
    _mapEl.addEventListener('touchmove',  function(){}, {passive:true});
  }
} catch(e) {}


// Apply saved settings on startup


var dlMarkers=[],dlVisible=true;
// Datalink actif par défaut
document.getElementById('radarBtn').classList.add('active');
document.getElementById('radarBtn')?.addEventListener('click',()=>{
  dlVisible=!dlVisible;
  document.getElementById('radarBtn').classList.toggle('active',dlVisible);
  dlMarkers.forEach(m=>{try{if(dlVisible)m.addTo(map);else map.removeLayer(m);}catch(e){}});
});


function dlSym(camp,col,sz){
  sz=sz||22;
  const h=sz,cx=sz/2;
  if(camp===1){
    const r=cx-2;
    return `<svg width="${h}" height="${h}" viewBox="0 0 ${h} ${h}">
      <circle cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke="${col}" stroke-width="2"/>
      <line x1="${cx}" y1="${2}" x2="${cx}" y2="${h-2}" stroke="${col}" stroke-width="1.5"/>
      <line x1="${2}" y1="${cx}" x2="${h-2}" y2="${cx}" stroke="${col}" stroke-width="1.5"/>
    </svg>`;
  }
  if(camp===2){
    const m=cx;
    return `<svg width="${h}" height="${h}" viewBox="0 0 ${h} ${h}">
      <polygon points="${m},2 ${h-2},${h-2} 2,${h-2}"
        fill="${col}" fill-opacity=".88" stroke="rgba(0,0,0,.5)" stroke-width="1.2"/>
    </svg>`;
  }
  return `<svg width="${h}" height="${h}" viewBox="0 0 ${h} ${h}">
    <rect x="2" y="2" width="${h-4}" height="${h-4}" fill="none" stroke="${col}" stroke-width="2"/>
    <line x1="${cx}" y1="${2}" x2="${cx}" y2="${h-2}" stroke="${col}" stroke-width="1" opacity=".4"/>
    <line x1="${2}" y1="${cx}" x2="${h-2}" y2="${cx}" stroke="${col}" stroke-width="1" opacity=".4"/>
  </svg>`;
}

function dlVec(hdg,col){
  const r=hdg*Math.PI/180,len=22;
  const dx=Math.sin(r)*len,dy=-Math.cos(r)*len;
  const sz=60,c=30;
  return `<svg width="${sz}" height="${sz}" viewBox="0 0 ${sz} ${sz}" style="overflow:visible">
    <line x1="${c}" y1="${c}" x2="${c+dx}" y2="${c+dy}"
      stroke="${col}" stroke-width="1.5" opacity=".6" stroke-dasharray="4 3"/>
    <circle cx="${c+dx}" cy="${c+dy}" r="1.5" fill="${col}" opacity=".7"/>
  </svg>`;
}

// ── IDM Markpoints (DL NavPoints — shared static positions, NOT contacts)
function updateMarkpoints(marks){
  _lastDlMarks = marks;
  dlMarkers.forEach(m=>{try{map.removeLayer(m)}catch(e){}});dlMarkers=[];
  if(!marks||!marks.length)return;
  if(!dlVisible){dlVisible=true;document.getElementById('radarBtn').classList.add('active');}
  const z = map.getZoom();
  const sz = z >= 10 ? 10 : z >= 8 ? 8 : 6;
  const col = '#60a5fa';  // blue — shared IDM data
  marks.forEach(mk=>{
    if(mk.lat==null||mk.lon==null)return;
    // Diamond marker
    const diamond = `<svg width="${sz*2}" height="${sz*2}" viewBox="0 0 ${sz*2} ${sz*2}">
      <rect x="${sz*0.3}" y="${sz*0.3}" width="${sz*1.4}" height="${sz*1.4}"
        fill="none" stroke="${col}" stroke-width="1.5"
        transform="rotate(45 ${sz} ${sz})"/>
    </svg>`;
    const mS=L.marker([mk.lat,mk.lon],{icon:L.divIcon({
      html:diamond,className:'',iconSize:[sz*2,sz*2],iconAnchor:[sz,sz]
    }),zIndexOffset:80});
    if(dlVisible)mS.addTo(map);dlMarkers.push(mS);
    // Label
    if(z >= 7){
      const lbl = mk.label||'DL';
      const altFL = mk.alt!=null&&mk.alt>0?'FL'+String(Math.round(mk.alt/100)).padStart(3,'0'):'';
      const lH=`<div class="dl-block">
        <div class="dl-callsign friend" style="font-size:${z>=9?10:9}px;color:${col}">${lbl}</div>
        ${altFL&&z>=8?`<div class="dl-data friend" style="color:${col}">${altFL}</div>`:''}
      </div>`;
      const mL=L.marker([mk.lat,mk.lon],{icon:L.divIcon({
        html:lH,className:'',iconSize:[80,24],iconAnchor:[-(sz+2),10]
      }),zIndexOffset:81,interactive:false});
      if(dlVisible)mL.addTo(map);dlMarkers.push(mL);
    }
  });
}

// Redessiner les contacts quand le zoom change
map.on('zoomend', ()=>{
  if(_lastDlMarks) updateMarkpoints(_lastDlMarks);
  if(_lastAcmiContacts) updateAcmiContacts(_lastAcmiContacts);
});
let _lastDlMarks=[];
var _lastAcmiContacts=null;

// ── Contacts ACMI coalition (TRTT — mode dieu) ───────────────────
// Séparé du datalink L16 : bouton propre, toggle indépendant
var acmiMarkers=[], acmiVisible=true;

function updateAcmiContacts(contacts){
  _lastAcmiContacts = contacts;
  acmiMarkers.forEach(m=>{try{map.removeLayer(m)}catch(e){}});acmiMarkers=[];
  if(!contacts||!contacts.length||!acmiVisible)return;
  const z = map.getZoom();
  const sz = z >= 10 ? 14 : z >= 8 ? 10 : 7;
  contacts.forEach(c=>{
    if(c.lat==null||c.lon==null)return;
    // camp=3 (unknown) traité comme allié en solo — BMS injecte les couleurs tardivement
    const camp = c.camp === 2 ? 2 : 1;
    const col = '#4ade80'; // vert allié (ennemis exclus côté serveur)
    const mS=L.marker([c.lat,c.lon],{icon:L.divIcon({
      html:dlSym(1,col,sz),className:'',iconSize:[sz,sz],iconAnchor:[sz/2,sz/2]
    }),zIndexOffset:80,interactive:false});
    mS.addTo(map);acmiMarkers.push(mS);
    // Vecteur cap si assez zoomé
    if(c.heading!=null && z>=9){
      const mV=L.marker([c.lat,c.lon],{icon:L.divIcon({
        html:dlVec(c.heading,col),className:'',iconSize:[36,36],iconAnchor:[18,18]
      }),zIndexOffset:40,interactive:false});
      mV.addTo(map);acmiMarkers.push(mV);
    }
    // Label : callsign court + altitude — seulement si zoom >= 9
    if(z >= 9){
      const raw = c.callsign || c.type_name || '';
      // Garder le type avion : "F-16CM-52" → "F-16", "Su-27" → "Su-27"
      const call = raw.replace(/-\d+$/, '').trim();
      const altFL = c.alt!=null&&c.alt>0 ? 'FL'+String(Math.round(c.alt/100)).padStart(3,'0') : '';
      const lH=`<div class="dl-block">
        ${call?`<div class="dl-callsign friend" style="font-size:10px;opacity:.8">${call}</div>`:''}
        ${altFL?`<div class="dl-data friend">${altFL}</div>`:''}
      </div>`;
      const mL=L.marker([c.lat,c.lon],{icon:L.divIcon({
        html:lH,className:'',iconSize:[80,24],iconAnchor:[-(sz/2+2),10]
      }),zIndexOffset:81,interactive:false});
      mL.addTo(map);acmiMarkers.push(mL);
    }
  });
}


// ── HSD Lines L1–L4 (STPTs 31–54) ──────────────────────────────────────
let hsdMarkers = [], hsdVisible = true;

function updateHsdLines(lines) {
  hsdMarkers.forEach(m=>{try{map.removeLayer(m)}catch(e){}});
  hsdMarkers = [];
  if(!lines || !lines.length) return;
  lines.forEach(line => {
    if(!line.points || line.points.length < 2) return;
    const pts = line.points.map(p => [p.lat, p.lon]);
    const poly = L.polyline(pts, {
      color:   line.color || '#4ade80',
      weight:  2,
      opacity: 0.85,
      dashArray: '6 3',
    });
    if(hsdVisible) poly.addTo(map);
    hsdMarkers.push(poly);
    // Label at midpoint
    const mid = pts[Math.floor(pts.length / 2)];
    const lbl = L.marker(mid, {
      icon: L.divIcon({
        html: `<div style="font-family:'Consolas','Courier New',monospace;font-size:9px;font-weight:700;
          color:${line.color};text-shadow:0 1px 4px #000;padding:1px 4px;
          background:rgba(2,6,14,.7);border-radius:1px;white-space:nowrap">${line.line}</div>`,
        className:'', iconSize:[24,14], iconAnchor:[12,7]
      }),
      zIndexOffset: 10
    });
    if(hsdVisible) lbl.addTo(map);
    hsdMarkers.push(lbl);
  });
}

document.getElementById('hsdBtn')?.addEventListener('click', function() {
  hsdVisible = !hsdVisible;
  this.classList.toggle('active', hsdVisible);
  hsdMarkers.forEach(m=>{try{hsdVisible?m.addTo(map):map.removeLayer(m);}catch(e){}});
});

// ── MK Markpoints (pilot mark points, STPTs 26-30) ───────────────────
let mkMarkers=[];
function updateMkMarkpoints(marks){
  mkMarkers.forEach(m=>{try{map.removeLayer(m)}catch(e){}});
  mkMarkers=[];
  if(!marks||!marks.length) return;
  marks.forEach(mk=>{
    if(mk.lat==null||mk.lon==null) return;
    const sym=`<svg width="22" height="22" viewBox="-11 -11 22 22" xmlns="http://www.w3.org/2000/svg">
      <line x1="-9" y1="0" x2="9" y2="0" stroke="${C_MK}" stroke-width="${S_MK}" stroke-linecap="round"/>
      <line x1="0" y1="-9" x2="0" y2="9" stroke="${C_MK}" stroke-width="${S_MK}" stroke-linecap="round"/>
    </svg>`;
    const mS=L.marker([mk.lat,mk.lon],{
      icon:L.divIcon({html:sym,className:'',iconSize:[22,22],iconAnchor:[11,11]}),
      zIndexOffset:150
    }).addTo(map);
    mkMarkers.push(mS);
    const altFL=mk.alt>0?'FL'+String(Math.round(mk.alt/100)).padStart(3,'0'):'';
    const lH=`<div class="dl-block"><div class="dl-callsign" style="color:${C_MK}">${mk.label}${altFL?' · '+altFL:''}</div></div>`;
    const mL=L.marker([mk.lat,mk.lon],{
      icon:L.divIcon({html:lH,className:'',iconSize:[90,20],iconAnchor:[-13,10]}),
      zIndexOffset:151
    }).addTo(map);
    mkMarkers.push(mL);
  });
}
