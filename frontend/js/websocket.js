// Falcon-Pad — websocket.js
// WebSocket connection and message dispatch
// Calls: updateAircraft(), updateRadarContacts(), updateAcmiContacts() (from map.js)
// Copyright (C) 2024 Riesu — GNU GPL v3
// Loaded AFTER map.js and panels.js

function connectWS(){
  const proto=location.protocol==='https:'?'wss:':'ws:';
  const ws=new WebSocket(`${proto}//${location.host}/ws`);
  ws.onmessage=e=>{
    const msg=JSON.parse(e.data);
    if(msg.type==='aircraft'){
      updateAircraft(msg.data);
      // Mettre à jour l'heure BMS si disponible
      if(msg.data.bms_time != null){
        _bmsTimeSec = msg.data.bms_time;
        _bmsTimeTs  = Date.now();
      }
    }
    if(msg.type==='radar')updateRadarContacts(msg.data);
    if(msg.type==='acmi'){_lastAcmiContacts=msg.data;updateAcmiContacts(msg.data);}
    if(msg.type==='mk_marks')updateMkMarkpoints(msg.data);
    if(msg.type==='status'){
      const on=msg.data.connected;
      document.getElementById('dot').className='dot '+(on?'on':'off');
      document.getElementById('statusText').textContent=on?'BMS 4.38 CONNECTED':'NOT DETECTED';
    }
  };
  ws.onclose=()=>setTimeout(connectWS,2000);
}
connectWS();

