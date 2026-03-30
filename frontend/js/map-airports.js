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
  const col  = isEnemy ? '#f87171' : '#60a5fa';
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
      const col = isEnemy ? 'rgba(248,113,113,.85)' : 'rgba(96,165,250,.85)';
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

// ── Runway data ────────────────────────────────────────────────
const RUNWAY_DATA = [
  {icao:'RKTN',name:'Daegu AB',rwy:0,hdg:327.5,len:2743,c:[[35.883663,128.667015],[35.883885,128.66744],[35.904457,128.650634],[35.904229,128.650212]]},{icao:'RKTN',name:'Daegu AB',rwy:1,hdg:327.5,len:2754,c:[[35.882936,128.66592],[35.883162,128.666342],[35.903814,128.64947],[35.903585,128.649048]]},{icao:'RKJB',name:'Muan Apt',rwy:0,hdg:90.8,len:2794,c:[[34.988282,126.355991],[34.987878,126.355991],[34.987922,126.38666],[34.988327,126.386664]]},{icao:'RKSO',name:'Osan AB',rwy:0,hdg:186.6,len:2745,c:[[37.107717,127.046449],[37.107756,127.045939],[37.083195,127.042867],[37.08316,127.043375]]},{icao:'RKSO',name:'Osan AB',rwy:1,hdg:186.6,len:2745,c:[[37.107918,127.04392],[37.107955,127.043411],[37.083402,127.040337],[37.083361,127.040848]]},{icao:'RKTY',name:'Yecheon AB',rwy:0,hdg:182.6,len:2746,c:[[36.655298,128.355143],[36.655313,128.354636],[36.630626,128.353722],[36.630617,128.354233]]},{icao:'ZKTS',name:'Toksan AB',rwy:0,hdg:52.1,len:2484,c:[[39.27708,127.346012],[39.276736,127.34637],[39.290795,127.3688],[39.291138,127.368442]]},{icao:'RKPS',name:'Sacheon AB',rwy:0,hdg:215.6,len:2750,c:[[35.100714,128.087058],[35.100941,128.086671],[35.080615,128.069441],[35.080387,128.069827]]},{icao:'RKPS',name:'Sacheon AB',rwy:1,hdg:215.7,len:2751,c:[[35.102998,128.085936],[35.10322,128.085545],[35.082896,128.068315],[35.082675,128.068707]]},{icao:'ZKUJ',name:'Uiju AB',rwy:0,hdg:49.0,len:2493,c:[[40.040129,124.517393],[40.039743,124.517854],[40.054846,124.539484],[40.055233,124.539023]]},{icao:'RKSM',name:'Seoul AB',rwy:0,hdg:82.8,len:2957,c:[[37.446373,127.093555],[37.445966,127.093628],[37.449713,127.126783],[37.45012,127.12671]]},{icao:'RKSM',name:'Seoul AB',rwy:1,hdg:89.2,len:2744,c:[[37.449879,127.095767],[37.449469,127.095784],[37.450244,127.126841],[37.450655,127.126825]]},{icao:'RKTI',name:'Jungwon AB',rwy:0,hdg:275.6,len:2750,c:[[36.634671,127.516339],[36.635081,127.51638],[36.637084,127.485666],[36.636674,127.485625]]},{icao:'RKTI',name:'Jungwon AB',rwy:1,hdg:275.4,len:2852,c:[[36.632599,127.516742],[36.632916,127.516774],[36.634993,127.484914],[36.634675,127.484881]]},{icao:'RJOI',name:'Iwakuni AB',rwy:0,hdg:265.0,len:2441,c:[[34.15313,132.248972],[34.153664,132.248894],[34.151218,132.222548],[34.150685,132.22262]]},{icao:'RKPK',name:'Gimhae Apt',rwy:0,hdg:277.7,len:2749,c:[[35.182237,128.951059],[35.182636,128.951114],[35.185564,128.921087],[35.185165,128.921027]]},{icao:'RKPK',name:'Gimhae Apt',rwy:1,hdg:277.9,len:3206,c:[[35.180288,128.950746],[35.180819,128.950825],[35.184232,128.915799],[35.183701,128.915723]]},{icao:'RKJJ',name:'Gwangju AB',rwy:0,hdg:240.6,len:2835,c:[[35.134226,126.816195],[35.134576,126.815945],[35.121713,126.789037],[35.121362,126.789277]]},{icao:'RKJJ',name:'Gwangju AB',rwy:1,hdg:240.6,len:2835,c:[[35.135725,126.815124],[35.136075,126.814874],[35.123212,126.78796],[35.122862,126.78821]]},{icao:'KP-0005',name:'Taetan AB (G)',rwy:0,hdg:357.4,len:2503,c:[[38.238811,126.650634],[38.238835,126.651157],[38.261302,126.649337],[38.261276,126.648815]]},{icao:'KP-0030',name:'Panghyon AB',rwy:0,hdg:147.6,len:2597,c:[[39.910465,124.924693],[39.910198,124.924173],[39.890739,124.940999],[39.891009,124.941506]]},{icao:'RJOW',name:'Iwami Apt',rwy:0,hdg:168.6,len:2001,c:[[34.684957,131.787578],[34.684868,131.787097],[34.667321,131.791906],[34.66741,131.792387]]},{icao:'RKNY',name:'Yangyang Apt',rwy:0,hdg:310.8,len:2500,c:[[38.055058,128.676352],[38.05537,128.67668],[38.069756,128.654739],[38.069444,128.65441]]},{icao:'RKSI',name:'Incheon Apt *',rwy:0,hdg:305.8,len:3750,c:[[37.460193,126.463405],[37.460637,126.463789],[37.479929,126.428947],[37.479487,126.428556]]},{icao:'RKSI',name:'Incheon Apt *',rwy:1,hdg:305.8,len:3751,c:[[37.457142,126.460724],[37.457584,126.461112],[37.476881,126.426262],[37.476438,126.425875]]},{icao:'KP-0023',name:'Onchon AB',rwy:0,hdg:83.7,len:2502,c:[[39.815001,124.919894],[39.815409,124.919843],[39.817488,124.949006],[39.817083,124.949046]]},{icao:'RJOA',name:'Hiroshima Apt',rwy:0,hdg:1.2,len:3000,c:[[34.432547,132.910191],[34.432548,132.910845],[34.459516,132.910858],[34.459517,132.910204]]},{icao:'KP-0008',name:'Sondok AB',rwy:0,hdg:263.4,len:2502,c:[[39.750682,127.48869],[39.751087,127.488621],[39.748112,127.459616],[39.747707,127.459685]]},{icao:'RKSS',name:'Gimpo Apt',rwy:0,hdg:315.6,len:3573,c:[[37.545249,126.811295],[37.545627,126.811769],[37.568189,126.782909],[37.567809,126.782435]]},{icao:'RKSS',name:'Gimpo Apt',rwy:1,hdg:315.7,len:3172,c:[[37.542991,126.808384],[37.543371,126.808858],[37.563396,126.783243],[37.563015,126.782768]]},{icao:'KP-0020',name:'Hwangju AB',rwy:0,hdg:152.5,len:2504,c:[[38.682744,125.777293],[38.682925,125.77776],[38.662777,125.790628],[38.662601,125.790156]]},{icao:'RKSW',name:'Suwon AB',rwy:0,hdg:306.3,len:2743,c:[[37.22823,127.028906],[37.228566,127.029207],[37.242818,127.003916],[37.242484,127.00362]]},{icao:'RKSW',name:'Suwon AB',rwy:1,hdg:306.3,len:2743,c:[[37.227119,127.027862],[37.227454,127.028163],[37.241708,127.002872],[37.241373,127.002572]]},{icao:'KP-0011',name:'Mirim Airport',rwy:0,hdg:5.5,len:1251,c:[[39.06162,125.599413],[39.061595,125.59994],[39.072823,125.600799],[39.072847,125.600273]]},{icao:'RKJK',name:'Gunsan AB',rwy:0,hdg:101.3,len:2749,c:[[35.90714,126.599591],[35.906742,126.599495],[35.902279,126.629517],[35.902678,126.629607]]},{icao:'RKNN',name:'Gangneung AB',rwy:0,hdg:203.3,len:2761,c:[[37.765804,128.949017],[37.765963,128.948534],[37.743008,128.93657],[37.742853,128.937048]]},{icao:'RKNW',name:'Wonju AB',rwy:0,hdg:64.6,len:2738,c:[[37.427754,127.941412],[37.427386,127.941644],[37.438331,127.969412],[37.438699,127.969181]]},{icao:'RKSG',name:'Pyeongtaek AB',rwy:0,hdg:319.2,len:2309,c:[[36.952564,127.038492],[36.952839,127.038876],[36.968295,127.021521],[36.968019,127.021136]]},{icao:'RKTH',name:'Pohang AB',rwy:0,hdg:183.2,len:2133,c:[[35.997509,129.423488],[35.997524,129.422978],[35.978354,129.422152],[35.978339,129.42266]]},{icao:'RKTP',name:'Seosan AB',rwy:0,hdg:245.6,len:2744,c:[[36.706605,126.49829],[36.706977,126.49807],[36.696412,126.470264],[36.69604,126.470483]]},{icao:'RKTP',name:'Seosan AB',rwy:1,hdg:245.6,len:2744,c:[[36.708337,126.49727],[36.708708,126.497051],[36.698143,126.469244],[36.697771,126.469464]]},{icao:'RKTU',name:'Cheongju Apt',rwy:0,hdg:218.9,len:2744,c:[[36.732248,127.513095],[36.732577,127.512563],[36.713041,127.493765],[36.712711,127.494298]]},{icao:'RKTU',name:'Cheongju Apt',rwy:1,hdg:218.6,len:2744,c:[[36.732914,127.510383],[36.733161,127.509982],[36.713625,127.491185],[36.713378,127.491585]]},{icao:'KP-0035',name:'Hwangsuwon AB',rwy:0,hdg:325.0,len:2901,c:[[38.672715,125.376188],[38.672957,125.376617],[38.694085,125.357024],[38.693842,125.356594]]},{icao:'KP-0019',name:'Hyon-ni AB',rwy:0,hdg:79.4,len:2702,c:[[39.147695,125.867532],[39.147337,125.867634],[39.152173,125.898328],[39.152534,125.898236]]},{icao:'KP-0059',name:'Iwon AB',rwy:0,hdg:171.2,len:2509,c:[[40.327783,128.631085],[40.327712,128.630548],[40.305483,128.635634],[40.305556,128.636167]]},{icao:'KP-0018',name:'Kaechon AB',rwy:0,hdg:46.3,len:2503,c:[[39.79407,125.893871],[39.79378,125.894246],[39.809632,125.915044],[39.809923,125.914672]]},{icao:'KP-0015',name:'Koksan AB',rwy:0,hdg:32.3,len:2503,c:[[38.807253,126.392391],[38.807041,126.392836],[38.826276,126.407847],[38.826488,126.407401]]},{icao:'KP-0039',name:'Kwail AB',rwy:0,hdg:125.4,len:2499,c:[[38.70657,125.538208],[38.706245,125.53793],[38.69355,125.561675],[38.693864,125.561955]]},{icao:'KP-0053',name:'Manpo AB',rwy:0,hdg:72.4,len:1117,c:[[41.563091,126.252673],[41.562834,126.252808],[41.566123,126.265472],[41.566374,126.265345]]},{icao:'KP-0032',name:'Orang AB',rwy:0,hdg:58.8,len:2515,c:[[41.377494,129.437117],[41.377032,129.437509],[41.3892,129.462916],[41.389662,129.462523]]},{icao:'KP-0029',name:'Samjiyon AB',rwy:0,hdg:31.6,len:3308,c:[[42.053663,128.389224],[42.053384,128.389858],[42.079001,128.410225],[42.079278,128.40959]]},{icao:'KP-0021',name:'Sunchon AB',rwy:0,hdg:125.3,len:2504,c:[[39.440112,125.92096],[39.439773,125.920663],[39.427087,125.94474],[39.427426,125.945037]]},{icao:'KP-0006',name:'Taechon AB',rwy:0,hdg:164.1,len:2010,c:[[39.791475,124.713719],[39.79131,124.713039],[39.774091,124.720148],[39.774257,124.720826]]},
];

