// Parse the model's JSON, then apply the controls. Same rules as triage/controls.py (checked by n8n/code/controls.test.js).
%%CONTROLS%%

const email = $("Build OpenAI request").item.json;
let ex;
try {
  const msg = $json.choices[0].message;
  if (msg.refusal) throw new Error(`model refused: ${msg.refusal}`);
  ex = JSON.parse(msg.content);
} catch (err) {
  // no usable answer -> confidence 0 -> a person looks at it (or the SSI check still catches it)
  ex = { category: "OTHER", confidence: 0, trade_ids: [], cusip: null, isin: null, quantity: null, settlement_date: null,
         deadline: null, counterparty: null, ssi_change_detected: false, summary: "", requested_action: "",
         error: String(err.message || err) };
}
// second opinion on bank details, whatever the model said
ex.ssi_change_detected = Boolean(ex.ssi_change_detected) || detectSsiChange(email.subject, email.body).length > 0;
const decision = decide(email, ex, 0.75);
return { json: { email, extraction: ex, decision, route: decision.route } };
