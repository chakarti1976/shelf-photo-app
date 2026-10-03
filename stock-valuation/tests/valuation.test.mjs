// Checks the JS port against the values cached in the original spreadsheet
// (ZETA sheet, Q1 2026). Run: node --test tests/
import test from "node:test";
import assert from "node:assert/strict";
import * as V from "../static/valuation.js";

const close = (a, b, tol = 1e-6) => assert.ok(Math.abs(a - b) <= tol * Math.max(1, Math.abs(b)), `${a} != ${b}`);
const price = 32.63;

test("Graham", () => {
  const g = V.graham({ eps: -0.01, growth: 4.09, aaaYield: 5.81, price });
  close(g.value, -0.1263201377); close(g.valueRev, -0.08398623064);
  close(g.buy, -0.1136881239); close(g.buyRev, -0.07558760757); close(g.result, -0.09463786575);
});

test("DCF", () => {
  const hist = [323.3, 430.3, 504, 528, 674.3, 576.9, 944.8, 898.6, 596.1, 971];
  const d = V.dcf({ fcfTTM: 971, growth: 0.07, cash: 757, debt: 1265, sharesM: 227.375, price });
  close(d.future[0], 1038.97); close(d.future[8], 1785.143895); close(d.terminal, 26267.11732);
  close(d.sumPV, 17757.09269); close(d.equity, 17249.09269); close(d.value, 75.86187001);
  const s = V.growthStats(hist);
  close(s.avg, 0.1737333621); close(s.cagr, 0.109746383);
});

test("EV/EBITDA", () => {
  const e = V.evEbitda({ ebitda: 1457.3, multiple: 10.15, sharesM: 227.375, price });
  close(e.path[10], 1994.835975); close(e.terminalEbitda, 2094.577774);
  close(e.terminalEV, 21259.96441); close(e.terminalPV, 8196.63661);
  close(e.value, 36.04897904); close(e.buy, 34.24653009);
});

test("Multiple", () => {
  const m = V.multiple({ eps: -0.01, price, peers: [
    { price: 189.69, eps: 8.31 }, { price: 91.34, eps: 4.1 }, { price: 262.92, eps: 11.03 }, { price: 381.73, eps: 14.06 }] });
  close(m.avgPE, 24.02291085); close(m.value, -0.2402291085);
});

test("DDM", () => {
  const d = V.ddm({ quarterly: [1.08, 1.23, 1.42, 1.62, 1.86], price });
  close(d.value, 265.36); close(d.avgGrowth, 0.145588413); close(d.cagr, 0.1148535927);
  close(d.second, 25.58680016);
});

test("Lynch: EBITDA growth and #N/A P/E", () => {
  close(V.growthStats([1055, 985.9, 1244.8, 1349.9, 1457.3]).cagr, 0.06674177031);
  assert.equal(V.lynch({ pe: null, eps: -0.01, epsGrowth: 4.09, ebitdaGrowth: 0.0667, price }), null);
  const l = V.lynch({ pe: 20, eps: 2, epsGrowth: 10, ebitdaGrowth: 0.08, price: 30 });
  close(l.value, 2 * 2 * 8);
});

test("Results", () => {
  const values = { graham: -0.09463786575, multiple: -0.2402291085, dcf: 75.86187001, ev: 34.24653009, ddm: 265.36 };
  const include = { graham: true, multiple: true, dcf: true, ev: true, ddm: true };
  const weights = { graham: 0.1, multiple: 0.1, dcf: 0.5, ev: 0.2, ddm: 0.1 };
  const r = V.summary({ values, weights, include });
  close(r.simple, 75.02670662); close(r.weightedRaw, 71.28275432); close(r.weighted, 71.28275432);
  const b = V.buyDecision(r.simple, 0.05, price);
  close(b.buy, 71.27537129); assert.equal(b.signal, "Купи");
});
