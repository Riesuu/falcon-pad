// Falcon-Pad — map-core.js
// Map init, utils, shared state, theater, tiles, DMZ, colors, UI prefs
// Copyright (C) 2024 Riesu — GNU GPL v3
// Loaded FIRST — before all other map-*.js files

/** Escape HTML special chars to prevent XSS */
function _esc(s){if(s==null)return'';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}

function showToast(msg, duration) {
  duration = duration || 3000;
  var n = document.createElement('div');
  n.className = 'bms-toast';
  n.textContent = msg;
  document.body.appendChild(n);
  setTimeout(function(){ n.remove(); }, duration);
}

// ── Shared cross-file state ────────────────────────────────────
var _bmsTimeSec = null;
var _bmsTimeTs  = 0;
var _lastAircraftData = null;
var _activeSteerIdx = 0;

// ── Nav utility functions (used by panels.js too) ──────────────
function fmtLL(v, isLon) {
  if (v === undefined || v === null) return '—';
  const dir = isLon ? (v >= 0 ? 'E' : 'W') : (v >= 0 ? 'N' : 'S');
  const abs = Math.abs(v);
  const deg = Math.floor(abs);
  const min = ((abs - deg) * 60).toFixed(3);
  return `${dir} ${String(deg).padStart(isLon?3:2,'0')}° ${min}'`;
}

function haversineNm(lat1, lon1, lat2, lon2) {
  const R = 3440.065;
  const f1 = lat1*Math.PI/180, f2 = lat2*Math.PI/180;
  const df = (lat2-lat1)*Math.PI/180;
  const dl = (lon2-lon1)*Math.PI/180;
  const a = Math.sin(df/2)**2 + Math.cos(f1)*Math.cos(f2)*Math.sin(dl/2)**2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
}

function bearingTo(lat1, lon1, lat2, lon2) {
  const f1 = lat1*Math.PI/180, f2 = lat2*Math.PI/180;
  const dl = (lon2-lon1)*Math.PI/180;
  const y = Math.sin(dl)*Math.cos(f2);
  const x = Math.cos(f1)*Math.sin(f2) - Math.sin(f1)*Math.cos(f2)*Math.cos(dl);
  return ((Math.atan2(y,x)*180/Math.PI) + 360) % 360;
}

// ── Leaflet map ────────────────────────────────────────────────
const map = L.map('map',{preferCanvas:true,zoomControl:true,rotate:true,rotateControl:false,bearing:0,touchRotate:false,shiftKeyRotate:false,compassBearing:false}).setView([37.5,127.5],7);

// ── Theater management ─────────────────────────────────────────
var _currentTheater = null;

function updateTheater(data) {
  if(!data || !data.name) return;
  if(_currentTheater === data.name) return;
  _currentTheater = data.name;
  console.log('[theater] switched to:', data.name);
  _updateTheaterTag(data.name);

  loadAirports();
  if(!followAircraft) map.setView([data.center_lat, data.center_lon], data.zoom);
}

function _updateTheaterTag(name) {
  var el = document.getElementById('theaterTag');
  if(!el) return;
  if(name) { el.textContent = name; el.style.display = 'inline-block'; }
  else { el.style.display = 'none'; }
}

(async function _initTheater() {
  try {
    const d = await (await fetch('/api/theater')).json();
    if(d && d.name) {
      _currentTheater = d.name;
      _updateTheaterTag(d.name);
      if(!window._hasAircraftPos) map.setView([d.center_lat, d.center_lon], d.zoom);
    }
  } catch(e) { console.warn('[theater] init failed:', e); }
})();

if(map.touchRotate) map.touchRotate.disable();
if(map.compassBearing) map.compassBearing.disable();
if(map.shiftKeyRotate) map.shiftKeyRotate.disable();

// ── Tile layers ────────────────────────────────────────────────
const layers = {
  osm:       L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:''}),
  osmfr:     L.tileLayer('https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png',{maxZoom:20,subdomains:'abc',attribution:''}),
  dark:      L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{maxZoom:20,subdomains:'abcd',attribution:''}),
  satellite: L.tileLayer('https://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',{maxZoom:20,subdomains:['mt0','mt1','mt2','mt3'],attribution:''}),
  terrain:   L.tileLayer('https://{s}.google.com/vt/lyrs=p&x={x}&y={y}&z={z}',{maxZoom:20,subdomains:['mt0','mt1','mt2','mt3'],attribution:''})
};
var _activeTileKey = 'dark';
function switchLayer(key) {
  Object.values(layers).forEach(l => { try { map.removeLayer(l); } catch(e){} });
  if(layers[key]) layers[key].addTo(map);
  _activeTileKey = key;
  document.querySelectorAll('input[name="layer"]').forEach(r => r.checked = (r.value === key));
}
layers.dark.addTo(map);
let _darkFallbackDone = false;
layers.dark.on('tileerror', function(){
  if(_darkFallbackDone) return;
  _darkFallbackDone = true;
  map.removeLayer(layers.dark);
  layers.osm.addTo(map);
  _activeTileKey = 'osm';
  document.getElementById('lDark').checked = false;
  document.getElementById('lOsm').checked  = true;
});
map.attributionControl.setPrefix('');


