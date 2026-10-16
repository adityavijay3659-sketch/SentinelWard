# Phase 6 — LinuxONE operator guide

You perform the remote steps. This guide and the tools do not create, log into or deploy
to a server automatically. Phase 7 handoff is separate. Keep your local source and evidence;
the server is disposable, with no promised persistence or backup. Do not put passwords,
private keys, raw recordings or tokens into chat, Git or screenshots.

## 1. Before the event: dummy practice only

Create your instance in the portal, save its IP, Linux username and SSH key locally, and
use the credentials provided by the portal. A key password prompt is handled locally.
Do not reuse the team leader's historical IP, username or private key. Replace placeholders
below with your own instance details; do not type the angle brackets literally.

From PowerShell:

```powershell
ssh -i '<local-private-key-path>' '<linux-user>@<your-instance-ip>'
```

Verify the SSH host fingerprint through the portal/administrator before accepting it.
Do not disable host-key verification. On Linux, these commands inspect the server only:

```bash
uname -m
cat /etc/os-release
python3 --version
lscpu
free -h
df -h "$HOME"
date -u
timedatectl show -p NTPSynchronized -p Timezone
```

Expect s390x if this is LinuxONE and Python 3.12 for this application. Record the actual
values; do not assume the team leader's earlier CPU/memory measurements apply to yours.
If Python is not 3.12 or time is unsynchronized, resolve that prerequisite first.

Optional dummy practice, still without project code:

```bash
practice_dir=$(mktemp -d "$HOME/sentinel-practice.XXXXXX")
python3 -c 'import json,platform; print(json.dumps({"dummy": True, "machine": platform.machine()}))'
printf 'Practice only: %s\n' "$practice_dir"
```

Do not upload SentinelWard before the announced event start. These instructions authorize
no project deployment before that time. Package installation and project steps below are
for the permitted event period, on your own disposable instance.

## 2. Preserve the actual local source before transfer

Use the current checkout, not a GitHub archive that would omit uncommitted Phase 5/6 files.
Run from `C:\Users\Aditya\SentinelWard`, using a **new** output directory on D: each time:

```powershell
$phase6Python = 'D:\SentinelWard-Phase2-Venv\Scripts\python.exe'
& $phase6Python -B -m tools.phase6_acceptance preflight --c1-source 'C:\Users\Aditya\SentinelWard-M6-Readiness-20261012-01\research\candidates\m6_readiness_candidate.py'
& $phase6Python -B -m tools.phase6_acceptance snapshot --output 'D:\SentinelWard-Phase6\transfer-01'
Get-FileHash -Algorithm SHA256 -LiteralPath 'D:\SentinelWard-Phase6\transfer-01\sentinelward-phase6-source.tar.gz'
```

Preflight must say PASS, Python 3.12, expected imported source and M6 hash. Snapshot includes
current authorized source, fixtures, docs/tests/tools and the lockfile. It excludes .git,
environments, datasets and out-of-scope root files. The key-marker check is not a complete
secret scanner: review `source-manifest.json`, run the project's credential review, and
inspect the archive file list before transfer. Do not include a private `.env`.

After the event permits project execution, transfer only the reviewed archive and manifest:

```powershell
scp -i '<local-private-key-path>' 'D:\SentinelWard-Phase6\transfer-01\sentinelward-phase6-source.tar.gz' 'D:\SentinelWard-Phase6\transfer-01\source-manifest.json' '<linux-user>@<your-instance-ip>:~/'
```

Do not delete the local archive or original checkout after transfer. C1 is outside this
archive and must stay outside the production deployment.

## 3. Install into a new isolated Linux test directory

The commands assume Ubuntu with apt and sudo on your disposable server. Stop if the OS
differs; do not guess package substitutions or alter a shared host.

