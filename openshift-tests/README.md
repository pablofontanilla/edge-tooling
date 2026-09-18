# openshift-tests (Two-Node / TNF)

Scripts for running the `openshift-tests` e2e suite against Two-Node OpenShift
with Fencing (TNF) clusters, plus log-capture tooling for debugging
node-replacement, fencing, and network-disruption scenarios.

## Documentation

| Guide | Read it when you want to… |
|-------|---------------------------|
| [User Guide](docs/USER-GUIDE.md) | set up, run suites or single tests, collect captures, read results, troubleshoot |
| [Developer Guide](docs/DEVELOPER-GUIDE.md) | change the scripts: architecture, helper API, profile system, capture contract, known rough edges |
| [Cluster access + TNF runbook](docs/TNF-AND-CLUSTER.md) | reach the cluster and masters by hand; node-replacement runbook |
| [scripts/RECOVERY-TESTS-README.md](scripts/RECOVERY-TESTS-README.md) | original usage notes (kept for reference; the guides above supersede them) |

## Layout

| Path | Contents |
|------|----------|
| `scripts/` | Test runners, capture tooling, and result helpers |
| `docs/` | User guide, developer guide, cluster-access notes |
| `runs/` | Generated: one directory per session (git-ignored) |
| `tests-bin/` | Generated: extracted `openshift-tests` binary (git-ignored) |

## Prerequisites

- A deployed TNF cluster (via [two-node-toolbox](https://github.com/openshift-eng/two-node-toolbox)).
- `oc`, `ssh`, `jq` on your machine, and an SSH key accepted by the hypervisor
  and the masters.
- The `openshift-tests` binary — extract it from the cluster payload with
  `scripts/extract-tests-binary.sh` (writes to `tests-bin/`).

## Required environment

Set `PROXY_ENV` to your cluster's `proxy.env` (normally
`<two-node-toolbox>/deploy/openshift-clusters/proxy.env`). It is sourced for
`KUBECONFIG`, `HTTP(S)_PROXY`, and `EC2_PUBLIC_IP` (the hypervisor). If it is
unset the scripts exit immediately with a message naming the variable.

Everything else has a default. The full table is in the
[User Guide, §3](docs/USER-GUIDE.md#3-environment-variables).

## Profiles

`list-tests.sh` and `run-suite.sh` take `--profile NAME`. Explicit
`--suite`/`--filter` override the profile's defaults.

| Profile | Suite | Notes |
|---------|-------|-------|
| `recovery` | `openshift/two-node` | All recovery tests, including node replacement; reports `resource-agents` versions afterwards |
| `ra-verification` | `openshift/etcd/certrotation` + `openshift/two-node` | Excludes node replacement so both masters keep the same `resource-agents` build |
| `dualreplica` | `all`, filtered to `[OCPFeatureGate:DualReplica]` | Finds DualReplica tests in **any** suite |
| `cert-rotation` | `openshift/etcd/certrotation` | Verify suite name against cluster once |
| `e2e` | `openshift/conformance/parallel` | Full conformance |
| `upgrade` | `all`, via `run-upgrade` | Requires `--to-image` / `UPGRADE_TO_IMAGE` |

Run `scripts/run-suite.sh --list-profiles` for the current list.

## Quick start

```bash
cd openshift-tests
export PROXY_ENV=<two-node-toolbox>/deploy/openshift-clusters/proxy.env

# 1. Get the test binary for the current cluster payload
scripts/extract-tests-binary.sh

# 2. Run a whole suite by profile
scripts/run-suite.sh --profile recovery
scripts/run-suite.sh --profile ra-verification --with-captures
scripts/run-suite.sh --profile upgrade --to-image <release-image>

# 3. Run a single test (defaults to node replacement, captures on)
scripts/run-test.sh
scripts/run-test.sh --test "<test name substring>" --repeat 3 --stop-on-fail

# 4. Drive captures by hand in another terminal
scripts/run-all-captures.sh
scripts/stop-all-captures.sh

# 5. Inspect results and clean up
scripts/check-latest-run.sh
scripts/summarize-all-runs.sh
scripts/clean-test-runs.sh --keep 5
```

Do **not** run the suite with every `openshift-tests --monitor` on TNF; use the
capture scripts for cluster-side context instead. See the
[User Guide](docs/USER-GUIDE.md) for details.
