// Ask for a reply draft. It is stored as PENDING_APPROVAL and nothing sends it until an analyst approves.
const SYSTEM = %%DRAFT_SYSTEM%%;
const base = $("Build Jira payload").item.json;
const ticket = $json.key || $json.issues?.[0]?.key || $("Already open?").item.json.issues?.[0]?.key || null;
const ex = base.extraction;
const notes = [
  `Category: ${ex.category}`,
  `Trade IDs: ${(ex.trade_ids || []).join(", ") || "-"}`,
  `Security: ${ex.cusip || ex.isin || "-"}`,
  `Quantity: ${ex.quantity ?? "-"}`,
  `Settlement date: ${ex.settlement_date || "-"}`,
  `Deadline: ${ex.deadline || "-"}`,
  `Our ticket: ${ticket || "-"}`,
  `Their email (from ${base.email.from_name}):\n${base.email.body.slice(0, 4000)}`,
].join("\n");
return {
  json: {
    email_id: base.email.email_id,
    jira_key: ticket,
    openai_request: {
      model: "%%MODEL%%",
      temperature: 0.2,
      messages: [{ role: "system", content: SYSTEM }, { role: "user", content: notes }],
    },
  },
};
