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
  } catch(e) { /* app/info fetch failed */ }
})();


// ══════════════════════════════════════════════════════════════════
//  SETTINGS
// ══════════════════════════════════════════════════════════════════
let _settingsOpen = false;
// ── Element colors & sizes ──────────────────────────────────────
const _ELEM_KEYS = ['stpt','fplan','ppt'];
const _HSD_KEYS  = ['l1','l2','l3','l4'];

function onHsdColor(key, hex) {
  const varName = 'C_HSD_' + key.toUpperCase();
  if(typeof window[varName] !== 'undefined') window[varName] = hex;
  saveUiPref({['color_hsd_'+key]: hex});
  // Redraw HSD lines immediately
  if(typeof _lastHsdLines !== 'undefined' && typeof updateHsdLines === 'function') updateHsdLines(_lastHsdLines);
}

function onElemColor(key, hex) {
  const varMap = {draw:'C_DRAW',stpt:'C_STPT',fplan:'C_FPLAN',ppt:'C_PPT'};
  if(typeof window[varMap[key]] !== 'undefined') window[varMap[key]] = hex;
  if(key==='draw' && typeof activeColor!=='undefined') {
    activeColor = hex;
    document.querySelectorAll('.c-swatch').forEach(s=>s.classList.toggle('sel',s.dataset.color===hex));
  }
  saveUiPref({['color_'+key]: hex});
  // Color: direct update of existing layers (no redraw)
  if(typeof window._setMapColor === 'function') window._setMapColor(key, hex);
}

var _apColorTimer = null;
function onCustomColor(key, hex) {
  const varMap = {aircraft:'C_AIRCRAFT',ally:'C_ALLY',enemy:'C_ENEMY',ap_blue:'C_AP_BLUE',ap_red:'C_AP_RED'};
  if(varMap[key]) window[varMap[key]] = hex;
  saveUiPref({['color_'+key]: hex});
  if(key==='ap_blue'||key==='ap_red') {
    clearTimeout(_apColorTimer);
    _apColorTimer = setTimeout(function(){ _apColorTimer=null; if(typeof loadAirports==='function') loadAirports(); }, 400);
  }
}

function onBullColor(hex) {
  C_BULL = hex;
  saveUiPref({color_bull: hex});
  if(_bullLat != null) _buildBullseye(_bullLat, _bullLon);
}

function onElemSize(key, val) {
  const v = parseFloat(val);
  const varMap = {draw:'S_DRAW',stpt:'S_STPT',fplan:'S_FPLAN',ppt:'S_PPT'};
  if(typeof window[varMap[key]] !== 'undefined') window[varMap[key]] = v;
  const lbl = document.getElementById('sp-sv-'+key);
  if(lbl) lbl.textContent = v;
  saveUiPref({['size_'+key]: v});
  // Size: recreation needed
  if(typeof window._setMapSize === 'function') window._setMapSize(key, v);
}