```bash
umask 077
sha256sum "$HOME/sentinelward-phase6-source.tar.gz"
# Compare with the locally recorded SHA-256 before extracting.
mkdir "$HOME/sentinelward-phase6"
tar -tzf "$HOME/sentinelward-phase6-source.tar.gz"
tar -xzf "$HOME/sentinelward-phase6-source.tar.gz" -C "$HOME/sentinelward-phase6"
cd "$HOME/sentinelward-phase6"
sudo apt-get update
sudo apt-get install python3.12-venv python3.12-dev build-essential libpq-dev postgresql postgresql-client mosquitto mosquitto-clients git
python3.12 -m venv .venv
.venv/bin/python -m pip install uv
.venv/bin/uv sync --frozen --extra dev
.venv/bin/python -c 'import sentinelward.m6 as m; print(m.__file__); print(m.MODEL_VERSION); print(m.M6Config().model_dump())'
.venv/bin/python -m tools.phase6_acceptance check-snapshot --manifest "$HOME/source-manifest.json"
```

The lockfile controls project dependencies. Record uv, Python and installed package versions:

```bash
.venv/bin/uv --version
.venv/bin/python --version
.venv/bin/python -m pip freeze > "$HOME/phase6-installed-packages.txt"
```

If `pip` is absent in uv's environment, use `.venv/bin/uv pip freeze` instead. Some s390x
dependencies compile from source. Preserve failure output and stop on incompatibility;
do not silently unpin requirements. The optional offline forest tests need scikit-learn;
do not launch research training to resolve a missing dependency. Missing optional-package
tests remain visible in JUnit and block a claim that the *entire* suite passed remotely.

The source archive deliberately has no `.git`; initialize a local-only metadata repository
so the source-checkout tools can inventory it. This does not push or recreate original history:

```bash
git init
git add .
git -c user.name='Phase6 local snapshot' -c user.email='phase6@example.invalid' commit -m 'Imported reviewed Phase 6 snapshot'
```

Compare the original manifest's per-file hashes, not this new commit ID, to establish source
identity. The source manifest remains outside the checkout. Never add private runtime files.

## 4. Create private test database and broker

The runner refuses shared database names. Use a new identifier, not an existing DB:

```bash
sudo -u postgres createuser --pwprompt sentinel_phase6
sudo -u postgres createdb --owner=sentinel_phase6 sentinel_phase6_event01
mkdir -p "$HOME/phase6-private" "$HOME/phase6-evidence"
chmod 700 "$HOME/phase6-private" "$HOME/phase6-evidence"
```

Set `SENTINEL_TEST_DATABASE_URL` privately to
`postgresql://sentinel_phase6:<URL-encoded-password>@127.0.0.1:5432/sentinel_phase6_event01`.
Use an editor in `~/phase6-private/environment.sh`; avoid entering secrets as shell commands
saved in history. That file must contain `export` assignments and have mode 600. Include
`SENTINEL_DATABASE_URL` with the same value and `LANGGRAPH_STRICT_MSGPACK=true`.
An instance-local PostgreSQL server is still shared infrastructure: do not stop its service
for fault tests. Use a separately owned cluster/process if a server-stop test is required.

Find the installed Dynamic Security plugin, without assuming a Windows or x86 path:

```bash
dpkg -L mosquitto | grep mosquitto_dynamic_security
```

It must resolve to an actual `.so`. The existing lab tool expects binary and plugin in
one directory; create private symlinks to the actual installed paths:

```bash
mkdir "$HOME/phase6-private/broker-bin"
ln -s "$(command -v mosquitto)" "$HOME/phase6-private/broker-bin/mosquitto"
# Replace /actual/path/... below with the inspected plugin path.
ln -s /actual/path/mosquitto_dynamic_security.so "$HOME/phase6-private/broker-bin/mosquitto_dynamic_security.so"
.venv/bin/python tools/phase4_lab.py start --root "$HOME/phase6-private/broker" --broker-bin "$HOME/phase6-private/broker-bin" --port 18883
```

This starts a separate loopback broker, creates lab-only ACLs/credentials, and does not
replace `/etc/mosquitto` or enable a new service. Inspect its private broker log if it fails.
Set `SENTINEL_TEST_PHASE4_CONFIG=$HOME/phase6-private/broker/runtime.json` in the private
environment file. Source it with `source "$HOME/phase6-private/environment.sh"`.

The generated inventory has three beds and is for regression tests, not twelve-bed connected
acceptance. The actual team broker/inventory must be supplied by its owner. Do not extend
ACLs or invent team credentials to pretend these are equivalent.

## 5. Run isolated verification and actual service startup

No actual Telegram is needed. Keep `SENTINEL_EXTERNAL_EFFECT_MODE=simulate` and do not set
Telegram bot credentials. Use a fresh output directory for every run:

