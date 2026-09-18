# openshift-tests on TNF — User Guide

This guide is for engineers who want to **run** the `openshift-tests` e2e suite
(recovery, DualReplica, cert-rotation, conformance, upgrade) against a Two-Node
OpenShift with Fencing (TNF) cluster and collect diagnostics while it runs. If
you want to change or extend the scripts, read the
[Developer Guide](DEVELOPER-GUIDE.md) instead.

All paths below are relative to `openshift-tests/` unless stated otherwise.

## 1. What you get

| Need | Script |
|------|--------|
| Get an `openshift-tests` binary that matches the cluster | `scripts/extract-tests-binary.sh` |
| See which tests a suite/profile contains | `scripts/list-tests.sh` |
| Run a whole suite (batch or interactive) | `scripts/run-suite.sh` |
| Run one or a few named tests, optionally many times | `scripts/run-test.sh` |
| Collect cluster-side logs while a test runs | `scripts/run-all-captures.sh` / `scripts/stop-all-captures.sh` |
| Check results | `scripts/check-latest-run.sh`, `scripts/check-test-result.sh`, `scripts/summarize-all-runs.sh` |
| Verify both masters run the same `resource-agents` build | `scripts/gather-resource-agent-versions.sh` |
| Free disk space | `scripts/clean-test-runs.sh` |

Every runner writes into `runs/` (git-ignored). Nothing here is committed.

## 2. Prerequisites

### Cluster

