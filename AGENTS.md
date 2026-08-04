# NGOPilot Agent Notes

## Deployment authentication

The local deployment CLIs were authenticated on 2026-08-03:

- Railway: `倪嘉辰（Wilson） <wilson1111223@gmail.com>`
- Render: `Wilsonnijc@outlook.com`
- AWS CLI `default`: account `106189426186`, currently
  `arn:aws:iam::106189426186:root`

Use the existing user-level CLI credentials for deployment work. Verify them before
making deployment changes:

```sh
railway whoami
render whoami
aws sts get-caller-identity
```

The signed AWS CLI is installed at `~/.local/aws-cli` and exposed through
`~/.local/bin/aws`. The Homebrew AWS CLI is unlinked because its Python runtime
is incompatible with this macOS version.

The user has explicitly authorized the current root session for NGOPilot AWS work.
Use it only for specific, user-requested NGOPilot actions after verifying exact
targets. Do not create root access keys, expose or copy its tokens, or treat this as
authorization for unrelated account-wide changes. Prefer a least-privilege profile
if one is configured later.

Railway, Render, and AWS manage their credentials outside this repository. Never
copy access tokens, credential files, or device authorization codes into the
repository, logs, deployment manifests, or chat output. If a verification command
fails, run the corresponding interactive login flow with the user present.
