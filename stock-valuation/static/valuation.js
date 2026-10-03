// Valuation models — a 1:1 port of the formulas in the
// "Оценка на акции Q1 2026" spreadsheet. Pure functions, shared by the
// browser UI and the node tests. A model returns null when its inputs
// are missing (the spreadsheet showed "" or #N/A in that case).

const ok = (x) => typeof x === "number" && Number.isFinite(x);
const avg = (xs) => {
  const v = xs.filter(ok);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
};
const signal = (price, buyPrice) =>
  ok(price) && ok(buyPrice) ? (price < buyPrice ? "Купи" : "Продай") : null;
// A percentage gap to a zero/negative value is meaningless, so it is left blank.
const diff = (price, value) => (ok(price) && ok(value) && value > 0 ? (price - value) / value : null);

// "Моделът на Бенджамин Греъм"
// Original: V = EPS × (8.5 + 2g) × 4.4 / Y      Revised: V = EPS × (7 + 1g) × 4.4 / Y
// The result sheet uses the average of the two buy prices.
export function graham({ eps, growth, aaaYield, baseYield = 4.4, margin = 0.1,
  peNoGrowth = 8.5, gMult = 2, peNoGrowthRev = 7, gMultRev = 1, price }) {
  if (!ok(eps) || !ok(growth) || !ok(aaaYield) || aaaYield === 0) return null;
  const value = (eps * (peNoGrowth + growth * gMult) * baseYield) / aaaYield;
  const valueRev = (eps * (peNoGrowthRev + growth * gMultRev) * baseYield) / aaaYield;
  const buy = (1 - margin) * value;
  const buyRev = (1 - margin) * valueRev;
  const result = (buy + buyRev) / 2;
  return {
    value, valueRev, buy, buyRev, result,
    signal: signal(price, buy), signalRev: signal(price, buyRev),
    diff: diff(price, buy), diffRev: diff(price, buyRev), diffAvg: diff(price, result),
  };
}

// "Модел на Дисконтираните Парични Потоци" — amounts in millions.
// As in the sheet: 9 explicit years of FCF growing at `growth` from the TTM
// base, a terminal value built on year 9 and discounted as year 10, plus
// cash minus debt, per share.
export function dcf({ fcfTTM, growth, terminalGrowth = 0.03, discount = 0.1,
  cash, debt, sharesM, price, years = 9 }) {
  if (!ok(fcfTTM) || !ok(growth) || !ok(sharesM) || sharesM === 0 || discount === terminalGrowth) return null;
  const future = [];
  const pv = [];
  let f = fcfTTM;
  for (let i = 1; i <= years; i++) {
    f *= 1 + growth;
    future.push(f);
    pv.push(f / (1 + discount) ** i);
  }
  const terminal = (f * (1 + terminalGrowth)) / (discount - terminalGrowth);
  const terminalPV = terminal / (1 + discount) ** (years + 1);
  const sumPV = pv.reduce((a, b) => a + b, 0) + terminalPV;
  const equity = sumPV + (cash || 0) - (debt || 0);
  const value = equity / sharesM;
  return { future, pv, terminal, terminalPV, sumPV, equity, value,
    diff: diff(price, value), signal: signal(price, value) };
}

// Historic growth stats shown next to the DCF / EBITDA history tables.
// `series` is oldest → newest. Like the sheet, the "5-year" CAGR compares
// the newest value with the one 4 positions back and takes the 5th root.
export function growthStats(series, cagrYears = 5) {
  const s = series.filter(ok);
  const yoy = [];
  for (let i = 1; i < s.length; i++) if (s[i - 1] !== 0) yoy.push((s[i] - s[i - 1]) / s[i - 1]);
  let cagr = null;
  if (s.length >= cagrYears) {
    const a = s[s.length - cagrYears], b = s[s.length - 1];
    if (a > 0 && b > 0) cagr = (b / a) ** (1 / cagrYears) - 1;
  }
  return { yoy, avg: avg(yoy), cagr };
}

// "EV/EBITDA" — amounts in millions. EBITDA grows at g1 for years 1-4 and
// g2 for years 5-10; the terminal year adds one more g1 step, is priced at
// the EBITDA multiple and discounted 10 years. Only the terminal value is
// used, exactly as in the spreadsheet.
export function evEbitda({ ebitda, g1 = 0.05, g2 = 0.02, multiple, discount = 0.1,
  margin = 0.05, sharesM, price }) {
  if (!ok(ebitda) || ebitda === 0 || !ok(multiple) || !ok(sharesM) || sharesM === 0) return null;
  const path = [ebitda];
  for (let i = 1; i <= 10; i++) path.push(path[i - 1] * (1 + (i <= 4 ? g1 : g2)));
  const terminalEbitda = path[10] * (1 + g1);
  const terminalEV = terminalEbitda * multiple;
  const terminalPV = terminalEV / (1 + discount) ** 10;
  const value = terminalPV / sharesM;
  const buy = (1 - margin) * value;
  return { path, terminalEbitda, terminalEV, terminalPV, value, buy,
    diff: diff(price, buy), signal: signal(price, buy) };
}