A deployed TNF cluster from
[two-node-toolbox](https://github.com/openshift-eng/two-node-toolbox). The
toolbox writes a `proxy.env` file next to the cluster's `KUBECONFIG`, normally at
`<two-node-toolbox>/deploy/openshift-clusters/proxy.env`. That file exports:

- `KUBECONFIG`
- `HTTP_PROXY` / `HTTPS_PROXY` (Squid on the hypervisor)
- `EC2_PUBLIC_IP` (the hypervisor's public address)

The scripts source it to reach both the API (through the proxy) and the
hypervisor (over SSH).

### Local tools

| Tool | Used by |
|------|---------|
| `oc` | binary extraction, test discovery, all `oc logs` captures |
| `ssh` | hypervisor and master captures, resource-agents check |
| `jq` | `capture-update-setup-job.sh` |
| `bc` | `clean-test-runs.sh` size report |
| `rg` (optional) | faster `--stop-on-match`; falls back to `grep` |
| `column` | `gather-resource-agent-versions.sh` output |

### SSH access

Captures and the resource-agents check reach the masters by nested SSH:
your machine → hypervisor (`ec2-user`) → master (`core`). Your key must be
accepted by both hops. The default key is `~/.ssh/id_redhat`; if that file does
not exist the scripts fall back to `~/.ssh/id_ed25519`.

## 3. Environment variables

Only one variable is mandatory. The scripts fail fast with a message naming the
variable when it is missing.

| Variable | Required | Default | Meaning |
|----------|----------|---------|---------|
| `PROXY_ENV` | **yes** | — | Path to the cluster's `proxy.env`. |
| `HYPERVISOR_IP` | no | `EC2_PUBLIC_IP` from `proxy.env` | Hypervisor address for SSH and `virsh`. |
| `SSH_USER` | no | `ec2-user` | Hypervisor SSH user. |
| `SSH_KEY_PATH` | no | `~/.ssh/id_redhat`, else `~/.ssh/id_ed25519` | Key for both SSH hops. |
| `MASTER_SSH_USER` | no | `core` | User on the masters. |
| `MASTER_0_IP`, `MASTER_1_IP` | no | resolved from `virsh net-dhcp-leases` | Override master addresses if DHCP lookup fails. |
| `VIRSH_LEASE_NETWORK` | no | `ostestbm` | libvirt network queried for master leases. |
| `OPENSHIFT_TESTS` | no | `tests-bin/openshift-tests` | Explicit path to the test binary. |
| `UPGRADE_TO_IMAGE` | upgrade profile | — | Target release image (same as `--to-image`). |
| `TEST_TIMEOUT` | no | `60m` | Per-run `openshift-tests --timeout` for `run-test.sh`. |
| `STOP_ON_MATCH` | no | — | Same as `--stop-on-match` for `run-test.sh`. |
| `POLL_SEC`, `MIN_NODES` | no | `900`, `2` | `--wait-for-cluster` polling interval and node count. |
| `OPENSHIFT_TESTS_DISABLE_MONITORS` | no | CI default (see below) | Comma list passed as `--disable-monitor=`. Set empty to disable none. |
| `OPENSHIFT_TESTS_CLUSTER_STABILITY` | no | `Disruptive` | Passed as `--cluster-stability=`. |
| `OPENSHIFT_TESTS_EXTRA_ARGS` | no | — | Extra flags appended verbatim. At most two `--monitor` entries. |
| `PATCHED_RA_MARKER` | no | — | Substring identifying a patched `resource-agents` build (see §9). |

The monitor defaults mirror the openshift/release CI workflow
`baremetalds-two-node-fencing-recovery`:

```text
OPENSHIFT_TESTS_DISABLE_MONITORS=etcd-log-analyzer,legacy-cvo-invariants,legacy-etcd-invariants,node-lifecycle,oc-adm-upgrade-status
OPENSHIFT_TESTS_CLUSTER_STABILITY=Disruptive
```

Do **not** enable every `openshift-tests --monitor` on TNF. It is the wrong tool
for two-node clusters and has crashed runs. `run-test.sh` refuses more than two
`--monitor` flags in `OPENSHIFT_TESTS_EXTRA_ARGS`. For operational context use
the capture scripts (§7), which are unrelated to monitors.

## 4. First-time setup

```bash
cd openshift-tests
export PROXY_ENV=<two-node-toolbox>/deploy/openshift-clusters/proxy.env

# 1. Pull the openshift-tests binary that matches the running cluster payload.
scripts/extract-tests-binary.sh          # writes tests-bin/openshift-tests

# 2. Sanity-check discovery.
scripts/list-tests.sh --profile recovery
```

`extract-tests-binary.sh` reads the cluster's `ClusterVersion`, resolves the
`tests` image of that release, extracts `/usr/bin/openshift-tests` into
`tests-bin/`, and compares the binary's version string with the cluster
version. If a binary already exists it asks before replacing it and keeps a
`.bak` until the new one is verified.

Binary lookup order for `run-suite.sh` and `list-tests.sh`:

1. `$OPENSHIFT_TESTS`
2. `tests-bin/openshift-tests`
3. `~/.cache/openshift-tests/openshift-tests`

`run-test.sh` only checks the first two.

If you build `openshift-tests` yourself from origin (`make openshift-tests`),
copy it into `tests-bin/` or point `OPENSHIFT_TESTS` at it.

## 5. Profiles

A profile is a short name that picks a suite, an optional name filter, and a run
mode. Both `list-tests.sh` and `run-suite.sh` accept `--profile`. Explicit
`--suite` / `--filter` always override the profile's values.

| Profile | Suite run | Filter / notes |
|---------|-----------|----------------|
| `recovery` | `openshift/two-node` | All recovery tests including node replacement. Reports `resource-agents` versions afterwards. |
| `ra-verification` | `all`, pinned to the union of `openshift/etcd/certrotation` + `openshift/two-node` | **Excludes** node replacement so no master is reprovisioned and both keep the same `resource-agents` build. Reports versions afterwards. |
| `dualreplica` | `all` | Filtered to `DualReplica` (`[OCPFeatureGate:DualReplica]`), wherever those tests live. |
| `cert-rotation` | `openshift/etcd/certrotation` | Verify the suite name once against your cluster. |
| `e2e` | `openshift/conformance/parallel` | Full conformance. |
| `upgrade` | `all` via `openshift-tests run-upgrade` | Needs `--to-image` or `UPGRADE_TO_IMAGE`. No discrete test list. |

`scripts/run-suite.sh --list-profiles` prints the live list.

To see exactly what a profile will run, prefer `run-suite.sh --profile X
--list-only` over `list-tests.sh --profile X`: only `run-suite.sh` applies a
profile's multi-suite discovery and exclusions (this matters for
`ra-verification`).

## 6. Running tests

### 6.1 Whole suite: `run-suite.sh`

```bash
# Batch (default): one openshift-tests invocation runs the whole suite
scripts/run-suite.sh --profile recovery

# Same, with cluster-side captures for the duration of the run
scripts/run-suite.sh --profile recovery --with-captures

# Resource-agents verification without node replacement
scripts/run-suite.sh --profile ra-verification

# Repeat the entire suite three times (three sequential invocations)
scripts/run-suite.sh --profile recovery --repeat 3

# Interactive: confirm before each test, review after each
scripts/run-suite.sh --profile recovery --interactive --with-captures

# Upgrade
scripts/run-suite.sh --profile upgrade --to-image quay.io/openshift-release-dev/ocp-release:4.20.0-x86_64

# Ad hoc suite + regex filter, no profile
scripts/run-suite.sh --suite openshift/conformance/parallel --filter 'etcd'

# Preview only
scripts/run-suite.sh --profile ra-verification --list-only
```

Options:

| Flag | Meaning |
|------|---------|
| `--profile NAME` | Profile from §5. |
| `--suite SUITE` | Suite to run (default `openshift/two-node`). |
| `--filter REGEX` | Case-insensitive regex on test names (default `.`). |
| `--to-image IMAGE` | Target release for the `upgrade` profile. |
| `--repeat N` | Batch: run the suite N times. Interactive: run each test N times. |
| `--with-captures` / `--no-captures` | Start captures per iteration. **Default: off.** |
| `--interactive` | Prompt `[Y/n/q]` before each test and after each test. |
| `--list-only` | Print the resolved test list and exit. |
| `--name NAME` | Session directory prefix (default `<profile>-suite` or `<suite>-suite`). |

Behaviour worth knowing:

- **Batch mode runs the suite in one `openshift-tests` process** (`--max-parallel-tests=1`, `--timeout=60m`).
  Test order is whatever origin chooses; when a profile pins a curated set via
  `--file`, origin still shuffles that set with a fixed seed. You cannot force
  "node replacement last", which is why `ra-verification` excludes it instead.
- **Interactive mode delegates each test to `run-test.sh`**, so tests run in
  alphabetical order, one process per test, and all land in a single session
  directory.
- Discovery aborts if a suite returns zero tests (typo protection) and, for
  pinned sets, does a `--dry-run` pre-flight to confirm every name round-trips
  through `--file` before committing to a long run.
- `recovery` and `ra-verification` end by calling
  `gather-resource-agent-versions.sh` (§9). A failure there never fails the run.

### 6.2 Named tests: `run-test.sh`

`run-test.sh` always runs the `openshift/two-node` suite and narrows it with
`--run`. Use it for one test, a hand-picked list, or soak loops.

```bash
# Default: the node-replacement test, once, with captures
scripts/run-test.sh

# Named test, five times, stop when a known symptom shows up in the log
scripts/run-test.sh \
  --test "etcd recovery should recover from network disruption with etcd member re-addition" \
  --repeat 5 \
  --stop-on-match "timed out waiting for the learner to be promoted"

# Stop as soon as the focused test itself fails (ignores monitor-only failures)
scripts/run-test.sh --test "recovery restore quorum" --repeat 10 --stop-on-fail --no-captures

# All recovery tests, three iterations, no captures
scripts/run-test.sh $(scripts/list-tests.sh --profile recovery --command-line) --repeat 3 --no-captures

# Block until the cluster is Ready (after an install/upgrade), then run
scripts/run-test.sh --wait-for-cluster
```

Options:

| Flag | Meaning |
|------|---------|
| `--test "<focus>"` | Substring of a test name; repeatable. Regex metacharacters are escaped for you. Default: the node-replacement test. |
| `--repeat N` | Repeat the whole list N times (default 1). |
| `--timeout DURATION` | `openshift-tests --timeout` per run (default `60m`). |
| `--name LABEL` | Session directory prefix (default `tnf-two-node`). |
| `--stop-on-match "text"` | After each run, stop if the test log contains this literal text. |
| `--stop-on-fail` | Stop when the focused test reports failure in the log. |
| `--with-captures` / `--no-captures` | **Default: on** (the opposite of `run-suite.sh`). |
| `--wait-for-cluster` | Poll every `POLL_SEC` until the API answers, `MIN_NODES` nodes are Ready, and `ClusterVersion` is Available. |

Behaviour worth knowing:

- **`--repeat 1` with several `--test` values is collapsed into one
  `openshift-tests` invocation** (patterns joined with `|`). In that mode
  `--stop-on-match` and `--stop-on-fail` are not evaluated because there is
  nothing to stop between. With `--repeat 2+` each test gets its own process.
- **Session directories are reused within a UTC day.** If a directory named
  `<name>-<today>-*` already exists in `runs/`, the run appends to it. That is
  how interactive suite runs group their tests, and it also means two unrelated
  `run-test.sh` invocations on the same day with the same `--name` share a
  session. Pass a distinct `--name` to keep them apart.
- The exit code of `openshift-tests` is recorded as `PASS` or `FAIL(<rc>)` in
  `summary.tsv`. A monitor or suite-level failure makes the run `FAIL` even if
  the focused test passed; `--stop-on-fail` looks for the per-test
  `failed: (` line instead, so it is not fooled by that.

### 6.3 What a run looks like

For the node-replacement test expect **20–30+ minutes** and a lot of transient
Pacemaker/etcd noise before pass/fail. Do not interrupt it. Rough phases:
destroy and fencing → quorum recovery → VM recreate → BareMetalHost/Machine
provisioning → settle. Successful runs print `[stage timing] …` lines in the
test log.

## 7. Captures (cluster-side diagnostics)

`run-all-captures.sh` starts a set of background collectors and records their
PIDs; `stop-all-captures.sh` kills them (by process group, then SIGKILL after
two seconds). The runners do both for you when captures are enabled. You can
also drive them by hand in a second terminal:

```bash
export PROXY_ENV=...
scripts/run-all-captures.sh          # prints one line per collector and the PID file
# ... run something in another terminal ...
scripts/stop-all-captures.sh         # newest capture-pids-*.txt directly under runs/
```

With no argument, `stop-all-captures.sh` only looks for PID files directly
under `runs/`, which is where hand-started captures put them. Captures started
by a runner keep their PID file in the run's `captures/` directory, so pass
that path explicitly if you ever need to stop them by hand.

What is collected (each in its own file, suffixed `-<timestamp>`):

| Collector | Source | Notes |
|-----------|--------|-------|
| `virsh` | `virsh list --all` on the hypervisor | Every 15 s (`VIRSH_POLL_INTERVAL`). |
| `pacemaker-master-{0,1}` | `tail -f /var/log/pacemaker/pacemaker.log` | Reconnects after the node reboots; re-resolves the DHCP lease. |
| `corosync-master-{0,1}` | `journalctl -u corosync -f` | Same reconnect logic. |
| `ovn-chassis-trace` | Node annotations, host OVS `system-id`, SB `Chassis` rows, `virsh dumpxml` summary, l3-gateway-config, NNID tail, grep'd ovnkube-node logs | High-frequency, timestamped; tune with `OVN_CHASSIS_*` (below). |
| `disruption-evidence` | `openshift-etcd` debug/fencing pods and events; `ip6tables` counters on both masters | Every 10 s (`DISRUPTION_EVIDENCE_POLL_SEC`). |
| `ovn-k-node-follow`, `ovn-k-cp-follow`, `nnid-follow` | `oc logs -f` for ovnkube-node (all), one ovnkube-control-plane, network-node-identity | Reconnect after pod churn. |
| `baremetal-operator` | `oc logs -f` on the BMO deployment | Auto-detects `metal3-baremetal-operator` vs `baremetal-operator`. |
| `ceo-<pod>` | `oc logs -f` for **every** etcd-operator pod incarnation, plus `--previous` on first sight | Survives reschedules; a plain `oc logs deployment/... -f` would not. |
| `machine-api-{mao,mac-controllers,cbo,capi-operator,...}` | `oc logs -f` per Machine API / CAPI deployment | Reconnects when the pod is replaced. |
| `machine-api-snapshot` | `Machine`, `BareMetalHost`, events, `clusteroperator/machine-api` | Every 60 s (`MACHINE_API_SNAPSHOT_POLL_SEC`). |
| `tnf-fencing-job-<pod>` | `oc logs -f` per `tnf-fencing-job-*` pod in `openshift-etcd` | Discovers new pods every 10 s. |
| `update-setup-job` | `tnf-update-setup-job` status, latest pod, relevant CEO log lines | Every 10 s (`UPDATE_SETUP_POLL_SEC`). |

Collectors that need the API are skipped with a note when `KUBECONFIG` is not
set; those that need a specific deployment are skipped when it is absent.

Tuning knobs for the chassis trace (sample counts, not seconds):

| Variable | Default | Every N samples… |
|----------|---------|------------------|
| `OVN_CHASSIS_POLL_INTERVAL_SEC` | `1` | base interval between samples |
| `OVN_CHASSIS_SB_EVERY` | `1` | query SB `Chassis` via `ovn-sbctl` |
| `OVN_CHASSIS_VIRSH_EVERY` | `10` | `virsh list` + per-VM uuid/disk/mac summary |
| `OVN_CHASSIS_IDENTITY_EVERY` | `10` | tail `network-node-identity` |
| `OVN_CHASSIS_L3GW_EVERY` | `20` | dump `k8s.ovn.org/l3-gateway-config` per node |
| `OVN_CHASSIS_TRACE_EXTRA_EVERY` | `15` | ovnkube-node pod table + filtered log tails |

To validate connectivity before a long run, take a single sample:

```bash
OVN_CHASSIS_ONCE=1 scripts/capture-ovn-chassis-trace.sh
```

Where files land: when started by a runner, `CAPTURE_LOG_DIR` points at the
run's `captures/` directory and most collectors write there. Two collectors
currently ignore that variable and always write their `.log` under
`scripts/debug/` (git-ignored): `capture-virsh-status.sh` and
`capture-baremetal-operator.sh`. Their console output still lands in the run's
`captures/*.out`. See the Developer Guide for the fix.

## 8. Results

### Layout

```text
runs/
└── recovery-suite-20260918-141500/          # session
    ├── summary.tsv
    ├── test-set.txt                          # only when a curated set was pinned via --file
    ├── iter-01-20260918-141500/              # run-suite batch: one dir per suite iteration
    │   ├── test/
    │   │   ├── openshift-tests-raw.log       # -o output from openshift-tests
    │   │   ├── openshift-tests-timestamped.log
    │   │   ├── runner.log
    │   │   └── junit/
    │   └── captures/                         # only with --with-captures
    │       ├── capture-pids-<ts>.txt
    │       ├── start-captures.log, stop-captures.log
    │       └── <collector>-<ts>.log / .out
    └── iter-01-test-01-<ts>-<test-slug>/     # run-test.sh / interactive: one dir per test
        └── (same structure)
```

`run-test.sh` with `--repeat 1` and several tests produces one
`iter-01-all-tests-<ts>/` directory instead, and it does not write
`openshift-tests-raw.log` (its "timestamped" log is the console output as
received, without added timestamps). Upgrade runs put `test/` directly under
the session directory.

`summary.tsv` columns: `iter`, `test_index` (or `ALL`), `result` (`PASS` or
`FAIL(rc)`), `run_dir`, `focus`.

### Inspecting

```bash
# Latest session: summary table plus pass/fail counts
scripts/check-latest-run.sh

# One run directory: file listing, last 50 log lines, junit highlights
scripts/check-test-result.sh runs/<session>/iter-01-test-01-*

# Every session: per-session counts and overall pass rate
scripts/summarize-all-runs.sh
```

**Known limitation:** `check-latest-run.sh` and `summarize-all-runs.sh` only look
at sessions named `openshift-two-node-suite-*`, which is the auto-generated name
when `run-suite.sh` is invoked without `--profile`. Sessions created with a
profile (`recovery-suite-*`) or by `run-test.sh` (`tnf-two-node-*`) are not
picked up. Until that is fixed, read `summary.tsv` directly:

```bash
column -t -s $'\t' runs/recovery-suite-*/summary.tsv
```

### Cleaning up

```bash
scripts/clean-test-runs.sh --keep 5             # preview, then confirm
scripts/clean-test-runs.sh --older-than 7d --force
scripts/clean-test-runs.sh --pattern 'tnf-two-node-*' --force
scripts/clean-test-runs.sh --all
```

The script prints what it will delete and the total size, and asks for
confirmation unless `--force` is given.

## 9. Mixed resource-agents builds

The node-replacement test reprovisions a master from the base image. If you had
layered a patched `resource-agents` RPM (the podman-etcd OCF agent fix) onto the
masters, the replaced node comes back on the **stock** RPM while the other keeps
the patch. That skew is what produced the dual `force-new-cluster` wedge, so
after any run that may have replaced a node, check:

```bash
scripts/gather-resource-agent-versions.sh
# or, for a definitive patched/stock verdict:
PATCHED_RA_MARKER=<substring unique to your build> scripts/gather-resource-agent-versions.sh
```

The script resolves both masters from the hypervisor's DHCP leases, runs
`rpm -q resource-agents` on each, and prints:

- `OK` when both report the same build.
- `NOTE ... mixed build` when they differ, with guidance. Different version
  strings are only a problem if one side is stock; with `PATCHED_RA_MARKER` set
  the script says `SAFE` or `WARNING` outright.

`run-suite.sh` calls this automatically at the end of `recovery` and
`ra-verification` runs. If you need to keep every node on the same build for the
whole run, use `ra-verification`, which never replaces a node.

## 10. Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| `PROXY_ENV must be set ...` | Export `PROXY_ENV` to your cluster's `proxy.env`. |
| `HYPERVISOR_IP is not set` | `proxy.env` lacks `EC2_PUBLIC_IP`; export `HYPERVISOR_IP` yourself. |
| `openshift-tests binary not found` | Run `scripts/extract-tests-binary.sh`, or set `OPENSHIFT_TESTS`. |
| `Version mismatch detected!` | Binary is from another payload; re-extract after an upgrade. Warning only. |
| `Discovered 0 tests in suite '<x>'` | Suite name typo. Check with `openshift-tests run <suite> --dry-run`. |
| `Pre-flight --file check matched N/M tests` | A discovered test is not in the run suite (use a superset such as `all`), or a quoting mismatch. The set file path is printed. |
| `Failed to load proxy.env - using dummy hypervisor config` (`list-tests.sh`) | Listing still works; only hypervisor-dependent discovery is affected. |
| `OPENSHIFT_TESTS_EXTRA_ARGS contains N '--monitor' flags` | Max two; use captures for context instead. |
| Pacemaker/corosync log has only `IP unresolved, retrying` | DHCP lease lookup on `ostestbm` failed. Set `MASTER_0_IP` / `MASTER_1_IP`, or `VIRSH_LEASE_NETWORK`. |
| `capture-ovn-chassis-trace: failed to resolve master IPs` | Same as above; this collector exits instead of retrying. |
| Captures still running after a run | `scripts/stop-all-captures.sh <pid-file>`; as a last resort `xargs kill < <pid-file>`. |
| `check-latest-run.sh` says `No runs found` | See §8: it only matches `openshift-two-node-suite-*`. |
| `No space left on device` | `scripts/clean-test-runs.sh --keep 3 --force`. Captures with a 1 s chassis poll grow fast. |
| Cluster unreachable while a test is running | Expected during fencing and node replacement; wait for the test to finish. |

### Cluster access by hand

```bash
set -a && source "$PROXY_ENV" && set +a
oc get nodes

# masters are on 192.168.111.x behind the hypervisor
ssh -i ~/.ssh/id_redhat -J "ec2-user@${EC2_PUBLIC_IP}" core@192.168.111.21
```

Source `proxy.env` and try `oc` before concluding the cluster is unreachable.
