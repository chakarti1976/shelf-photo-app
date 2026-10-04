import * as V from "./valuation.js";

const $ = (s) => document.querySelector(s);
const ok = (x) => typeof x === "number" && Number.isFinite(x);
const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));
const first = (...xs) => xs.find(ok) ?? null;

let D = null;   // data from /api/data
let I = {};     // current inputs (fractions for percentages)
let SRC = {};   // where each default came from
let method = "simple";
let lastR = null;     // latest computed results, used when saving
let savedAt = null;   // set while viewing a saved valuation

// ------------------------------------------------------------ formatting
const nf = (d) => new Intl.NumberFormat("bg-BG", { minimumFractionDigits: d, maximumFractionDigits: d });
const fmt = {
  money: (x) => (ok(x) ? nf(2).format(x) + " " + (D?.currency || "") : "—"),
  num: (x) => (ok(x) ? nf(2).format(x) : "—"),
  m: (x) => (ok(x) ? nf(1).format(x) : "—"),
  pct: (x) => (ok(x) ? nf(2).format(x * 100) + "%" : "—"),
  big: (x) => {
    if (!ok(x)) return "—";
    const a = Math.abs(x);
    if (a >= 1e12) return nf(2).format(x / 1e12) + " трлн.";
    if (a >= 1e9) return nf(2).format(x / 1e9) + " млрд.";
    if (a >= 1e6) return nf(2).format(x / 1e6) + " млн.";
    return nf(0).format(x);
  },
  text: (x) => (x ?? "—"),
};
const signalHTML = (s, big = false) =>
  s ? `<span class="badge ${s === "Купи" ? "buy" : "sell"}${big ? " big-badge" : ""}">${s}</span>` : "—";
// Price vs value: below value (negative difference) is good.
const diffHTML = (x) => (ok(x) ? `<span class="${x <= 0 ? "pos" : "neg"}">${fmt.pct(x)}</span>` : "—");
const retHTML = (x) => (ok(x) ? `<span class="${x >= 0 ? "pos" : "neg"}">${fmt.pct(x)}</span>` : "—");

// ------------------------------------------------------------ input paths
const getPath = (path) => path.split(".").reduce((o, k) => (o == null ? o : o[k]), I);
function setPath(path, v) {
  const keys = path.split(".");
  let o = I;
  for (const k of keys.slice(0, -1)) o = o[k];
  o[keys.at(-1)] = v;
}

function field(path, label, kind = "num", narrow = false) {
  const v = getPath(path);
  const shown = !ok(v) ? "" : kind === "pct" ? +(v * 100).toFixed(4) : +v.toFixed(4);
  const src = SRC[path] ? `<span class="src">${SRC[path]}</span>` : "";
  return `<div class="row"><label>${label}${kind === "pct" ? " (%)" : ""}${src}</label>
    <input class="y${narrow ? " narrow" : ""}${ok(v) ? "" : " missing"}" data-path="${path}" data-kind="${kind}"
      inputmode="decimal" value="${shown}"></div>`;
}
const cell = (path, kind = "num") => {
  const v = getPath(path);
  const shown = !ok(v) ? "" : kind === "pct" ? +(v * 100).toFixed(4) : +v.toFixed(4);
  return `<input class="y narrow${ok(v) ? "" : " missing"}" data-path="${path}" data-kind="${kind}" inputmode="decimal" value="${shown}">`;
};
const out = (key, label, f = "num") => `<div class="row"><span>${label}</span><span class="out" data-out="${key}" data-fmt="${f}">—</span></div>`;
const o = (key, f = "num") => `<span data-out="${key}" data-fmt="${f}">—</span>`;

