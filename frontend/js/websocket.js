// Falcon-Pad — websocket.js
// WebSocket connection and message dispatch
// Calls: updateAircraft(), updateAcmiContacts() (from map.js)
// Copyright (C) 2024 Riesu — GNU GPL v3
// Loaded AFTER map.js and panels.js

function connectWS(){
  const proto=location.protocol==='https:'?'wss:':'ws:';
  const ws=new WebSocket(`${proto}//${location.host}/ws`);
  ws.onmessage=e=>{
    const msg=JSON.parse(e.data);
    if(msg.type==='aircraft'){
      updateAircraft(msg.data);
      if(msg.data.bms_time != null){
        _bmsTimeSec = msg.data.bms_time;
        _bmsTimeTs  = Date.now();
      }
    }
    if(msg.type==='acmi'){_lastAcmiContacts=msg.data;updateAcmiContacts(msg.data);}
    if(msg.type==='mission'){
      _missionCache=msg.data;
      missionMarkers.forEach(m=>{try{map.removeLayer(m)}catch(e){}});missionMarkers=[];pptLabelMarkers=[];
      pptCircles.forEach(p=>{try{map.removeLayer(p)}catch(e){}});pptCircles=[];
      _renderMissionData(msg.data,true);
    }
    if(msg.type==='mk_marks')updateMkMarkpoints(msg.data);
    if(msg.type==='hsd_lines')updateHsdLines(msg.data);
    if(msg.type==='theater')updateTheater(msg.data);
    if(msg.type==='status'){
      const on=msg.data.connected;
      document.getElementById('dot').className='dot '+(on?'on':'off');
      document.getElementById('statusText').textContent=on?'BMS 4.38 CONNECTED':'NOT DETECTED';
    }
  };
  ws.onopen=()=>{
    console.log('[ws] connected — resyncing...');
    if(typeof loadMission==='function') loadMission(true);
    if(typeof _initTheater==='function') _initTheater();
  };
  ws.onclose=()=>setTimeout(connectWS,2000);
}
connectWS();
