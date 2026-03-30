// Falcon-Pad — map-tools.js
// Ruler, arrow, touch support, clear, color swatches, layer selection, toggles
// Copyright (C) 2024 Riesu — GNU GPL v3

// ── Ruler ──────────────────────────────────────────────────────
var rStart=null,rLine=null,rLabel=null,rDot=null;

function updateRuler(to){
  if(!rStart)return;
  if(rLine)map.removeLayer(rLine);
  if(rLabel)map.removeLayer(rLabel);
  rLine=L.polyline([rStart,to],{color:activeColor,weight:2,opacity:.8,dashArray:'8 4'}).addTo(map);
  const dist=map.distance(rStart,to);
  const nm=dist/1852;
  const f1=rStart.lat*Math.PI/180,f2=to.lat*Math.PI/180;
  const dl=(to.lng-rStart.lng)*Math.PI/180;
  const y=Math.sin(dl)*Math.cos(f2);
  const x=Math.cos(f1)*Math.sin(f2)-Math.sin(f1)*Math.cos(f2)*Math.cos(dl);
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

// ── Arrow ──────────────────────────────────────────────────────
var aStart=null,aLine=null,aHead=null,aDot=null;

function _bearingDeg(from, to) {
  const f1=from.lat*Math.PI/180, f2=to.lat*Math.PI/180;
  const dl=(to.lng-from.lng)*Math.PI/180;
  const x=Math.sin(dl)*Math.cos(f2);
  const y=Math.cos(f1)*Math.sin(f2)-Math.sin(f1)*Math.cos(f2)*Math.cos(dl);
  return ((Math.atan2(x,y)*180/Math.PI)+360)%360;
}

function arrowHeadPts(from, to) {
  const fp = map.latLngToLayerPoint(from);
  const tp = map.latLngToLayerPoint(to);
  const ang = Math.atan2(tp.y - fp.y, tp.x - fp.x);
  const L2 = 20, A = Math.PI / 6;
  return [
    map.layerPointToLatLng(L.point(tp.x - L2*Math.cos(ang-A), tp.y - L2*Math.sin(ang-A))),
    map.layerPointToLatLng(L.point(tp.x - L2*Math.cos(ang+A), tp.y - L2*Math.sin(ang+A))),
  ];
}

function updateArrow(to){
  if(!aStart)return;
  [aLine,aHead].forEach(l=>{if(l)map.removeLayer(l)});
  aLine=L.polyline([aStart,to],{color:activeColor,weight:1.5,opacity:.9,interactive:false}).addTo(map);
  const [p1,p2]=arrowHeadPts(aStart,to);
  aHead=L.polygon([to,p1,p2],{color:activeColor,fillColor:activeColor,fillOpacity:1,weight:0,interactive:false}).addTo(map);
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
    const fLine=L.polyline([aStart,e.latlng],{color:activeColor,weight:1.5,opacity:.9,interactive:false}).addTo(map);
    drawMarkers.push(fLine);
    const [p1,p2]=arrowHeadPts(aStart,e.latlng);
    const fHead=L.polygon([e.latlng,p1,p2],{color:activeColor,fillColor:activeColor,fillOpacity:1,weight:0,interactive:false}).addTo(map);
    drawMarkers.push(fHead);
    const dist=map.distance(aStart,e.latlng)/1852;
    if(dist>0.05){
      const brg=_bearingDeg(aStart,e.latlng);
      const brgStr=String(Math.round(brg)).padStart(3,'0')+'°';
      const mid=L.latLng((aStart.lat+e.latlng.lat)/2,(aStart.lng+e.latlng.lng)/2);
      const html=`<div class="arrow-label" style="--ac:${activeColor}">
        <span class="arrow-brg">${brgStr}</span>
        <span class="arrow-dist">${dist.toFixed(1)}<span class="arrow-unit"> NM</span></span>
      </div>`;
      const lm=L.marker(mid,{icon:L.divIcon({html,className:'',iconSize:[120,24],iconAnchor:[60,12]})}).addTo(map);
      drawMarkers.push(lm);
    }
    clearArrow();
  }
});
map.on('mousemove',e=>{if(arrowActive&&aStart)updateArrow(e.latlng);});

