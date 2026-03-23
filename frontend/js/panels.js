// Falcon-Pad — panels.js
// TRTT config, settings, BMS clock, fullscreen, server info,
// tab switching, briefing, kneeboard/nine-lines, checklist, GPS panel
// Copyright (C) 2024 Riesu — GNU GPL v3
// Loaded AFTER map.js, BEFORE websocket.js

// ── App identity — fetched once, populates title/footer/links ───────────
(async function _initAppInfo() {
  try {
    const d = await (await fetch('/api/app/info')).json();
    document.title = d.name || 'Falcon-Pad';
    const nameEl = document.getElementById('app-name');
    if (nameEl) nameEl.textContent = (d.name || 'FALCON-PAD').toUpperCase();
    const linkEl = document.getElementById('app-link');
    if (linkEl) {
      linkEl.textContent = (d.name || 'FALCON-PAD').toUpperCase();
      linkEl.href = d.website || '#';
    }
    // Store for other uses (settings panel, about, etc.)
    window._appInfo = d;
  } catch(e) { console.warn('app/info fetch failed:', e); }
})();

function toggleTRTTPanel(){
  const p=document.getElementById('trttPanel');
  const visible=p.style.display==='none';
  p.style.display=visible?'block':'none';
  if(visible){
    fetch('/api/acmi/status').then(r=>r.json()).then(d=>{
      const parts=(d.trtt_host||'127.0.0.1:42674').split(':');
      document.getElementById('trttHostInput').value=parts[0];
      document.getElementById('trttPortInput').value=parts[1]||'42674';
      const _tps=document.getElementById('trttPanelStatus');if(_tps)_tps.textContent=
        d.connected?'● Connected — '+d.nb_contacts+' contacts':'○ Not connected';
    }).catch(()=>{});
  }
}
async function applyTRTTConfig(){
  const host=document.getElementById('trttHostInput').value.trim();
  const port=parseInt(document.getElementById('trttPortInput').value)||42674;
  if(!host){const _tps=document.getElementById('trttPanelStatus');if(_tps)_tps.textContent='Enter an IP';return;}
  const _tps=document.getElementById('trttPanelStatus');if(_tps)_tps.textContent='Connecting…';
  try{
    const r=await fetch('/api/trtt/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({host,port})});
    const d=await r.json();
    const _tps=document.getElementById('trttPanelStatus');if(_tps)_tps.textContent=d.status==='ok'?'✓ '+d.trtt_host:'Erreur';
    setTimeout(()=>document.getElementById('trttPanel').style.display='none',1500);
  }catch(e){const _tps=document.getElementById('trttPanelStatus');if(_tps)_tps.textContent='Erreur: '+e.message;}
}
document.addEventListener('click',e=>{
  if(!e.target.closest('#trttPanel')&&!e.target.closest('#trttConfigBtn'))
    document.getElementById('trttPanel').style.display='none';
});

// ══════════════════════════════════════════════════════════════════
//  SETTINGS
// ══════════════════════════════════════════════════════════════════
let _settingsOpen = false;
// ── Couleurs & tailles par élément ──────────────────────────────
const _ELEM_KEYS = ['draw','stpt','fplan','ppt','bull','mk'];
const _HSD_KEYS  = ['l1','l2','l3','l4'];

function onHsdColor(key, hex) {
  const varName = 'C_HSD_' + key.toUpperCase();
  if(typeof window[varName] !== 'undefined') window[varName] = hex;
  saveUiPref({['color_hsd_'+key]: hex});
  // Redraw HSD lines immédiatement
  if(typeof _lastHsdLines !== 'undefined') updateHsdLines(_lastHsdLines);
}

function onElemColor(key, hex) {
  const varMap = {draw:'C_DRAW',stpt:'C_STPT',fplan:'C_FPLAN',ppt:'C_PPT',bull:'C_BULL',mk:'C_MK'};
  if(typeof window[varMap[key]] !== 'undefined') window[varMap[key]] = hex;
  if(key==='draw' && typeof activeColor!=='undefined') {
    activeColor = hex;
    document.querySelectorAll('.c-swatch').forEach(s=>s.classList.toggle('sel',s.dataset.color===hex));
  }
  saveUiPref({['color_'+key]: hex});
  // Redraw live
  _redrawElem(key);
}

function onElemSize(key, val) {
  const v = parseFloat(val);
  const varMap = {draw:'S_DRAW',stpt:'S_STPT',fplan:'S_FPLAN',ppt:'S_PPT',bull:'S_BULL',mk:'S_MK'};
  if(typeof window[varMap[key]] !== 'undefined') window[varMap[key]] = v;
  const lbl = document.getElementById('sp-sv-'+key);
  if(lbl) lbl.textContent = v;
  saveUiPref({['size_'+key]: v});
  // Redraw live
  _redrawElem(key);
}

function _redrawElem(key) {
  // Redessine l'élément concerné sans tout recharger
  switch(key) {
    case 'stpt':
    case 'fplan':
    case 'draw':
      if(typeof loadMission === 'function') loadMission();
      break;
    case 'ppt':
      if(typeof loadMission === 'function') loadMission();
      break;
    case 'bull':
      // Redraw bullseye icon only
      if(typeof _bullLat !== 'undefined' && _bullLat != null)
        if(typeof updateBullseye === 'function') updateBullseye(_bullLat, _bullLon);
      break;
    case 'mk':
      if(typeof _lastMkMarks !== 'undefined') updateMkMarkpoints(_lastMkMarks);
      break;
  }
}

function _syncElemControls(p) {
  // HSD line colors
  _HSD_KEYS.forEach(k => {
    const cp = document.getElementById('sp-c-hsd-'+k);
    if(cp && p['color_hsd_'+k]) cp.value = p['color_hsd_'+k];
  });
  _ELEM_KEYS.forEach(k => {
    const cp = document.getElementById('sp-c-'+k);
    const sl = document.getElementById('sp-s-'+k);
    const sv = document.getElementById('sp-sv-'+k);
    if(cp && p['color_'+k]) cp.value = p['color_'+k];
    if(sl && p['size_'+k])  { sl.value = p['size_'+k]; if(sv) sv.textContent = p['size_'+k]; }
  });
}

async function loadSettings() {
  try {
    const d = await(await fetch('/api/settings')).json();
    document.getElementById('sp-port').value    = d.port         || 8000;
    document.getElementById('sp-briefdir').value= d.briefing_dir || '';
    document.getElementById('sp-bcast').value   = d.broadcast_ms || 200;
    // Sync couleurs & tailles des éléments
    _syncElemControls(d);
  } catch(e) {}
}

function toggleSettings() {
  _settingsOpen = !_settingsOpen;
  document.getElementById('settingsPanel').classList.toggle('open', _settingsOpen);
  if (_settingsOpen) loadSettings();
}



async function saveSettings() {
  const port     = parseInt(document.getElementById('sp-port').value);
  const bdir     = document.getElementById('sp-briefdir').value.trim();
  const bcast    = parseInt(document.getElementById('sp-bcast').value);
  const status   = document.getElementById('sp-status');
  const portWarn = document.getElementById('sp-port-warn');

  status.textContent = '⏳ Saving…';
  status.classList.add('show');

  try {
    const r = await fetch('/api/settings', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        port:         isNaN(port)  ? null : port,
        briefing_dir: bdir         || null,
        broadcast_ms: isNaN(bcast) ? null : bcast,
      })
    });
    const d = await r.json();
    if (d.ok) {
      status.textContent = '✓ Saved — ' + d.changed.join(', ');
      status.style.color = '#4ade80';
      if (d.needs_restart) {
        portWarn.classList.add('show');
        status.textContent += ' — RESTART SCRIPT';
        status.style.color = '#fbbf24';
      }
      setTimeout(() => {
        status.classList.remove('show');
        if (!d.needs_restart) toggleSettings();
      }, 2200);
    } else {
      status.textContent = '✗ Error';
      status.style.color = '#ef4444';
    }
  } catch(e) {
    status.textContent = '✗ ' + e;
    status.style.color = '#ef4444';
  }
}