```bash
.venv/bin/python -m tools.phase6_acceptance preflight
.venv/bin/python -m tools.phase6_acceptance verify --isolated-resources --output "$HOME/phase6-evidence/verification-01"
```

The runner applies migrations through the current head/checkpointer, runs Ruff/format,
strict mypy and full pytest. It uses fresh scratch paths under its output. It never
automatically resets a service or deletes a database. Exit 0=PASS, 2=FAIL, 3=BLOCKED/NOT RUN.
Read `summary.json`, private logs and JUnit. A missing VitalDB fixture remotely is NOT RUN/
BLOCKED, not evidence of a software regression. Existing authorized local recording tests
are retained separately. Do not upload real recordings without permission; dummy-only
LinuxONE restrictions take precedence. Do not replace unavailable subject 1030.

For startup, generate private fictional settings, bound staff credentials and matching
contexts from the inspected three-bed lab inventory. The generator keeps `writer=null`,
sets roster expiry to 24 hours and supplies a private service token. Regenerate in a fresh
directory if it expires. It starts no services and prints no secrets:

```bash
.venv/bin/python -m tools.phase6_acceptance init-profile --phase4 "$HOME/phase6-private/broker/runtime.json" --output "$HOME/phase6-private/profile-01"
source "$HOME/phase6-private/profile-01/environment.sh"
```

This profile is for reference startup only. HTTP remains loopback, environment `test`,
M6/demo enabled, and external effects simulated. See [Phase 5 runbook](phase-5-runbook.md)
for each setting's meaning. Then:

```bash
.venv/bin/python -m sentinelward validate-config
.venv/bin/python tools/phase5_smoke.py --root "$HOME/phase6-evidence/startup-01" --phase4 "$HOME/phase6-private/broker/runtime.json" --phase5 "$HOME/phase6-private/profile-01/phase5.json" --database "$SENTINEL_TEST_DATABASE_URL"
```

Expected: actual CLI child starts; unauthenticated internal access 401, authenticated 200,
nurse briefing read 200; owned child stops. This proves local reference startup, not teammate
backend/UI behavior. Run `python -m sentinelward serve` in a dedicated terminal when inspecting
the service manually. Use Ctrl+C to stop your own foreground service.

## 6. Connect the real team stack and observe

Before the twenty-minute test, obtain actual owner components and matching run identity:

| Owner | Required before connected acceptance |
|---|---|
| Backend | Real sessions/roster, API/WS, request grants, run/revision rejection, current generation job status |
| Simulator/attack | Declared assets, admission/end timing, reset, current-run identity and event logs |
| Models/decision | Actual M1–M5 and D outputs; never substitute a scripted verdict and claim model validation |
| Kartik | A2/A3/A4 adapters, scoped broker control/session cleanup, evidence and undo |
| Frontend | Actual rendered bed/alert/report/briefing states and authenticated controls |
| Deployment | TLS/ACLs, synchronized clocks, one active service leader, private configuration |

The current config factory intentionally builds local reference ports. Do not simply point
its URLs at the team stack and call it integrated. Actual injected ports and teammate-owned
routes must be verified by their owners. Missing integration is BLOCKED.

Copy `fixtures/phase6-observer.example.json` outside Git and edit actual run ID, observer
broker identity, TLS/CA, probe URLs and process IDs. The example uses the real internal
`/internal/v1/demo/status` path; add actual backend GET APIs only after confirming their
ownership/authentication. No invented public response schema. Use a least-privilege
read-only observer account on the team broker, not an admin/device identity. Load password
and bearer values into the named environment variables privately.

```bash
.venv/bin/python -m tools.phase6_acceptance evidence-template --output "$HOME/phase6-evidence/connected-01"
.venv/bin/python -m tools.phase6_observe --config "$HOME/phase6-private/observer.json" --output "$HOME/phase6-evidence/connected-01/observer"
```

Template creation exits 3 because nothing has run; that is expected. Start observation first,
wait for `OBSERVER_READY`, then start the declared run promptly in another terminal/the UI.
The default 1260 seconds provides one minute of setup margin; if the entire 1200-second run
is not captured, retain the incomplete attempt and repeat in a fresh directory. Observer
collects only metadata/hashes and read-only probes, not raw data or backend field assertions.
It never starts/resets the demo. A successful observer is not successful acceptance.

