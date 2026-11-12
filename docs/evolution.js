/* SwingPilot Evolution: read-only portfolio overview. No browser-side trading. */
(function () {
  "use strict";
  const host = document.getElementById("evo-dashboard");
  if (!host) return;
  const money = n => "CHF " + new Intl.NumberFormat("de-CH", {minimumFractionDigits: 2, maximumFractionDigits: 2}).format(Number(n) || 0);
  const number = n => new Intl.NumberFormat("de-CH", {minimumFractionDigits: 2, maximumFractionDigits: 2}).format(Number(n) || 0);
  const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, s => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[s]));
  const percent = n => (n > 0 ? "+" : "") + number(n) + " %";
  const pnlClass = n => n > 0 ? "ev-positive" : n < 0 ? "ev-negative" : "";
  let previous = null;
  function tradeLine(bot) {
    const trades = (bot.trades || []).slice(-2).reverse();
    return trades.length ? trades.map(t => '<div class="ev-trade"><b>' + escapeHtml(t.side) + '</b> ' +
      escapeHtml(t.qty) + ' × ' + escapeHtml(t.ticker) + ' · ' + escapeHtml(t.date) + '</div>').join("") :
      '<div class="ev-muted">Noch keine simulierten Orders</div>';
  }
  function card(bot, i) {
    const totalPnl = bot.nav_chf - bot.initial_capital_chf;
    const holdings = Object.entries(bot.positions || {}).filter(([,q]) => q > 0);
    const holdingStr = holdings.length ? holdings.map(([t,q]) => escapeHtml(t) + " × " + escapeHtml(q)).join(" · ") : "Keine Positionen";
    return '<article class="glass ev-bot">' +
      '<div class="ev-bot-head"><div><span class="ev-muted">Rang ' + (i+1) + ' · Generation ' + escapeHtml(bot.generation) + '</span><h3>' + escapeHtml(bot.name) + '</h3><div class="ev-muted">' + escapeHtml(bot.style) + '</div></div><span class="ev-pill">Aktiv</span></div>' +
      '<div class="ev-value">' + money(bot.nav_chf) + '</div>' +
      '<div class="ev-pnl ' + pnlClass(totalPnl) + '">' + (totalPnl >= 0 ? "+" : "") + money(totalPnl) + ' (' + percent(totalPnl / bot.initial_capital_chf * 100) + ') seit Start</div>' +
      '<div class="ev-info"><span>Cash: <b>' + money(bot.cash_chf) + '</b></span><span>Drawdown: <b>' + number(bot.drawdown_pct) + ' %</b></span></div>' +
      '<div class="ev-divider"></div><div class="ev-muted">Offene Positionen</div><div class="ev-holdings">' + holdingStr + '</div>' +
      '<div class="ev-divider"></div>' + tradeLine(bot) +
      ((bot.stale_holdings || []).length ? '<div class="ev-warning">Unbewertete Kurse: ' + escapeHtml(bot.stale_holdings.join(", ")) + '</div>' : "") +
      '</article>';
  }
  function render(data) {
    if (!Array.isArray(data.bots) || data.bots.length !== 5) throw new Error("Ungültige Bot-Daten");
    const total = Number(data.total_nav_chf);
    const totalPnl = total - Number(data.total_start_chf);
    const ranked = data.bots.slice().sort((a,b) => ((b.nav_chf-b.initial_capital_chf) / b.initial_capital_chf) - ((a.nav_chf-a.initial_capital_chf) / a.initial_capital_chf));
    const grave = (data.graveyard || []).slice().reverse();
    const events = (data.evolution_events || []).slice().reverse();
    const coverage = data.market_coverage || {};
    host.innerHTML = '<div class="ev-header"><div><div class="eyebrow">EVOLUTION ENGINE · PAPER ONLY</div>' +
      '<h2>5 Bots. Ein Wettbewerb.</h2><p class="ev-muted">Fünf getrennte Depots à CHF 2’000 · generationenbasierte Strategieoptimierung</p></div>' +
      '<button type="button" class="btn" id="ev-refresh">Bots aktualisieren ↻</button></div>' +
      '<div class="ev-summary"><div class="glass"><div class="eyebrow">Gemeinsamer Demo-Wert</div><div class="ev-big">' + money(total) + '</div><div class="' + pnlClass(totalPnl) + '">' + (totalPnl >= 0 ? "+" : "") + money(totalPnl) + ' (' + percent(totalPnl / data.total_start_chf * 100) + ')</div></div>' +
      '<div class="glass"><div class="eyebrow">Letzter Handelstag</div><div class="ev-big">' + escapeHtml(data.last_date) + '</div><div class="ev-muted">Start ' + escapeHtml(data.start_date) + '</div></div>' +
      '<div class="glass"><div class="eyebrow">Bot-Generationen</div><div class="ev-big">' + data.bots.reduce((x,b) => x + Number(b.generation>1),0) + ' ersetzt</div><div class="ev-muted">' + grave.length + ' ausgeschieden</div></div></div>' +
      '<div class="ev-legend">Rangliste – nach Rendite seit dem Start des Experiments</div><div class="ev-grid">' + ranked.map(card).join("") + '</div>' +
      '<div class="ev-bottom"><div class="glass"><h3>Evolution & neue Generationen</h3>' +
      (events.length ? events.map(e => '<div class="ev-event"><b>' + escapeHtml(e.born) + '</b> ersetzt ' + escapeHtml(e.retired) + ' · ' + money(e.inherited_capital_chf) + ' geerbt · Elternstrategie: ' + escapeHtml(e.parent) + ' · ' + escapeHtml(e.date) + '</div>').join("") : '<div class="ev-muted">Noch kein Bot ausgeschieden. Die Mindestlaufzeit und Verlustgrenzen schützen vor voreiligen Wechseln.</div>') +
      '</div><div class="glass"><h3>Archiv ausgeschiedener Bots</h3>' +
      (grave.length ? grave.map(g => '<div class="ev-event"><b>' + escapeHtml(g.bot_id) + '</b> · ' + percent(g.roi_pct) + ' · Endkapital ' + money(g.end_chf) + '</div>').join("") : '<div class="ev-muted">Noch keine ausgeschiedenen Bots</div>') +
      '</div></div>' +
      (data.warnings && data.warnings.length ? '<div class="ev-warning">Kursdatenwarnung: ' + escapeHtml(data.warnings.join("; ")) + '</div>' : '') +
      '<p class="ev-disclaimer">Stand: ' + escapeHtml(data.last_date) + ' · Scanner: ' + escapeHtml(coverage.valid ?? "?") + '/' + escapeHtml(coverage.attempted ?? "?") + ' gültige Werte. Nur Tageskurse; simulierte Schlusskurs-Ausführungen und Gebühren. Regelbasierte Parameter-Mutation, noch kein trainiertes KI-Modell. Keine Echtgeldorders und keine garantierten Gewinne. Das bisherige Depot oben ist ein separates Vergleichsexperiment und wird nicht zum Evolutionskapital addiert.</p>';
    document.getElementById("ev-refresh").addEventListener("click", load);
  }
  async function load() {
    if (!previous) host.innerHTML = '<div class="ev-muted">Lade die fünf virtuellen Bot-Depots …</div>';
    try {
      const res = await fetch("./data/evolution.json?ts=" + Date.now(), {cache:"no-store"});
      if (!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      previous = data;
      render(data);
    } catch (e) {
      host.innerHTML = '<div class="ev-warning">Evolution-Daten konnten nicht geladen werden: ' + escapeHtml(e.message) + '</div>';
    }
  }
  const reload = document.getElementById("reload");
  if (reload) reload.addEventListener("click", load);
  load();
})();