// Fermer settings si clic sur la carte
document.getElementById('map').addEventListener('click', () => {
  if (_settingsOpen) toggleSettings();
});

// ── Horloge — BMS time prioritaire, fallback UTC ─────────────────

function updateZulu(){
  const el = document.getElementById('zuluClock');
  if (!el) return;
  let secs = null;
  // Si BMS time reçu récemment (< 5s), interpoler depuis le timestamp
  if (typeof _bmsTimeSec !== 'undefined' && _bmsTimeSec !== null && (Date.now() - _bmsTimeTs) < 5000) {
    const elapsed = Math.floor((Date.now() - _bmsTimeTs) / 1000);
    secs = (_bmsTimeSec + elapsed) % 86400;
    el.title = 'BMS Time';
    el.style.color = 'rgba(74,222,128,.55)';
  } else {
    // Fallback UTC
    const n = new Date();
    secs = n.getUTCHours()*3600 + n.getUTCMinutes()*60 + n.getUTCSeconds();
    el.title = 'UTC Time (BMS not connected)';
    el.style.color = 'rgba(74,222,128,.35)';
  }
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  el.textContent = String(h).padStart(2,'0')+':'+String(m).padStart(2,'0')+':'+String(s).padStart(2,'0')+'Z';
}
updateZulu(); setInterval(updateZulu, 1000);

