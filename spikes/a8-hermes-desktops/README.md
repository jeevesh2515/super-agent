# A8. Separate Hermes desktops

This check starts five Hermes Bot Screens in five Linux containers from the
published v0.22.2 desktop image. Each has an independent anonymous data volume,
a private display socket, a non-root user and no network attachment. There are
no host folder or Docker socket mounts, published ports or active credentials.
The monitor checks that all five display sockets and role markers exist
concurrently. It stops and removes the temporary containers on exit.

On 2026-11-16, five 1440×900 screens started concurrently on Docker Desktop
for arm64. Their volumes and desktop sockets were distinct. Each container
had no IPv4 routes and no Ethernet interface. This test did not open a viewer,
take keyboard control, execute worker jobs, or verify general resistance to
container escapes. Its containers were not the five gateway processes used
for the [Runs test](../a7-hermes-runs/README.md).

To reproduce, run Docker and download the versioned image by digest once.
Then run the check from the repository root:

```sh
docker pull nousresearch/hermes-agent@sha256:79c98751d8d772ac0f7bfc31a75b123b9cfac254c2e15e4d0ac8762d6b119212
bash spikes/a8-hermes-desktops/check.sh
```

Each container has a 1,800 MiB limit. The test leaves Hermes's own screen
memory check enabled. Test full browser workloads before allocating five
active desktop workers on a single host. Jarvis still needs a reviewed
transport for authenticated viewing and takeover. Worker credentials and
desktop access must remain separate from the worker process and from the browser URL.

[Hermes Bot Screen](https://hermes-agent.nousresearch.com/docs/user-guide/features/bot-screen) · [Hermes Docker images](https://hermes-agent.nousresearch.com/docs/user-guide/docker).
