// node --test n8n/code/  (FIXTURES=path/to/cases.json, written by tests/test_n8n_parity.py)
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const c = require("./controls.js");

test("check digits", () => {
  assert.ok(c.cusipValid("037833100"));
  assert.ok(!c.cusipValid("037833101"));
  assert.ok(c.isinValid("US0378331005"));
  assert.ok(!c.isinValid("US0378331006"));
});

test("Thanksgiving pushes T+1", () => {
  // received Wednesday 25 Nov, settles Friday 27 Nov: one business day away, so High
  assert.deepStrictEqual(c.settlementUrgency("2026-11-25T10:00:00", "2026-11-27"), ["High", 1]);
});

test("look-alike sender domains", () => {
  assert.strictEqual(c.lookalikeOf("ha1den-sec.example"), "Halden Securities");
  assert.strictEqual(c.lookalikeOf("halden-sec.example"), null);
});

test("same decisions as the Python controls", { skip: !process.env.FIXTURES }, () => {
  const cases = JSON.parse(fs.readFileSync(process.env.FIXTURES, "utf8"));
  let n = 0;
  for (const k of cases) {
    const got = c.decide(k.email, k.extraction, 0.75);
    assert.strictEqual(got.route, k.expected.route, `${k.email.email_id} route`);
    assert.strictEqual(got.priority, k.expected.priority, `${k.email.email_id} priority`);
    assert.deepStrictEqual(got.validation_errors, k.expected.validation_errors, `${k.email.email_id} validation`);
    assert.deepStrictEqual(got.ssi_flags, k.expected.ssi_flags, `${k.email.email_id} ssi flags`);
    n += 1;
  }
  assert.ok(n > 400);
});
