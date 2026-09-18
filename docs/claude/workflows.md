# Common Workflows

## EC2 → Two-Node Toolbox Deployment

1. Deploy EC2 instance: `cd ec2-deploy && make deploy init`
2. Configure instance: `./configure.sh`
3. Clone two-node-toolbox on instance or use Ansible from local machine
4. Deploy cluster: `cd two-node-toolbox/deploy && make deploy arbiter-ipi`

## SNO for Single-Node Testing

1. Ensure prerequisites in `~/.sno-deploy/`
2. Deploy: `make CLUSTER="test-cluster"`
3. Access: Use credentials from `~/.sno-deploy/test-cluster/creds/`

## LVM Operator Development

1. Clone workspace: `git clone <this-repo> lvm-workspace`
2. Clone repos: `cd lvm-workspace/environments/lvm-operator/repos && git clone <lvm-operator>`
3. Develop with full context from workspace root

## Component Readiness Report

Snapshot HA vs edge topology regressions from Sippy (TNF, TNA, SNO). Requires Go 1.21+ and network access to Sippy; no credentials.

1. `cd ci-tooling/readiness-report`
2. Default TSV for 5.0: `go run ./cmd`
3. Markdown with untriaged tests: `go run ./cmd -format md -untriaged`
4. List views for a release: `go run ./cmd -list-views -release 4.22`

See [ci-tooling/readiness-report/README.md](../../ci-tooling/readiness-report/README.md) for flags and output columns. For nightly payload health (blocking jobs, Prow, JIRA), use [payload-monitor](../../payload-monitor/).

## openshift-tests on a TNF Cluster

Run recovery, DualReplica, cert-rotation, conformance, or upgrade suites against a deployed Two-Node with Fencing cluster and capture cluster-side logs while they run.

1. `export PROXY_ENV=<two-node-toolbox>/deploy/openshift-clusters/proxy.env`
2. `cd openshift-tests && scripts/extract-tests-binary.sh`
3. Whole suite: `scripts/run-suite.sh --profile recovery` (add `--with-captures` for diagnostics)
4. Single test, repeated: `scripts/run-test.sh --test "<name>" --repeat 3 --stop-on-fail`
5. Results: `runs/<session>/summary.tsv`; clean with `scripts/clean-test-runs.sh --keep 5`

See [openshift-tests/docs/USER-GUIDE.md](../../openshift-tests/docs/USER-GUIDE.md) for flags, profiles, and troubleshooting, and [DEVELOPER-GUIDE.md](../../openshift-tests/docs/DEVELOPER-GUIDE.md) to extend the scripts.