// ── Fullscreen ───────────────────────────────────────────────────
function toggleFullscreen(){
  if(!document.fullscreenElement){
    document.documentElement.requestFullscreen().catch(e=>{});
  } else {
    document.exitFullscreen().catch(e=>{});
  }
}
document.addEventListener('fullscreenchange',()=>{
  const btn = document.getElementById('fsBtn');
  const icon = document.getElementById('fsIcon');
  if(!btn||!icon) return;
  const fs = !!document.fullscreenElement;
  btn.style.color = fs ? 'rgba(74,222,128,.7)' : 'rgba(74,222,128,.3)';
  // Changer icône : exit si fullscreen, enter si normal
  icon.innerHTML = fs
    ? '<polyline points="9 3 3 3 3 9"/><polyline points="15 21 21 21 21 15"/><line x1="3" y1="3" x2="10" y2="10"/><line x1="21" y1="21" x2="14" y2="14"/>'
    : '<polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/>';
});

// ── Affichage IP serveur ─────────────────────────────────────────
(async function loadServerIp(){
  try{
    const d = await(await fetch('/api/server/info')).json();
    const el = document.getElementById('sysServerIp');
    if(el && d.ip){
      el.textContent = d.ip + ':' + d.port;
      el.title = 'Tablet → ' + d.url;
    }
  } catch(e){ /* silencieux */ }
})();

document.addEventListener('click',e=>{
  if(!e.target.closest('#colorPanel')&&!e.target.closest('#colorBtn'))
    document.getElementById('colorPanel').classList.remove('open');
  if(!e.target.closest('#layerPanel')&&!e.target.closest('#layerBtn'))
    document.getElementById('layerPanel').classList.remove('open');

  if(!e.target.closest('#calPanel')&&!_calMode)
    document.getElementById('calPanel').style.display='none';
});