// ── Touch support for ruler/arrow ──────────────────────────────
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
    if(arrowActive&&!rulerActive){if(!aStart){aStart=pt;aDot=L.circleMarker(aStart,{radius:5,color:'#fff',fillColor:activeColor,fillOpacity:1,weight:2}).addTo(map);}else{const fL=L.polyline([aStart,pt],{color:activeColor,weight:2,opacity:.9}).addTo(map);drawMarkers.push(fL);const[p1,p2]=arrowHeadPts(aStart,pt,map.getZoom());const fH=L.polygon([pt,p1,p2],{color:activeColor,fillColor:activeColor,fillOpacity:1,weight:1.5}).addTo(map);drawMarkers.push(fH);const d=map.distance(aStart,pt)/1852;if(d>0.05){const mid=L.latLng((aStart.lat+pt.lat)/2,(aStart.lng+pt.lng)/2);const lm=L.marker(mid,{icon:L.divIcon({html:'<div class="arrow-label" style="color:'+activeColor+'">'+d.toFixed(1)+' NM</div>',className:'',iconSize:[70,20],iconAnchor:[35,20]})}).addTo(map);drawMarkers.push(lm);}clearArrow();}e.preventDefault();}
  },{passive:false});
  mc.addEventListener('touchmove',function(e){if(e.touches.length!==1)return;const t=e.touches[0],rect=mc.getBoundingClientRect();const pt=map.containerPointToLatLng(L.point(t.clientX-rect.left,t.clientY-rect.top));if(rulerActive&&rStart){updateRuler(pt);e.preventDefault();}if(arrowActive&&aStart){updateArrow(pt);e.preventDefault();}},{passive:false});
})();

// ── Clear drawings ─────────────────────────────────────────────
document.getElementById('clearArrowsBtn')?.addEventListener('click',()=>{
  drawMarkers.forEach(m=>{try{map.removeLayer(m)}catch(e){}});drawMarkers=[];clearArrow();
});

// ── Color swatches ─────────────────────────────────────────────
const cGrid=document.getElementById('cGrid');
COLORS.forEach(c=>{
  const s=document.createElement('div');
  s.className='c-swatch'+(c===activeColor?' sel':'');
  s.style.background=c;
  s.dataset.color=c;s.onclick=()=>{activeColor=c;document.querySelectorAll('.c-swatch').forEach(x=>x.classList.remove('sel'));s.classList.add('sel');saveUiPref({active_color:c});};
  cGrid.appendChild(s);
});
document.getElementById('colorBtn')?.addEventListener('click',()=>document.getElementById('colorPanel').classList.toggle('open'));

// ── Layer selection ────────────────────────────────────────────
document.getElementById('layerBtn')?.addEventListener('click',()=>document.getElementById('layerPanel').classList.toggle('open'));
document.querySelectorAll('input[name="layer"]').forEach(r=>r.addEventListener('change',e=>{
  switchLayer(e.target.value);
  saveUiPref({layer:e.target.value});
}));

// ── PPT / Airport / Runway toggles ────────────────────────────
document.getElementById('pptLabelBtn')?.addEventListener('click',function(){
  pptLabelsVisible=!pptLabelsVisible;
  this.classList.toggle('active',pptLabelsVisible);
  pptLabelMarkers.forEach(m=>{try{pptLabelsVisible?m.addTo(map):map.removeLayer(m);}catch(e){}});
});

document.getElementById('pptBtn')?.addEventListener('click',function(){
  const v=this.classList.toggle('active');
  pptCircles.forEach(c=>{
    if(!v) { try{map.removeLayer(c)}catch(e){} }
    else if(!pptLabelMarkers.includes(c) || pptLabelsVisible) { try{c.addTo(map)}catch(e){} }
  });
  saveUiPref({ppt_visible:v});
});

document.getElementById('airportBtn')?.addEventListener('click',function(){
  const v=this.classList.toggle('active');
  const apNameOn=typeof _apNameVisible!=='undefined'?_apNameVisible:false;
  airportMarkers.forEach(m=>{
    if(!v){try{map.removeLayer(m)}catch(e){}}
    else if(apNameMarkers.includes(m)){if(apNameOn)try{m.addTo(map)}catch(e){}}
    else{try{m.addTo(map)}catch(e){}}
  });
  runwaysVisible=v;
  runwayLayers.forEach(l=>{try{v?l.addTo(map):map.removeLayer(l);}catch(e){}});
  document.getElementById('runwayBtn')?.classList.toggle('active',v);
  saveUiPref({airports_visible:v});
});
