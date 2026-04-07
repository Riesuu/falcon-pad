// Falcon-Pad — map-notes.js
// Tactical annotations: text + stylus/pen drawing
// Copyright (C) 2024 Riesu — GNU GPL v3

let _noteCount=0;

function _debounce(fn, ms){ let t; return (...a)=>{ clearTimeout(t); t=setTimeout(()=>fn(...a),ms); }; }

function _serializeNotes(){
  const all=[];
  document.querySelectorAll('.note-wrapper').forEach(w=>{
    const body=w.querySelector('.note-body');
    const cvs=w.querySelector('.note-canvas');
    if(!body) return;
    const entry={
      id:   w.dataset.noteId||(_noteCount++),
      left: w.style.left, top: w.style.top,
      bg:   w.style.background,
      tc:   body.style.color,
      text: body.value||'',
      mode: w.dataset.mode||'text'
    };
    if(cvs&&cvs.width>0) try{entry.draw=cvs.toDataURL('image/png');}catch(e){}
    all.push(entry);
  });
  return all;
}

async function _saveNotes(){
  try{ await saveUiPref({annotations: JSON.stringify(_serializeNotes())}); }
  catch(e){ console.warn('[notes] save error:',e); }
}

function _restoreNotes(data){
  if(!data||!data.length) return;
  data.forEach(n=>{
    const wrapper=_buildNote(n.bg||'#0f172a', n.tc||'#94a3b8');
    wrapper.style.left=n.left||'300px';
    wrapper.style.top=n.top||'200px';
    wrapper.dataset.noteId=n.id||(_noteCount++);
    const body=wrapper.querySelector('.note-body');
    if(body) body.value=n.text||'';
    if(n.mode==='draw') _setNoteMode(wrapper,'draw');
    if(n.draw){
      const cvs=wrapper.querySelector('.note-canvas');
      if(cvs){const img=new Image();img.onload=()=>{cvs.width=cvs.offsetWidth;cvs.height=cvs.offsetHeight;cvs.getContext('2d').drawImage(img,0,0);};img.src=n.draw;}
    }
    document.body.appendChild(wrapper);
  });
}

function _setNoteMode(wrapper, mode){
  wrapper.dataset.mode=mode;
  const body=wrapper.querySelector('.note-body');
  const cvs=wrapper.querySelector('.note-canvas');
  const textBtn=wrapper.querySelector('.note-mode-text');
  const drawBtn=wrapper.querySelector('.note-mode-draw');
  if(mode==='draw'){
    if(body)body.style.display='none';
    if(cvs){cvs.style.display='block';
      setTimeout(()=>{if(cvs.width!==cvs.offsetWidth||cvs.height!==cvs.offsetHeight){
        const old=cvs.toDataURL();cvs.width=cvs.offsetWidth;cvs.height=cvs.offsetHeight;
        const img=new Image();img.onload=()=>cvs.getContext('2d').drawImage(img,0,0);img.src=old;
      }},0);
    }
    if(textBtn)textBtn.classList.remove('active');
    if(drawBtn)drawBtn.classList.add('active');
  } else {
    if(body)body.style.display='block';
    if(cvs)cvs.style.display='none';
    if(textBtn)textBtn.classList.add('active');
    if(drawBtn)drawBtn.classList.remove('active');
  }
}

function _initCanvas(cvs, wrapper){
  const ctx=cvs.getContext('2d');
  let drawing=false, lastX=0, lastY=0;
  function getPos(e){
    const r=cvs.getBoundingClientRect();
    const x=(e.clientX||e.touches?.[0]?.clientX||0)-r.left;
    const y=(e.clientY||e.touches?.[0]?.clientY||0)-r.top;
    return [x*(cvs.width/r.width), y*(cvs.height/r.height)];
  }
  cvs.addEventListener('pointerdown',e=>{
    drawing=true;[lastX,lastY]=getPos(e);
    ctx.lineCap='round';ctx.lineJoin='round';
    ctx.lineWidth=e.pointerType==='pen'?2:3;
    ctx.strokeStyle=wrapper.querySelector('.note-body')?.style.color||'#94a3b8';
    ctx.beginPath();ctx.moveTo(lastX,lastY);
    e.preventDefault();
  });
  cvs.addEventListener('pointermove',e=>{
    if(!drawing)return;
    const[x,y]=getPos(e);
    if(e.pointerType==='pen'&&e.pressure>0) ctx.lineWidth=1+e.pressure*4;
    ctx.lineTo(x,y);ctx.stroke();ctx.beginPath();ctx.moveTo(x,y);
    lastX=x;lastY=y;e.preventDefault();
  });
  const stop=()=>{if(drawing){drawing=false;_saveNotes();}};
  cvs.addEventListener('pointerup',stop);
  cvs.addEventListener('pointerleave',stop);
}