// ══ Checklist Ramp Start BMS 4.38 ═══════════════════════════════
const CL_DATA=[
  {section:'BOARDING'},
  {n:1, item:'Canopy',            status:'Closed & locked',              loc:'sidewall & spider'},
  {n:2, item:'Exterior Lights',   status:'ON',                           loc:'Ext Lightning panel'},
  {n:3, item:'Engine Feed',       status:'NORM',                         loc:'Fuel panel'},
  {n:4, item:'Elec. Power',       status:'Main Power ON',                loc:'Elec panel'},
  {n:5, item:'ILS',               status:'Set as required',              loc:'Audio 2 panel'},
  {n:6, item:'Radio & volume',    status:'ON / Set',                     loc:'Audio 1 panel'},
  {n:7, item:'Radio Mode',        status:'Both UHF',                     loc:'Backup panel'},
  {n:8, item:'Vol IVC/AI',        status:'Set as desired',               loc:'UHF Backup panel'},
  {n:9, item:'Cockpit lights',    status:'Set as desired',               loc:'Lightning panel'},
  {n:10,item:'Air Source',        status:'NORM',                         loc:'Air Cond panel'},
  {n:11,item:'Anti-ice',          status:'ON',                           loc:'Anti-ice panel'},
  {n:12,item:'Radio',             status:'IVC-UHF BACKUP 6 / 225.00',   loc:'callsign - ready to start engine'},
  {section:'ENGINE START & CHECK'},
  {n:1, item:'Throttle',          status:'Check / IDLE CUTOFF',          loc:'IRL & 3D'},
  {n:2, item:'Start 2',           status:'ON — wait >20% RPM & SEC off', loc:'JFS panel'},
  {n:3, item:'Idle Detent',       status:'Toggle',                       loc:'Throttle'},
  {note:'FTIT <650 — OTHERWISE SHUTDOWN IMMEDIATELY! Hyd/oil >15PSI/40bar'},
  {n:4, item:'RPM',               status:'CHECK 70%',                    loc:'Engine gauges'},
  {n:5, item:'Master Caution',    status:'RESET',                        loc:'Left Eyebrow'},
  {n:6, item:'FLCS',              status:'RESET',                        loc:'Flt control panel'},
  {n:7, item:'Probe Heat',        status:'ON',                           loc:'Test panel'},
  {n:8, item:'Master Caution',    status:'CHECK OFF',                    loc:'Left eyebrow'},
  {n:9, item:'Probe Heat light',  status:'CHECK OFF',                    loc:'Caution panel'},
  {section:'AVIONICS START'},
  {n:1, item:'Avionics Power',    status:'ON — EGI ALIGN NORM',          loc:'Avionics Power panel'},
  {n:2, item:'Sensors Power',     status:'ON — RDR ALT STD-BY',          loc:'Sensor power panel'},
  {n:3, item:'Sym',               status:'Set as desired',               loc:'ICP'},
  {n:4, item:'RWR',               status:'ON',                           loc:'Threat warning aux'},
  {n:5, item:'EWS Power',         status:'ON',                           loc:'CMDS panel'},
  {n:6, item:'HMCS',              status:'Set as desired',               loc:'HMCS panel'},
  {n:7, item:'ECM',               status:'OPR ON',                       loc:'ECM panel'},
  {n:8, item:'C&I',               status:'UFC',                          loc:'IFF panel'},
  {n:9, item:'IFF Master',        status:'STAND-BY',                     loc:'IFF panel'},
  {n:10,item:'INS',               status:'NAV (after READY)',            loc:'Avionics Power panel'},
  {n:11,item:'MIDS',              status:'ON',                           loc:'Avionics Power panel'},
  {n:12,item:'Test',              status:'Clear & check',                loc:'MFD'},
  {n:13,item:'DTE Load',          status:'Load (after MIDS INIT)',       loc:'MFD'},
  {n:14,item:'Radio freq & nav',  status:'Check',                        loc:'MFD & DED'},
  {n:15,item:'Radio',             status:'IVC-VHF Flight',               loc:'callsign - radio check on victor'},
  {section:'SETTINGS'},
  {n:1, item:'Trim',              status:'Set as required',              loc:'Manual Trim panel'},
  {n:2, item:'CatI/III',          status:'Set as required',              loc:'LG panel'},
  {n:3, item:'RWR Mode',          status:'Set as desired',               loc:'Threat warning prime'},
  {n:4, item:'HMCS',              status:'Aligned',                      loc:'ICP'},
  {n:5, item:'TCN / ILS',         status:'Set as briefed',               loc:'ICP'},
  {n:6, item:'Joker / Bingo',     status:'Set as briefed',               loc:'ICP'},
  {n:7, item:'Data-link members', status:'Set as briefed',               loc:'ICP'},
  {n:8, item:'Loadout (SMS)',      status:'Set as briefed',               loc:'MFD'},
  {n:9, item:'Selective Jettison',status:'Pre-set as required',          loc:'MFD'},
  {n:10,item:'TGP/WPN/HAD',       status:'ON and set',                   loc:'MFD'},
  {n:11,item:'HDG - CRS',         status:'Set as required',              loc:'HSI'},
  {n:12,item:'Alt Baro',          status:'Set',                          loc:'HUD panel'},
  {n:13,item:'Seat',              status:'Adjust as desired',            loc:'Right sidewall'},
  {section:'BEFORE TAXI'},
  {n:1, item:'Anti-ice',          status:'AUTO (after 2min)',            loc:'Anti-ice panel'},
  {n:2, item:'Oxygen supply',     status:'ON (after 2min)',              loc:'Oxygen regulator'},
  {n:3, item:'RDR ALT',           status:'ON',                           loc:'SNSR Power panel'},
  {n:4, item:'NWS',               status:'Engaged',                      loc:'Stick & Right indexer'},
  {n:5, item:'FCR',               status:'CRM',                          loc:'MFD'},
  {n:6, item:'Landing Lights',    status:'TAXI',                         loc:'GEAR panel'},
  {n:7, item:'Seat',              status:'ARMED',                        loc:'Seat'},
  {n:8, item:'IFF Master',        status:'NORM',                         loc:'IFF panel'},
  {n:9, item:'Position Lights',   status:'FLASH',                        loc:'Ext Lightning panel'},
  {n:10,item:'Radio',             status:'Ground',                       loc:'Remove EPU pins & remove chocks'},
  {n:11,item:'Brakes',            status:'Check',                        loc:'Rudder/throttle'},
  {n:12,item:'Master Caution',    status:'CHECK OFF',                    loc:'Eyebrow'},
  {n:13,item:'F-ACK (PFL)',       status:'CHECK OFF',                    loc:'Eyebrow/PFL'},
  {n:14,item:'Warning Lights',    status:'CHECK OFF',                    loc:'Caution panel'},
  {n:15,item:'Radio',             status:'IVC',                          loc:'callsign - ready to taxi'},
  {n:16,item:'Radio (Lead)',      status:'Ground',                       loc:'ready to taxi'},
  {section:'BEFORE TAKE OFF (Hold Short)'},
  {n:1, item:'Radio',             status:'IVC',                          loc:'callsign - holdshort'},
  {n:2, item:'Pressure QNH',      status:'Set',                          loc:'Instr altimeter'},
  {n:3, item:'Data-link BIT (Deputy)',status:'CONT & Send',              loc:'MFD & TQS'},
  {n:4, item:'Landing Light',     status:'ON',                           loc:'LG panel'},
  {n:5, item:'ACMI (Deputies)',   status:'Recording ON',                 loc:''},
  {n:6, item:'Visor',             status:'Set as desired',               loc:'Helmet'},
  {n:7, item:'Radio Tower (Lead)',status:'Ready for departure',          loc:''},
];

let clState={};
try{clState=JSON.parse(localStorage.getItem('bms_cl_state')||'{}');}catch(e){}
function clSave(){try{localStorage.setItem('bms_cl_state',JSON.stringify(clState));}catch(e){}}

