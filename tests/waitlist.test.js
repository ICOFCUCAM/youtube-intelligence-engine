// node --test tests/waitlist.test.js  (also run from pytest: tests/test_waitlist.py)
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { handler, CONSENT_VERSION } = require("../api/waitlist.js");

const ON = { WAITLIST_ENABLED: "1", SUPABASE_URL: "https://abcdefgh.supabase.co", SUPABASE_ANON_KEY: "anon-key" };
const GOOD = { email: "  Creator@Example.ORG ", offer: "shorts", channel_size: "1k_10k", consent: true };

function res() {
  return {
    headers: {}, statusCode: 0, body: "",
    setHeader(k, v) { this.headers[k.toLowerCase()] = v; },
    end(b) { this.body = b; },
    get json() { return JSON.parse(this.body); },
  };
}
function req(body, { method = "POST", ctype = "application/json" } = {}) {
  return { method, headers: { "content-type": ctype }, body };
}
function fakeFetch(status = 201) {
  const calls = [];
  const f = async (url, init) => { calls.push({ url, init }); return { status }; };
  f.calls = calls;
  return f;
}
async function call(body, opts = {}, env = ON, status = 201) {
  const r = res(), f = fakeFetch(status), logs = [];
  await handler(req(body, opts), r, { env, fetch: f, log: (m) => logs.push(m) });
  return { r, f, logs };
}

test("switched off unless explicitly enabled and configured", async () => {
  for (const env of [{}, { ...ON, WAITLIST_ENABLED: "0" }, { ...ON, SUPABASE_ANON_KEY: "" }, { ...ON, SUPABASE_URL: "" }]) {
    const { r, f } = await call(GOOD, {}, env);
    assert.equal(r.statusCode, 503);
    assert.equal(r.json.error, "waitlist_closed");
    assert.equal(f.calls.length, 0, "nothing is stored while closed");
  }
});

test("refuses a storage URL that is not a Supabase project", async () => {
  const { r, f } = await call(GOOD, {}, { ...ON, SUPABASE_URL: "https://evil.example.com" });
  assert.equal(r.statusCode, 503);
  assert.equal(f.calls.length, 0);
});

test("valid signup is stored minimally, email normalised", async () => {
  const { r, f } = await call(GOOD);
  assert.equal(r.statusCode, 200);
  assert.deepEqual(r.json, { ok: true });
  assert.equal(r.headers["cache-control"], "no-store");
  assert.equal(f.calls.length, 1);
  assert.equal(f.calls[0].url, "https://abcdefgh.supabase.co/rest/v1/yie_waitlist_signups");
  assert.equal(f.calls[0].init.headers.Prefer, "return=minimal");
  assert.deepEqual(JSON.parse(f.calls[0].init.body),
    { email: "creator@example.org", offer: "shorts", channel_size: "1k_10k", other_platforms: [],
      consent_version: CONSENT_VERSION });
});

test("duplicate email gets the same answer as a new one", async () => {
  const { r } = await call(GOOD, {}, ON, 409);
  assert.equal(r.statusCode, 200);
  assert.deepEqual(r.json, { ok: true });
});

test("validation", async () => {
  const cases = [
    [{ ...GOOD, email: "not-an-email" }, "invalid_email"],
    [{ ...GOOD, email: "a@b" }, "invalid_email"],
    [{ ...GOOD, email: "x".repeat(250) + "@example.org" }, "invalid_email"],
    [{ ...GOOD, email: 42 }, "invalid_email"],
    [{ ...GOOD, offer: "everything" }, "invalid_offer"],
    [{ ...GOOD, channel_size: "huge" }, "invalid_channel_size"],
    [{ ...GOOD, consent: "yes" }, "consent_required"],
    [{ ...GOOD, consent: undefined }, "consent_required"],
    [[GOOD], "invalid_json"],
    ["{not json", "invalid_json"],
  ];
  for (const [body, code] of cases) {
    const { r, f } = await call(body);
    assert.equal(r.statusCode, 400, code);
    assert.equal(r.json.error, code);
    assert.equal(f.calls.length, 0);
  }
});

test("channel size is optional", async () => {
  const { r, f } = await call({ ...GOOD, channel_size: "" });
  assert.equal(r.statusCode, 200);
  assert.equal(JSON.parse(f.calls[0].init.body).channel_size, null);
});

test("honeypot: bots get a fake success and nothing is stored", async () => {
  const { r, f } = await call({ ...GOOD, website: "http://spam.example" });
  assert.equal(r.statusCode, 200);
  assert.equal(f.calls.length, 0);
});

test("method, content type and size limits", async () => {
  assert.equal((await call(GOOD, { method: "GET" })).r.statusCode, 405);
  assert.equal((await call(GOOD, { ctype: "text/plain" })).r.statusCode, 415);
  assert.equal((await call(JSON.stringify({ ...GOOD, pad: "x".repeat(5000) }))).r.statusCode, 413);
});

test("storage failures are generic and never log the email", async () => {
  const { r, logs } = await call(GOOD, {}, ON, 500);
  assert.equal(r.statusCode, 502);
  assert.ok(logs.length === 1 && !logs[0].includes("creator@example.org"));
  const r2 = res(), logs2 = [];
  await handler(req(GOOD), r2, { env: ON, fetch: async () => { throw new Error("down creator@example.org"); }, log: (m) => logs2.push(m) });
  assert.equal(r2.statusCode, 502);
  assert.ok(!logs2.join(" ").includes("creator@"));
});

test("other platforms: optional, de-duplicated, sorted, validated", async () => {
  const ok = await call({ ...GOOD, other_platforms: ["tiktok", "linkedin", "tiktok"] });
  assert.equal(ok.r.statusCode, 200);
  assert.deepEqual(JSON.parse(ok.f.calls[0].init.body).other_platforms, ["linkedin", "tiktok"]);
  const none = await call({ ...GOOD, other_platforms: ["none"] });
  assert.deepEqual(JSON.parse(none.f.calls[0].init.body).other_platforms, ["none"]);
  for (const bad of [["myspace"], "tiktok", [1], ["none", "tiktok"], Array(8).fill("x")]) {
    const { r, f } = await call({ ...GOOD, other_platforms: bad });
    assert.equal(r.statusCode, 400, JSON.stringify(bad));
    assert.equal(r.json.error, "invalid_platforms");
    assert.equal(f.calls.length, 0);
  }
});
