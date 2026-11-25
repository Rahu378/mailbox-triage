// Controls for the n8n "Parse + controls" Code node. JS twin of triage/controls.py.
// Pure functions only, so node --test can check them against fixtures from the Python side.
// n8n/build.py pastes this file into the workflow JSON, so there are no imports here.

const HOLIDAYS = new Set([
  "2026-01-01", "2026-01-19", "2026-02-16", "2026-05-25", "2026-06-19", "2026-07-03",
  "2026-09-07", "2026-10-12", "2026-11-11", "2026-11-26", "2026-12-25",
]);
const KNOWN_ORGS = {
  "halden-sec.example": "Halden Securities", "northgatecm.example": "Northgate Capital Markets",
  "kestrelprime.example": "Kestrel Prime", "oakmontlowe.example": "Oakmont & Lowe",
  "sablestreet.example": "Sable Street Partners", "marlowexec.example": "Marlow Agency Execution",
  "meridiancustody.example": "Meridian Custody", "atlastrust.example": "Atlas Trust",
};
const CATEGORIES = ["TRADE_QUERY", "SETTLEMENT_FAIL", "SSI_UPDATE", "CA_ELECTION", "PRICE_CHALLENGE", "OTHER"];
const REQUIRED = {
  SETTLEMENT_FAIL: [["trade_ids", "trade ID"], ["settlement_date", "settlement date"]],
  TRADE_QUERY: [["trade_ids", "trade ID"]],
  CA_ELECTION: [["deadline", "election deadline"]],
  PRICE_CHALLENGE: [],
};

const iso = (d) => d.toISOString().slice(0, 10);
const day = (s) => new Date(`${String(s).slice(0, 10)}T00:00:00Z`);

function isBusinessDay(d) {
  const wd = d.getUTCDay();
  return wd !== 0 && wd !== 6 && !HOLIDAYS.has(iso(d));
}

function bdaysBetween(a, b) {
  if (iso(a) === iso(b)) return 0;
  const sign = b > a ? 1 : -1;
  let [x, y] = sign === 1 ? [a, b] : [b, a];
  let n = 0;
  const d = new Date(x);
  while (d < y) {
    d.setUTCDate(d.getUTCDate() + 1);
    if (isBusinessDay(d)) n += 1;
  }
  return sign * n;
}

function settlementUrgency(receivedIso, settleIso) {
  if (!settleIso) return ["Medium", null];
  const gap = bdaysBetween(day(receivedIso), day(settleIso));
  if (gap <= 0) return ["Highest", gap];
  if (gap === 1) return ["High", gap];
  if (gap === 2) return ["Medium", gap];
  return ["Low", gap];
}

function cusipValid(c) {
  if (!/^[0-9A-Z]{9}$/.test(c || "")) return false;
  let total = 0;
  for (let i = 0; i < 8; i++) {
    const ch = c[i];
    let v = /\d/.test(ch) ? Number(ch) : ch.charCodeAt(0) - 55;
    if (i % 2 === 1) v *= 2;
    total += Math.floor(v / 10) + (v % 10);
  }
  return (10 - (total % 10)) % 10 === Number(c[8]);
}

function isinValid(s) {
  if (!/^[A-Z]{2}[0-9A-Z]{9}[0-9]$/.test(s || "")) return false;
  const digits = s.slice(0, 11).split("").map((ch) => parseInt(ch, 36).toString()).join("");
  let total = 0;
  digits.split("").reverse().forEach((ch, i) => {
    let d = Number(ch);
    if (i % 2 === 0) { d *= 2; if (d > 9) d -= 9; }
    total += d;
  });
  return (10 - (total % 10)) % 10 === Number(s[11]);
}

function editDistance(a, b) {
  let prev = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    for (let j = 1; j <= b.length; j++) {
      cur.push(Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] !== b[j - 1] ? 1 : 0)));
    }
    prev = cur;
  }
  return prev[b.length];
}

function lookalikeOf(domain) {
  for (const [known, org] of Object.entries(KNOWN_ORGS)) {
    if (domain !== known && editDistance(domain, known) <= 2) return org;
  }
  return null;
}

const SSI_CHANGE = new RegExp(
  "(?:new|updated?|chang(?:e|ed|es)|moved|amended)\\b[^.\\n]{0,40}\\b(?:bank details|account number|settlement account|"
  + "wire instructions|settlement instructions|ssis?|beneficiary|payment details|bank account)|"
  + "(?:bank details|settlement instructions|ssis?|wire instructions|bank account)\\b[^.\\n]{0,40}\\b(?:have changed|changed|"
  + "change effective|update|updated|are changing)", "i");