let clOpenSecs={};
try{clOpenSecs=JSON.parse(sessionStorage.getItem('bms_cl_open')||'{}');}catch(e){}
function clSaveOpen(){try{sessionStorage.setItem('bms_cl_open',JSON.stringify(clOpenSecs));}catch(e){}}

function clRender(){
  const list=document.getElementById('cl-list');
  if(!list)return;

  // Pre-count items per section
  let secCounts={},curSec='';
  CL_DATA.forEach(row=>{
    if(row.section){curSec=row.section;secCounts[curSec]={total:0,done:0};}
    else if(row.n && curSec){
      secCounts[curSec].total++;
      const key=`${curSec}_${row.n}`;
      if(clState[key])secCounts[curSec].done++;
    }
  });

  let html='',sec='',total=0,done=0,groupOpen=false;
  CL_DATA.forEach((row,idx)=>{
    if(row.section){
      // Close previous group
      if(groupOpen) html+='</div>';
      sec=row.section;
      const isOpen=!!clOpenSecs[sec];
      const cnt=secCounts[sec]||{total:0,done:0};
      const badge=cnt.done>0?`<span class="cl-section-count">${cnt.done}/${cnt.total}</span>`
                             :`<span class="cl-section-count">${cnt.total}</span>`;
      html+=`<div class="cl-section${isOpen?' open':''}" onclick="clToggleSec(this,'${sec.replace(/'/g,"\\'")}')">
        ${row.section}${badge}</div>`;
      html+=`<div class="cl-group${isOpen?' open':''}">`;
      groupOpen=true;
    } else if(row.note){
      html+=`<div class="cl-note">&#9888; ${row.note}</div>`;
    } else {
      const key=`${sec}_${row.n}`;
      const chk=!!clState[key];
      total++;if(chk)done++;
      html+=`<div class="cl-row${chk?' done':''}" onclick="clToggle('${key}',this)">
        <input type="checkbox" class="cl-cb"${chk?' checked':''} onclick="event.stopPropagation();clToggle('${key}',this.closest('.cl-row'))">
        <span class="cl-num">${row.n}</span>
        <span class="cl-item">${row.item}<br><span style="font-size:10px;color:#475569">${row.loc}</span></span>
        <span class="cl-status">${row.status}</span>
      </div>`;
    }
  });
  if(groupOpen) html+='</div>';
  list.innerHTML=html;
  const p=document.getElementById('cl-prog');
  if(p)p.textContent=`${done} / ${total}`;
}

function clToggleSec(el,sec){
  const isOpen=el.classList.toggle('open');
  const group=el.nextElementSibling;
  if(group)group.classList.toggle('open',isOpen);
  clOpenSecs[sec]=isOpen;clSaveOpen();
}

function clToggle(key,row){
  clState[key]=!clState[key];clSave();
  if(row){row.classList.toggle('done',clState[key]);const cb=row.querySelector('.cl-cb');if(cb)cb.checked=clState[key];}
  const p=document.getElementById('cl-prog');
  if(p){const d=Object.values(clState).filter(Boolean).length,t=CL_DATA.filter(r=>r.n).length;p.textContent=`${d} / ${t}`;}
  // Update section badges
  document.querySelectorAll('.cl-section').forEach(secEl=>{
    const secName=secEl.textContent.replace(/\d+\/?\d*/g,'').trim();
    const badge=secEl.querySelector('.cl-section-count');
    if(!badge)return;
    let st=0,sd=0;
    CL_DATA.forEach(r=>{if(r.section===secName)st=-1;if(st===-1&&r.n){st++;const k=secName+'_'+r.n;if(clState[k])sd++;}});
    // recount properly
    let t2=0,d2=0,inSec=false;
    CL_DATA.forEach(r=>{if(r.section===secName)inSec=true;else if(r.section)inSec=false;
      if(inSec&&r.n){t2++;if(clState[secName+'_'+r.n])d2++;}});
    badge.textContent=d2>0?d2+'/'+t2:String(t2);
  });
}

function clReset(){clState={};clOpenSecs={};clSave();clSaveOpen();clRender();}
function clToggleMaster(){
  const m=document.getElementById('cl-master');
  const b=document.getElementById('cl-master-body');
  if(!m||!b)return;
  const isOpen=m.classList.toggle('open');
  b.classList.toggle('open',isOpen);
}
clRender(); // Init on page load

// ── Tab switching ────────────────────────────────────────────────
var PANELS = {
  gps:       document.getElementById('panel-gps'),
  charts:    document.getElementById('panel-charts'),
  kneeboard: document.getElementById('panel-kneeboard'),
  briefing:  document.getElementById('panel-briefing'),
};
let _activeTab = null;
let _chartsLoaded = false;