function _buildNote(bgColor, textColor){
  const wrapper=document.createElement('div');
  wrapper.className='note-wrapper';
  wrapper.dataset.mode='text';
  wrapper.style.background=bgColor;
  wrapper.style.border='1px solid rgba(74,222,128,.2)';

  const header=document.createElement('div');header.className='note-header';

  const textBtn=document.createElement('button');textBtn.className='note-mode-btn note-mode-text active';textBtn.innerHTML='T';textBtn.title='Text mode';
  textBtn.addEventListener('click',()=>_setNoteMode(wrapper,'text'));
  const drawBtn=document.createElement('button');drawBtn.className='note-mode-btn note-mode-draw';drawBtn.title='Draw mode (stylus/pen)';
  drawBtn.innerHTML='<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>';
  drawBtn.addEventListener('click',()=>_setNoteMode(wrapper,'draw'));
  const clearBtn=document.createElement('button');clearBtn.className='note-clear-btn';clearBtn.innerHTML='⌫';clearBtn.title='Clear drawing';
  clearBtn.addEventListener('click',()=>{const c=wrapper.querySelector('.note-canvas');if(c){const x=c.getContext('2d');x.clearRect(0,0,c.width,c.height);_saveNotes();}});

  const bgPicker=document.createElement('div');bgPicker.className='note-mini-picker';bgPicker.title='Background';
  const bgSwatch=document.createElement('div');bgSwatch.className='swatch';bgSwatch.style.background=bgColor;
  const bgInput=document.createElement('input');bgInput.type='color';bgInput.value='#0f172a';
  bgInput.addEventListener('input',()=>{bgColor=bgInput.value;bgSwatch.style.background=bgColor;wrapper.style.background=bgColor;_saveNotes();});
  bgPicker.appendChild(bgSwatch);bgPicker.appendChild(bgInput);
  const txPicker=document.createElement('div');txPicker.className='note-mini-picker';txPicker.title='Pen/text color';
  const txSwatch=document.createElement('div');txSwatch.className='swatch';txSwatch.style.background=textColor;
  const txInput=document.createElement('input');txInput.type='color';txInput.value='#94a3b8';
  txInput.addEventListener('input',()=>{textColor=txInput.value;txSwatch.style.background=textColor;const b=wrapper.querySelector('.note-body');if(b)b.style.color=textColor;_saveNotes();});
  txPicker.appendChild(txSwatch);txPicker.appendChild(txInput);

  const colors=document.createElement('div');colors.className='note-header-colors';
  colors.appendChild(textBtn);colors.appendChild(drawBtn);colors.appendChild(clearBtn);
  const spacer=document.createElement('div');spacer.style.cssText='width:6px';
  colors.appendChild(spacer);colors.appendChild(bgPicker);colors.appendChild(txPicker);

  const closeBtn=document.createElement('button');closeBtn.className='note-close';closeBtn.innerHTML='×';closeBtn.title='Delete';
  closeBtn.addEventListener('click',()=>{wrapper.remove();_saveNotes();});
  header.appendChild(colors);header.appendChild(closeBtn);

  const body=document.createElement('textarea');body.className='note-body';
  body.placeholder='Note…';body.style.color=textColor;
  body.addEventListener('input', _debounce(_saveNotes, 800));

  const cvs=document.createElement('canvas');cvs.className='note-canvas';
  _initCanvas(cvs, wrapper);

  wrapper.appendChild(header);wrapper.appendChild(body);wrapper.appendChild(cvs);

  let drag=false,ox=0,oy=0;
  header.addEventListener('mousedown',e=>{if(e.target.closest('.note-mode-btn,.note-clear-btn,.note-close,.note-mini-picker'))return;drag=true;ox=e.clientX-wrapper.offsetLeft;oy=e.clientY-wrapper.offsetTop;e.preventDefault();});
  header.addEventListener('touchstart',e=>{if(e.target.closest('.note-mode-btn,.note-clear-btn,.note-close,.note-mini-picker'))return;drag=true;const t=e.touches[0];ox=t.clientX-wrapper.offsetLeft;oy=t.clientY-wrapper.offsetTop;},{passive:true});
  document.addEventListener('mousemove',e=>{if(drag){wrapper.style.left=(e.clientX-ox)+'px';wrapper.style.top=(e.clientY-oy)+'px';}});
  document.addEventListener('touchmove',e=>{if(drag){const t=e.touches[0];wrapper.style.left=(t.clientX-ox)+'px';wrapper.style.top=(t.clientY-oy)+'px';}},{passive:true});
  document.addEventListener('mouseup',()=>{if(drag){drag=false;_saveNotes();}});
  document.addEventListener('touchend',()=>{if(drag){drag=false;_saveNotes();}});

  new ResizeObserver(()=>{
    if(wrapper.dataset.mode==='draw'&&cvs.style.display!=='none'){
      const w=cvs.offsetWidth,h=cvs.offsetHeight;
      if(w>0&&h>0&&(cvs.width!==w||cvs.height!==h)){
        const old=cvs.toDataURL();cvs.width=w;cvs.height=h;
        const img=new Image();img.onload=()=>cvs.getContext('2d').drawImage(img,0,0);img.src=old;
      }
    }
  }).observe(wrapper);

  return wrapper;
}

function createNote(){
  const _no=_noteCount%8;_noteCount++;
  const wrapper=_buildNote('#0f172a','#94a3b8');
  wrapper.style.left=(300+_no*28)+'px';wrapper.style.top=(200+_no*28)+'px';
  wrapper.dataset.noteId=Date.now();
  document.body.appendChild(wrapper);
  const body=wrapper.querySelector('.note-body');
  if(body) body.focus();
  _saveNotes();
}
document.getElementById('annotationBtn')?.addEventListener('click',createNote);