Use `fixtures/phase6-scenario.json` and the
[team smoke checklist](demo-v1.1-team-smoke-test.md) for the actual sequence:

1. RESET then RUN with fresh run/episodes; capture MQTT, DB and API/WS identity.
2. Confirm admitted beds live; B04/B07 are not prematurely shown as normal admitted patients.
3. Observe all eight actual verdict routes across the golden run plus separate owner-declared
   route cases if the run does not produce every verdict. Record which were scripted contracts.
4. Exercise A1 screen ACK/escalation with simulated Telegram and bound actor identity.
5. At B03/B04/B07 source completion, verify OFFLINE + last values + `offline_since` in DB,
   actual API, WebSocket and UI. An active urgent alert must survive recording end.
6. Verify actual containment/evidence/undo; confirm A5 as IT before drafting/review. Human
   attestation records a fictional send; no real report is sent. Check A7 boundary and T+19 A8.
7. Hold an old-run M6 score and A5/A7/A8 record at an owner-controlled test delivery boundary.
   After reset/new run, release them. Backend must reject old identities before current bed,
   alerts, decisions, record replacement and WS/UI projection. A wire observer alone cannot
   prove this rejection; retain backend decision/audit evidence.
8. RESET and start a second run; verify fresh episode IDs, cleared baseline/pressure/PH/agent
   active state, no old timers/jobs, and preserved historical audit/report attestations.

Use declared dummy demo data only on LinuxONE unless the organizer permits the official
recording assets. Unavailable assets remain blockers. Do not tune M6 to make the scenario
pass. Beds 3/4/7 have 330 seconds of actual recording each; none supports the fresh 900-second
baseline. Partial cuff-gap outputs must say partial/research; other beds do not guarantee
readiness merely by lasting longer. C1 is never deployed in this test.

## 7. Separate failure and performance runs

Keep the clean 20-minute run separate from failure-injection runs. Record exact resources
and operator commands in private evidence. Do not kill unknown PIDs or stop shared systemd
services. Do not run generic stop scripts against stale Linux PID receipts; inspect executable
and command ownership first. Stop only the foreground process or child you started.

| Case | Operator action on owned isolated resources | Required observation |
|---|---|---|
| DB unavailable | Stop only your dedicated test cluster, or deny its dedicated test connection | New mutations fail unhealthy; no fabricated successful actions; recover with history intact |
| Broker disconnect/reconnect | Stop/restart only your private broker, with identity verified | No invented missed scores; durable outbox retries without duplicate effects |
| Backend failure | Owner supplies a failing test endpoint/proxy | Persistent failure/outbox state; no acknowledged-success claim |
| Broker control failure | Owner denies the test control operation | A1 urgent stays active; isolation is failed/unknown, never falsely successful |
| Simulated Telegram failure | Existing fake notifier regression | Screen alert survives; retry/ACK state remains deterministic |
| Restart in escalation/approval | Stop/restart only your service during an active test case | Original deadline and one effect; no duplicated human approval/send |
| Granite unavailable/late/reset | Optional isolated writer profile only | Template, preserved review/PDF and retired stale generation; urgent independent |
| Invalid role/prompt/message | Existing bounded fixtures against isolated endpoints | Rejection/audit; no unauthorized effect, schema mutation or prose execution |

Record start/end times, outcome, repeat counts and hashes for each case. A full-system fault
not executed is BLOCKED even if a corresponding local unit test passed.

For full-stack load, collect producer `runs/<run_id>/events.jsonl` files with the locked
`run_id,t_s,ts,bed_id,event,detail` contract. Preserve each producer separately. Correlate
source event → actual model/verdict, verdict receipt → persisted/published action, and
backend/API → UI visibility separately. Use synchronized UTC clocks and flag skew.

Compute expected vitals counts from the actual admitted/source-active seconds, not 12×1200.
QoS0 losses, duplicate QoS1 deliveries and deduplicated effects are distinct denominators.
Report p50/p95/max with sample count and unobserved/failed events. Missing evidence is unknown,
not zero delay or prevented false alerts. Inspect observer queue loss, source seq gaps,
broker/service outbox growth, errors, CPU/RSS/memory and process start IDs across restart.
Observer resource ticks need time-difference normalization; they are not CPU percentages.
The observer's HTTP response time is not model detection or screen rendering latency.

