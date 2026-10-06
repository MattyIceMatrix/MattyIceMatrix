# Open-source contributions

Where my work shows up outside my own repositories, and who has contributed to mine.
Statuses are as of **6 October 2026** unless a later date is given.

Most of this work comes out of **[VLC-1](https://github.com/MattyIceMatrix/vlc-1)**
([DOI 10.5281/zenodo.22728393](https://doi.org/10.5281/zenodo.22728393)), an open
specification and conformance checker for proving that an AI audit log is
**complete**, not just tamper-evident. It scores a log from L0 to L5 by what a
verifier can prove from the log alone: that nothing was dropped, reordered,
rewritten or silently left out, and that refusals are recorded as refusals.

---

## 1. Upstream reports: AI and MCP gateways

On **29 September 2026** I installed six AI/MCP gateways, ran each one with its
audit logging switched on, sent allowed and refused tool calls
through it, and scored the resulting log with VLC-1. Every report went upstream
with the exact run, what the log showed, and a proposed fix. The full captures
are in [`vlc-1/examples/third-party/gateways-live`](https://github.com/MattyIceMatrix/vlc-1/tree/main/examples/third-party/gateways-live)
and the scores in [`vlc-1/THIRD-PARTY.md`](https://github.com/MattyIceMatrix/vlc-1/blob/main/THIRD-PARTY.md).
Each is one live run of one version and configuration; none of the findings
below has been confirmed by the vendor unless stated.

| Project | Version | Report | Status |
|---|---|---|---|
| Maxim AI **Bifrost** | 2.2.3 | [maximhq/bifrost#7769](https://github.com/maximhq/bifrost/issues/7769) | ✅ **Fixed upstream** in [#7913](https://github.com/maximhq/bifrost/pull/7913), merged 2026-10-04 |
| **IBM ContextForge** | 1.0.11 | [IBM/mcp-context-forge#7063](https://github.com/IBM/mcp-context-forge/issues/7063) | Reported |
| **NVIDIA OpenShell** | 0.1.2 | [NVIDIA/OpenShell#3817](https://github.com/NVIDIA/OpenShell/issues/3817) | Reported |
| **agentgateway** (Linux Foundation) | 1.5.0 | [agentgateway/agentgateway#3710](https://github.com/agentgateway/agentgateway/issues/3710) | Reported |
| **Docker MCP Gateway** | v0.44.1 | [docker/mcp-gateway#591](https://github.com/docker/mcp-gateway/issues/591) | Reported |
| **Lasso MCP Gateway** | 1.2.1 | [lasso-security/mcp-gateway#32](https://github.com/lasso-security/mcp-gateway/issues/32) | Reported |

### Bifrost: unauthenticated deletion of tool logs ✅ fixed
- **Found:** with no admin authentication configured, `DELETE /api/mcp-logs`, on
  the same port that executes tools, removed the record of the caller's own
  refused call, and the dropped-write counter at `/api/logs/dropped` still read 0.
- **Credit:** of the gateways scored, Bifrost was the only one that recorded a
  refusal *as* a refusal, with the reason, and it keeps an out-of-band
  dropped-write counter.
- **Outcome:** [#7913](https://github.com/maximhq/bifrost/pull/7913) refuses the
  delete with HTTP 403 unless authenticated management access is configured, and
  #7769 was closed as completed. The report's two other suggestions (a tombstone or
  counter for deletions, an append-only mode) are not part of that change. Not yet
  re-tested against the fixed release.

### IBM ContextForge: refusals missing from the security tables
- With `AUDIT_TRAIL_ENABLED`, `PERMISSION_AUDIT_ENABLED` and
  `SECURITY_LOGGING_LEVEL=all`, a PII-plugin block appeared in
  `structured_log_entries` as an ERROR row ("invocation failed",
  `is_security_event` 0) plus a `POST /rpc - 200` row; a token-scope refusal left
  only `POST /rpc - 200`.
- `security_events` held eight authentication successes, one for each refused
  request, and neither refusal; `permission_audit_log` was empty. Both refusals
  appeared only in the plain-text log.

### NVIDIA OpenShell: a strong decision log without integrity or ordering
- **Credit:** every denial carried a reason, every allow named the rule that
  decided it, policy loads carried the policy version and full SHA-256, and the
  record was held outside the agent.
- **Found:** no integrity field, no sequence number and no drop accounting;
  7 of 75 adjacent lines out of timestamp order; decision lines did not carry the
  hash of the policy in force. Removing all six DENIED lines left a log that
  scored identically.

### agentgateway: a policy refusal looks like a missing tool
- **Credit:** every MCP request is logged with method, tool, session and status,
  and the log is held outside the agent.
- **Found:** a call refused by the `mcpAuthorization` rules is logged identically
  to a call to a tool that does not exist (same `Unknown tool` error, same HTTP
  400, no policy field). No integrity field or ordinal; configuration loaded
  without a hash.

### Docker MCP Gateway: a refused call logged like an executed one
- A call outside the `--tools` allow-list is logged as `Calling tool …`, the same
  line an executed call gets; a call refused by `--block-secrets` leaves a scan
  with no outcome. Refused and executed calls differ only by lines that are
  missing. No timestamps; according to the source, allowed/denied audit events go
  only to Docker Desktop.

### Lasso MCP Gateway: masked output stored as tool output
- The guardrail's masking is stored as if it were the tool's output, with no
  marker; a call that failed inside the gateway has no row; requests are not
  traced; the gateway writes wherever the agent's host tells it to.

---

## 2. Standards

| Body | Document | Contribution | Status |
|---|---|---|---|
| Linux Foundation Decentralized Trust | Proof-of-Control v0.1 | [LFDT-ProofOfControl/ov-poc-standard#89](https://github.com/LFDT-ProofOfControl/ov-poc-standard/issues/89), filed 2026-09-30 | Open; public comments close 2026-10-30 |

The draft's C7.6 (Evidence Custody and Resilience) already asks for per-source
sequence numbers and anchoring. The comment proposes three Level 2 additions taken
from VLC-1: start and end records per source, in-band drop records, and refusals
recorded as refusals.

---

## 3. Independent review exchanges

- **[trustless-ai/recompute-kit#48](https://github.com/trustless-ai/recompute-kit/issues/48):**
  the thread where pipavlo82 and babyblueviper1 published independent reviews of
  VLC-1. The findings were fixed in VLC-1, and pipavlo82 checked the fixes against
  the repository tree itself, not against my account of them (2026-09-21).

---

## 4. Contributions to VLC-1 from others

Outside reviewers have found problems in VLC-1's specification and checker; every
one was confirmed and fixed, and each is written up in
[`FINDINGS-EXTERNAL.md`](https://github.com/MattyIceMatrix/vlc-1/blob/main/FINDINGS-EXTERNAL.md)
with the reporter credited.

| Contributor | Findings | Summary |
|---|---|---|
| **Shahab K.** | EXT-001, EXT-002 (2026-09-13) | A coverage declaration could raise the structural level; L2 loss accounting assumed the producer survives its own outage. |
| **pipavlo82** (trustless-ai) | EXT-003 – EXT-008 (2026-09-21), EXT-015, EXT-016 (2026-09-22) | Completeness identity over the wrong record class, presence-instead-of-type checks, a manifest that could fail open, L1 wording, witness and unmapped-tool gaps. |
| **babyblueviper1** (invinoveritas) | EXT-009 – EXT-012, EXT-017 | Silent loss accepted in ordinal mode, duplicate member names, a crashing input line, a CI check that could never fail, re-rooting. Most were fixed by the reporter in [vlc-1#2](https://github.com/MattyIceMatrix/vlc-1/pull/2) and [vlc-1#3](https://github.com/MattyIceMatrix/vlc-1/pull/3). |
| **ogasurfproject-jpg** (JIDEC / Horizon Shield) | EXT-022 follow-up | Bound their ledger's end marker so it scores L1 on the log alone ([vlc-1#12](https://github.com/MattyIceMatrix/vlc-1/pull/12)); the Bitcoin-stamped n 65 head is now checked in VLC-1's CI ([vlc-1#22](https://github.com/MattyIceMatrix/vlc-1/pull/22)). |

My own audits of VLC-1 (EXT-018, EXT-019) are recorded in the same file.

---

*Corrections welcome. Open an issue on [VLC-1](https://github.com/MattyIceMatrix/vlc-1/issues).*
