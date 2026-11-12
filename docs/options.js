(function () {
"use strict";
const el = id => document.getElementById(id);
const fmt = n => new Intl.NumberFormat("de-CH", {minimumFractionDigits:2,maximumFractionDigits:2}).format(Number(n)||0);
const money = n => "CHF " + fmt(n);
const escapeHtml = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const signed = n => (n>=0 ? "+" : "−") + money(Math.abs(n));
const cls = n => n>0 ? "up" : n<0 ? "down" : "";
function positionRow(pos) {
 return '<div class="contract"><strong>' + escapeHtml(pos.underlying) + ' ' +
 escapeHtml(pos.side?.toUpperCase()) + ' ' + fmt(pos.strike) +
 '</strong> · Verfall ' + escapeHtml(pos.expiry) +
 '<div class="secondary">' + escapeHtml(pos.symbol) +
 ' · ' + escapeHtml(pos.qty) + ' Kontrakt · Geld ' + money(pos.mark_chf) + '</div></div>';
}
function botCard(b, index) {
 const delta = Number(b.nav_chf)-Number(b.original_capital_chf);
 const positions=Object.values(b.positions||{});
 const pending=b.pending;
 const pendingHtml=pending ? '<div class="actions"><strong>Vorgemerkt:</strong> '+
 escapeHtml(pending.action === "BUY" ? "Optionskauf" : "Optionsverkauf") +
 ' · ' + escapeHtml(pending.symbol) + ' <div class="secondary">Simulierte Ausführung erst zum nächsten verfügbaren Schlusskurs</div></div>'
 : '<div class="secondary">Keine vorgemerkte Order</div>';
 const warning=(b.warnings||[]).length ? '<div class="notice warning">'+(b.warnings||[]).map(escapeHtml).join("; ")+'</div>' : "";
 const trade=(b.trades||[]).at(-1);
 const latest=trade ? '<div class="contract">Letzter Trade: '+escapeHtml(trade.side)+' · '+escapeHtml(trade.symbol)+' · '+escapeHtml(trade.date)+'</div>' : '<div class="secondary">Noch keine ausgeführte Optionsorder</div>';
 return '<article class="card"><div class="row"><div><div class="rank">Rang '+(index+1)+' · Generation '+escapeHtml(b.generation)+'</div><h3>'+escapeHtml(b.name)+'</h3><div class="secondary">'+escapeHtml(b.style)+'</div></div><span class="agent-status '+((b.warnings||[]).length?'agent-warn':'')+'">'+((b.warnings||[]).length?'Prüfen':'Aktiv')+'</span></div>'+
 '<div class="big">'+money(b.nav_chf)+'</div><div class="'+cls(delta)+'">'+signed(delta)+' ('+((delta/Number(b.original_capital_chf))*100).toFixed(2)+' %)</div>'+
 '<div class="divider"></div><div class="kv"><span>Cash</span><strong>'+money(b.cash_chf)+'</strong></div>'+
 '<div class="kv"><span>Drawdown</span><strong>'+fmt(b.drawdown_pct)+' %</strong></div>'+
 '<div class="kv"><span>Abgeschlossene Trades</span><strong>'+escapeHtml(b.closed_trades)+'</strong></div>'+
 '<div class="divider"></div><div class="eyebrow">Offene Optionen</div>'+
 (positions.length ? positions.map(positionRow).join("") : '<p class="secondary">Keine offenen Kontrakte</p>') +
 pendingHtml+latest+warning+'</article>';
}
function render(s) {
 if (!s.bots || s.bots.length!==5) throw new Error("Unvollständiger Bot-Status");
 const nav=Number(s.total_nav_chf);
 const pnl=nav-Number(s.total_start_chf);
 el("nav").textContent=money(nav);
 el("total-pnl").textContent=signed(pnl)+" ("+(pnl/Number(s.total_start_chf)*100).toFixed(2)+" %)";
 el("total-pnl").className=cls(pnl);
 el("market-date").textContent=s.last_date || "–";
 el("retire-count").textContent=(s.graveyard||[]).length;
 el("agent-count").textContent=s.bots.length;
 const rank=s.bots.slice().sort((a,b)=>
 (Number(b.nav_chf)-Number(b.original_capital_chf))/Number(b.original_capital_chf) -
 (Number(a.nav_chf)-Number(a.original_capital_chf))/Number(a.original_capital_chf));
 el("bots").innerHTML=rank.map(botCard).join("");
 const error=s.last_error || (s.warnings||[]).join("; ");
 let title=s.status==="setup_required" ? "Noch kein Optionsdaten-Zugang – Simulation pausiert" :
  s.status==="attention" ? "Achtung: Daten oder Kontrakte prüfen" :
  s.status==="active" ? "Automatisierte Options-Paper-Simulation aktiv" :
  "Options-Paper-Simulation vorbereitet";
 el("status").className="notice"+(error||s.status==="setup_required"?" warning":"");
 el("status").innerHTML='<strong>'+escapeHtml(title)+'</strong> · letzter Datenabruf '+escapeHtml(s.last_check || "noch keiner")+
 '<div>'+(error?escapeHtml(error):'Kein Datenfehler gemeldet. Letzter abgeschlossener Handelstag: '+escapeHtml(s.last_date))+'</div>'+
 '<div class="secondary">Ohne valide Optionskurse erfolgt keine Order. Alle Angaben sind Simulationen.</div>';
 const ev=(s.evolution_events||[]).slice().reverse();
 el("events").innerHTML=ev.length?ev.map(e=>'<div class="event"><strong>'+escapeHtml(e.born)+
 '</strong> ersetzt '+escapeHtml(e.retired)+' · Restkapital '+money(e.inherited_capital_chf)+
 ' · '+escapeHtml(e.date)+'</div>').join(""):'<div class="secondary">Alle fünf Start-Generationen leben noch.</div>';
 const dead=(s.graveyard||[]).slice().reverse();
 el("graveyard").innerHTML=dead.length?dead.map(g=>'<div class="event"><strong>'+escapeHtml(g.bot_id)+
 '</strong> · Start '+money(g.start_chf)+' · Ende '+money(g.end_chf)+
 ' · '+escapeHtml(g.date)+'</div>').join(""):'<div class="secondary">Noch keine ausgeschiedenen Bots.</div>';
}
async function reload(){
 try{
  const r=await fetch("./data/options.json?x="+Date.now(),{cache:"no-store"});
  if(!r.ok) throw Error("HTTP "+r.status);
  const state=await r.json();
  render(state);
 }catch(e){el("status").className="notice warning";el("status").textContent="Options-Daten konnten nicht geladen werden: "+e.message;}
}
el("reload").addEventListener("click",reload);
reload();
})();