function switchTab(name, btn) {
  const panel = PANELS[name];
  if (!panel) return;

  // Toggle: cliquer sur l'onglet actif le ferme
  if (_activeTab === name) {
    panel.classList.remove('open');
    btn.classList.remove('active');
    _activeTab = null;
    return;
  }

  // Fermer tous les autres
  Object.entries(PANELS).forEach(([k, p]) => {
    p.classList.remove('open');
  });
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));

  panel.classList.add('open');
  btn.classList.add('active');
  _activeTab = name;

  // Charger la Charts iframe au premier clic
  if (name === 'charts' && !_chartsLoaded) {
    _chartsLoaded = true;
    document.getElementById('charts-frame').src = (window._appInfo && window._appInfo.website) || 'https://www.falcon-charts.com';
  }

  // Refresh GPS data immédiatement
  if (name === 'gps') refreshGpsPanel();

  // Charger la liste briefing à chaque ouverture
  if (name === 'briefing') briefingLoadList();
}

// ══════════════════════════════════════════════════════════════════
//  BRIEFING
// ══════════════════════════════════════════════════════════════════
let _briefActive = null;

function briefingLoadList() {
  fetch('/api/briefing/list')
    .then(r => r.json())
    .then(d => briefingRenderList(d.files))
    .catch(() => {});
}

function briefingRenderList(files) {
  const list  = document.getElementById('briefFileList');
  const count = document.getElementById('briefFileCount');
  count.textContent = files.length + ' DOC';
  if (!files.length) {
    list.innerHTML = '<div class="brief-empty">No documents<br>Import PDF, image<br>or Word (.docx)</div>';
    return;
  }
  list.innerHTML = files.map(f => {
    const iconCls = f.ext === 'pdf' ? 'pdf' : (f.ext === 'docx' ? 'docx' : 'img');
    const label   = f.ext.toUpperCase();
    const isActive = _briefActive === f.name ? ' active' : '';
    return `<div class="brief-file-item${isActive}" onclick="briefingOpen('${f.name}','${f.ext}')" data-name="${f.name}">
      <div class="brief-file-icon ${iconCls}">${label}</div>
      <div class="brief-file-info">
        <div class="brief-file-name">${f.name}</div>
        <div class="brief-file-meta">${f.size_kb} KB · ${f.modified}</div>
      </div>
      <span class="brief-file-del" onclick="event.stopPropagation();briefingDelete('${f.name}')" title="Delete">✕</span>
    </div>`;
  }).join('');
}

function briefingOpen(name, ext) {
  _briefActive = name;
  // Mettre à jour sélection visuelle
  document.querySelectorAll('.brief-file-item').forEach(el => {
    el.classList.toggle('active', el.dataset.name === name);
  });
  const iframe = document.getElementById('briefIframe');
  const ph     = document.getElementById('briefPlaceholder');
  const url    = '/api/briefing/file/' + encodeURIComponent(name);
  iframe.src   = url;
  iframe.style.display = 'block';
  ph.style.display     = 'none';
}

async function briefingUpload(files) {
  if (!files || !files.length) return;
  const btn = document.querySelector('.brief-upload-btn');
  const origTxt = btn.innerHTML;
  btn.innerHTML = '⏳ UPLOADING…';
  btn.style.pointerEvents = 'none';
  let lastFiles = [];
  for (const file of files) {
    const fd = new FormData();
    fd.append('file', file);
    try {
      const r = await fetch('/api/briefing/upload', {method:'POST', body:fd});
      const d = await r.json();
      if (d.files) lastFiles = d.files;
    } catch(e) { console.error('Upload erreur:', e); }
  }
  briefingRenderList(lastFiles);
  btn.innerHTML = origTxt;
  btn.style.pointerEvents = '';
  // Reset input
  document.getElementById('briefingFileInput').value = '';
}

async function briefingDelete(name) {
  if (!confirm('Delete "' + name + '" ?')) return;
  try {
    const r = await fetch('/api/briefing/delete/' + encodeURIComponent(name), {method:'DELETE'});
    const d = await r.json();
    if (_briefActive === name) {
      _briefActive = null;
      document.getElementById('briefIframe').style.display = 'none';
      document.getElementById('briefPlaceholder').style.display = 'flex';
    }
    briefingRenderList(d.files);
  } catch(e) { console.error('Delete erreur:', e); }
}

// ── Kneeboard subtabs ────────────────────────────────────────────
function switchKbTab(name, el) {
  document.querySelectorAll('.kb-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.kb-page').forEach(p => p.classList.remove('active'));
  el.classList.add('active');
  const page = document.getElementById('kb-' + name);
  if (page) page.classList.add('active');
  if(name==='chklist') setTimeout(clRender,0);
}