function _redrawElem(key) {
  switch(key) {
    case 'stpt':
    case 'fplan':
    case 'draw':
    case 'ppt':
      // Use cached redraw — no fetch, no setView
      if(typeof _redrawMission === 'function') _redrawMission();
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
  // Bullseye color picker
  const bullCp = document.getElementById('sp-c-bull');
  if(bullCp && p.color_bull) bullCp.value = p.color_bull;
  const bullSz = document.getElementById('sp-s-bull');
  if(bullSz && p.size_bull) bullSz.value = p.size_bull;
  // Aircraft / contacts / airport colors
  ['aircraft','ally','enemy','ap_blue','ap_red'].forEach(k => {
    const cp = document.getElementById('sp-c-'+k);
    if(cp && p['color_'+k]) cp.value = p['color_'+k];
  });
}

async function loadSettings() {
  try {
    const d = await(await fetch('/api/settings')).json();
    document.getElementById('sp-port').value    = d.port         || 8000;
    document.getElementById('sp-bcast').value   = d.broadcast_ms || 200;
    // Sync element colors & sizes
    _syncElemControls(d);
  } catch(e) {
    console.error('[settings] load failed:', e);
    const st = document.getElementById('sp-status');
    if(st){ st.textContent='✗ Failed to load settings'; st.style.color='#ef4444'; st.classList.add('show'); }
  }
}

function toggleSettings() {
  _settingsOpen = !_settingsOpen;
  document.getElementById('settingsPanel').classList.toggle('open', _settingsOpen);
  if(typeof window._setSettingsOpen === 'function') window._setSettingsOpen(_settingsOpen);
  if (_settingsOpen) loadSettings();
}



async function saveSettings() {
  const port     = parseInt(document.getElementById('sp-port').value);
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

// ── Clock — BMS time priority, fallback UTC ──────────────────────

function updateZulu(){
  const el = document.getElementById('zuluClock');
  if (!el) return;
  let secs = null;
  // If BMS time received recently (< 5s), interpolate from timestamp
  if (typeof _bmsTimeSec !== 'undefined' && _bmsTimeSec !== null && (Date.now() - _bmsTimeTs) < 5000) {
    const elapsed = Math.floor((Date.now() - _bmsTimeTs) / 1000);
    secs = (_bmsTimeSec + elapsed) % 86400;
    el.title = 'BMS Time';
    el.style.color = 'rgba(74,222,128,1)';
  } else {
    // Fallback UTC
    const n = new Date();
    secs = n.getUTCHours()*3600 + n.getUTCMinutes()*60 + n.getUTCSeconds();
    el.title = 'UTC Time (BMS not connected)';
    el.style.color = 'rgba(74,222,128,.6)';
  }
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  el.textContent = String(h).padStart(2,'0')+':'+String(m).padStart(2,'0')+':'+String(s).padStart(2,'0')+'Z';
}
updateZulu(); setInterval(updateZulu, 1000);

// ── Mission clock (tab bar) ──────────────────────────────────────
var _mclockBase = -1, _mclockWall = 0, _mclockLastBms = -1;
function updateMissionClock(){
  const el = document.getElementById('missionClock');
  if (!el) return;
  if (_bmsTimeSec != null && _bmsTimeSec !== _mclockLastBms) {
    _mclockBase = _bmsTimeSec;
    _mclockWall = Date.now();
    _mclockLastBms = _bmsTimeSec;
  }
  if (_mclockBase < 0) return;
  const secs = (_mclockBase + Math.floor((Date.now() - _mclockWall) / 1000)) % 86400;
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  el.textContent = String(h).padStart(2,'0')+':'+String(m).padStart(2,'0')+':'+String(s).padStart(2,'0')+'Z';
}
setInterval(updateMissionClock, 1000);

// ── Fullscreen ───────────────────────────────────────────────────
function toggleFullscreen(){
  if(!document.fullscreenElement){
    document.documentElement.requestFullscreen().catch(()=>{});
  } else {
    document.exitFullscreen().catch(()=>{});
  }
}
document.addEventListener('fullscreenchange',()=>{
  const btn = document.getElementById('fsBtn');
  const icon = document.getElementById('fsIcon');
  if(!btn||!icon) return;
  const fs = !!document.fullscreenElement;
  btn.style.color = fs ? 'rgba(74,222,128,.7)' : 'rgba(74,222,128,.3)';
  // Toggle icon: exit if fullscreen, enter if normal
  icon.innerHTML = fs
    ? '<polyline points="9 3 3 3 3 9"/><polyline points="15 21 21 21 21 15"/><line x1="3" y1="3" x2="10" y2="10"/><line x1="21" y1="21" x2="14" y2="14"/>'
    : '<polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/>';
});

// ── Server IP display ────────────────────────────────────────────
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


// ══ Checklist T.O. BMS1F-16CJ-1CL-1 (loaded from JSON) ═══════════
var CL_DATA=[];
fetch('/api/checklist').then(r=>r.json()).then(data=>{
  if(data&&data.length){CL_DATA=data;clRender();}
}).catch(()=>{});

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
  CL_DATA.forEach(row=>{
    if(row.section){
      // Close previous group
      if(groupOpen) html+='</div>';
      sec=row.section;
      const isOpen=!!clOpenSecs[sec];
      const cnt=secCounts[sec]||{total:0,done:0};
      const badge=cnt.done>0?`<span class="cl-section-count">${cnt.done}/${cnt.total}</span>`
                             :`<span class="cl-section-count">${cnt.total}</span>`;
      var secColor=row.color?` style="border-left:3px solid ${row.color};color:${row.color}"`:'';
      html+=`<div class="cl-section${isOpen?' open':''}"${secColor} onclick="clToggleSec(this,'${sec.replace(/'/g,"\\'")}')">
        ${_esc(row.section)}${badge}</div>`;
      html+=`<div class="cl-group${isOpen?' open':''}">`;
      groupOpen=true;
    } else if(row.note){
      html+=`<div class="cl-note">&#9888; ${_esc(row.note)}</div>`;
    } else {
      const key=`${sec}_${row.n}`;
      const chk=!!clState[key];
      total++;if(chk)done++;
      html+=`<div class="cl-row${chk?' done':''}" onclick="clToggle('${key}',this)">
        <input type="checkbox" class="cl-cb"${chk?' checked':''} onclick="event.stopPropagation();clToggle('${key}',this.closest('.cl-row'))">
        <span class="cl-num">${_esc(row.n)}</span>
        <span class="cl-item">${_esc(row.item)}<br><span style="font-size:10px;color:#475569">${_esc(row.loc)}</span></span>
        <span class="cl-status">${_esc(row.status)}</span>
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

  // Close all other panels
  Object.entries(PANELS).forEach(([, p]) => {
    p.classList.remove('open');
  });
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));

  panel.classList.add('open');
  btn.classList.add('active');
  _activeTab = name;

  // Charger la Charts iframe au premier clic
  if (name === 'charts' && !_chartsLoaded) {
    _chartsLoaded = true;
    document.getElementById('charts-frame').src = (window._appInfo && window._appInfo.charts) || 'https://www.falcon-charts.com';
  }

  // Refresh GPS data immediately
  if (name === 'gps') refreshGpsPanel();

  // Load briefing list on each open
  if (name === 'briefing') briefingLoadList();
}

// ══════════════════════════════════════════════════════════════════
//  BRIEFING
// ══════════════════════════════════════════════════════════════════
let _briefActive = null;

var _briefSidebarHidden = false;
function toggleBriefSidebar() {
  var sb = document.getElementById('briefSidebar');
  var btn = document.getElementById('briefToggle');
  if (!sb || !btn) return;
  _briefSidebarHidden = !_briefSidebarHidden;
  if (_briefSidebarHidden) {
    sb.style.setProperty('display', 'none', 'important');
  } else {
    sb.style.removeProperty('display');
  }
  var svg = btn.querySelector('svg');
  if (svg) svg.style.transform = _briefSidebarHidden ? 'scaleX(-1)' : '';
}

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
    const eName = _esc(f.name);
    const eExt  = _esc(f.ext);
    const iconCls = f.ext === 'pdf' ? 'pdf' : (f.ext === 'docx' ? 'docx' : (f.ext === 'html' || f.ext === 'htm' ? 'html' : 'img'));
    const label   = eExt.toUpperCase();
    const isBms   = f.source === 'bms';
    const badge   = isBms ? '<span class="brief-bms-badge">BMS</span>' : '';
    const isActive = _briefActive === f.name ? ' active' : '';
    const safeName = f.name.replace(/'/g,"\\'");
    const safeExt  = f.ext.replace(/'/g,"\\'");
    const delBtn   = isBms ? '' : `<span class="brief-file-del" onclick="event.stopPropagation();briefingDelete('${safeName}')" title="Delete">✕</span>`;
    return `<div class="brief-file-item${isActive}" onclick="briefingOpen('${safeName}','${safeExt}')" data-name="${eName}">
      <div class="brief-file-icon ${iconCls}">${label}</div>
      <div class="brief-file-info">
        <div class="brief-file-name">${eName}${badge}</div>
        <div class="brief-file-meta">${_esc(f.size_kb)} KB · ${_esc(f.modified)}</div>
      </div>
      ${delBtn}
    </div>`;
  }).join('');
}

var _pdfZoom = 1.0;
var _pdfDoc = null;
var _pdfBaseScale = 1.0;

function _pdfRedraw() {
  var pdfDiv = document.getElementById('briefPdfViewer');
  var inner = pdfDiv.querySelector('.pdf-pages');
  if (!inner || !_pdfDoc) return;
  var lbl = document.getElementById('pdfZoomLbl');
  if (lbl) lbl.textContent = Math.round(_pdfZoom * 100) + '%';
  inner.innerHTML = '';
  var w = pdfDiv.clientWidth || 800;
  // Render at 2x device pixels for crisp text
  var dpr = window.devicePixelRatio || 1;
  for (var p = 1; p <= _pdfDoc.numPages; p++) {
    (function(num) {
      _pdfDoc.getPage(num).then(function(page) {
        _pdfBaseScale = w / page.getViewport({scale:1}).width;
        var scale = _pdfBaseScale * dpr;
        var vp = page.getViewport({scale: scale});
        var canvas = document.createElement('canvas');
        canvas.width = vp.width; canvas.height = vp.height;
        canvas.style.width = (vp.width / dpr) + 'px';
        canvas.style.height = (vp.height / dpr) + 'px';
        canvas.style.display = 'block';
        canvas.style.marginBottom = '2px';
        inner.appendChild(canvas);
        page.render({canvasContext: canvas.getContext('2d'), viewport: vp});
      });
    })(p);
  }
}

function _pdfApplyZoom() {
  var inner = document.querySelector('#briefPdfViewer .pdf-pages');
  if (!inner) return;
  inner.style.transformOrigin = 'top left';
  inner.style.transform = 'scale(' + _pdfZoom + ')';
  var lbl = document.getElementById('pdfZoomLbl');
  if (lbl) lbl.textContent = Math.round(_pdfZoom * 100) + '%';
}

function _pdfInitPinch(container) {
  var startDist = 0, startZoom = 1;
  container.addEventListener('touchstart', function(e) {
    if (e.touches.length === 2) {
      e.preventDefault();
      var dx = e.touches[0].clientX - e.touches[1].clientX;
      var dy = e.touches[0].clientY - e.touches[1].clientY;
      startDist = Math.sqrt(dx*dx + dy*dy);
      startZoom = _pdfZoom;
    }
  }, {passive: false});
  container.addEventListener('touchmove', function(e) {
    if (e.touches.length === 2) {
      e.preventDefault();
      var dx = e.touches[0].clientX - e.touches[1].clientX;
      var dy = e.touches[0].clientY - e.touches[1].clientY;
      var dist = Math.sqrt(dx*dx + dy*dy);
      _pdfZoom = Math.min(4, Math.max(1, startZoom * (dist / startDist)));
      _pdfApplyZoom();
    }
  }, {passive: false});
}

function briefingOpen(name, ext) {
  _briefActive = name;
  document.querySelectorAll('.brief-file-item').forEach(el => {
    el.classList.toggle('active', el.dataset.name === name);
  });
  var iframe  = document.getElementById('briefIframe');
  var pdfDiv  = document.getElementById('briefPdfViewer');
  var ph      = document.getElementById('briefPlaceholder');
  var url     = '/api/briefing/file/' + encodeURIComponent(name);
  ph.style.display = 'none';

  if (ext === 'pdf' && window._pdfjsReady) {
    iframe.style.display = 'none';
    pdfDiv.style.display = 'block';
    _pdfZoom = 1.0;
    pdfDiv.innerHTML =
      '<div class="pdf-toolbar">' +
        '<button onclick="_pdfZoom=Math.max(1,_pdfZoom-0.25);_pdfApplyZoom()">−</button>' +
        '<span class="pdf-zoom-lbl" id="pdfZoomLbl">100%</span>' +
        '<button onclick="_pdfZoom=Math.min(4,_pdfZoom+0.25);_pdfApplyZoom()">+</button>' +
      '</div>' +
      '<div class="pdf-pages"></div>';
    _pdfInitPinch(pdfDiv.querySelector('.pdf-pages'));
    window._pdfjsReady.then(function(pdfjsLib) {
      if (!pdfjsLib) { iframe.src = url; iframe.style.display = 'block'; pdfDiv.style.display = 'none'; return; }
      pdfjsLib.getDocument(url).promise.then(function(pdf) {
        _pdfDoc = pdf;
        _pdfZoom = 1.0;
        _pdfRedraw();
      }).catch(function() { iframe.src = url; iframe.style.display = 'block'; pdfDiv.style.display = 'none'; });
    });
  } else {
    pdfDiv.style.display = 'none';
    iframe.src = url;
    iframe.style.display = 'block';
  }
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
    } catch(e) { /* upload error */ }
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
  } catch(e) { /* delete error */ }
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

// ── Airfield selectors (DEP / ARR / ALT) ───────────────────────
(function(){
  var _afData = []; // cached airport list

  function _loadAirfields(){
    fetch('/api/airports').then(r=>r.json()).then(aps=>{
      _afData = aps;
      ['dep','arr','alt'].forEach(role=>{
        const sel = document.getElementById('kb-af-'+role+'-sel');
        if(!sel) return;
        sel.innerHTML = '<option value="">— Select —</option>';
        aps.forEach(ap=>{
          const o = document.createElement('option');
          o.value = ap.icao;
          o.textContent = ap.icao + ' — ' + ap.name;
          sel.appendChild(o);
        });
        // Restore saved selection
        const saved = localStorage.getItem('bms_af_'+role);
        if(saved) { sel.value = saved; _showAfInfo(role, saved); }
      });
      // Check merged layout from saved values
      _updateMergedLayout({
        dep: localStorage.getItem('bms_af_dep'),
        arr: localStorage.getItem('bms_af_arr'),
      });
      // Auto-detect from mission data
      _autoDetectAirfields();
    }).catch(()=>{});
  }

  function _autoDetectAirfields(){
    fetch('/api/mission/airfields').then(r=>r.json()).then(af=>{
      ['dep','arr','alt'].forEach(role=>{
        if(!af[role]) return;
        const sel = document.getElementById('kb-af-'+role+'-sel');
        if(!sel) return;
        sel.value = af[role];
        localStorage.setItem('bms_af_'+role, af[role]);
        _showAfInfo(role, af[role]);
      });
      _updateMergedLayout(af);
      _tryAutoFillBullseye();
    }).catch(()=>{});
  }

  function _updateMergedLayout(af){
    const grid   = document.querySelector('.kb-airfields');
    const depBlk = document.getElementById('kb-af-dep');
    const arrBlk = document.getElementById('kb-af-arr');
    const depTag = depBlk ? depBlk.querySelector('.kb-af-tag') : null;
    if(!grid||!depBlk||!arrBlk||!depTag) return;
    const same = af.dep && af.arr && af.dep === af.arr;
    arrBlk.style.display = same ? 'none' : '';
    depTag.textContent   = same ? 'DEP / ARR' : 'DEP';
    grid.style.gridTemplateColumns = same ? '1fr 1fr' : '1fr 1fr 1fr';
  }

  // Auto-fill bullseye: bearing/range from DEP airport to bullseye reference
  var _bullAutoFilled = false;
  function _tryAutoFillBullseye(){
    if(_bullAutoFilled) return;
    const el = document.getElementById('kb-bull-val');
    if(!el) return;
    const depIcao = localStorage.getItem('bms_af_dep');
    if(!depIcao) return;
    if(typeof _bullLat==='undefined'||_bullLat==null||_bullLon==null) return;
    const ap = _afData.find(a=>a.icao===depIcao);
    if(!ap) return;
    const brg = bearingTo(ap.lat, ap.lon, _bullLat, _bullLon);
    const nm  = haversineNm(ap.lat, ap.lon, _bullLat, _bullLon);
    el.textContent = String(Math.round(brg)).padStart(3,'0')+'/'+Math.round(nm)+' NM';
    _bullAutoFilled = true;
  }
  // Retry until bullseye data arrives from SharedMem
  setInterval(_tryAutoFillBullseye, 3000);

  function _showAfInfo(role, icao){
    const el = document.getElementById('kb-af-'+role+'-info');
    if(!el) return;
    if(!icao){ el.innerHTML=''; return; }
    const ap = _afData.find(a=>a.icao===icao);
    if(!ap){ el.innerHTML='<span style="color:#475569">No data</span>'; return; }
    var html = '';
    if(ap.tacan) html += '<div class="af-row"><span class="af-lbl">TCN</span><span class="af-val">'+ap.tacan+'</span></div>';
    if(ap.freq)  html += '<div class="af-row"><span class="af-lbl">APP</span><span class="af-val">'+ap.freq+' MHz</span></div>';
    if(ap.ils && ap.ils.length){
      ap.ils.forEach(function(ils){
        var parts = '<span class="af-lbl">ILS</span><span class="af-val">RWY '+ils.rwy;
        if(ils.freq) parts += ' · '+ils.freq+' MHz';
        parts += ' · CRS '+ils.crs+'°</span>';
        html += '<div class="af-row af-ils">'+parts+'</div>';
      });
    }
    el.innerHTML = html || '<span style="color:#475569">No nav data</span>';
  }

  ['dep','arr','alt'].forEach(function(role){
    var sel = document.getElementById('kb-af-'+role+'-sel');
    if(!sel) return;
    sel.addEventListener('change',function(){
      localStorage.setItem('bms_af_'+role, sel.value);
      _showAfInfo(role, sel.value);
      _updateMergedLayout({
        dep: localStorage.getItem('bms_af_dep'),
        arr: localStorage.getItem('bms_af_arr'),
      });
    });
  });

  // Load on startup + refresh when theater changes
  _loadAirfields();
  var _afTheater = null;
  setInterval(function(){
    if(typeof _currentTheater!=='undefined' && _currentTheater !== _afTheater){
      _afTheater = _currentTheater;
      _loadAirfields();
    }
  }, 5000);

  // Expose for WebSocket mission updates
  window.refreshAirfields = _autoDetectAirfields;
})();

// Persister kneeboard (notes, plan de vol, 9-line)
const _kbPersist = {
  'kb-notes-ta':'bms_kb_notes',
  'kb-fplan-ta':'bms_kb_fplan',
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

// ── Kneeboard NOTES: text + stylus drawing ─────────────────────
(function(){
  const ta=document.getElementById('kb-notes-ta');
  const cvs=document.getElementById('kb-notes-cvs');
  const textBtn=document.getElementById('kbNoteTextBtn');
  const drawBtn=document.getElementById('kbNoteDrawBtn');
  const clearBtn=document.getElementById('kbNoteClearBtn');
  const colorInput=document.getElementById('kbNoteColorInput');
  const colorSwatch=document.getElementById('kbNoteColorSwatch');
  if(!ta||!cvs) return;

  var penColor='#94a3b8';
  var noteMode='text'; // 'text' or 'draw'

  function setMode(m){
    noteMode=m;
    if(m==='draw'){
      ta.style.display='none';cvs.style.display='block';
      textBtn.classList.remove('active');drawBtn.classList.add('active');
      // Size canvas to container
      setTimeout(()=>{
        const w=cvs.offsetWidth, h=cvs.offsetHeight;
        if(w>0&&h>0&&(cvs.width!==w||cvs.height!==h)){
          const old=cvs.toDataURL();
          cvs.width=w;cvs.height=h;
          const img=new Image();img.onload=()=>cvs.getContext('2d').drawImage(img,0,0);img.src=old;
        }
      },0);
    } else {
      ta.style.display='block';cvs.style.display='none';
      textBtn.classList.add('active');drawBtn.classList.remove('active');
    }
  }

  textBtn.addEventListener('click',()=>setMode('text'));
  drawBtn.addEventListener('click',()=>setMode('draw'));
  clearBtn.addEventListener('click',()=>{
    const ctx=cvs.getContext('2d');ctx.clearRect(0,0,cvs.width,cvs.height);
    try{localStorage.removeItem('bms_kb_notes_draw');}catch(e){}
  });
  colorInput.addEventListener('input',()=>{penColor=colorInput.value;colorSwatch.style.background=penColor;});

  // Canvas drawing with pointer events (stylus + mouse + touch)
  const ctx=cvs.getContext('2d');
  var drawing=false;

  function getPos(e){
    const r=cvs.getBoundingClientRect();
    return [(e.clientX-r.left)*(cvs.width/r.width), (e.clientY-r.top)*(cvs.height/r.height)];
  }

  cvs.addEventListener('pointerdown',e=>{
    drawing=true;
    const[x,y]=getPos(e);
    ctx.lineCap='round';ctx.lineJoin='round';
    ctx.lineWidth=e.pointerType==='pen'?2:3;
    ctx.strokeStyle=penColor;
    ctx.beginPath();ctx.moveTo(x,y);
    e.preventDefault();
  });
  cvs.addEventListener('pointermove',e=>{
    if(!drawing)return;
    const[x,y]=getPos(e);
    if(e.pointerType==='pen'&&e.pressure>0) ctx.lineWidth=1+e.pressure*4;
    ctx.lineTo(x,y);ctx.stroke();ctx.beginPath();ctx.moveTo(x,y);
    e.preventDefault();
  });
  function stopDraw(){
    if(!drawing)return;drawing=false;
    try{localStorage.setItem('bms_kb_notes_draw',cvs.toDataURL('image/png'));}catch(e){}
  }
  cvs.addEventListener('pointerup',stopDraw);
  cvs.addEventListener('pointerleave',stopDraw);

  // Restore drawing from localStorage
  try{
    const saved=localStorage.getItem('bms_kb_notes_draw');
    if(saved){
      const img=new Image();
      img.onload=()=>{
        cvs.width=cvs.offsetWidth||400;cvs.height=cvs.offsetHeight||600;
        cvs.getContext('2d').drawImage(img,0,0);
      };
      img.src=saved;
    }
  }catch(e){}

  // Resize canvas on window resize
  window.addEventListener('resize',()=>{
    if(noteMode!=='draw')return;
    const w=cvs.offsetWidth,h=cvs.offsetHeight;
    if(w>0&&h>0&&(cvs.width!==w||cvs.height!==h)){
      const old=cvs.toDataURL();cvs.width=w;cvs.height=h;
      const img=new Image();img.onload=()=>cvs.getContext('2d').drawImage(img,0,0);img.src=old;
    }
  });
})();

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
    list.innerHTML = '<span style="font-family:system-ui,sans-serif;font-size:11px;color:#3d6b52;padding:4px 0">No flight plan loaded</span>';
    count.textContent = '0 WPT';
    return;
  }
  count.textContent = route.length + ' WPT';
  route.forEach((sp, i) => {
    const chip = document.createElement('div');
    chip.className = 'steer-chip' + (i === _activeSteerIdx ? ' active' : '');
    const num=document.createElement('span');num.className='steer-num';num.textContent='STPT '+(i+1);
    const fl=document.createElement('span');fl.className='steer-fl';fl.textContent='FL'+String(Math.round(Math.abs(sp.alt)/100)).padStart(3,'0');
    chip.appendChild(num);chip.appendChild(fl);
    chip.onclick = () => {
      _activeSteerIdx = i;
      document.querySelectorAll('.steer-chip').forEach((c,j) => c.classList.toggle('active', j===i));
      refreshGpsPanel();
    };
    list.appendChild(chip);
  });
}

// Hook into existing updateAircraft and loadMission (map.js must be loaded first)
if(typeof updateAircraft !== 'undefined') {
  const _origUpdateAircraft = updateAircraft;
  window.updateAircraft = function(d) {
    _origUpdateAircraft(d);
    _lastAircraftData = d;
    if (_activeTab === 'gps') refreshGpsPanel();
  };
}

const _origLoadMission = typeof loadMission !== 'undefined' ? loadMission : ()=>{};
window.loadMission = function(noSetView=false) {
  _origLoadMission(noSetView);
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
      // ini/status attempt logged
      if(s.loaded&&s.mtime&&s.mtime!==_lastIniMtime){
        _lastIniFile=s.file;_lastIniMtime=s.mtime;
        loadMission(true);
        // mission loaded
        return;
      }
    }catch(e){ /* init error */ }
  }
  // no mission found after 3 attempts
})();
