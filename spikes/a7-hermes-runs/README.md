# A7. Local Hermes Runs smoke test

This opt-in test runs the installed Hermes gateway with a temporary profile
for each worker. Each gateway listens on a distinct loopback port and uses
its own temporary bearer. The only configured model is a local fixture.
The test gives the gateways no real model credentials, personal input,
desktop, account connector or browser session. Profiles share a host and
are not an operating system isolation boundary.

With the backend environment active, supply the executable for a trusted
local Hermes installation with the Runs API:

```sh
PYTHONPATH=apps/api/src python -B spikes/a7-hermes-runs/smoke.py \
  --hermes-executable /path/to/hermes --workers 5
```

The test checks five coordinator job IDs, retrieves five distinct successful
Hermes receipts and verifies the synthetic answer from each. It checks that
a repeated coordinator request does not create another job. The temporary
gateways stop and their profiles are removed when the script exits. The
test excludes provider subscriptions, OS-level containment, desktops,
memory and inter-worker handoff.

To open the same five temporary gateways in the operator UI, add
`--serve-workspace`. Set up the local token and frontend as in the
[voice setup guide](../../apps/voice-foundation.md). Leave port 8000 free for
the harness, which starts the backend. In the UI connect the workspace and
select a role. The gateways execute the requested run through the actual
Hermes harness with a local fixture model. Its answers are deliberately
fixed for verification. Voice uses only the local fake adapter in this mode.

The separate `--live-voice-handoff` action uses the configured OpenAI project
key and invokes the paid Realtime endpoint after the temporary gateways are
ready. Authorize the implementation before running it. The test sends a built-in
generated utterance and a fixed tool definition. It dispatches one local
research fixture and matches a verified receipt and exact synthetic answer
before requesting a tool-free announcement. It checks PCM correlated to the
announcement. It does not open a microphone or confirm the words played.
The live OpenAI handoff has not been run.

A local integration run used the installed Hermes gateway and a local model
fixture with scripted Realtime events. It verified one Researcher receipt,
separate acknowledgment and announcement PCM, and transport closure. A
separate browser run submitted a typed request to one installed gateway and
displayed its verified result while the microphone was disconnected. The
five-gateway browser run hit low disk space during profile startup. The
separate five-gateway Runs check succeeded.

On 2026-11-16, the installed Hermes v0.22.2 gateways produced this result:

```json
{"gateways": 5, "verified_receipts": 5, "local_fixture": true}
```

[Hermes Runs API](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server).