// Persister kneeboard (notes, plan de vol, 9-line)
const _kbPersist = {
  'kb-notes-ta':'bms_kb_notes',
  'kb-fplan-ta':'bms_kb_fplan',
  'kb-callsign':'bms_kb_callsign','kb-package':'bms_kb_package',
  'kb-tot':'bms_kb_tot','kb-tanker':'bms_kb_tanker',
  'kb-bull-val':'bms_kb_bull','kb-bingo':'bms_kb_bingo',
  'kb-9l-1':'bms_9l_1','kb-9l-2':'bms_9l_2','kb-9l-3':'bms_9l_3',
  'kb-9l-4':'bms_9l_4','kb-9l-5':'bms_9l_5','kb-9l-6':'bms_9l_6',
  'kb-9l-7':'bms_9l_7','kb-9l-8':'bms_9l_8','kb-9l-9':'bms_9l_9',
  'kb-9l-laser':'bms_9l_laser',
  'kb-fac-id':'bms_fac_id','kb-fac-self':'bms_fac_self',
  'kb-pre-1':'bms_pre_1','kb-pre-2':'bms_pre_2','kb-pre-3':'bms_pre_3',
  'kb-pre-4':'bms_pre_4','kb-pre-5':'bms_pre_5','kb-pre-6':'bms_pre_6',
  'kb-rmk':'bms_9l_rmk','kb-fah':'bms_9l_fah','kb-thr':'bms_9l_thr','kb-tot9':'bms_9l_tot9',
};
Object.entries(_kbPersist).forEach(([id,key])=>{
  const el=document.getElementById(id);
  if(!el)return;
  try{el.value=localStorage.getItem(key)||'';}catch(e){}
  el.addEventListener('input',()=>{try{localStorage.setItem(key,el.value);}catch(e){}});
});
// Persistance radio offset
try{
  const sv=localStorage.getItem('bms_cas_offset');
  if(sv){const r=document.querySelector(`input[name="cas-offset"][value="${sv}"]`);if(r)r.checked=true;}
}catch(e){}
document.querySelectorAll('input[name="cas-offset"]').forEach(r=>{
  r.addEventListener('change',()=>{try{localStorage.setItem('bms_cas_offset',r.value);}catch(e){}});
});
function clearNineLines(){
  const ids=['kb-9l-1','kb-9l-2','kb-9l-3','kb-9l-4','kb-9l-5','kb-9l-6','kb-9l-7','kb-9l-8','kb-9l-9',
    'kb-9l-laser','kb-fac-id','kb-fac-self','kb-pre-1','kb-pre-2','kb-pre-3','kb-pre-4','kb-pre-5','kb-pre-6',
    'kb-rmk','kb-fah','kb-thr','kb-tot9'];
  ids.forEach(id=>{
    const el=document.getElementById(id);
    if(el){el.value='';try{localStorage.removeItem('bms_'+id.replace('kb-',''));}catch(e){}}
  });
  // Reset radios
  document.querySelectorAll('input[name="cas-offset"]').forEach(r=>r.checked=false);
  try{localStorage.removeItem('bms_cas_offset');}catch(e){}
}
function copyNineLines(){
  const g=id=>document.getElementById(id)?.value||'';
  const offset=document.querySelector('input[name="cas-offset"]:checked')?.value||'';
  const lines=[
    `FAC: "${g('kb-fac-id')}, this is ${g('kb-fac-self')}, standing by for aircraft check-in"`,
    `Leader/Mission: ${g('kb-pre-1')}`,
    `Aircraft: ${g('kb-pre-2')}`,
    `Position/Alt: ${g('kb-pre-3')}`,
    `Ordinance: ${g('kb-pre-4')}`,
    `TOS: ${g('kb-pre-5')}`,
    g('kb-pre-6')?`Remarks: ${g('kb-pre-6')}`:'',
    '---',
    `1. IP/BP: ${g('kb-9l-1')}`,
    `2. Heading: ${g('kb-9l-2')}${offset?' | Offset: '+offset:''}`,
    `3. Distance: ${g('kb-9l-3')}`,
    `4. Elevation: ${g('kb-9l-4')}`,
    `5. Target: ${g('kb-9l-5')}`,
    `6. Location: ${g('kb-9l-6')}`,
    `7. Mark: ${g('kb-9l-7')}${g('kb-9l-laser')?' | Laser: '+g('kb-9l-laser'):''}`,
    `8. Friendlies: ${g('kb-9l-8')}`,
    `9. Egress: ${g('kb-9l-9')}`,
    '---',
    g('kb-rmk')?`Remarks: ${g('kb-rmk')}`:'',
    g('kb-fah')?`Final Attack Hdg: ${g('kb-fah')}`:'',
    g('kb-thr')?`Threats: ${g('kb-thr')}`:'',
    g('kb-tot9')?`TOT: ${g('kb-tot9')}`:'',
  ].filter(Boolean);
  try{navigator.clipboard.writeText(lines.join('\n'));}catch(e){}
  showToast('9-LINE COPIED');
}

// GPS utilities (bearingTo, haversineNm, fmtLL) → moved to map.js

