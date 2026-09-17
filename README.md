# Harness Engineering experiment

Use GitHub Issues/PRs as the user interface and a local self-hosted Runner as the execution host.

## Current state

- Repository initialized with an owner-only, manually triggered connectivity workflow.
- No Issue/PR event currently starts local execution.
- Runner registered as `he-skeleton-local`; the user-level macOS service is active. Connectivity test passed: [run 35201703061](https://github.com/big91987/he_skeleton/actions/runs/35201703061).
- Agent execution, persisted sessions, human feedback resumption, screenshots and preview deployment are not connected yet.

## Directory layout

```text
<work-root>/
  he_skeleton/              # source repository
  he_skeleton_runner/
    runtime/                # official runner application and private registration files
    jobs/                   # disposable workflow workspaces, created on first execution
    sessions/               # durable checkpoints, integration pending
    previews/               # long-lived preview files, integration pending
```

Separate directories do not provide OS isolation. The initial host is a macOS ARM64 machine using its logged-in user's permissions. A dedicated OS account or VM is a later option if stronger isolation is needed.

## First connectivity test

Once the runner is approved, registered and online, open **Actions → Local runner connectivity → Run workflow**, select `main`. Only the repository owner can run this job. It checks tool availability without invoking a model, reading credentials, checking out contributed code or publishing application content.

## Next milestones

1. Verify GitHub-to-local execution.
2. Add a tool-neutral execution input/result contract and the first real Agent adapter.
3. Persist task context and execution checkpoints independently of job workspaces.
4. Connect explicit owner commands on Issues/PRs to pause and resume.
5. Publish a static preview and screenshots, then verify a real feedback round trip.

The first preview will only prove browser interaction for a static application; backend/GPU acceptance requires a suitable real environment.
