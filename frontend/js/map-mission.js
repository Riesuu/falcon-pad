// Falcon-Pad — map-mission.js
// Mission loading, rendering, upload, INI auto-load, live color/size updates
// Copyright (C) 2024 Riesu — GNU GPL v3

// ── Upload ─────────────────────────────────────────────────────
document.getElementById('uploadBtn')?.addEventListener('click',()=>document.getElementById('fileInput').click());
document.getElementById('fileInput')?.addEventListener('change',async e=>{
  const file=e.target.files[0];if(!file)return;
  const fd=new FormData();fd.append('file',file);
  const r=await fetch('/api/upload',{method:'POST',body:fd});
  if(r.ok){
    loadMission(true);
  } else {
    let errMsg = 'INI import failed';
    try{ const d=await r.json(); errMsg=d.message||d.detail||errMsg; }catch(e){}
    const n=document.createElement('div');
    n.className='bms-toast';
    n.style.cssText='background:rgba(239,68,68,.15);border-color:rgba(239,68,68,.4);color:#ef4444';
    n.textContent='\u2717 '+errMsg;
    document.body.appendChild(n);setTimeout(()=>n.remove(),4000);
  }
});

// ── INI auto-load polling ──────────────────────────────────────
var _lastIniFile=null;
var _lastIniMtime=0;
setInterval(async()=>{
  try{
    const s=await(await fetch('/api/ini/status')).json();
    if(s.loaded&&s.mtime&&s.mtime!==_lastIniMtime){
      _lastIniFile=s.file;_lastIniMtime=s.mtime;
      loadMission(true);
      const n=document.createElement('div');n.className='bms-toast';
      n.textContent='\u2726 MISSION LOADED \u2014 '+s.file;
      document.body.appendChild(n);setTimeout(()=>n.remove(),3000);
    }
  }catch(e){}
},3000);

// ── Mission cache & redraw ─────────────────────────────────────
var _missionCache = null;

function _redrawMission() {
  if(!_missionCache) return;
  missionMarkers.forEach(m=>{try{map.removeLayer(m)}catch(e){}});
  missionMarkers=[];pptLabelMarkers=[];
  pptCircles.forEach(p=>{try{map.removeLayer(p)}catch(e){}});pptCircles=[];
  _renderMissionData(_missionCache, true);
}

// ── Live color/size updates ────────────────────────────────────
function _applyColorLive(key, hex) {
  switch(key) {
    case 'draw':  C_DRAW = hex; activeColor = hex; break;
    case 'stpt':  C_STPT = hex; missionMarkers.forEach(m => {
        if(m._fpType==='stpt') try{m.setStyle({color:hex,fillColor:hex});}catch(e){}
        if(m._fpType==='stpt_line') try{m.setStyle({color:hex});}catch(e){}
      }); break;
    case 'fplan': C_FPLAN = hex; missionMarkers.forEach(m => {
        if(m._fpType==='fplan') try{m.setStyle({color:hex,fillColor:hex});}catch(e){}
        if(m._fpType==='fplan_line') try{m.setStyle({color:hex});}catch(e){}
      }); break;
    case 'ppt':   C_PPT = hex;
      pptCircles.forEach(c=>{try{c.setStyle({color:hex,fillColor:hex});}catch(e){}});
      missionMarkers.forEach(m=>{if(m._fpType==='ppt')try{m.setStyle({fillColor:hex});}catch(e){}});
      break;
  }
}

function _applySizeLive(key) {
  switch(key) {
    case 'stpt_line':  missionMarkers.forEach(m=>{if(m._fpType==='stpt_line')try{m.setStyle({weight:S_STPT_LINE});}catch(e){}});break;
    case 'stpt':       missionMarkers.forEach(m=>{if(m._fpType==='stpt')try{m.setRadius(S_STPT);}catch(e){}});break;
    case 'fplan_line': missionMarkers.forEach(m=>{if(m._fpType==='fplan_line')try{m.setStyle({weight:S_FPLAN_LINE});}catch(e){}});break;
    case 'fplan':      missionMarkers.forEach(m=>{if(m._fpType==='fplan')try{m.setRadius(S_FPLAN);}catch(e){}});break;
    case 'ppt':        pptCircles.forEach(c=>{try{c.setStyle({weight:S_PPT});}catch(e){}});break;
    case 'ppt_dot':    missionMarkers.forEach(m=>{if(m._fpType==='ppt')try{m.setRadius(S_PPT_DOT);}catch(e){}});break;
  }
}

window._setMapColor = _applyColorLive;
window._setMapSize  = function(key, v) {
  switch(key) {
    case 'stpt':       S_STPT       = v; break;
    case 'stpt_line':  S_STPT_LINE  = v; break;
    case 'fplan':      S_FPLAN      = v; break;
    case 'fplan_line': S_FPLAN_LINE = v; break;
    case 'ppt':        S_PPT        = v; break;
    case 'ppt_dot':    S_PPT_DOT    = v; break;
  }
  _applySizeLive(key);
};
window._setHsdColor = function(key, hex) {
  switch(key) {
    case 'l1': C_HSD_L1 = hex; break;
    case 'l2': C_HSD_L2 = hex; break;
    case 'l3': C_HSD_L3 = hex; break;
    case 'l4': C_HSD_L4 = hex; break;
  }
  if(_lastHsdLines && _lastHsdLines.length) updateHsdLines(_lastHsdLines);
};
var _settingsPanelOpen = false;
window._setSettingsOpen = v => { _settingsPanelOpen = v; };