// ------------------------------------------------------------ defaults
function defaults(d) {
  const f = d.finviz || {}, y = d.yahoo || {}, s = d.sec || {}, dv = d.dividends;
  const src = {};
  const pick = (key, pairs, fallback = null, fallbackSrc = "по подразбиране") => {
    for (const [v, from] of pairs) if (ok(v)) { src[key] = from; return v; }
    src[key] = fallbackSrc;
    return fallback;
  };
  const in_ = {};
  in_.price = pick("price", [[y.price, "Yahoo"], [f.price, "Finviz"]]);
  const epsHist = Object.values(s.epsHistory || {});
  in_.eps = pick("eps", [[f.eps, "Finviz"], [epsHist.at(-1), "SEC"]]);
  const epsCagr = epsHist.length >= 6 && epsHist.at(-6) > 0 && epsHist.at(-1) > 0
    ? (epsHist.at(-1) / epsHist.at(-6)) ** (1 / 5) - 1 : null;
  // Graham growth is entered as a plain percent number (4.09 = 4.09%).
  in_.growthG = pick("growthG", [[ok(f.epsNext5Y) ? f.epsNext5Y * 100 : null, "Finviz, анализатори 5 г."],
    [ok(f.epsPast5Y) ? f.epsPast5Y * 100 : null, "Finviz, минали 5 г."], [ok(epsCagr) ? epsCagr * 100 : null, "SEC, EPS 5 г."]], 5);
  in_.aaa = pick("aaa", [[d.aaa?.value, `FRED ${d.aaa?.date || ""}`]], 4.4, "няма данни — въведи");
  in_.baseYield = 4.4;
  in_.marginG = 0.1;

  // DCF (millions)
  const fcfYears = Object.keys(s.fcf || {});
  in_.fcfHist = fcfYears.map((yr) => ({ year: yr, val: s.fcf[yr] }));
  const finvizFcf = ok(f.marketCap) && ok(f.pfcf) && f.pfcf > 0 ? f.marketCap / f.pfcf / 1e6 : null;
  in_.fcfTTM = pick("fcfTTM", [[s.fcfTTM, `SEC, TTM до ${s.fcfTTMEnd || ""}`], [finvizFcf, "Finviz (Капитализация ÷ P/FCF)"],
    [in_.fcfHist.at(-1)?.val, "SEC, последна година"]]);
  const fcfStats = V.growthStats([...in_.fcfHist.map((r) => r.val), in_.fcfTTM]);
  in_.growthDCF = pick("growthDCF", [
    [ok(f.epsNext5Y) ? clamp(f.epsNext5Y, 0, 0.15) : null, "анализатори EPS 5 г. (макс. 15%)"],
    [ok(fcfStats.cagr) ? clamp(fcfStats.cagr, 0, 0.15) : null, "история на FCF (макс. 15%)"]], 0.07);
  in_.terminalGrowth = 0.03;
  in_.discount = 0.1;
  in_.cash = pick("cash", [[s.cash, `SEC ${s.balanceDate || ""}`]]);
  in_.debt = pick("debt", [[s.debt, `SEC ${s.balanceDate || ""}`]], 0);
  in_.sharesM = pick("sharesM", [[ok(f.sharesOut) ? f.sharesOut / 1e6 : null, "Finviz"], [s.sharesM, "SEC"]]);

  // EV/EBITDA
  in_.ebitdaHist = Object.keys(s.ebitda || {}).map((yr) => ({ year: yr, val: s.ebitda[yr] }));
  in_.g1 = 0.05; in_.g2 = 0.02; in_.marginEV = 0.05;
  const peerEV = (d.peers || []).map((p) => p.evEbitda).filter((x) => ok(x) && x > 0 && x < 100);
  in_.evMultiple = pick("evMultiple", [[peerEV.length ? peerEV.reduce((a, b) => a + b) / peerEV.length : null, "средно за сравнимите (Finviz)"],
    [ok(f.evEbitda) && f.evEbitda > 0 ? f.evEbitda : null, "собствен EV/EBITDA (Finviz)"]], 10);

  // Multiple
  in_.peers = (d.peers || []).map((p) => ({ ticker: p.ticker, name: p.name, price: p.price, eps: p.eps }));

  // DDM
  in_.divs = dv ? dv.payments.map((v, i) => ({ year: dv.years[i], val: v })) : [];
  in_.perYear = dv?.perYear || 4;
  const ddm0 = V.ddm({ quarterly: in_.divs.map((r) => r.val), perYear: in_.perYear });
  in_.wacc = 0.1;
  in_.growthDDM = pick("growthDDM", [[ok(ddm0?.cagr) ? clamp(ddm0.cagr, 0, 0.07) : null, "история (0–7%)"]], 0.05);

  // Lynch
  in_.pe = pick("pe", [[f.pe, "Finviz"], [ok(in_.price) && ok(in_.eps) && in_.eps > 0 ? in_.price / in_.eps : null, "цена ÷ EPS"]]);

  // Results
  in_.weights = { graham: 0.1, multiple: 0.1, dcf: 0.5, ev: 0.2, ddm: 0.1, lynch: 0 };
  in_.include = { graham: true, multiple: true, dcf: true, ev: true, ddm: true, lynch: false };
  in_.marginR = 0.05;
  return { in_, src };
}