// ── Colors & sizes ─────────────────────────────────────────────
const COLORS=['#ef4444','#f97316','#f59e0b','#eab308','#10b981','#4ade80','#3b82f6','#8b5cf6','#ec4899','#ffffff','#94a3b8','#1e293b'];
var activeColor='#3b82f6';
var C_DRAW  = '#3b82f6';
var S_STPT_LINE  = 2;
var S_FPLAN_LINE = 2;
var C_HSD_L1 = '#4ade80';
var C_HSD_L2 = '#60a5fa';
var C_HSD_L3 = '#f59e0b';
var C_HSD_L4 = '#f87171';
var C_STPT  = '#e2e8f0'; var S_STPT  = 5;
var C_FPLAN = '#f59e0b'; var S_FPLAN = 4;
var C_PPT   = '#ef4444'; var S_PPT   = 1.2; var S_PPT_DOT = 5;
var C_BULL  = '#60a5fa'; var S_BULL  = 8;
var C_MK    = '#fbbf24'; var S_MK    = 2.5;
var C_AIRCRAFT = '#5eead4';
var C_ALLY     = '#4ade80';
var C_ENEMY    = '#ef4444';
var C_UNKNOWN  = '#f59e0b';
var C_AP_BLUE  = '#60a5fa';
var C_AP_RED   = '#f87171';

function applyUiPrefs(p) {
  if(p.color_hsd_l1) C_HSD_L1 = p.color_hsd_l1;
  if(p.color_hsd_l2) C_HSD_L2 = p.color_hsd_l2;
  if(p.color_hsd_l3) C_HSD_L3 = p.color_hsd_l3;
  if(p.color_hsd_l4) C_HSD_L4 = p.color_hsd_l4;
  if(p.color_draw)  C_DRAW  = p.color_draw;
  if(p.size_stpt_line)  S_STPT_LINE  = p.size_stpt_line;
  if(p.size_fplan_line) S_FPLAN_LINE = p.size_fplan_line;
  if(p.color_stpt)  C_STPT  = p.color_stpt;
  if(p.size_stpt)   S_STPT  = p.size_stpt;
  if(p.color_fplan) C_FPLAN = p.color_fplan;
  if(p.size_fplan)  S_FPLAN = p.size_fplan;
  if(p.color_ppt)   C_PPT   = p.color_ppt;
  if(p.size_ppt)    S_PPT   = p.size_ppt;
  if(p.color_bull)  C_BULL  = p.color_bull;
  if(p.color_aircraft) C_AIRCRAFT = p.color_aircraft;
  if(p.color_ally)     C_ALLY     = p.color_ally;
  if(p.color_enemy)    C_ENEMY    = p.color_enemy;
  if(p.color_unknown)  C_UNKNOWN  = p.color_unknown;
  if(p.color_ap_blue)  C_AP_BLUE  = p.color_ap_blue;
  if(p.color_ap_red)   C_AP_RED   = p.color_ap_red;
  if(p.size_bull)   S_BULL  = p.size_bull;
  if(p.active_color && COLORS.includes(p.active_color)) {
    activeColor = p.active_color;
    C_DRAW = p.active_color;
  }
}

// ── UI Prefs persistence ───────────────────────────────────────
async function saveUiPref(patch){
  try{
    const r=await fetch('/api/ui-prefs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(patch)});
    if(!r.ok) console.warn('[ui-prefs] save failed:',r.status,await r.text());
  }catch(e){ console.error('[ui-prefs] save error:',e); }
}

async function loadUiPrefs(){
  try{
    const resp=await fetch('/api/ui-prefs');
    if(!resp.ok) return;
    const p=await resp.json();
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
    if(p.ppt_visible===false){pptCircles.forEach(c=>{try{map.removeLayer(c)}catch(e){}});document.getElementById('pptBtn')?.classList.remove('active');}
    if(p.airports_visible===false){airportMarkers.forEach(m=>{try{map.removeLayer(m)}catch(e){}});document.getElementById('airportBtn')?.classList.remove('active');}
    if(p.runways_visible===false){runwaysVisible=false;document.getElementById('runwayBtn')?.classList.remove('active');runwayLayers.forEach(l=>{try{map.removeLayer(l)}catch(e){}});}
    if(p.ap_name_visible===true){document.getElementById('apNameBtn')?.classList.add('active');apLabelMarkers.forEach(m=>{try{m.addTo(map)}catch(e){}});}
    if(p.bull_visible===false){
      _clearBullseye();
      document.getElementById('bullBtn')?.classList.remove('active');
    }
    if(p.rwy_offsets){ try{ rwyOffsets = JSON.parse(p.rwy_offsets); }catch(e){} }
    if(p.annotations){ try{ _restoreNotes(JSON.parse(p.annotations)); }catch(e){} }
    if(_missionCache) _redrawMission();
  }catch(e){ console.error('[ui-prefs] error:',e); }
}

// ── Shared marker arrays ───────────────────────────────────────
var rulerActive=false,arrowActive=false;
var drawMarkers=[],missionMarkers=[],aircraftMarker=null;
var pptCircles=[],pptLabelMarkers=[],pptLabelsVisible=true,airportMarkers=[];

// ── Touch passive listeners ────────────────────────────────────
try {
  const _mapEl = document.getElementById('map');
  if (_mapEl) {
    _mapEl.addEventListener('touchstart', function(){}, {passive:true});
    _mapEl.addEventListener('touchmove',  function(){}, {passive:true});
  }
} catch(e) {}
