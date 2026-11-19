"use strict";
/**
 * POST /api/waitlist - join the YouTube Intelligence Engine waitlist (Vercel serverless function).
 *
 * Switched OFF unless WAITLIST_ENABLED=1, SUPABASE_URL and SUPABASE_ANON_KEY are set in the Vercel
 * project; until then it answers 503 and stores nothing. Storage: supabase/waitlist.sql (anon may
 * only INSERT). Emails are never logged. A duplicate email gets the same answer as a new one, so
 * the endpoint cannot be used to find out who is on the list. No dependencies.
 */

const OFFERS = new Set(["shorts", "reports", "agency", "api", "not_sure"]);
const SIZES = new Set(["starting", "under_1k", "1k_10k", "10k_100k", "over_100k"]);
const CONSENT_VERSION = "2026-11-v1";
const EMAIL = /^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,63}$/;
const SUPABASE_HOST = /^https:\/\/[a-z0-9-]+\.supabase\.co$/;
const MAX_BODY = 4096;

function send(res, status, body) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.end(JSON.stringify(body));
}

function bad(res, code, message) {
  return send(res, 400, { error: code, message });
}

async function handler(req, res, deps = {}) {
  const env = deps.env || process.env;
  const doFetch = deps.fetch || globalThis.fetch;
  const log = deps.log || ((m) => console.error(m));

  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return send(res, 405, { error: "method_not_allowed" });
  }
  const base = String(env.SUPABASE_URL || "").replace(/\/+$/, "");
  if (env.WAITLIST_ENABLED !== "1" || !env.SUPABASE_ANON_KEY || !base) {
    return send(res, 503, { error: "waitlist_closed", message: "The waitlist is not open yet." });
  }
  if (!SUPABASE_HOST.test(base)) {
    log("waitlist: SUPABASE_URL is not an https://<ref>.supabase.co address");
    return send(res, 503, { error: "waitlist_closed", message: "The waitlist is not open yet." });
  }
  const ctype = String((req.headers && req.headers["content-type"]) || "").split(";")[0].trim().toLowerCase();
  if (ctype !== "application/json") {
    return send(res, 415, { error: "unsupported_media_type" });
  }

  let body = req.body;
  if (typeof body === "string") {
    if (body.length > MAX_BODY) return send(res, 413, { error: "payload_too_large" });
    try {
      body = JSON.parse(body);
    } catch (e) {
      return bad(res, "invalid_json", "That request could not be read.");
    }
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return bad(res, "invalid_json", "That request could not be read.");
  }
  if (JSON.stringify(body).length > MAX_BODY) return send(res, 413, { error: "payload_too_large" });

  // Honeypot: a field people never see. Bots that fill it get a normal-looking success.
  if (typeof body.website === "string" && body.website.trim() !== "") {
    return send(res, 200, { ok: true });
  }

  const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  if (email.length < 6 || email.length > 254 || !EMAIL.test(email)) {
    return bad(res, "invalid_email", "Please enter a valid email address.");
  }
  if (!OFFERS.has(body.offer)) {
    return bad(res, "invalid_offer", "Please choose which offer you would use first.");
  }
  const size = body.channel_size === undefined || body.channel_size === null || body.channel_size === ""
    ? null : body.channel_size;
  if (size !== null && !SIZES.has(size)) {
    return bad(res, "invalid_channel_size", "Please choose a channel size from the list.");
  }
  if (body.consent !== true) {
    return bad(res, "consent_required", "Please tick the box to agree to be emailed about the waitlist.");
  }

  const key = env.SUPABASE_ANON_KEY;
  let r;
  try {
    r = await doFetch(`${base}/rest/v1/yie_waitlist_signups`, {
      method: "POST",
      headers: {
        apikey: key,
        Authorization: `Bearer ${key}`,
        "Content-Type": "application/json",
        Prefer: "return=minimal",
      },
      body: JSON.stringify({ email, offer: body.offer, channel_size: size, consent_version: CONSENT_VERSION }),
    });
  } catch (e) {
    log("waitlist: storage unreachable");
    return send(res, 502, { error: "unavailable", message: "Something went wrong. Please try again later." });
  }
  // 201 = added; 409 = already on the list. Same answer either way (no email enumeration).
  if (r.status === 201 || r.status === 409) return send(res, 200, { ok: true });
  log(`waitlist: storage answered HTTP ${r.status}`);
  return send(res, 502, { error: "unavailable", message: "Something went wrong. Please try again later." });
}

module.exports = (req, res) => handler(req, res);
module.exports.handler = handler;
module.exports.CONSENT_VERSION = CONSENT_VERSION;