// ------------------------------------------------------------ compute
function compute() {
  const R = {};
  const price = I.price;
  R.graham = V.graham({ eps: I.eps, growth: I.growthG, aaaYield: I.aaa, baseYield: I.baseYield, margin: I.marginG, price });
  const eh = (D.sec?.epsHistory) || {};
  const ev = Object.values(eh);
  R.epsNow = I.eps; R.eps5 = ev.length >= 6 ? ev.at(-6) : null; R.eps10 = ev.length >= 11 ? ev.at(-11) : null;
  R.epsG5 = ok(R.epsNow) && R.eps5 > 0 && R.epsNow > 0 ? (R.epsNow / R.eps5) ** (1 / 5) - 1 : null;
  R.epsG10 = ok(R.epsNow) && R.eps10 > 0 && R.epsNow > 0 ? (R.epsNow / R.eps10) ** (1 / 10) - 1 : null;

  R.fcfStats = V.growthStats([...I.fcfHist.map((r) => r.val), I.fcfTTM]);
  R.dcf = V.dcf({ fcfTTM: I.fcfTTM, growth: I.growthDCF, terminalGrowth: I.terminalGrowth, discount: I.discount,
    cash: I.cash, debt: I.debt, sharesM: I.sharesM, price });

  const eb = I.ebitdaHist.map((r) => r.val);
  R.ebStats = V.growthStats(eb);
  R.ebAvg = eb.filter(ok).length ? eb.filter(ok).reduce((a, b) => a + b, 0) / eb.filter(ok).length : null;
  R.ev = V.evEbitda({ ebitda: eb.filter(ok).at(-1), g1: I.g1, g2: I.g2, multiple: I.evMultiple, discount: I.discount,
    margin: I.marginEV, sharesM: I.sharesM, price });

  R.mult = V.multiple({ peers: I.peers, eps: I.eps, price });
  R.ddm = V.ddm({ quarterly: I.divs.map((r) => r.val), perYear: I.perYear, growth: I.growthDDM, wacc: I.wacc, price });
  R.lynch = V.lynch({ pe: I.pe, eps: I.eps, epsGrowth: I.growthG, ebitdaGrowth: R.ebStats.cagr, price });

  R.values = { graham: R.graham?.result, multiple: R.mult?.value, dcf: R.dcf?.value, ev: R.ev?.buy,
    ddm: R.ddm?.value, lynch: R.lynch?.value };
  R.sum = V.summary({ values: R.values, weights: I.weights, include: I.include });
  R.fair = method === "simple" ? R.sum.simple : R.sum.weighted;
  R.final = V.buyDecision(R.fair, I.marginR, price);
  for (const k of Object.keys(R.values)) R["diff_" + k] = ok(R.values[k]) && R.values[k] > 0 ? (price - R.values[k]) / R.values[k] : null;
  return R;
}

function render(R) {
  const flat = (k) => k.split(".").reduce((o, p) => (o == null ? o : o[p]), R);
  document.querySelectorAll("[data-out]").forEach((el) => {
    const v = flat(el.dataset.out);
    const f = el.dataset.fmt;
    el.innerHTML = f === "signal" ? signalHTML(v) : f === "signalBig" ? signalHTML(v, true)
      : f === "diff" ? diffHTML(v) : fmt[f](v);
  });
}

const recalc = () => render(compute());