// ── Runway rendering & calibration ─────────────────────────────
var runwayLayers = [], runwaysVisible = true;
var rwyOffsets = {};

async function saveRwyOffsets(){
  try{ await saveUiPref({rwy_offsets: JSON.stringify(rwyOffsets)}); }catch(e){}
}

function applyOffset(latlon, icao) {
  const o = rwyOffsets[icao] || {dlat:0,dlon:0};
  return [latlon[0]+o.dlat, latlon[1]+o.dlon];
}

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
  if (_currentTheater && _currentTheater.toLowerCase().startsWith('korea')) {
    RUNWAY_DATA.forEach(r => {
      const apMatch = (apData || []).find(a => a.icao === r.icao);
      const isEnemy = apMatch ? apMatch.side === 'red' : false;
      const col     = isEnemy ? 'rgba(248,113,113,.75)' : 'rgba(148,185,220,.8)';
      const fillCol = isEnemy ? 'rgba(220,60,60,.18)'   : 'rgba(120,160,200,.15)';
      _drawRwyPoly(r.c.map(pt => applyOffset(pt, r.icao)), col, fillCol);
    });
  }
  const koreaIcaos = new Set(RUNWAY_DATA.map(r => r.icao));
  const seenKeys   = new Set();
  (apData || []).forEach(ap => {
    if (koreaIcaos.has(ap.icao) || !ap.ils || ap.ils.length === 0) return;
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
      const corners = _computeRwyCorners(ap.lat, ap.lon, crs, 2500, 45).map(pt => applyOffset(pt, ap.icao));
      _drawRwyPoly(corners, col, fillCol);
    });
  });
}

var _calMode = false, _calIcao = null, _calAnchorPt = null;

function openCalPanel() {
  document.getElementById('calPanel').style.display = 'block';
  const sel = document.getElementById('calIcaoSel');
  sel.innerHTML = '';
  [...new Set(RUNWAY_DATA.map(r=>r.icao))].sort().forEach(ic => {
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
    window._calTmpMarker = L.circleMarker(_calAnchorPt, {radius:S_BULL,color:C_BULL,fillColor:C_BULL+'44',fillOpacity:1,weight:2,interactive:false}).addTo(map);
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
