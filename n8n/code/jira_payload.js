// Jira Cloud v3 issue + the JQL that finds an open ticket for the same trade (so follow-ups become comments).
// Your Jira site. The HTTP nodes downstream read it from here (n8n 2.x blocks $env in nodes by default).
const JIRA_BASE_URL = "%%JIRA_BASE_URL%%";
const { email, extraction: ex, decision } = $json;  // input comes straight from Route
const LABEL = { TRADE_QUERY: "trade-query", SETTLEMENT_FAIL: "settlement-fail", CA_ELECTION: "ca-election", PRICE_CHALLENGE: "price-challenge" };
const PREFIX = { TRADE_QUERY: "Query", SETTLEMENT_FAIL: "FAIL", CA_ELECTION: "Election", PRICE_CHALLENGE: "Price" };
const ref = (ex.trade_ids || []).join(", ") || ex.cusip || ex.isin || "no ref";
const bits = [PREFIX[ex.category], ref];
if (ex.quantity) bits.push(Number(ex.quantity).toLocaleString("en-US"));
if (ex.settlement_date) bits.push(`SD ${ex.settlement_date}`);
if (ex.deadline) bits.push(`deadline ${ex.deadline}`);
if (ex.counterparty) bits.push(ex.counterparty);
const refKey = (ex.trade_ids || [])[0] || ex.cusip || ex.isin || null;
const labels = ["mailbox-triage", LABEL[ex.category], ...(ex.trade_ids || []).map((t) => `trade-${t}`)];
if (refKey) labels.push(`ref-${refKey}`);
if (["Highest", "High"].includes(decision.priority) && ["SETTLEMENT_FAIL", "TRADE_QUERY"].includes(ex.category)) labels.push("t1-at-risk");
const para = (t) => ({ type: "paragraph", content: [{ type: "text", text: t }] });
const issue = {
  fields: {
    project: { key: "MO" },
    issuetype: { name: "Task" },
    summary: bits.join(" | ").slice(0, 250),
    priority: { name: decision.priority },
    labels,
    description: { type: "doc", version: 1, content: [
      para(`From ${email.from_name} <${email.from_addr}> at ${email.received_at}`),
      para(`Subject: ${email.subject}`),
      para(`Trade IDs: ${ref} | CUSIP: ${ex.cusip || "-"} | ISIN: ${ex.isin || "-"} | Qty: ${ex.quantity || "-"} | Settlement: ${ex.settlement_date || "-"} | Deadline: ${ex.deadline || "-"} | Counterparty: ${ex.counterparty || "-"}`),
      para(`Why this priority: ${decision.reasons.join("; ")}`),
      para(`Model confidence ${Number(ex.confidence).toFixed(2)}. Email id ${email.email_id}.`),
    ] },
  },
};
if (ex.settlement_date || ex.deadline) issue.fields.duedate = ex.settlement_date || ex.deadline;
// one open ticket per (category, trade or security): a follow-up email becomes a comment
const jql = refKey
  ? `project = MO AND labels = "mailbox-triage" AND labels = "${LABEL[ex.category]}" AND labels = "ref-${refKey}" AND statusCategory != Done`
  : `project = MO AND labels = "__no_dedupe__"`;
return { json: { ...$json, issue, jql, jira_base_url: JIRA_BASE_URL.replace(/\/$/, "") } };