// ------------------------------------------------------------ layout
function sparkline(hist) {
  if (!hist?.length) return "";
  const ys = hist.map((h) => h[1]);
  const lo = Math.min(...ys), hi = Math.max(...ys), W = 260, H = 60;
  const pts = ys.map((v, i) => `${(i / (ys.length - 1)) * W},${H - 4 - ((v - lo) / (hi - lo || 1)) * (H - 8)}`).join(" ");
  const up = ys.at(-1) >= ys[0];
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-label="Цена за 1 година">
    <polyline fill="none" stroke="${up ? "var(--buy)" : "var(--sell)"}" stroke-width="2" points="${pts}"/></svg>`;
}

const metric = (label, val) => `<div class="metric"><div class="label">${label}</div><div class="val">${val}</div></div>`;

function layout() {
  const f = D.finviz || {}, y = D.yahoo || {};
  const name = f.name || y.name || D.sec?.entityName || D.ticker;
  const models = [["graham", "Модел на Бен Греъм"], ["multiple", "Оценка на множител"], ["dcf", "DCF"],
    ["ev", "EV/EBITDA"], ["ddm", "Оценка на дивидент"], ["lynch", "Модел на Линч"]];

  const warnings = D.warnings.length ? `<div class="card warn"><b>Някои източници не отговориха</b> — съответните полета са в червено и могат да се попълнят ръчно.
    <ul>${D.warnings.map((w) => `<li>${w}</li>`).join("")}</ul></div>` : "";

  $("#content").innerHTML = `
  ${warnings}
  <section class="card hero">
    <div>
      <div class="name">${name} <span class="sub">${D.ticker}${y.exchange ? " · " + y.exchange : ""}</span></div>
      <div class="sub">${[f.sector, f.industry, f.country].filter(Boolean).join(" · ")}</div>
      ${sparkline(y.history)}
    </div>
    <div class="kpis">
      <div class="kpi"><div class="label">${savedAt ? "Цена към " + fmtDate(savedAt) : "Настояща цена"}</div><div class="big">${fmt.money(I.price)}</div></div>
      <div class="kpi"><div class="label">Реална стойност</div><div class="big">${o("fair", "money")}</div></div>
      <div class="kpi"><div class="label">Приемлива цена за покупка</div><div class="big">${o("final.buy", "money")}</div></div>
      <div class="kpi"><div class="label">Решение</div><div>${o("final.signal", "signalBig")}</div></div>
    </div>
    <div class="savebar">
      ${savedAt ? `<span class="saved-tag">Запазена оценка от ${fmtDate(savedAt)}</span>` : ""}
      <input id="note" placeholder="Бележка (по избор)" maxlength="300">
      <button type="button" id="saveBtn">Запази оценката</button>
      <span id="saveMsg" class="note"></span>
    </div>
  </section>

  <section class="card">
    <h2>Резултати</h2>
    <div class="scroll"><table>
      <tr><th>Модел</th><th>Реална стойност</th><th>Разлика спрямо цената</th><th>Сигнал</th><th>Тегло (%)</th><th>Включи</th></tr>
      ${models.map(([k, label]) => `<tr><td>${label}</td><td>${o("values." + k, "money")}</td><td>${o("diff_" + k, "diff")}</td>
        <td>${o(k === "graham" ? "graham.signal" : k === "multiple" ? "mult.signal" : k === "ev" ? "ev.signal" : k + ".signal", "signal")}</td>
        <td>${cell("weights." + k, "pct")}</td>
        <td><input type="checkbox" data-include="${k}" ${I.include[k] ? "checked" : ""}></td></tr>`).join("")}
    </table></div>
    <div class="row"><span>Метод</span><span class="seg">
      <button type="button" data-method="simple" class="${method === "simple" ? "on" : ""}">Средно аритметично (като в таблицата)</button>
      <button type="button" data-method="weighted" class="${method === "weighted" ? "on" : ""}">Средно претеглено</button></span></div>
    ${out("fair", "Реална стойност", "money")}
    ${field("marginR", "Марж на сигурност", "pct")}
    ${out("final.buy", "Приемлива цена за покупка", "money")}
    ${out("final.diff", "Разлика", "diff")}
    ${out("final.signal", "Купи/Продай", "signal")}
    <p class="note">Моделът на Линч не участва в средната стойност (както в оригиналната таблица) — може да се включи с отметката.
      Непълни модели се пропускат автоматично; при претеглената средна теглата се преразпределят.</p>
  </section>

  <section class="card">
    <h2>Базови параметри</h2>
    <div class="metrics">
      ${metric("Капитализация", fmt.big(f.marketCap))}
      ${metric("P/E", fmt.num(f.pe))}
      ${metric("EPS (TTM)", fmt.num(f.eps))}
      ${metric("52-седмичен връх", fmt.money(y.high52))}
      ${metric("52-седмично дъно", fmt.money(y.low52))}
      ${metric("Възвръщаемост 1 г.", retHTML(y.return1y))}
      ${metric("Възвръщаемост 2 г.", retHTML(y.return2y))}
      ${metric("Бета", fmt.num(f.beta))}
      ${metric("Волатилност (седм./мес.)", fmt.text(f.volatility))}
      ${metric("RSI (14)", fmt.num(f.rsi))}
      ${metric("Търгуван обем", fmt.big(y.volume ?? f.volume))}
      ${metric("Институции", fmt.pct(f.instOwn))}
      ${metric("Акции в обръщение", fmt.big(f.sharesOut ?? (D.sec?.sharesM ?? NaN) * 1e6))}
      ${metric("Оценка от анализатори (1=Купи, 5=Продай)", fmt.num(f.recom))}
      ${metric("Целева цена (анализатори)", fmt.money(f.targetPrice))}
      ${metric("Възвръщаемост на активите (ROA)", fmt.pct(f.roa))}
      ${metric("Възвръщаемост на капитала (ROE)", fmt.pct(f.roe))}
      ${metric("Възвръщаемост на инвестициите", fmt.pct(f.roi))}
      ${metric("Брутен марж", fmt.pct(f.grossMargin))}
      ${metric("Оперативен марж", fmt.pct(f.operMargin))}
      ${metric("Марж на печалбата", fmt.pct(f.profitMargin))}
      ${metric("Доходи (печалба)", fmt.big(f.income))}
      ${metric("Продажби", fmt.big(f.sales))}
      ${metric("Цена / Свободни парични потоци", fmt.num(f.pfcf))}
      ${metric("Дивидент (год.)", fmt.num(f.dividend))}
      ${metric("Дивидентна доходност", fmt.pct(f.dividendYield))}
      ${metric("Процент на изплащане", fmt.pct(f.payout))}
      ${metric("Ex-dividend дата", fmt.text(D.dividends?.lastExDate))}
      ${metric("Движение 1 месец", fmt.pct(f.perfMonth))}
      ${metric("Движение спрямо SMA20 / 50 / 200", [f.sma20, f.sma50, f.sma200].map(fmt.pct).join(" / "))}
      ${metric("Отчет за печалби", fmt.text(f.earningsDate))}
    </div>
  </section>

  <div class="grid">
  <section class="card">
    <h2>Модел на Бенджамин Греъм</h2>
    ${field("eps", "EPS")}
    ${field("growthG", "Нарастване (очаквания), %")}
    ${field("aaa", "Y — настоящ ийлд AAA облигации, %")}
    ${field("baseYield", "Среден ийлд AAA (4.4)")}
    ${field("marginG", "Марж на сигурност", "pct")}
    <h3>Оригинална формула: EPS × (8.5 + 2g) × 4.4 / Y</h3>
    ${out("graham.value", "Реална стойност", "money")}
    ${out("graham.buy", "Цена за покупка", "money")}
    ${out("graham.signal", "Купи/Продай", "signal")}
    <h3>Преработена формула: EPS × (7 + 1g) × 4.4 / Y</h3>
    ${out("graham.valueRev", "Реална стойност", "money")}
    ${out("graham.buyRev", "Цена за покупка", "money")}
    ${out("graham.signalRev", "Купи/Продай", "signal")}
    <h3>Средна цена (отива в резултатите)</h3>
    ${out("graham.result", "Средна цена за покупка", "money")}
    ${out("graham.diffAvg", "Разлика", "diff")}
    <h3>История на EPS (SEC)</h3>
    ${out("epsNow", "Настоящ EPS")} ${out("eps5", "EPS преди 5 г.")} ${out("eps10", "EPS преди 10 г.")}
    ${out("epsG5", "Растеж 5 г.", "pct")} ${out("epsG10", "Растеж 10 г.", "pct")}
  </section>

  <section class="card">
    <h2>Модел на дисконтираните парични потоци (DCF)</h2>
    <h3>Свободни парични потоци, млн.</h3>
    <div class="scroll"><table><tr>${I.fcfHist.map((r) => `<th>${r.year}</th>`).join("")}<th>TTM</th></tr>
      <tr>${I.fcfHist.map((r, i) => `<td>${cell(`fcfHist.${i}.val`)}</td>`).join("")}<td>${cell("fcfTTM")}</td></tr></table></div>
    ${out("fcfStats.avg", "Среден растеж", "pct")}
    ${out("fcfStats.cagr", "Растеж 5 г.", "pct")}
    ${field("growthDCF", "Растеж", "pct")}
    ${field("terminalGrowth", "Бъдещ растеж 10+", "pct")}
    ${field("discount", "Минимална търсена възвръщаемост", "pct")}
    ${field("cash", "Пари и еквиваленти, млн.", "num")}
    ${field("debt", "Целият дълг, млн.", "num")}
    ${field("sharesM", "Акции в обръщение, млн.", "num")}
    <h3>Бъдещи парични потоци, млн.</h3>
    <div class="scroll"><table><tr><th></th>${[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => `<th>${n}</th>`).join("")}<th>Терм.</th></tr>
      <tr><td>FCF</td>${[0, 1, 2, 3, 4, 5, 6, 7, 8].map((n) => `<td>${o(`dcf.future.${n}`, "m")}</td>`).join("")}<td>${o("dcf.terminal", "m")}</td></tr>
      <tr><td>Настояща</td>${[0, 1, 2, 3, 4, 5, 6, 7, 8].map((n) => `<td>${o(`dcf.pv.${n}`, "m")}</td>`).join("")}<td>${o("dcf.terminalPV", "m")}</td></tr>
    </table></div>
    ${out("dcf.sumPV", "Сбор от FCF, млн.", "m")}
    ${out("dcf.equity", "Собствен капитал, млн.", "m")}
    ${out("dcf.value", "DCF реална стойност", "money")}
    ${out("dcf.diff", "Разлика", "diff")}
    ${out("dcf.signal", "Купи/Продай", "signal")}
  </section>

  <section class="card">
    <h2>EV/EBITDA</h2>
    <h3>EBITDA, млн. (оперативна печалба + амортизация, SEC)</h3>
    <div class="scroll"><table><tr>${I.ebitdaHist.map((r) => `<th>${r.year}</th>`).join("") || "<th>Няма данни</th>"}</tr>
      <tr>${I.ebitdaHist.map((r, i) => `<td>${cell(`ebitdaHist.${i}.val`)}</td>`).join("") || "<td></td>"}</tr></table></div>
    ${out("ebStats.avg", "Средно %", "pct")}
    ${out("ebAvg", "Среден EBITDA, млн.", "m")}
    ${out("ebStats.cagr", "Растеж 5 г.", "pct")}
    ${field("g1", "Растеж 5 г.", "pct")}
    ${field("g2", "Растеж 5+ г.", "pct")}
    ${field("evMultiple", "EBITDA множител")}
    ${field("marginEV", "Марж на сигурност", "pct")}
    <p class="note">Отстъпката и броят акции се взимат от DCF модела.</p>
    ${out("ev.terminalEbitda", "Терминален EBITDA, млн.", "m")}
    ${out("ev.terminalPV", "Дисконтирана терминална стойност, млн.", "m")}
    ${out("ev.value", "Реална стойност", "money")}
    ${out("ev.buy", "Цена за покупка", "money")}
    ${out("ev.diff", "Разлика", "diff")}
    ${out("ev.signal", "Купи/Продай", "signal")}
  </section>

  <section class="card">
    <h2>Оценка на множител</h2>
    <div class="scroll"><table><tr><th>Тикер</th><th>Цена</th><th>EPS</th><th>P/E</th></tr>
      ${I.peers.map((p, i) => `<tr><td title="${p.name || ""}">${p.ticker}</td><td>${cell(`peers.${i}.price`)}</td>
        <td>${cell(`peers.${i}.eps`)}</td><td>${o(`mult.pes.${i}`)}</td></tr>`).join("") || `<tr><td colspan="4">Няма намерени сравними компании — въведи ги горе.</td></tr>`}
    </table></div>
    ${out("mult.avgPE", "Осреднен P/E")}
    ${out("mult.avgEPS", "Осреднен EPS")}
    <div class="row"><span>EPS на компанията</span><span class="out">${fmt.num(I.eps)}</span></div>
    ${out("mult.value", "Реална стойност", "money")}
    ${out("mult.diff", "Разлика", "diff")}
    ${out("mult.signal", "Купи/Продай", "signal")}
    <p class="note">Сравнимите компании са от Finviz „Peers“. За свой избор ги въведи в полето горе и натисни „Оцени“.</p>
  </section>

  <section class="card">
    <h2>Модел за оценка на дивидента</h2>
    ${I.divs.length ? `<div class="scroll"><table><tr><th></th>${I.divs.map((r) => `<th>${r.year}</th>`).join("")}</tr>
      <tr><td>Изплащане</td>${I.divs.map((r, i) => `<td>${cell(`divs.${i}.val`)}</td>`).join("")}</tr>
      <tr><td>Годишно</td>${I.divs.map((_, i) => `<td>${o(`ddm.annual.${i}`)}</td>`).join("")}</tr></table></div>`
      : `<p class="note">Компанията не плаща дивидент — моделът се пропуска.</p>`}
    ${field("perYear", "Плащания годишно")}
    ${out("ddm.avgGrowth", "Растеж %", "pct")}
    ${out("ddm.cagr", "Среден растеж", "pct")}
    ${field("growthDDM", "Растеж", "pct")}
    ${field("wacc", "WACC", "pct")}
    ${out("ddm.value", "Реална стойност (DDM)", "money")}
    ${out("ddm.diff", "Разлика", "diff")}
    ${out("ddm.signal", "Купи/Продай", "signal")}
    <h3>Втори модел (информативно)</h3>
    ${out("ddm.second", "Стойност", "money")}
    ${out("ddm.signalSecond", "Купи/Продай", "signal")}
  </section>

  <section class="card">
    <h2>Модел на Питър Линч</h2>
    ${field("pe", "P/E")}
    <div class="row"><span>EPS (TTM)</span><span class="out">${fmt.num(I.eps)}</span></div>
    ${out("lynch.peg", "PEG")}
    ${out("lynch.ebitdaGrowthPct", "Растеж на EBITDA (%)")}
    <div class="row"><span>EPS растеж (от модела на Греъм)</span><span class="out" data-out="growthEcho" data-fmt="num">—</span></div>
    ${out("lynch.value", "Реална стойност", "money")}
    ${out("lynch.diff", "Разлика", "diff")}
    ${out("lynch.signal", "Купи/Продай", "signal")}
    <p class="note">Формулата е както в таблицата: PEG × EPS × растеж на EBITDA. При отрицателна печалба (без P/E) моделът няма стойност.</p>
  </section>
  </div>
  <p class="note">Данни към ${new Date(D.fetchedAt).toLocaleString("bg-BG")}. Сумите в моделите DCF и EV/EBITDA са в милиони във валутата на отчетите (SEC — USD).
    Това е инструмент за анализ, не инвестиционен съвет.</p>`;
}

// ------------------------------------------------------------ events
document.addEventListener("input", (e) => {
  const el = e.target;
  if (!el.dataset.path) return;
  const raw = el.value.replace(",", ".").trim();
  let v = raw === "" ? null : Number(raw);
  if (!ok(v)) v = null;
  if (v !== null && el.dataset.kind === "pct") v /= 100;
  setPath(el.dataset.path, v);
  el.classList.toggle("missing", v === null);
  full();
});
document.addEventListener("change", (e) => {
  if (e.target.dataset.include) { I.include[e.target.dataset.include] = e.target.checked; full(); }
});
document.addEventListener("click", (e) => {
  const m = e.target.dataset?.method;
  if (m) { method = m; document.querySelectorAll("[data-method]").forEach((b) => b.classList.toggle("on", b.dataset.method === m)); full(); }
});

function full() { const R = compute(); R.growthEcho = I.growthG; render(R); lastR = R; }

$("#search").addEventListener("submit", async (e) => {
  e.preventDefault();
  const ticker = $("#ticker").value.trim().toUpperCase();
  if (!ticker) return;
  const btn = e.submitter || $("#search button");
  btn.disabled = true;
  $("#status").className = "status";
  $("#status").textContent = `Събирам данни за ${ticker}…`;
  try {
    const peers = $("#peers").value.trim();
    const r = await fetch(`/api/data/${encodeURIComponent(ticker)}${peers ? `?peers=${encodeURIComponent(peers)}` : ""}`);
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    D = await r.json();
    if (!D.yahoo && !D.finviz) throw new Error("Няма данни за този тикер. Провери го (за европейски борси напр. SAP.DE).");
    D.currency = D.yahoo?.currency || "USD";
    ({ in_: I, src: SRC } = defaults(D));
    savedAt = null;
    showView("calc");
    layout();
    full();
    $("#status").textContent = "";
    $("#content").hidden = false;
    try { localStorage.setItem("lastTicker", ticker); } catch { /* storage unavailable */ }
  } catch (err) {
    $("#status").className = "status error";
    $("#status").textContent = "Грешка: " + err.message;
  } finally {
    btn.disabled = false;
  }
});

try { const t = localStorage.getItem("lastTicker"); if (t) $("#ticker").value = t; } catch { /* ignore */ }

// ------------------------------------------------------------ saved valuations
const fmtDate = (iso) => new Date(iso).toLocaleString("bg-BG", { dateStyle: "short", timeStyle: "short" });
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const MODEL_LABELS = { graham: "Греъм", multiple: "Множител", dcf: "DCF", ev: "EV/EBITDA", ddm: "Дивидент", lynch: "Линч" };
let saved = [];

function showView(v) {
  $("#calcView").hidden = v !== "calc";
  $("#savedView").hidden = v !== "saved";
  document.querySelectorAll("[data-view]").forEach((b) => b.classList.toggle("on", b.dataset.view === v));
  if (v === "saved") loadSaved();
}
document.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));

async function saveCurrent() {
  if (!D || !lastR) return;
  const btn = $("#saveBtn");
  btn.disabled = true;
  const f = D.finviz || {}, y = D.yahoo || {};
  const body = {
    ticker: D.ticker, name: f.name || y.name || D.sec?.entityName || D.ticker, currency: D.currency,
    price: I.price, fairValue: lastR.fair, buyPrice: lastR.final.buy, signal: lastR.final.signal,
    method, note: $("#note").value.trim() || null,
    models: Object.fromEntries(Object.entries(lastR.values).map(([k, v]) => [k, ok(v) ? v : null])),
    inputs: { values: I, src: SRC }, data: D,
  };
  try {
    const r = await fetch("/api/valuations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    $("#saveMsg").textContent = "Запазено ✓";
  } catch (err) {
    $("#saveMsg").textContent = "Грешка при запис: " + err.message;
  } finally {
    btn.disabled = false;
  }
}
document.addEventListener("click", (e) => { if (e.target.id === "saveBtn") saveCurrent(); });

async function loadSaved() {
  $("#savedBody").innerHTML = `<tr><td colspan="10">Зареждам…</td></tr>`;
  try {
    const r = await fetch("/api/valuations");
    const j = await r.json();
    saved = j.items;
    $("#storageWarn").hidden = j.storage.persistent;
    renderSaved();
  } catch (err) {
    $("#savedBody").innerHTML = `<tr><td colspan="10" class="neg">Грешка: ${esc(err.message)}</td></tr>`;
  }
}

function renderSaved() {
  const q = $("#savedFilter").value.trim().toUpperCase();
  const rows = saved.filter((v) => !q || v.ticker.includes(q) || (v.name || "").toUpperCase().includes(q));
  const money = (x, cur) => (ok(x) ? nf(2).format(x) + " " + (cur || "") : "—");
  $("#savedBody").innerHTML = rows.map((v) => {
    const gap = ok(v.price) && ok(v.buy_price) && v.buy_price > 0 ? (v.price - v.buy_price) / v.buy_price : null;
    const models = Object.entries(v.models || {}).filter(([, x]) => ok(x))
      .map(([k, x]) => `${MODEL_LABELS[k] || k}: ${nf(2).format(x)}`).join(" · ");
    return `<tr>
      <td>${fmtDate(v.created_at)}</td>
      <td class="left"><b>${esc(v.ticker)}</b><div class="sub">${esc(v.name)}</div></td>
      <td>${money(v.price, v.currency)}</td>
      <td title="${esc(models)}">${money(v.fair_value, v.currency)}</td>
      <td>${money(v.buy_price, v.currency)}</td>
      <td>${diffHTML(gap)}</td>
      <td>${signalHTML(v.signal)}</td>
      <td class="left">${esc(v.note)}</td>
      <td><button type="button" class="small" data-open="${v.id}">Отвори</button></td>
      <td><button type="button" class="small ghost" data-del="${v.id}" title="Изтрий">✕</button></td></tr>`;
  }).join("") || `<tr><td colspan="10">Още няма запазени оценки. Направи оценка и натисни „Запази оценката“.</td></tr>`;
  $("#savedCount").textContent = rows.length ? `${rows.length} записа` : "";
}
document.addEventListener("input", (e) => { if (e.target.id === "savedFilter") renderSaved(); });

document.addEventListener("click", async (e) => {
  const openId = e.target.dataset?.open, delId = e.target.dataset?.del;
  if (openId) {
    const r = await fetch(`/api/valuations/${openId}`);
    if (!r.ok) return;
    const v = await r.json();
    D = v.data; I = v.inputs.values; SRC = v.inputs.src || {}; method = v.method || "simple"; savedAt = v.created_at;
    $("#ticker").value = v.ticker;
    showView("calc");
    layout();
    full();
    if (v.note) $("#note").value = v.note;
    $("#status").textContent = "";
    $("#content").hidden = false;
    window.scrollTo(0, 0);
  } else if (delId) {
    const v = saved.find((x) => String(x.id) === delId);
    if (!confirm(`Да изтрия ли оценката на ${v?.ticker} от ${v ? fmtDate(v.created_at) : ""}?`)) return;
    const r = await fetch(`/api/valuations/${delId}`, { method: "DELETE" });
    if (r.ok) { saved = saved.filter((x) => String(x.id) !== delId); renderSaved(); }
  }
});

$("#exportCsv").addEventListener("click", () => {
  const head = ["Дата", "Тикер", "Компания", "Валута", "Цена", "Реална стойност", "Цена за покупка", "Резултат", "Метод", "Бележка",
    ...Object.values(MODEL_LABELS)];
  // Bulgarian Excel expects ";" between columns and a decimal comma.
  const cellCsv = (x) => {
    if (x == null) return "";
    if (typeof x === "number") return String(+x.toFixed(4)).replace(".", ",");
    return /[";\n]/.test(String(x)) ? `"${String(x).replace(/"/g, '""')}"` : String(x);
  };
  const lines = saved.map((v) => [fmtDate(v.created_at), v.ticker, v.name, v.currency, v.price, v.fair_value, v.buy_price, v.signal,
    v.method === "weighted" ? "претеглено" : "средно", v.note, ...Object.keys(MODEL_LABELS).map((k) => v.models?.[k])].map(cellCsv).join(";"));
  const blob = new Blob(["﻿" + [head.join(";"), ...lines].join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `ocenki-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
});
