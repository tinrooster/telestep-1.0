"""The narrated player: one self-contained HTML file that plays a recording back as a slideshow, showing each step's
screenshot while its voice note plays and moving on by itself (like the Play all button in the review window).

No server and no internet needed: pictures and sound are embedded, so the file can be emailed or opened from a USB stick.
Recordings made without narration still work: each step is shown for a few seconds, longer for longer captions."""
import html
import json
from pathlib import Path

import telestep_audio as audio
import telestep_report as rep

PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>__TITLE__</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--acc:__ACC__;--bg:#14171a;--panel:#1d2227;--ink:#e8ecf0;--dim:#9aa5b1}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 "Segoe UI",system-ui,sans-serif;display:flex;flex-direction:column;height:100vh}
header{display:flex;align-items:center;gap:12px;padding:8px 16px;background:var(--panel);border-bottom:1px solid #2b323a}
header img{height:34px}header h1{font-size:17px;margin:0;font-weight:600}header .by{color:var(--dim);font-size:13px;margin-left:auto}
main{flex:1;display:flex;min-height:0}
.left{flex:1;display:flex;flex-direction:column;min-width:0}
.stage{flex:1;display:flex;align-items:center;justify-content:center;padding:12px;min-height:0;position:relative}
.stage img{max-width:100%;max-height:100%;object-fit:contain;border-radius:6px;box-shadow:0 4px 24px #0008}
.card{max-width:640px;text-align:center;font-size:24px;padding:30px;border:2px solid var(--acc);border-radius:12px}
.card small{display:block;color:var(--dim);font-size:13px;letter-spacing:.1em;text-transform:uppercase;margin-bottom:8px}
.badge{position:absolute;left:22px;top:22px;background:var(--acc);color:#fff;font-weight:700;padding:3px 12px;border-radius:14px}
.cap{padding:6px 18px 0;font-size:20px;font-weight:600;min-height:32px}.com{padding:0 18px;color:var(--dim);font-style:italic;min-height:22px}
.bar{display:flex;gap:2px;padding:10px 16px 4px}.seg{flex:1;height:6px;background:#2f3740;border-radius:3px;cursor:pointer;overflow:hidden}.seg i{display:block;height:100%;width:0;background:var(--acc)}
.seg.done i{width:100%}
.ctl{display:flex;align-items:center;gap:10px;padding:6px 16px 14px}
button,select{background:#2b323a;color:var(--ink);border:1px solid #3a434d;border-radius:8px;padding:7px 14px;font:inherit;cursor:pointer}
button:hover{background:#36404a}button.big{background:var(--acc);border-color:var(--acc);color:#fff;font-weight:700;min-width:96px}
.ctl .n{color:var(--dim);margin-left:auto}
aside{width:300px;background:var(--panel);border-left:1px solid #2b323a;overflow:auto}
aside div{padding:8px 12px;border-bottom:1px solid #262d34;cursor:pointer;font-size:13px;display:flex;gap:8px}
aside div:hover{background:#252c33}aside div.on{background:#2a3744;border-left:3px solid var(--acc)}aside b{color:var(--acc);min-width:22px}
#start{position:fixed;inset:0;background:#000b;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:14px;z-index:5}
#start button{font-size:22px;padding:16px 34px}
@media(max-width:800px){aside{display:none}.cap{font-size:17px}}
</style></head><body>
<header>__LOGO__<h1>__TITLE__</h1><span class="by">__BY__</span></header>
<main><div class="left"><div class="stage" id="stage"></div><div class="cap" id="cap"></div><div class="com" id="com"></div>
<div class="bar" id="bar"></div>
<div class="ctl"><button id="prev" title="Previous (Left arrow)">&#9198;</button><button id="play" class="big" title="Play / pause (Space)">&#9654; Play</button>
<button id="next" title="Next (Right arrow)">&#9197;</button>
<select id="rate" title="Speed"><option value="1">1x</option><option value="1.25">1.25x</option><option value="1.5">1.5x</option><option value="2">2x</option></select>
<span class="n" id="count"></span></div></div><aside id="list"></aside></main>
<div id="start"><div style="font-size:20px">__TITLE__</div><button id="go">&#9654; Play walkthrough</button><div style="color:#9aa5b1">__HINT__</div></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const S=JSON.parse(document.getElementById('data').textContent);
const $=id=>document.getElementById(id);
let i=0,playing=false,timer=null,timer2=null,rate=1,t0=0,dur=0,raf=0;const au=new Audio();
const bar=$('bar'),list=$('list');
S.forEach((s,k)=>{const g=document.createElement('div');g.className='seg';g.innerHTML='<i></i>';g.onclick=()=>show(k);bar.appendChild(g);
 const d=document.createElement('div');d.innerHTML='<b></b><span></span>';d.children[0].textContent=s.n||'';d.children[1].textContent=(s.audio?'\u{1F50A} ':'')+s.text;d.onclick=()=>show(k);list.appendChild(d)});
function pic(src){const st=$('stage');st.innerHTML='';const im=document.createElement('img');im.src=src;st.appendChild(im);return st}
function show(k,keep){i=Math.max(0,Math.min(S.length-1,k));const s=S[i];clearTimeout(timer);clearTimeout(timer2);cancelAnimationFrame(raf);au.pause();au.onended=null;
 const st=$('stage');
 if(s.imgs.length){pic(s.imgs[0]);if(s.n){const b=document.createElement('div');b.className='badge';b.textContent='Step '+s.n;st.appendChild(b)}}
 else{st.innerHTML='<div class="card"><small>'+(s.kind==='section'?'Section':s.label||'Note')+'</small></div>';st.firstChild.append(document.createTextNode(s.text))}
 $('cap').textContent=s.imgs.length?s.text:'';$('com').textContent=s.comment||'';
 [...bar.children].forEach((g,j)=>{g.className='seg'+(j<i?' done':'');g.firstChild.style.width=j<i?'100%':'0'});
 [...list.children].forEach((d,j)=>d.className=j===i?'on':'');list.children[i].scrollIntoView({block:'nearest'});
 $('count').textContent=(i+1)+' / '+S.length;if(playing)run()}
function words(s){return s.text.split(/\s+/).length+(s.comment?s.comment.split(/\s+/).length:0)}
function run(){const s=S[i];t0=performance.now();
 if(s.audio){au.src=s.audio;au.playbackRate=rate;au.onended=next;dur=(s.dur||3)*1000/rate;au.play().catch(()=>{pause()})}
 else{dur=Math.max(2500,words(s)*450)/rate;timer=setTimeout(next,dur)}
 if(s.imgs.length>1)timer2=setTimeout(()=>{const im=$('stage').querySelector('img');if(im)im.src=s.imgs[1]},dur/2);
 tick()}
function tick(){const g=bar.children[i];g.firstChild.style.width=Math.min(100,(performance.now()-t0)/dur*100)+'%';raf=requestAnimationFrame(tick)}
function next(){if(i<S.length-1)show(i+1);else{pause();[...bar.children].forEach(g=>{g.className='seg done'})}}
function play(){playing=true;$('play').innerHTML='&#10074;&#10074; Pause';if(i>=S.length-1&&!S.length)return;run()}
function pause(){playing=false;$('play').innerHTML='&#9654; Play';clearTimeout(timer);clearTimeout(timer2);cancelAnimationFrame(raf);au.pause()}
$('play').onclick=()=>playing?pause():play();$('prev').onclick=()=>show(i-1);$('next').onclick=()=>show(i+1);
$('rate').onchange=e=>{rate=parseFloat(e.target.value);au.playbackRate=rate;if(playing)show(i)};
$('go').onclick=()=>{$('start').style.display='none';play()};
addEventListener('keydown',e=>{if(e.code==='Space'){e.preventDefault();$('play').click()}else if(e.key==='ArrowRight')show(i+1);else if(e.key==='ArrowLeft')show(i-1);else if(e.key==='Home')show(0)});
show(0);
</script></body></html>"""


def _items(session, tpl):
    out = []
    for b in rep.build_blocks(session, tpl):
        if b["type"] == "step":
            a = b["audio"]
            out.append({"kind": "step", "n": b["n"], "text": b["text"], "comment": b["comment"],
                        "imgs": [rep._data_uri(session.dir / rel) for _l, rel in b["images"]],
                        "audio": rep._data_uri(session.dir / a) if a else "",
                        "dur": round(audio.duration(session.dir / a), 2) if a else 0})
        elif b["type"] == "section":
            out.append({"kind": "section", "n": "", "text": b["text"], "comment": "", "imgs": [], "audio": "", "dur": 0})
        elif b["type"] == "callout":
            out.append({"kind": "note", "label": rep.CALLOUT[b["level"]][0], "n": "", "text": b["text"].strip(),
                        "comment": "", "imgs": [], "audio": "", "dur": 0})
    return out


def write(session, tpl):
    items = _items(session, tpl)
    if not any(i["kind"] == "step" for i in items):
        raise ValueError("no steps to play")
    has_audio = any(i["audio"] for i in items)
    logo = f"<img alt='' src='{rep._data_uri(rep._logo(tpl))}'>" if rep._logo(tpl) else ""
    title = rep.clean_text(session.title)
    page = (PAGE.replace("__TITLE__", html.escape(title)).replace("__ACC__", tpl.accent or "#1e88e5")
            .replace("__LOGO__", logo).replace("__BY__", html.escape(rep._byline(tpl) or ""))
            .replace("__HINT__", "Space = play / pause, arrow keys = previous / next" +
                     ("" if has_audio else " (this recording has no voice notes, so each step shows for a few seconds)"))
            .replace("__DATA__", json.dumps(items).replace("</", "<\\/")))
    path = session.dir / "walkthrough.html"
    path.write_text(page, encoding="utf-8")
    return path
