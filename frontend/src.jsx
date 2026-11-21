import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';

const base = (window.RELAY_CONFIG?.api || import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
const modes = [['', 'Normal routing'], ['key_1=429', 'First key · 429'], ['key_1=500', 'First key · 500'], ['*=429', 'All keys · 429']];
const newId = () => crypto.randomUUID();
async function request(path, options) {
  let response;
  try { response = await fetch(base + path, options); }
  catch { throw new Error('Cannot reach the gateway. Check your connection and try again.'); }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'The gateway rejected this request (' + response.status + ').');
  return data;
}
function Mark({small=false}) {
  return <span aria-hidden="true" className={'mark '+(small?'small':'')}><i/><i/><i/></span>;
}
function Metadata({meta:m}) {
  return <div className="metadata"><b data-testid="meta-source">{m.resolution_source}</b>
    <span data-testid="meta-model">{m.model}</span><span data-testid="meta-latency">{m.latency_ms} ms</span>
    <span>In <strong data-testid="meta-input-tokens">{m.input_tokens}</strong></span>
    <span>Out <strong data-testid="meta-output-tokens">{m.output_tokens}</strong></span>
    <span>{m.key_id || 'cached'} · {m.fallback_attempts} retries</span></div>;
}
function App(){
  const [sid,setSid]=useState(newId), [turns,setTurns]=useState([]), [draft,setDraft]=useState('');
  const [prompt,setPrompt]=useState(''), [mode,setMode]=useState(''), [lab,setLab]=useState(false);
  const [health,setHealth]=useState(null), [busy,setBusy]=useState(false), [error,setError]=useState('');
  const [pending,setPending]=useState(''), [lastFirst,setLastFirst]=useState(null);
  const input=useRef(null), end=useRef(null), running=useRef(false);
  useEffect(()=>{let live=true; const check=()=>request('/health').then(v=>live&&setHealth(v)).catch(()=>live&&setHealth(false));
    check(); const timer=setInterval(check,30000); return ()=>{live=false;clearInterval(timer);};},[]);
  useEffect(()=>{if(turns.length||pending||error)end.current?.scrollIntoView({block:'nearest'});},[turns,pending,error]);
  function reset(){if(running.current)return; setSid(newId());setTurns([]);setLastFirst(null);setDraft('');setPrompt('');setMode('');setError('');input.current?.focus();}
  async function send(text=draft,replay=false){
    if(running.current||!text.trim())return;
    const message=text.trim(), session=replay?newId():sid, system=replay?lastFirst.prompt:prompt;
    if(replay){setSid(session);setTurns([]);setPrompt(system);setMode('');}
    running.current=true;setBusy(true);setError('');setDraft('');setPending(message);
    try {
      const headers={'Content-Type':'application/json'};
      if(mode&&!replay)headers['X-Simulate-Failure']=mode;
      const d=await request('/chat',{method:'POST',headers,body:JSON.stringify({session_id:session,message,...(system?{system_prompt:system}:{})})});
      if(d.session_id!==session || typeof d.reply!=='string' || !d.metadata || !['LLM_CACHE','LIVE_INFERENCE'].includes(d.metadata.resolution_source)) throw new Error('The gateway returned an incomplete reply');
      if(!turns.length||replay)setLastFirst({message,prompt:system});
      setTurns(old=>[...old,{message,reply:d.reply,metadata:d.metadata}]);
    }catch(e){setError(e.message);setDraft(message);}
    finally{running.current=false;setPending('');setBusy(false);input.current?.focus();}
  }
  const cached=turns.filter(t=>t.metadata.resolution_source==='LLM_CACHE').length;
  return <div className="shell"><header><div className="brand"><Mark/>Relay<span className="slash">/</span><span className="sub">Inference workspace</span></div>
    <span className={'status '+(health?'online':'')}><i/>{health?'Gateway online':health===null?'Connecting':'Gateway offline'}</span></header>
  <main><section className="workspace"><div className="workspace-head"><span className="eyebrow">Conversation</span><button className="quiet" onClick={reset} disabled={busy}>＋ New session</button></div>
    <div className="scroll" role="log" aria-live="polite">
    {!turns.length&&!pending&&<div className="welcome"><div className="tile"><Mark/></div><h1>Start a conversation<span>.</span></h1>
      <p>Ask a question, then inspect how the gateway answered.</p>
      <div className="suggest">{['Explain API key failover','When is a response cached?'].map(s=><button disabled={busy} key={s} onClick={()=>{setDraft(s);input.current?.focus();}}>{s} ↗</button>)}</div></div>}
    {turns.map((t,i)=><article key={i}><div className="userline"><small>You</small><p>{t.message}</p></div>
      <div className="answer" data-testid="assistant-message"><small><Mark small/>Relay</small><p>{t.reply}</p><Metadata meta={t.metadata}/></div></article>)}
    {pending&&<div className="pending"><p>{pending}</p><small>Waiting for the gateway…</small></div>}
    {error&&<p className="error" role="alert">{error}. Your message is in the composer.</p>}<div ref={end}/></div>
    <form onSubmit={e=>{e.preventDefault();send();}}><textarea ref={input} aria-label="Chat message" data-testid="chat-input" value={draft} disabled={busy} maxLength={4000}
      onChange={e=>setDraft(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();send();}}} placeholder="Message Relay…" />
      <div className="formfoot"><small>Shift + Enter for a new line</small><button className="primary" data-testid="send-button" disabled={busy||!draft.trim()}>Send ↑</button></div></form>
  </section><aside><div className="panel"><div className="eyebrow">Session inspector</div><h2>Request activity</h2>
    <div className="numbers"><div><strong>{turns.length}</strong><small>Replies</small></div><div><strong>{cached}</strong><small>Cache hits</small></div></div>
    <dl><dt>Session</dt><dd title={sid}>{sid.slice(0,8)}</dd><dt>Keys loaded</dt><dd>{health?.keys_configured??'—'}</dd><dt>Last route</dt><dd>{turns.at(-1)?.metadata.key_id||(turns.length?'Cache':'—')}</dd></dl>
    {turns.length>0&&<a href={base+'/sessions/'+encodeURIComponent(sid)+'/messages'} target="_blank" rel="noreferrer">Open history JSON ↗</a>}</div>
    <div className="panel lab"><button className="lab-toggle" aria-expanded={lab} onClick={()=>setLab(!lab)}>Resilience Lab <span>{lab?'−':'+'}</span></button>
      <p>Test routing and replay a cached request.</p>{lab&&<div className="controls"><label>Failure simulation<select disabled={busy} value={mode} onChange={e=>setMode(e.target.value)}>{modes.map(([v,l])=><option value={v} key={l}>{l}</option>)}</select></label>
      <button className="replay" disabled={busy||!lastFirst} onClick={()=>send(lastFirst.message,true)}>Replay first turn ↗</button><small>Starts a fresh session with the same first message and system prompt.</small></div>}</div>
    <details className="panel"><summary>System prompt</summary><textarea aria-label="Session system prompt" data-testid="system-prompt-input" maxLength={4000} placeholder="Use the default assistant instructions" disabled={busy||turns.length>0} value={prompt} onChange={e=>setPrompt(e.target.value)}/><small>Set before the first turn.</small></details>
    <a className="healthlink" href={base+'/health'} target="_blank" rel="noreferrer">Gateway health ↗</a>
  </aside></main></div>;
}
createRoot(document.getElementById('root')).render(<App/>);
