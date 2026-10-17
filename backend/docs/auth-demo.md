# Demo login (opt-in, demo auth store only)

Off by default. Enabled only with an explicit private JSON file:

```
rakathon-backend auth-serve --auth-store demo --auth-dir DIR --origin URL \
  --runtime-dir RUNTIME --demo-login-file /private/demo-login.json
```

`--demo-login-file` requires `--auth-store demo` and is rejected otherwise.
The clinical `--storage` may stay `mock` or `iris-fhir`.
Without the flag, `POST /api/v1/auth/demo-login` is 404 and
login/session responses carry no demo fields.

## Private file

Strict JSON with exactly these four keys, each `{username, password}`:

```json
{
  "koordinator": {"username": "demo.koordinator", "password": "..."},
  "lekar": {"username": "demo.lekar", "password": "..."},
  "mdt": {"username": "demo.mdt", "password": "..."},
  "pacient": {"username": "demo.pacient", "password": "..."}
}
```

Safety rules, all fail closed with a generic error and no secret details:

- regular file, never a symlink, read through `O_NOFOLLOW`
- owned by the serving user with mode exactly `0600`, size 1..8192 bytes
- parent directory private (owned by the serving user, no group/other bits)
- usernames valid `name.surname` accounts, unique after normalization
- passwords 1..256 chars; file holds no roles

Expected B7 roles are fixed in code, never read from the file:
`koordinator` is `coordinator`, `lekar` and `mdt` are `clinician`,
`pacient` is `viewer`.
Provision the four accounts with the existing `auth-user-add` flow;
there is no provisioning on start and no password rotation here.

## Frontend contract

- `GET /api/v1/auth/session` adds `demoAccounts:
  ["koordinator","lekar","mdt","pacient"]` only when enabled,
  including the anonymous `{"authenticated": false}` response.
- `POST /api/v1/auth/demo-login` accepts only `{"account": <one id>}`
  with the same proxy key, exact `Origin`, `X-Rakathon-Auth: 1`,
  and JSON content gates as password login.
  It logs in through the existing B7 path with the stored credentials.
  A username or role mismatch revokes the issued session and returns
  generic `401 invalid_credentials`.
- Authenticated login/session/demo-login responses add optional
  `demoView: <id>` when the verified username and role match a
  configured demo account. No-config responses are unchanged.
- The existing username/password path, B6 matrix, and identity
  resolution are untouched. Auth responses send `Cache-Control: no-store`.