function detectSsiChange(subject, body) {
  const text = `${subject}\n${body}`;
  const reasons = [];
  if (SSI_CHANGE.test(text)) reasons.push("asks to change settlement / bank details");
  if (/\b(?:ABA|SWIFT|BIC|IBAN)\b/.test(text) && /\baccount\b/i.test(text)) reasons.push("contains bank routing details");
  if (/switched (?:custodians?|banks?|agents?)|new (?:custodian|agent|bank)\b|(?:going forward|from (?:now|monday|today)).{0,60}\b(?:send|pay|wire|deliver|remit)\b/i.test(text)
      && /\b(?:acct|account|a\/c)\b/i.test(text)) {
    reasons.push("redirects payments or deliveries to a new account");
  }
  return reasons;
}

function validate(ex, receivedIso) {
  const errs = [];
  for (const t of ex.trade_ids || []) if (!/^T\d{7}$/.test(t)) errs.push(`trade ID ${t} isn't in our format`);
  if (ex.cusip && !cusipValid(ex.cusip)) errs.push(`CUSIP ${ex.cusip} fails the check digit`);
  if (ex.isin && !isinValid(ex.isin)) errs.push(`ISIN ${ex.isin} fails the check digit`);
  if (["SETTLEMENT_FAIL", "TRADE_QUERY", "CA_ELECTION", "PRICE_CHALLENGE"].includes(ex.category) && !(ex.cusip || ex.isin)) {
    errs.push("no security identifier");
  }
  for (const [key, label] of [["settlement_date", "settlement date"], ["deadline", "deadline"]]) {
    const v = ex[key];
    if (!v) continue;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(v) || Number.isNaN(day(v).getTime())) { errs.push(`${label} '${v}' isn't a date`); continue; }
    const d = day(v);
    if (!isBusinessDay(d)) errs.push(`${label} ${v} isn't a business day`);
    if (Math.abs(bdaysBetween(day(receivedIso), d)) > 10) errs.push(`${label} ${v} is more than 10 business days from today`);
  }
  if (ex.quantity !== null && ex.quantity !== undefined && !(ex.quantity > 0 && ex.quantity < 1e9)) {
    errs.push(`quantity ${ex.quantity} looks wrong`);
  }
  for (const [key, label] of REQUIRED[ex.category] || []) {
    const v = ex[key];
    if (!v || (Array.isArray(v) && !v.length)) errs.push(`missing ${label}`);
  }
  return errs;
}

function decide(email, ex, floor = 0.75) {
  const flags = detectSsiChange(email.subject, email.body);
  const senderDomain = String(email.from_addr).split("@").pop();
  const look = lookalikeOf(senderDomain);
  if (look) flags.push(`sender domain ${senderDomain} is a look-alike of ${look}`);
  if (ex.category === "SSI_UPDATE") flags.unshift("classified as an SSI update");
  if (ex.ssi_change_detected && !flags.length) flags.push("extractor flagged a settlement-instruction change");
  if (flags.length) {
    return { route: "SSI_CALLBACK", priority: "Highest", sla_gap_bdays: null, ssi_flags: flags, validation_errors: [],
             reasons: ["Possible change to settlement or bank details", "Call back on the number in static data, not anything in this email"] };
  }
  const errs = validate(ex, email.received_at);
  if (ex.category === "OTHER" && ex.confidence >= floor) {
    return { route: "FYI", priority: null, sla_gap_bdays: null, reasons: ["No action needed"], validation_errors: [], ssi_flags: [] };
  }
  if (ex.confidence < floor || errs.length) {
    const why = ex.confidence < floor ? [`confidence ${ex.confidence.toFixed(2)} below ${floor.toFixed(2)}`] : [];
    return { route: "HUMAN_REVIEW", priority: null, sla_gap_bdays: null, reasons: why.concat(errs), validation_errors: errs, ssi_flags: [] };
  }
  let p, gap, why;
  if (ex.category === "SETTLEMENT_FAIL") {
    [p, gap] = settlementUrgency(email.received_at, ex.settlement_date);
    p = p === "Highest" ? "Highest" : "High";
    why = "Fail: at least High, Highest once it's due";
  } else if (ex.category === "CA_ELECTION") {
    [p, gap] = settlementUrgency(email.received_at, ex.deadline);
    p = ["Highest", "High"].includes(p) ? p : "Medium";
    why = "Election: driven by the response deadline";
  } else if (ex.category === "PRICE_CHALLENGE") {
    [p, gap] = ["Medium", null];
    why = "Price challenge: before the next NAV strike";
  } else {
    [p, gap] = settlementUrgency(email.received_at, ex.settlement_date);
    why = "T+1: priority from business days to settlement";
  }
  return { route: "JIRA", priority: p, sla_gap_bdays: gap, reasons: [why], validation_errors: [], ssi_flags: [] };
}

if (typeof module !== "undefined") {
  module.exports = { decide, validate, detectSsiChange, lookalikeOf, cusipValid, isinValid, settlementUrgency, bdaysBetween, CATEGORIES };
}
