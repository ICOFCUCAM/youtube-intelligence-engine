"use strict";
/**
 * /api/waitlist - the YouTube Intelligence Engine waitlist (Vercel serverless function).
 *
 *   GET  /api/waitlist                 -> a proof-of-work challenge for the form
 *   POST /api/waitlist {email, ...}    -> sign up (emails a confirmation link; stores nothing yet)
 *   POST /api/waitlist {confirm: tok}  -> confirm from that link (only now is the sign-up stored)
 *
 * Switched OFF unless WAITLIST_ENABLED=1 and SUPABASE_URL, SUPABASE_ANON_KEY and WAITLIST_SECRET
 * (32+ characters) are set; confirmation emails also need RESEND_API_KEY and WAITLIST_FROM_EMAIL,
 * unless WAITLIST_SINGLE_OPT_IN=1. Until then it answers 503 and stores nothing. Storage:
 * supabase/waitlist.sql (anon may only INSERT). Emails are never logged. Duplicates get the same
 * answer as new sign-ups, so the endpoint cannot reveal who is on the list. No dependencies.
 *
 * Abuse protection, in layers (no third-party CAPTCHA, nothing loaded from another site):
 *  1. Same-origin only: a POST must carry an Origin header naming this site (403 otherwise).
 *  2. Per-visitor and per-email limits, in memory only (429). Best effort per warm instance.
 *  3. Honeypot field that people never see.
 *  4. Proof of work: the browser must find a nonce so that SHA-256(challenge:email:nonce) starts
 *     with POW_BITS zero bits (about a second on a desktop, a few on a slow phone). The challenge is signed, expires in
 *     10 minutes and is bound to the email, so one solution cannot be reused for other addresses.
 *  5. Double opt-in: nothing is stored until the owner of the address clicks the emailed link.
 *     The link carries the sign-up, signed with WAITLIST_SECRET, so unconfirmed sign-ups are never
 *     stored anywhere by us.
 *  6. In the database: a flood brake (supabase/waitlist.sql), answered here as 429.
 */

const crypto = require("crypto");

const OFFERS = new Set(["shorts", "reports", "agency", "api", "not_sure"]);
const SIZES = new Set(["starting", "under_1k", "1k_10k", "10k_100k", "over_100k"]);
const PLATFORMS = new Set(["tiktok", "instagram", "facebook", "linkedin", "x", "podcasts", "none"]);
const CONSENT_VERSION = "2026-11-v3";
const EMAIL = /^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,63}$/;
const SUPABASE_HOST = /^https:\/\/[a-z0-9-]+\.supabase\.co$/;
const MAX_BODY = 4096;
const RATE_MAX = 8;
const RATE_WINDOW_MS = 10 * 60 * 1000;
const EMAIL_MAX = 2;                       // confirmation emails per address per window
const CHALLENGE_TTL_MS = 10 * 60 * 1000;
const CONFIRM_TTL_MS = 48 * 60 * 60 * 1000;
const POW_BITS = 17;
const RESEND_URL = "https://api.resend.com/emails";

/** Fixed-window counter per key, in memory. Keys are client addresses; nothing is persisted. */
function createLimiter(max = RATE_MAX, windowMs = RATE_WINDOW_MS, maxKeys = 10000) {
  const hits = new Map();
  return function allow(key, now = Date.now()) {
    let h = hits.get(key);
    if (!h || now - h.start >= windowMs) {
      if (hits.size >= maxKeys) {
        for (const [k, v] of hits) if (now - v.start >= windowMs) hits.delete(k);
        if (hits.size >= maxKeys) hits.delete(hits.keys().next().value);
      }
      h = { start: now, n: 0 };
      hits.set(key, h);
    }
    h.n += 1;
    return h.n <= max;
  };
}
const defaultLimiter = createLimiter();
const defaultEmailLimiter = createLimiter(EMAIL_MAX);
const defaultChallengeLimiter = createLimiter(30);

// --- small helpers ---------------------------------------------------------------------------
function send(res, status, body) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.end(JSON.stringify(body));
}
function bad(res, code, message) {
  return send(res, 400, { error: code, message });
}
const CLOSED = { error: "waitlist_closed", message: "The waitlist is not open yet." };
const FAILED = { error: "unavailable", message: "Something went wrong. Please try again later." };

