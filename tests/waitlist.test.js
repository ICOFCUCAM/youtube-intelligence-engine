// node --test tests/waitlist.test.js  (also run from pytest: tests/test_waitlist.py)
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { handler, CONSENT_VERSION, createLimiter, solve, sign, powOk } = require("../api/waitlist.js");

const SECRET = "test-secret-that-is-at-least-32-characters-long";
// Single opt-in, easy proof of work: the original behaviour, for the validation tests below.
const ON = { WAITLIST_ENABLED: "1", SUPABASE_URL: "https://abcdefgh.supabase.co", SUPABASE_ANON_KEY: "anon-key",
             WAITLIST_SECRET: SECRET, WAITLIST_SINGLE_OPT_IN: "1", WAITLIST_POW_BITS: "4" };
// Double opt-in (the default once email is configured).
const DOI = { ...ON, WAITLIST_SINGLE_OPT_IN: undefined, RESEND_API_KEY: "re_test", WAITLIST_FROM_EMAIL: "Waitlist <w@example.app>" };
const GOOD = { email: "  Creator@Example.ORG ", offer: "shorts", channel_size: "1k_10k", consent: true };

function res() {
  return {
    headers: {}, statusCode: 0, body: "",
    setHeader(k, v) { this.headers[k.toLowerCase()] = v; },
    end(b) { this.body = b; },
    get json() { return JSON.parse(this.body); },
  };
}
const SITE = { host: "yie.example.app", origin: "https://yie.example.app" };
function req(body, { method = "POST", ctype = "application/json", headers = {} } = {}) {
  return { method, headers: { "content-type": ctype, ...SITE, "x-forwarded-for": "203.0.113.7", ...headers }, body };
}
function fakeFetch(status = 201) {
  const calls = [];
  const f = async (url, init) => { calls.push({ url, init }); return { status }; };
  f.calls = calls;
  return f;
}
async function challenge(env = ON) {
  const r = res();
  await handler({ method: "GET", headers: {} }, r, { env, fetch: fakeFetch(), log() {}, challengeLimiter: () => true });
  return r;
}
/** Adds a solved proof of work to a form body, as the page script does. */
async function withPow(body, env = ON) {
  if (!body || typeof body !== "object" || Array.isArray(body) || body.confirm !== undefined) return body;
  const cr = await challenge(env);
  if (cr.statusCode !== 200) return body;      // closed: no challenge to solve
  const c = cr.json;
  const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  return { ...body, challenge: c.challenge, nonce: solve(c.challenge, email, c.bits) };
}
async function call(body, opts = {}, env = ON, status = 201) {
  const r = res(), f = fakeFetch(status), logs = [];
  const b = opts.noPow ? body : await withPow(body, env);
  await handler(req(b, opts), r, { env, fetch: f, log: (m) => logs.push(m), limiter: opts.limiter || (() => true),
                                   emailLimiter: opts.emailLimiter || (() => true), now: opts.now });
  return { r, f, logs };
}

test("switched off unless explicitly enabled and configured", async () => {
  for (const env of [{}, { ...ON, WAITLIST_ENABLED: "0" }, { ...ON, SUPABASE_ANON_KEY: "" }, { ...ON, SUPABASE_URL: "" },
                     { ...ON, WAITLIST_SECRET: "" }, { ...ON, WAITLIST_SECRET: "too-short" },
                     { ...DOI, RESEND_API_KEY: "" }, { ...DOI, WAITLIST_FROM_EMAIL: "" }]) {
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
      consent_version: CONSENT_VERSION, confirmed_at: null });
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
  assert.equal((await call(GOOD, { method: "PUT" })).r.statusCode, 405);
  assert.equal((await call(GOOD, { ctype: "text/plain" })).r.statusCode, 415);
  assert.equal((await call(JSON.stringify({ ...GOOD, pad: "x".repeat(5000) }))).r.statusCode, 413);
});