// "Оценка на Множител" — average peer P/E × company EPS.
export function multiple({ peers, eps, price }) {
  const pes = (peers || []).map((p) => (ok(p.price) && ok(p.eps) && p.eps !== 0 ? p.price / p.eps : null));
  const avgPE = avg(pes);
  const avgEPS = avg((peers || []).map((p) => p.eps));
  if (!ok(avgPE) || !ok(eps)) return { pes, avgPE, avgEPS, value: null, signal: null, diff: null };
  const value = avgPE * eps;
  return { pes, avgPE, avgEPS, value, diff: diff(price, value), signal: signal(price, value) };
}

// "Модел за Оценка на Дивидента" — Gordon growth on the annualised
// latest per-payment dividend (× payments per year; 4 for quarterly), plus the spreadsheet's secondary model.
export function ddm({ quarterly, perYear = 4, growth = 0.07, wacc = 0.1, price }) {
  const q = (quarterly || []).filter(ok);
  if (!q.length || q[q.length - 1] === 0) return null;
  const annual = q.map((d) => d * perYear);
  const last = annual[annual.length - 1];
  const yoy = [];
  for (let i = 1; i < annual.length; i++) yoy.push(annual[i - 1] ? (annual[i] - annual[i - 1]) / annual[i - 1] : null);
  const avgGrowth = avg(yoy);
  const cagr = q.length >= 2 && q[0] > 0 ? (q[q.length - 1] / q[0]) ** (1 / 5) - 1 : null;
  const value = wacc > growth ? (last * (1 + growth)) / (wacc - growth) : null;
  // Second model, kept verbatim from the sheet (M16:M21, J16).
  let second = null;
  if (ok(price)) {
    const terminal = last * (1 + growth) ** 10;
    const mult = price / last;
    const discounted = (terminal * mult) / 1.1 ** 10;
    const toDD = discounted / 1.1 ** 13.49;
    second = (discounted + toDD) * 0.9 * 0.9;
  }
  return { annual, yoy, avgGrowth, cagr, value, second,
    diff: diff(price, value), signal: signal(price, value),
    diffSecond: diff(price, second), signalSecond: signal(price, second) };
}

// "Модел на Питър Линч" — as in the sheet: PEG × EPS × EBITDA growth (%),
// where PEG = P/E ÷ EPS growth (%). Undefined when P/E is (#N/A).
export function lynch({ pe, eps, epsGrowth, ebitdaGrowth, price }) {
  if (!ok(pe) || !ok(eps) || !ok(epsGrowth) || epsGrowth === 0 || !ok(ebitdaGrowth)) return null;
  const peg = pe / epsGrowth;
  const ebitdaGrowthPct = ebitdaGrowth * 100;
  const value = peg * eps * ebitdaGrowthPct;
  const ratio = ok(price) && value !== 0 ? price / value : null;
  return { peg, ebitdaGrowthPct, value, ratio, diff: diff(price, value),
    signal: ratio === null ? null : ratio < 1.01 ? "Купи" : "Продай" };
}

// "РЕЗУЛТАТИ" — simple average of Graham, multiple, DCF, EV/EBITDA and DDM
// (the sheet's I15; Lynch is shown but not averaged), plus the weighted
// version (M21). Missing models are skipped instead of erroring.
export function summary({ values, weights, include, margin = 0.05, price }) {
  const keys = Object.keys(values).filter((k) => include[k] && ok(values[k]));
  const simple = avg(keys.map((k) => values[k]));
  let wSum = 0, wVal = 0;
  for (const k of keys) { wSum += weights[k] || 0; wVal += (weights[k] || 0) * values[k]; }
  const weightedRaw = wVal; // the sheet's literal SUM(value × weight)
  const weighted = wSum ? wVal / wSum : null; // renormalised when a model is missing
  return { simple, weighted, weightedRaw, weightSum: wSum, keys };
}

export function buyDecision(value, margin, price) {
  if (!ok(value)) return { buy: null, diff: null, signal: null };
  const buy = (1 - margin) * value;
  return { buy, diff: diff(price, buy), signal: signal(price, buy) };
}