function header(req, name) {
  const v = req.headers && req.headers[name];
  return Array.isArray(v) ? String(v[0] || "") : String(v || "");
}
function clientKey(req) {
  const fwd = header(req, "x-forwarded-for").split(",")[0].trim();
  return fwd || header(req, "x-real-ip").trim() || (req.socket && req.socket.remoteAddress) || "unknown";
}
/** The request's Origin when it names the host it was sent to (or an allowed extra origin), else null. */
function sameOrigin(req, env) {
  const origin = header(req, "origin").trim();
  if (!origin) return null;
  let o;
  try {
    o = new URL(origin);
  } catch (e) {
    return null;
  }
  const extra = String(env.WAITLIST_ALLOWED_ORIGINS || "").split(",").map((x) => x.trim()).filter(Boolean);
  if (extra.includes(o.origin)) return o.origin;
  const host = (header(req, "x-forwarded-host") || header(req, "host")).split(",")[0].trim().toLowerCase();
  return o.protocol === "https:" && host !== "" && o.host.toLowerCase() === host ? o.origin : null;
}

const b64u = (buf) => Buffer.from(buf).toString("base64url");
function sign(secret, purpose, data) {
  const payload = b64u(JSON.stringify(data));
  const mac = crypto.createHmac("sha256", secret).update(`${purpose}.${payload}`).digest("base64url");
  return `${payload}.${mac}`;
}
/** Returns the signed data, or null if the token is malformed, forged or expired. */
function verify(secret, purpose, token, now) {
  if (typeof token !== "string" || token.length > 2048) return null;
  const parts = token.split(".");
  if (parts.length !== 2) return null;
  const want = crypto.createHmac("sha256", secret).update(`${purpose}.${parts[0]}`).digest();
  const got = Buffer.from(parts[1], "base64url");
  if (got.length !== want.length || !crypto.timingSafeEqual(got, want)) return null;
  let data;
  try {
    data = JSON.parse(Buffer.from(parts[0], "base64url").toString("utf8"));
  } catch (e) {
    return null;
  }
  if (!data || typeof data !== "object" || typeof data.exp !== "number" || data.exp <= now) return null;
  return data;
}

function leadingZeroBits(buf) {
  let n = 0;
  for (const byte of buf) {
    if (byte === 0) { n += 8; continue; }
    return n + Math.clz32(byte) - 24;
  }
  return n;
}
/** True when nonce solves the challenge for this email. Exported for tests. */
function powOk(challenge, email, nonce, bits) {
  const h = crypto.createHash("sha256").update(`${challenge}:${email}:${nonce}`).digest();
  return leadingZeroBits(h) >= bits;
}
/** Brute-force a nonce (tests and tooling only; the browser does this in the page script). */
function solve(challenge, email, bits) {
  for (let i = 0; ; i++) if (powOk(challenge, email, String(i), bits)) return String(i);
}

function config(env) {
  const base = String(env.SUPABASE_URL || "").replace(/\/+$/, "");
  const secret = String(env.WAITLIST_SECRET || "");
  const single = env.WAITLIST_SINGLE_OPT_IN === "1";
  const bits = Math.min(24, Math.max(1, parseInt(env.WAITLIST_POW_BITS || POW_BITS, 10) || POW_BITS));
  const problems = [];
  if (env.WAITLIST_ENABLED !== "1") problems.push(null);           // closed on purpose: say nothing
  if (!env.SUPABASE_ANON_KEY || !base) problems.push("SUPABASE_URL and SUPABASE_ANON_KEY are required");
  else if (!SUPABASE_HOST.test(base)) problems.push("SUPABASE_URL is not an https://<ref>.supabase.co address");
  if (secret.length < 32) problems.push("WAITLIST_SECRET must be at least 32 characters");
  if (!single && (!env.RESEND_API_KEY || !env.WAITLIST_FROM_EMAIL)) {
    problems.push("RESEND_API_KEY and WAITLIST_FROM_EMAIL are required (or set WAITLIST_SINGLE_OPT_IN=1)");
  }
  return { base, secret, single, bits, key: env.SUPABASE_ANON_KEY, problems };
}