test("storage failures are generic and never log the email", async () => {
  const { r, logs } = await call(GOOD, {}, ON, 500);
  assert.equal(r.statusCode, 502);
  assert.ok(logs.length === 1 && !logs[0].includes("creator@example.org"));
  const r2 = res(), logs2 = [];
  await handler(req(await withPow(GOOD)), r2, { env: ON, fetch: async () => { throw new Error("down creator@example.org"); },
                                               log: (m) => logs2.push(m), limiter: () => true });
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

test("only accepts posts from the site itself", async () => {
  const cases = [
    { origin: undefined },
    { origin: "https://evil.example.com" },
    { origin: "http://yie.example.app" },          // not https
    { origin: "null" },
    { origin: "https://yie.example.app.evil.com" },
  ];
  for (const headers of cases) {
    const { r, f } = await call(GOOD, { headers });
    assert.equal(r.statusCode, 403, JSON.stringify(headers));
    assert.equal(f.calls.length, 0);
  }
  // Vercel's forwarded host wins over the internal Host header
  const fwd = await call(GOOD, { headers: { host: "internal", "x-forwarded-host": "yie.example.app" } });
  assert.equal(fwd.r.statusCode, 200);
  // an explicitly allowed extra origin (e.g. a custom domain during a move)
  const r = res(), f = fakeFetch();
  await handler(req(await withPow(GOOD), { headers: { origin: "https://www.example.org" } }), r,
    { env: { ...ON, WAITLIST_ALLOWED_ORIGINS: "https://www.example.org" }, fetch: f, log() {}, limiter: () => true });
  assert.equal(r.statusCode, 200);
});

test("per-visitor rate limit, without storing addresses", async () => {
  const limiter = createLimiter(3, 1000);
  const codes = [];
  for (let i = 0; i < 5; i++) codes.push((await call(GOOD, { limiter })).r.statusCode);
  assert.deepEqual(codes, [200, 200, 200, 429, 429]);
  const other = await call(GOOD, { limiter, headers: { "x-forwarded-for": "198.51.100.9, 10.0.0.1" } });
  assert.equal(other.r.statusCode, 200, "a different visitor is unaffected");
  const limited = await call(GOOD, { limiter });
  assert.equal(limited.r.json.error, "rate_limited");
  assert.ok(Number(limited.r.headers["retry-after"]) > 0);
  assert.equal(limited.f.calls.length, 0, "nothing reaches storage once limited");
  // window resets
  const l2 = createLimiter(1, 1000);
  assert.equal(l2("a", 0), true); assert.equal(l2("a", 10), false); assert.equal(l2("a", 1000), true);
  // memory is bounded
  const l3 = createLimiter(1, 1000, 2);
  l3("a", 0); l3("b", 0); l3("c", 0);
  assert.equal(l3("c", 1), false, "newest key kept after eviction");
});

test("database flood brake becomes a polite 429", async () => {
  const { r, logs } = await call(GOOD, {}, ON, 429);
  assert.equal(r.statusCode, 429);
  assert.equal(r.json.error, "busy");
  assert.ok(logs.every((m) => !m.includes("example.org")), "no email in logs");
});

// --- proof of work ----------------------------------------------------------------------------
test("GET gives a signed, expiring challenge; closed waitlist gives none", async () => {
  const r = await challenge();
  assert.equal(r.statusCode, 200);
  assert.equal(r.json.bits, 4);
  assert.match(r.json.challenge, /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/);
  assert.equal(r.headers["cache-control"], "no-store");
  assert.notEqual(r.json.challenge, (await challenge()).json.challenge, "fresh every time");
  assert.equal((await challenge({})).statusCode, 503);
  assert.equal((await challenge({ ...ON, WAITLIST_POW_BITS: undefined })).json.bits, 17, "default difficulty");
});

test("sign-up without a valid proof of work is refused and nothing is stored", async () => {
  const c = (await challenge()).json;
  const email = "creator@example.org";
  const good = solve(c.challenge, email, c.bits);
  let wrong = 0; while (powOk(c.challenge, email, String(wrong), 4)) wrong++;
  const forged = sign("another-secret-of-at-least-32-characters!!", "pow", { n: "x", b: 1, exp: Date.now() + 60000 });
  const expired = sign(SECRET, "pow", { n: "x", b: 1, exp: Date.now() - 1 });
  const cases = [
    {},                                                        // missing
    { challenge: c.challenge, nonce: String(wrong) },          // wrong answer
    { challenge: c.challenge, nonce: good, email: "other@example.org" },   // bound to the email
    { challenge: forged, nonce: solve(forged, email, 1) },     // not signed by us
    { challenge: expired, nonce: solve(expired, email, 1) },   // expired
    { challenge: c.challenge.replace(/^./, "A"), nonce: good },   // tampered
    { challenge: c.challenge, nonce: 7 },                      // wrong type
  ];
  for (const extra of cases) {
    const { r, f } = await call({ ...GOOD, ...extra }, { noPow: true });
    assert.equal(r.statusCode, 400, JSON.stringify(extra));
    assert.equal(r.json.error, "challenge_failed");
    assert.equal(f.calls.length, 0);
  }
  const ok = await call({ ...GOOD, challenge: c.challenge, nonce: good }, { noPow: true });
  assert.equal(ok.r.statusCode, 200);
});

test("challenges cannot be lowered: difficulty is the signed one", async () => {
  const c = (await challenge({ ...ON, WAITLIST_POW_BITS: "12" })).json;
  const email = "creator@example.org";
  // a nonce that meets 1 bit but (almost surely) not 12
  let n = 0; while (!powOk(c.challenge, email, String(n), 1) || powOk(c.challenge, email, String(n), 12)) n++;
  const { r } = await call({ ...GOOD, challenge: c.challenge, nonce: String(n), bits: 1 }, { noPow: true },
                           { ...ON, WAITLIST_POW_BITS: "12" });
  assert.equal(r.json.error, "challenge_failed");
});

// --- double opt-in ----------------------------------------------------------------------------
function doiFetch(emailStatus = 200, storeStatus = 201) {
  const calls = [];
  const f = async (url, init) => { calls.push({ url, init }); return { status: url.includes("resend.com") ? emailStatus : storeStatus }; };
  f.calls = calls;
  return f;
}
async function doi(body, { fetch = doiFetch(), now, emailLimiter = () => true, env = DOI } = {}) {
  const r = res(), logs = [];
  await handler(req(await withPow(body, env)), r, { env, fetch, log: (m) => logs.push(m), limiter: () => true, emailLimiter, now });
  return { r, f: fetch, logs };
}

test("double opt-in: sign-up only emails a link; nothing is stored until it is confirmed", async () => {
  const { r, f } = await doi(GOOD);
  assert.equal(r.statusCode, 200);
  assert.deepEqual(r.json, { ok: true, confirm: true });
  assert.equal(f.calls.length, 1, "one call: the email, not the database");
  const mail = f.calls[0];
  assert.equal(mail.url, "https://api.resend.com/emails");
  assert.equal(mail.init.headers.Authorization, "Bearer re_test");
  const m = JSON.parse(mail.init.body);
  assert.deepEqual(m.to, ["creator@example.org"]);
  assert.equal(m.from, "Waitlist <w@example.app>");
  const link = m.text.match(/https:\/\/yie\.example\.app\/confirm#t=(\S+)/);
  assert.ok(link, "link points at this site's confirm page, token in the fragment");
  assert.ok(m.text.includes("ignore this email"));

  // confirming stores the sign-up, marked confirmed
  const store = doiFetch();
  const c = await doi({ confirm: link[1] }, { fetch: store });
  assert.equal(c.r.statusCode, 200);
  assert.equal(store.calls.length, 1);
  assert.equal(store.calls[0].url, "https://abcdefgh.supabase.co/rest/v1/yie_waitlist_signups");
  const row = JSON.parse(store.calls[0].init.body);
  assert.equal(row.email, "creator@example.org");
  assert.equal(row.offer, "shorts");
  assert.equal(row.channel_size, "1k_10k");
  assert.equal(row.consent_version, CONSENT_VERSION);
  assert.ok(!isNaN(Date.parse(row.confirmed_at)));
  // confirming twice (or already on the list) answers the same
  assert.equal((await doi({ confirm: link[1] }, { fetch: doiFetch(200, 409) })).r.statusCode, 200);
});

test("double opt-in: forged, tampered or expired links store nothing", async () => {
  const { f } = await doi(GOOD);
  const token = JSON.parse(f.calls[0].init.body).text.match(/#t=(\S+)/)[1];
  const [payload, mac] = token.split(".");
  const evil = Buffer.from(JSON.stringify({ s: { email: "victim@example.org", offer: "api", size: null, platforms: [] },
                                            exp: Date.now() + 1e6 })).toString("base64url");
  const later = Date.now() + 49 * 3600 * 1000;
  for (const [tok, now] of [[`${evil}.${mac}`, undefined], [`${payload}.${mac}x`, undefined], ["garbage", undefined],
                            [42, undefined], [token, () => later],
                            [sign("another-secret-of-at-least-32-characters!!", "confirm", { s: {}, exp: Date.now() + 1e6 }), undefined]]) {
    const store = doiFetch();
    const r = await doi({ confirm: tok }, { fetch: store, now });
    assert.equal(r.r.statusCode, 400, String(tok).slice(0, 20));
    assert.equal(r.r.json.error, "invalid_link");
    assert.equal(store.calls.length, 0);
  }
  // a proof-of-work challenge is not a confirmation token (purpose-bound signatures)
  const c = (await challenge(DOI)).json.challenge;
  assert.equal((await doi({ confirm: c })).r.json.error, "invalid_link");
});

test("double opt-in: at most two emails per address per window, without revealing it", async () => {
  const emailLimiter = createLimiter(2, 60000);
  const f = doiFetch();
  const answers = [];
  for (let i = 0; i < 4; i++) answers.push((await doi(GOOD, { fetch: f, emailLimiter })).r.json);
  assert.ok(answers.every((a) => a.ok && a.confirm), "same answer every time");
  assert.equal(f.calls.length, 2, "but only two emails sent");
});

test("double opt-in: email provider failure is generic and logs no address", async () => {
  const { r, logs } = await doi(GOOD, { fetch: doiFetch(500) });
  assert.equal(r.statusCode, 502);
  assert.ok(logs.every((m) => !m.includes("example.org")));
});

test("honeypot in double opt-in mode looks like success and sends nothing", async () => {
  const { r, f } = await doi({ ...GOOD, website: "x" });
  assert.deepEqual(r.json, { ok: true, confirm: true });
  assert.equal(f.calls.length, 0);
});
