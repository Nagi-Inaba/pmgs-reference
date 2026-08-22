# ADR 0010: Worker HTTP representation negotiation

## Status

Accepted for PR #38.

## Context

The optional Cloudflare Worker serves pre-generated HTML and Markdown representations from the same public export. The route must select a representation from the request `Accept` header without treating a mere substring match as authoritative, and method responses must advertise only methods actually implemented by the route class.

## Decision

- HTML remains the default representation when `Accept` is absent, unsupported, tied, or explicitly rejects every representation currently offered.
- `q=0` makes that matching media range unacceptable; it is never preferred over a positive-quality alternative.
- Media-range parameters that appear before `q` constrain matching. A range such as `text/html;level=1` does not match the plain HTML representation. Parameters after `q` are accept extensions and do not constrain representation matching.
- Both generated text representations are UTF-8, so `charset=utf-8` is a matching media parameter.
- Specific media types outrank type wildcards, which outrank `*/*`; quality and original header order break ties within the same specificity.
- API routes advertise `GET, HEAD, OPTIONS`; non-API page routes advertise `GET, HEAD` and reject `OPTIONS` with 405.
- Negotiated page responses retain `Vary: Accept`.

## Consequences

The Worker performs deterministic local header parsing only. It does not inspect R2 contents to decide representation and does not add a 406 response path in this change. The fallback-to-HTML behavior is therefore an explicit compatibility contract rather than an inference from malformed or unsupported `Accept` values.

## Verification

The behavior is covered by helper tests and Worker integration tests, including quality values, wildcards, `q=0`, pre-`q` media parameters, post-`q` accept extensions, UTF-8 charset matching, negotiated content type, and route-specific `Allow` headers. Measured hosted-CI evidence is recorded in `docs/verification/2026-08-22-worker-http-contract.md`.