async function readJson(req, res) {
  const ctype = header(req, "content-type").split(";")[0].trim().toLowerCase();
  if (ctype !== "application/json") { send(res, 415, { error: "unsupported_media_type" }); return null; }
  let body = req.body;
  if (typeof body === "string") {
    if (body.length > MAX_BODY) { send(res, 413, { error: "payload_too_large" }); return null; }
    try {
      body = JSON.parse(body);
    } catch (e) {
      bad(res, "invalid_json", "That request could not be read."); return null;
    }
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    bad(res, "invalid_json", "That request could not be read."); return null;
  }
  if (JSON.stringify(body).length > MAX_BODY) { send(res, 413, { error: "payload_too_large" }); return null; }
  return body;
}

/** Validates the form fields. Returns {email, offer, size, platforms} or sends a 400 and returns null. */
function validate(body, res) {
  const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  if (email.length < 6 || email.length > 254 || !EMAIL.test(email)) {
    bad(res, "invalid_email", "Please enter a valid email address."); return null;
  }
  if (!OFFERS.has(body.offer)) {
    bad(res, "invalid_offer", "Please choose which offer you would use first."); return null;
  }
  const size = body.channel_size === undefined || body.channel_size === null || body.channel_size === ""
    ? null : body.channel_size;
  if (size !== null && !SIZES.has(size)) {
    bad(res, "invalid_channel_size", "Please choose a channel size from the list."); return null;
  }
  let platforms = body.other_platforms === undefined || body.other_platforms === null ? [] : body.other_platforms;
  if (!Array.isArray(platforms) || platforms.length > PLATFORMS.size ||
      !platforms.every((p) => typeof p === "string" && PLATFORMS.has(p))) {
    bad(res, "invalid_platforms", "Please choose platforms from the list."); return null;
  }
  platforms = [...new Set(platforms)].sort();
  if (platforms.includes("none") && platforms.length > 1) {
    bad(res, "invalid_platforms", "Choose platforms, or 'nowhere else' - not both."); return null;
  }
  if (body.consent !== true) {
    bad(res, "consent_required", "Please tick the box to agree to be emailed about the waitlist."); return null;
  }
  return { email, offer: body.offer, size, platforms };
}

async function store(cfg, s, confirmed, doFetch, log, res) {
  let r;
  try {
    r = await doFetch(`${cfg.base}/rest/v1/yie_waitlist_signups`, {
      method: "POST",
      headers: {
        apikey: cfg.key,
        Authorization: `Bearer ${cfg.key}`,
        "Content-Type": "application/json",
        Prefer: "return=minimal",
      },
      body: JSON.stringify({ email: s.email, offer: s.offer, channel_size: s.size, other_platforms: s.platforms,
                             consent_version: CONSENT_VERSION,
                             confirmed_at: confirmed ? new Date(confirmed).toISOString() : null }),
    });
  } catch (e) {
    log("waitlist: storage unreachable");
    return send(res, 502, FAILED);
  }
  // 201 = added; 409 = already on the list. Same answer either way (no email enumeration).
  if (r.status === 201 || r.status === 409) return send(res, 200, { ok: true });
  // 429 = the database's flood brake: too many sign-ups site-wide just now.
  if (r.status === 429) {
    log("waitlist: database flood brake engaged");
    return send(res, 429, { error: "busy", message: "Lots of sign-ups right now. Please try again in a few minutes." });
  }
  log(`waitlist: storage answered HTTP ${r.status}`);
  return send(res, 502, FAILED);
}

function confirmationEmail(link) {
  return [
    "Hello,",
    "",
    "Someone (hopefully you) asked to join the YouTube Intelligence Engine waitlist with this address.",
    "To confirm, open this link within 48 hours and press the button:",
    "",
    link,
    "",
    "If it wasn't you, ignore this email. Nothing has been saved, and you won't hear from us again.",
    "",
    "Not affiliated with, endorsed by or sponsored by YouTube or Google.",
  ].join("\n");
}