function refreshGpsPanel() {
  const d = _lastAircraftData;
  if (!d) return;
  document.getElementById('gps-lat').textContent  = fmtLL(d.lat, false);
  document.getElementById('gps-lon').textContent  = fmtLL(d.lon, true);
  document.getElementById('gps-hdg').textContent  = d.heading  != null ? String(Math.round(d.heading)).padStart(3,'0') + '°' : '—';
  document.getElementById('gps-alt').textContent  = d.altitude != null ? 'FL' + String(Math.round(Math.abs(d.altitude)/100)).padStart(3,'0') : '—';
  document.getElementById('gps-kias').textContent = d.kias     != null && d.kias > 5 ? Math.round(d.kias) + ' kt' : '—';

  // Distance au steerpoint actif
  let distText = '—';
  const steerChips = document.querySelectorAll('.steer-chip');
  if (steerChips.length && _lastMissionRoute && _lastMissionRoute[_activeSteerIdx]) {
    const sp = _lastMissionRoute[_activeSteerIdx];
    const nm = haversineNm(d.lat, d.lon, sp.lat, sp.lon);
    const brg = bearingTo(d.lat, d.lon, sp.lat, sp.lon);
    distText = String(Math.round(brg)).padStart(3,'0') + '° / ' + nm.toFixed(1) + ' NM';
  }
  document.getElementById('gps-dist').textContent = distText;

  // Bullseye bearing/distance
  const bullEl = document.getElementById('gps-bull');
  if (bullEl) {
    if (_bullLat != null && _bullLon != null && d.lat && d.lon) {
      const bBrg = bearingTo(d.lat, d.lon, _bullLat, _bullLon);
      const bNm  = haversineNm(d.lat, d.lon, _bullLat, _bullLon);
      bullEl.textContent = String(Math.round(bBrg)).padStart(3,'0') + '° / ' + bNm.toFixed(1) + ' NM';
    } else {
      bullEl.textContent = '—';
    }
  }
}

let _lastMissionRoute = [];
function buildGpsSteers(route) {
  _lastMissionRoute = route;
  const list = document.getElementById('gps-steer-list');
  const count = document.getElementById('gps-steer-count');
  list.innerHTML = '';
  if (!route || !route.length) {
    list.innerHTML = '<span style="font-family:system-ui,sans-serif;font-size:11px;color:#3d6b52;padding:4px 0">Aucun plan de vol chargé</span>';
    count.textContent = '0 WPT';
    return;
  }
  count.textContent = route.length + ' WPT';
  route.forEach((sp, i) => {
    const chip = document.createElement('div');
    chip.className = 'steer-chip' + (i === _activeSteerIdx ? ' active' : '');
    chip.innerHTML = `<span class="steer-num">STPT ${i+1}</span>
      <span class="steer-fl">FL${String(Math.round(Math.abs(sp.alt)/100)).padStart(3,'0')}</span>`;
    chip.onclick = () => {
      _activeSteerIdx = i;
      document.querySelectorAll('.steer-chip').forEach((c,j) => c.classList.toggle('active', j===i));
      refreshGpsPanel();
    };
    list.appendChild(chip);
  });
}

// Hook into existing updateAircraft and loadMission
const _origUpdateAircraft = updateAircraft;
window.updateAircraft = function(d) {
  _origUpdateAircraft(d);
  _lastAircraftData = d;
  if (_activeTab === 'gps') refreshGpsPanel();
};

const _origLoadMission = loadMission;
window.loadMission = function() {
  _origLoadMission();
  // Rebuild steerpoints after data loads
  setTimeout(() => {
    fetch('/api/mission').then(r=>r.json()).then(md => {
      const route = md.route && md.route.length ? md.route : (md.flightplan || []);
      buildGpsSteers(route);
    });
  }, 300);
};

// Close panels when clicking on map
map.on('click', () => {
  if (_activeTab && _activeTab !== 'gps') {
    // Ne ferme pas sur clic map pour GPS (utile en vol)
    PANELS[_activeTab].classList.remove('open');
    document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
    _activeTab = null;
  }
});

// Init mission on secondary device (tablet) — retry with delay
(async function _initMission(){
  for(let attempt=0;attempt<3;attempt++){
    try{
      await new Promise(r=>setTimeout(r, 1000 + attempt*2000));
      const s=await(await fetch('/api/ini/status')).json();
      console.log('[INIT] ini/status attempt',attempt+1,':',JSON.stringify(s));
      if(s.loaded&&s.mtime&&s.mtime!==_lastIniMtime){
        _lastIniFile=s.file;_lastIniMtime=s.mtime;
        loadMission();
        console.log('[INIT] Mission loaded:',s.file,'mtime:',s.mtime);
        return;
      }
    }catch(e){console.warn('[INIT] error:',e);}
  }
  console.log('[INIT] No mission found after 3 attempts');
})();