For reproducible capture diagnostics, retain the actual simulator/attacker event logs and run:

```bash
.venv/bin/python -m tools.phase6_metrics --observer "$HOME/phase6-evidence/connected-01/observer" --events /actual/simulator/runs/current-run/events.jsonl /actual/attacker/runs/current-run/events.jsonl --output "$HOME/phase6-evidence/connected-01/metrics"
```

Replace the event paths with the real files for the declared run. Do not fabricate missing
producer logs. The tool requires one unambiguous `run_start` at `t_s=0`, verifies observer
file hashes, reports per-bed source-second coverage and duplicate/out-of-order receipts,
deduplicates M6 window receipts, retains unavailable labels, and summarizes window-end to
score-receipt and HTTP response times. p95 uses nearest rank. Expected vitals frames are
11,790 for the declared joins/ends, not 14,400. Unobserved seconds are not automatically
classified as network loss. PASS means capture diagnostics completed, not scenario success.
Detailed event-to-decision/action/UI targets still need correlated owner evidence.

Documented scenario targets are generally 15 seconds for verdicts and 30 seconds from a
relevant cuff event, with tighter individual targets in Doc 12. Thirty-second A1 escalation
is a separate automation clock. Keep exact original targets and failures; do not reinterpret
frozen M6 insufficiency as a passing drift target. No clinical accuracy metrics.

Templates are the required default. If explicitly testing optional Granite, verify a compatible
s390x build/model and artifact hashes first; do not assume the Windows GGUF works on a
big-endian host. Keep the same approved model/parameters, 45/120-second deadlines and
512-token cap. Run existing strict workflow acceptance separately from resilience fallback.
Compare three alternating template/model full-stack pairs under the same source workload,
record raw latencies/resource measures, and retain the existing ≤10% p95 impact gate.
If that gate or deadlines fail, disable the writer; do not tune/retrain or claim deployment
acceptance from earlier laptop results. If no compatible approved artifact is available,
keep Granite disabled and mark that target gate NOT RUN.

## 8. Complete the evidence checklist and bring results home

Edit `connected-01/connected-evidence.json`: actual run ID, whether Granite was enabled,
and each gate's PASS/FAIL/BLOCKED/NOT RUN, explanation and evidence references. Never delete
a gate. Each PASS needs files inside `connected-01` with matching SHA-256. Example receipt:

```json
{"path":"backend/stale-score-rejection.txt","sha256":"<actual 64-character digest>"}
```

Include sufficient scenario-specific MQTT/DB/API/WS/UI/log evidence to support the assertion;
a health response or one screenshot cannot prove all gates. Use `sha256sum <file>` for the
actual hash. Keep historical attempts, missing-field qualifications and failure evidence.

```bash
.venv/bin/python -m tools.phase6_acceptance assess --evidence "$HOME/phase6-evidence/connected-01/connected-evidence.json" > "$HOME/phase6-evidence/connected-01/assessment.json"
```

Exit 0 means all required **operator-reported** gates have retained, hash-matching evidence.
It is not an independent remote audit; human review of evidence is still required. Exit 2
means failed/invalid evidence; 3 means incomplete. Real Telegram must stay NOT RUN.

Before teardown, review/sanitize logs and gather evidence without credentials, payloads or
data. Where export is permitted, copy your reviewed evidence to Windows:

```powershell
scp -r -i '<local-private-key-path>' '<linux-user>@<your-instance-ip>:~/phase6-evidence' 'D:\SentinelWard-Phase6\linuxone-evidence-01'
```

Verify local files and their checksums before any instance deletion. If download/export is
not supported, copy permitted sanitized textual results manually, retain screenshots where
permitted, and mark inaccessible artifacts as missing; this can leave acceptance BLOCKED.
Do not assume a server snapshot or backup exists. Preserve the authoritative local code.

Share the sanitized summary, JUnit counts, failures/skips, architecture/dependency versions,
source hashes and owner-blocker list for interpretation. Do not paste private logs wholesale.
Phase 6 completes only when critical actual connected evidence passes. Full live phone
acceptance remains open; final handoff/submission belongs to Phase 7.