async function sendConfirmation(env, to, link, doFetch, log) {
  try {
    const r = await doFetch(RESEND_URL, {
      method: "POST",
      headers: { Authorization: `Bearer ${env.RESEND_API_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify({ from: env.WAITLIST_FROM_EMAIL, to: [to], subject: "Confirm your place on the waitlist",
                             text: confirmationEmail(link) }),
    });
    if (r.status >= 200 && r.status < 300) return true;
    log(`waitlist: email provider answered HTTP ${r.status}`);
  } catch (e) {
    log("waitlist: email provider unreachable");
  }
  return false;
}

// --- the handler -----------------------------------------------------------------------------
async function handler(req, res, deps = {}) {
  const env = deps.env || process.env;
  const doFetch = deps.fetch || globalThis.fetch;
  const log = deps.log || ((m) => console.error(m));
  const now = deps.now || Date.now;
  const allow = deps.limiter || defaultLimiter;
  const allowEmail = deps.emailLimiter || defaultEmailLimiter;
  const allowChallenge = deps.challengeLimiter || defaultChallengeLimiter;

  if (req.method !== "POST" && req.method !== "GET") {
    res.setHeader("Allow", "GET, POST");
    return send(res, 405, { error: "method_not_allowed" });
  }
  const cfg = config(env);
  if (cfg.problems.length) {
    for (const p of cfg.problems) if (p) log(`waitlist: ${p}`);
    return send(res, 503, CLOSED);
  }

  if (req.method === "GET") {
    if (!allowChallenge(clientKey(req))) {
      res.setHeader("Retry-After", String(RATE_WINDOW_MS / 1000));
      return send(res, 429, { error: "rate_limited", message: "Too many attempts. Please try again in a few minutes." });
    }
    const challenge = sign(cfg.secret, "pow", { n: b64u(crypto.randomBytes(12)), b: cfg.bits, exp: now() + CHALLENGE_TTL_MS });
    return send(res, 200, { challenge, bits: cfg.bits });
  }

  const origin = sameOrigin(req, env);
  if (!origin) return send(res, 403, { error: "forbidden", message: "Please use the form on the website." });
  if (!allow(clientKey(req))) {
    res.setHeader("Retry-After", String(RATE_WINDOW_MS / 1000));
    return send(res, 429, { error: "rate_limited", message: "Too many attempts. Please try again in a few minutes." });
  }
  const body = await readJson(req, res);
  if (!body) return undefined;

  // Confirmation from the emailed link: verify the signed sign-up, then store it.
  if (body.confirm !== undefined) {
    const d = verify(cfg.secret, "confirm", body.confirm, now());
    if (!d || !d.s) {
      return bad(res, "invalid_link", "This link is invalid or has expired. Please sign up again.");
    }
    return store(cfg, d.s, now(), doFetch, log, res);
  }

  // Honeypot: a field people never see. Bots that fill it get a normal-looking success.
  if (typeof body.website === "string" && body.website.trim() !== "") {
    return send(res, 200, { ok: true, confirm: !cfg.single });
  }
  const s = validate(body, res);
  if (!s) return undefined;

  const ch = verify(cfg.secret, "pow", body.challenge, now());
  if (!ch || typeof body.nonce !== "string" || body.nonce.length > 32 ||
      !powOk(body.challenge, s.email, body.nonce, ch.b)) {
    return bad(res, "challenge_failed", "The anti-spam check didn't complete. Please try again.");
  }

  if (cfg.single) return store(cfg, s, null, doFetch, log, res);

  if (!allowEmail(crypto.createHash("sha256").update(s.email).digest("base64url"))) {
    // Already sent recently: answer as if sent, without sending again (no inbox flooding).
    return send(res, 200, { ok: true, confirm: true });
  }
  const token = sign(cfg.secret, "confirm", { s, exp: now() + CONFIRM_TTL_MS });
  const sent = await sendConfirmation(env, s.email, `${origin}/confirm#t=${token}`, doFetch, log);
  if (!sent) return send(res, 502, FAILED);
  return send(res, 200, { ok: true, confirm: true });
}

module.exports = (req, res) => handler(req, res);
module.exports.handler = handler;
module.exports.CONSENT_VERSION = CONSENT_VERSION;
module.exports.createLimiter = createLimiter;
module.exports.powOk = powOk;
module.exports.solve = solve;
module.exports.sign = sign;
