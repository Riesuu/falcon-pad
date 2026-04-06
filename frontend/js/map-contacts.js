// Falcon-Pad — map-contacts.js
// ACMI contacts (allies), HSD lines, MK markpoints
// Copyright (C) 2024 Riesu — GNU GPL v3

// ── ACMI contacts ──────────────────────────────────────────────
var acmiMarkers=[], acmiVisible=true;
var _lastAcmiContacts=null;

map.on('zoomend', ()=>{
  if(_lastAcmiContacts) updateAcmiContacts(_lastAcmiContacts);
});

function updateAcmiContacts(contacts){
  _lastAcmiContacts = contacts;
  acmiMarkers.forEach(m=>{try{map.removeLayer(m)}catch(e){}});acmiMarkers=[];
  if(!contacts||!contacts.length||!acmiVisible)return;
  const z = map.getZoom();
  const iconSz=40, cx=iconSz/2, sq=3, lineLen=16;

  const valid=contacts.filter(c=>c.lat!=null&&c.lon!=null);
  const allPx=valid.map(c=>map.latLngToContainerPoint([c.lat,c.lon]));

  // Group friendlies by screen proximity
  const GR=120;
  const used=new Set();
  const groups=[];
  for(let i=0;i<valid.length;i++){
    if(used.has(i)||(valid[i].camp||3)!==1) continue;
    const members=[i];
    for(let j=i+1;j<valid.length;j++){
      if(used.has(j)||(valid[j].camp||3)!==1) continue;
      const dx=allPx[i].x-allPx[j].x, dy=allPx[i].y-allPx[j].y;
      if(dx*dx+dy*dy<GR*GR) members.push(j);
    }
    members.forEach(m=>used.add(m));
    const cLat=members.reduce((s,m)=>s+valid[m].lat,0)/members.length;
    const cLon=members.reduce((s,m)=>s+valid[m].lon,0)/members.length;
    groups.push({leader:i,members,cLat,cLon});
  }

  // Render blips (skip unknown/neutral — not realistic, not on HSD)
  valid.forEach(c=>{
    const camp=c.camp||3;
    if(camp!==1&&camp!==2) return;
    const hdg=(c.heading||0);
    let svg;
    if(camp===1){
      svg=`<svg width="${iconSz}" height="${iconSz}" viewBox="0 0 ${iconSz} ${iconSz}">
        <rect x="${cx-sq}" y="${cx-sq}" width="${sq*2}" height="${sq*2}"
          fill="${C_ALLY}" stroke="${C_ALLY}" stroke-width="1"/>
        ${c.heading!=null?`<line x1="${cx}" y1="${cx}" x2="${cx}" y2="${cx-lineLen}"
          stroke="${C_ALLY}" stroke-width="1.5"
          transform="rotate(${hdg},${cx},${cx})"/>`:''}</svg>`;
    } else {
      const col=camp===2?C_ENEMY:'#e2e8f0';
      svg=`<svg width="${iconSz}" height="${iconSz}" viewBox="0 0 ${iconSz} ${iconSz}">
        <g transform="rotate(${hdg},${cx},${cx})">
          <polygon points="${cx},${cx-8} ${cx-6},${cx+5} ${cx+6},${cx+5}"
            fill="${col}" stroke="${col}" stroke-width="0.5" stroke-linejoin="round"/>
          <line x1="${cx}" y1="${cx-8}" x2="${cx}" y2="${cx-20}"
            stroke="${col}" stroke-width="1.5" opacity=".7"/>
        </g></svg>`;
    }
    const mS=L.marker([c.lat,c.lon],{icon:L.divIcon({
      html:svg,className:'',iconSize:[iconSz,iconSz],iconAnchor:[cx,cx]
    }),zIndexOffset:camp===1?80:70,interactive:false});
    mS.addTo(map);acmiMarkers.push(mS);
  });

  // Friendly labels (one per group)
  if(z < 9) return;
  const col=C_ALLY;
  groups.forEach(g=>{
    const n=g.members.length;
    const lead=valid[g.leader];
    const call=(lead.callsign||lead.type_name||'').replace(/-\d+$/,'').trim();
    const altFL=lead.alt!=null&&lead.alt>0?'FL'+String(Math.round(lead.alt/100)).padStart(3,'0'):'';
    const hdgStr=lead.heading!=null?String(Math.round(lead.heading)).padStart(3,'0')+'°':'';
    const spdStr=lead.speed!=null&&lead.speed>5?String(Math.round(lead.speed))+'kt':'';
    let txt;
    if(n===1){
      txt=`<div>${call}</div><div style="opacity:.8">${[hdgStr,spdStr,altFL].filter(Boolean).join(' ')}</div>`;
    } else {
      txt=`<div>${call} x${n} ${altFL}</div>`;
    }
    const lH=`<div style="
      pointer-events:none;white-space:nowrap;
      font-family:'Consolas','Courier New',monospace;font-size:11px;font-weight:700;
      letter-spacing:.6px;line-height:1.4;color:${col};
      text-shadow:0 0 4px rgba(74,222,128,.3),0 1px 3px #000;
    ">${txt}</div>`;
    const mL=L.marker([g.cLat,g.cLon],{icon:L.divIcon({
      html:lH,className:'',iconSize:[120,18],iconAnchor:[-10,8]
    }),zIndexOffset:81,interactive:false});
    mL.addTo(map);acmiMarkers.push(mL);
  });
}

// ── HSD Lines L1-L4 ────────────────────────────────────────────
var hsdMarkers = [], hsdVisible = true;
var _lastHsdLines = [];
var _lastMkMarks  = [];

function updateHsdLines(lines) {
  _lastHsdLines = lines;
  hsdMarkers.forEach(m=>{try{map.removeLayer(m)}catch(e){}});
  hsdMarkers = [];
  if(!lines || !lines.length) return;
  lines.forEach(line => {
    if(!line.points || line.points.length < 2) return;
    const pts = line.points.map(p => [p.lat, p.lon]);
    const lineColorKey = 'C_HSD_' + line.line;
    const lineColor = window[lineColorKey] || line.color || '#4ade80';
    const poly = L.polyline(pts, {color:lineColor,weight:2,opacity:0.85,dashArray:'6 3'});
    if(hsdVisible) poly.addTo(map);
    hsdMarkers.push(poly);
    const mid = pts[Math.floor(pts.length / 2)];
    const lbl = L.marker(mid, {
      icon: L.divIcon({
        html: `<div style="font-family:'Consolas','Courier New',monospace;font-size:9px;font-weight:700;
          color:${lineColor};text-shadow:0 1px 4px #000;padding:1px 4px;
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

// ── MK Markpoints ──────────────────────────────────────────────
var mkMarkers=[];
function updateMkMarkpoints(marks){
  _lastMkMarks = marks;
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
    const lH=`<div style="pointer-events:none;white-space:nowrap;font-family:'Consolas',monospace;font-size:11px;font-weight:700;letter-spacing:.6px;color:${C_MK};text-shadow:0 1px 4px rgba(0,0,0,.9)">${mk.label}${altFL?' \u00b7 '+altFL:''}</div>`;
    const mL=L.marker([mk.lat,mk.lon],{
      icon:L.divIcon({html:lH,className:'',iconSize:[90,20],iconAnchor:[-13,10]}),
      zIndexOffset:151
    }).addTo(map);
    mkMarkers.push(mL);
  });
}