// ── Load & render mission ──────────────────────────────────────
function loadMission(noSetView=false){
  missionMarkers.forEach(m=>{try{map.removeLayer(m)}catch(e){}});missionMarkers=[];pptLabelMarkers=[];
  pptCircles.forEach(p=>{try{map.removeLayer(p)}catch(e){}});pptCircles=[];
  fetch('/api/mission').then(r=>r.json()).then(d=>{
    _missionCache = d;
    _renderMissionData(d, noSetView);
  }).catch(e=>console.error('[loadMission]',e));
}

function _renderMissionData(d, noSetView=false){
    if(d.flightplan?.length){
      const c=C_FPLAN;
      const _fl=L.polyline(d.flightplan.map(p=>[p.lat,p.lon]),{color:c,weight:S_FPLAN_LINE,opacity:.8});_fl._fpType='fplan_line';_fl.addTo(map);missionMarkers.push(_fl);
      d.flightplan.forEach((p,i)=>{
        const _fm=L.circleMarker([p.lat,p.lon],{radius:S_FPLAN,color:c,fillColor:c,fillOpacity:.85,weight:2});_fm._fpType='fplan';_fm.addTo(map);missionMarkers.push(_fm);
        missionMarkers.push(L.marker([p.lat,p.lon],{icon:L.divIcon({
          html:`<div style="font-family:'Consolas','Courier New',monospace;color:${c};font-size:9px;font-weight:700;text-shadow:0 1px 4px #000">${i+1}</div>`,
          className:'',iconSize:[16,12],iconAnchor:[-5,6]
        })}).addTo(map));
      });
    }
    if(d.route?.length){
      const c=C_STPT;
      for(let i=0;i<d.route.length-1;i++){
        const _sl=L.polyline([[d.route[i].lat,d.route[i].lon],[d.route[i+1].lat,d.route[i+1].lon]],{color:c,weight:S_STPT_LINE});_sl._fpType='stpt_line';_sl.addTo(map);missionMarkers.push(_sl);
      }
      d.route.forEach((p,i)=>{
        const _sm=L.circleMarker([p.lat,p.lon],{radius:S_STPT,color:c,fillColor:c,fillOpacity:.9,weight:2});_sm._fpType='stpt';_sm.addTo(map);missionMarkers.push(_sm);
        missionMarkers.push(L.marker([p.lat,p.lon],{icon:L.divIcon({
          html:`<div style="font-family:'Consolas','Courier New',monospace;color:${C_STPT};font-size:9px;font-weight:700;text-shadow:0 1px 4px #000">${i+1}</div>`,
          className:'',iconSize:[16,12],iconAnchor:[-5,6]
        })}).addTo(map));
      });
      if(!noSetView) map.setView([d.route[0].lat,d.route[0].lon],9);
    }
    if(d.threats?.length){
      const c=C_PPT;
      const pptOn = document.getElementById('pptBtn')?.classList.contains('active');
      d.threats.forEach(t=>{
        const circ=L.circle([t.lat,t.lon],{radius:(t.range_m||t.range_nm*1852),color:c,fillColor:c,fillOpacity:.05,weight:S_PPT,dashArray:'5 4'});
        if(pptOn) circ.addTo(map);
        pptCircles.push(circ);
        const _pm=L.circleMarker([t.lat,t.lon],{radius:S_PPT_DOT,color:'#fff',fillColor:c,fillOpacity:1,weight:2});_pm._fpType='ppt';
        if(pptOn) _pm.addTo(map);
        pptCircles.push(_pm);
        const nm=t.name?t.name.trim():'';
        const pptNum=(t.num!==undefined)?t.num:t.index;
        const numStr=String(pptNum).padStart(2,'0');
        const pptLbl=L.marker([t.lat,t.lon],{icon:L.divIcon({
          html:`<div style="display:inline-flex;align-items:center;gap:0;background:rgba(6,0,0,.88);border-top:1px solid rgba(220,38,38,.18);border-bottom:1px solid rgba(220,38,38,.18);border-right:1px solid rgba(220,38,38,.18);border-left:2px solid #dc2626;padding:2px 8px 2px 6px;white-space:nowrap;pointer-events:none;font-family:'Consolas','Courier New',monospace;letter-spacing:.06em"><span style="color:#6b7280;font-size:8px;font-weight:600;margin-right:4px">PPT</span><span style="color:#ef4444;font-size:10px;font-weight:700;margin-right:${nm?'6':'0'}px">${numStr}</span>${nm?`<span style="color:#d1d5db;font-size:10px;font-weight:600;letter-spacing:.08em">${nm}</span>`:''}</div>`,
          className:'',iconSize:[90,18],iconAnchor:[-6,9]
        }),zIndexOffset:50});
        if(pptOn && pptLabelsVisible) pptLbl.addTo(map);
        pptLabelMarkers.push(pptLbl);
        pptCircles.push(pptLbl);
      });
    }
}
