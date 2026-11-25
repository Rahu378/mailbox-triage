// Runs the Code nodes from the generated workflow (n8n/mailbox_triage.json) in a small emulation of n8n's
// Code-node runtime, chained the way the workflow chains them, with the model call stubbed out.
// FIXTURES (written by tests/test_n8n_parity.py) holds the emails, a model answer for each, and the
// decision the Python pipeline made.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const wf = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "mailbox_triage.json"), "utf8"));
const codeOf = (name) => wf.nodes.find((n) => n.name === name).parameters.jsCode;
const compile = (name) => new Function("$json", "$", "$execution", "$itemIndex", "$env", codeOf(name));
const nodes = Object.fromEntries(["Normalize email", "Build OpenAI request", "Parse + controls", "Build Jira payload",
  "Build draft request"].map((n) => [n, compile(n)]));

function run(email, extraction) {
  const out = {};
  const $ = (name) => ({ item: { json: out[name] } });
  const step = (name, input) => { out[name] = nodes[name](input, $, { id: "test" }, 0, {}).json; return out[name]; };
  const imap = { from: { text: `${email.from_name} <${email.from_addr}>` }, subject: email.subject,
                 date: email.received_at, textPlain: email.body, messageId: email.email_id };
  step("Normalize email", imap);
  const req = step("Build OpenAI request", out["Normalize email"]);
  assert.strictEqual(req.openai_request.response_format.json_schema.strict, true);
  const parsed = step("Parse + controls", { choices: [{ message: { content: JSON.stringify(extraction) } }] });
  if (parsed.route === "JIRA") {
    const jp = step("Build Jira payload", parsed);
    assert.ok(jp.issue.fields.summary.length > 0 && jp.issue.fields.priority.name);
    out["Already open?"] = { issues: [] };
    const dr = step("Build draft request", { key: "MO-1" });
    assert.strictEqual(dr.jira_key, "MO-1");
  }
  return parsed;
}

test("workflow Code nodes run end to end and route like the Python pipeline", { skip: !process.env.FIXTURES }, () => {
  const cases = JSON.parse(fs.readFileSync(process.env.FIXTURES, "utf8"));
  for (const k of cases) {
    const email = { ...k.email, from_name: k.email.from_name || "" };
    const ex = { summary: "", requested_action: "", ...k.extraction };
    const got = run(email, ex);
    assert.strictEqual(got.decision.route, k.expected.route, k.email.email_id);
    assert.strictEqual(got.decision.priority, k.expected.priority, k.email.email_id);
  }
});

test("a model failure lands in human review, not in Jira", () => {
  const email = { email_id: "X1", from_name: "A B", from_addr: "a.b@kestrelprime.example", subject: "T7000001",
                  body: "Can you check T7000001?", received_at: "2026-11-18T10:00:00" };
  const out = {};
  const $ = (name) => ({ item: { json: out[name] } });
  out["Normalize email"] = nodes["Normalize email"]({ from: { text: "A B <a.b@kestrelprime.example>" }, subject: email.subject,
    date: email.received_at, textPlain: email.body, messageId: "X1" }, $, { id: "t" }, 0, {}).json;
  out["Build OpenAI request"] = nodes["Build OpenAI request"](out["Normalize email"], $, { id: "t" }, 0, {}).json;
  const parsed = nodes["Parse + controls"]({ error: { message: "rate limited" } }, $, { id: "t" }, 0, {}).json;
  assert.strictEqual(parsed.decision.route, "HUMAN_REVIEW");
});
