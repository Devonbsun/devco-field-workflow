/* Starts only after the Android wrapper announces this loaded Billing page. */
(function () {
'use strict';
const cfg = window.devcoVoiceConfig;
const form = document.querySelector('form[action="/finish"]');
if (!cfg || !form) return;
const note = form.elements.note;
const status = document.getElementById('voice-status');
const heard = document.getElementById('voice-heard');
const review = document.getElementById('voice-review');
const preview = document.getElementById('voice-note-preview');
const choice = document.getElementById('voice-close');
const finalize = document.getElementById('voice-finalize');
const caution = document.getElementById('voice-caution');
const original = document.getElementById('voice-original');
const session = 'v' + Date.now() + '_' + Math.random().toString(36).slice(2);
const draftKey = 'devco-voice:' + cfg.job + ':' + cfg.ju;
let started = false, stopped = false, phase = 'idle', attempt = {notes:0, close:0};
let generation = 0, request = null, rawNotes = '', rawClose = '', guardTimer = null;

function nativePrompt(stage) {
 phase = stage;
 location.href = 'devco-voice://prompt?session=' + encodeURIComponent(session) + '&stage=' + encodeURIComponent(stage);
}
function stop(message, notifyNative=true) {
 stopped = true; generation++;
 if (request) request.abort(); request = null;
 clearInterval(guardTimer);
 if (notifyNative && started) location.href = 'devco-voice://stop';
 if (message) status.textContent = message;
}
function stash() {
 try { localStorage.setItem(draftKey,JSON.stringify({rawNotes,rawClose,close:choice.value})); } catch(e) {}
}
function updateReview() {
 preview.textContent = note.value || 'No notes';
 finalize.value = choice.value;
 finalize.disabled = !choice.value;
 stash();
}
function showReview(message) {
 phase = 'review'; review.hidden = false;
 status.textContent = message || 'Review your note and closing task before finalizing.';
 original.textContent = rawNotes;
 updateReview();
}
async function post(path, payload) {
 request = new AbortController();
 const response = await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal:request.signal});
 const data = await response.json();
 if (!response.ok) throw Error(data.error || 'Could not save');
 request = null;
 return data;
}
async function currentJU() {
 const response = await fetch('/status',{cache:'no-store'});
 if (!response.ok) throw Error('Connection unavailable');
 const current = await response.json();
 return current.job === cfg.job && current.ju === cfg.ju;
}
async function guard() {
 if (document.hidden || stopped) return;
 try { if (!(await currentJU())) stop('The active JU changed. Reopen closeout for the current JU; your draft is kept.'); }
 catch(e) { stop('Connection lost. Your draft is kept; use the manual controls after reconnecting.'); }
}
window.devcoVoiceReady = async function () {
 if (started || stopped || !cfg.autostart || document.hidden) return;
 started = true;
 try {
  await window.devcoSaveBillingNote();
  if (stopped || document.hidden) return;
  if (!(await currentJU())) { stop('The active JU changed. Reopen closeout for the current JU.'); return; }
  guardTimer = setInterval(guard,2500);
  nativePrompt('notes');
 } catch(e) { stop('Could not save the existing note. Your draft is kept; use the manual controls.'); }
};
window.devcoVoiceEvent = async function (event) {
 if (event.session !== session || stopped) return;
 const baseStage = event.stage.replace(/^retry-/,'');
 if (baseStage !== phase.replace(/^retry-/,'')) return;
 if (event.type === 'partial') { heard.textContent = event.transcript; return; }
 if (event.type === 'permission' || event.type === 'speaking' || event.type === 'listening' || event.type === 'processing') {
  status.textContent = event.message; return;
 }
 if (event.type === 'error' || event.type === 'stopped') { stop(event.message,false); showReview(event.message); return; }
 if (event.type === 'retry') {
  if (event.transcript) heard.textContent = event.transcript;
  if (attempt[baseStage]++ < 1) nativePrompt('retry-' + baseStage);
  else { stop('Speech was unclear. Enter the note or choose a closing task below.'); showReview(status.textContent); }
  return;
 }
 if (event.type !== 'result') return;
 const ticket = ++generation;
 heard.textContent = event.transcript;
 if (baseStage === 'notes') {
  rawNotes = event.transcript; stash(); phase = 'saving';
  status.textContent = 'Cleaning and saving your note…';
  try {
   await window.devcoSaveBillingNote();
   if (stopped || ticket !== generation) return;
   const expected = note.value;
   const result = await post('/voice-note',{job:cfg.job,ju:cfg.ju,transcript:rawNotes,expected_note:expected});
   if (stopped || ticket !== generation) return;
   window.devcoAcceptSavedNote(result.note);
   original.textContent = rawNotes; preview.textContent = result.note || 'No notes';
   caution.textContent = result.review_reason || '';
   review.hidden = false;
   status.textContent = 'Note saved. Asking for the closing task…';
   nativePrompt('close');
  } catch(e) { if (e.name !== 'AbortError') { stop(e.message); showReview(e.message); } }
 } else if (baseStage === 'close') {
  rawClose = event.transcript; stash(); phase = 'matching';
  try {
   const result = await post('/voice-close',{job:cfg.job,ju:cfg.ju,transcript:rawClose});
   if (stopped || ticket !== generation) return;
   if (!result.close) {
    if (attempt.close++ < 1) { nativePrompt('retry-close'); return; }
    stop(result.message); showReview(result.message); return;
   }
   choice.value = result.close;
   showReview(result.message);
   // Selection is deliberately separate from the user's final submit action.
   location.href = 'devco-voice://stop';
   clearInterval(guardTimer);
  } catch(e) { if (e.name !== 'AbortError') { stop(e.message); showReview(e.message); } }
 }
};
choice.addEventListener('change',()=>{stop('Review your note and chosen closing task.');showReview(status.textContent);});
note.addEventListener('input',()=>{if(started&&!stopped&&phase!=='review')stop('Manual editing selected. Your note still saves automatically.');updateReview();});
// Any manual close button cancels speech but retains the existing manual behavior.
form.addEventListener('submit',()=>{stop('',true);try{localStorage.removeItem(draftKey);}catch(e){}},true);
document.getElementById('voice-manual').addEventListener('click',()=>{stop('Manual controls selected.');showReview(status.textContent);note.focus();});
document.addEventListener('visibilitychange',()=>{
 // Native code handles the microphone permission sheet; never restart on a photo or resume.
 if (document.hidden && phase !== 'notes' && phase !== 'retry-notes') { if (started) stop('Voice paused. Your note is kept.',false); }
});
window.addEventListener('pagehide',()=>stop('',false));
try {
 const saved=JSON.parse(localStorage.getItem(draftKey)||'null');
 if(saved){rawNotes=saved.rawNotes||'';rawClose=saved.rawClose||'';original.textContent=rawNotes;}
} catch(e) {}
if(!cfg.autostart)status.textContent='Review the saved note and use the manual controls to complete this JU.';
// Older app versions and ordinary browsers retain fully functional manual closeout.
setTimeout(()=>{if(!started&&!stopped)status.textContent='Automatic voice needs the DEVCO voice update. Manual controls are available.';},2500);
})();
