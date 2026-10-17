# HTTP Docker packaging (persistent auth + real IRIS storage)

Linux-first. The existing loopback-only backend is unchanged: this image listens on
`127.0.0.1:18765` via `--network host` and never weakens bind checks or adds a relay.
The existing host `8765` service and any existing Vite process are left untouched.
`--network host` needs no `-p` publish flag; never add one with host networking.
Docker Desktop supports this only with host networking explicitly enabled, otherwise
use Linux. The default Vite example uses port `5173`; when `5173` is occupied use the
isolated `5174` example with a matching `--origin` override (see section 7).

The `http` image is self-contained: Python 3.13 installs project dependencies from
`pyproject.toml` with `pip check`, including the converter prompt resources, and needs
no host OpenCode binary and no Azure secret at build time. Workdir is
`/opt/rakathon/backend` and includes `scripts/run_converter.py` for the worker import
namespace. The image runs as nonroot `USER 65532` by default. The existing
`rakathon-converter` image workflow is preserved and untouched.

## 1. Private state outside the checkout

```sh
export STATE="$HOME/.local/share/rakathon-http"
mkdir -m 700 -p "$STATE"
id -u | grep -qx 0 && echo "refusing UID 0: rerun as a nonroot user" && exit 1
```

Create only the private `$STATE` parent here. `auth-init` (section 4) creates
`$STATE/auth` itself with mode `700`; never pre-create `$STATE/auth` or the CLI
refuses with `already_exists`. `$STATE/auth` holds the persistent SQLite account
store plus the `0600` auth keys and proxy key created by `auth-init`. Never store
secrets in Git. Reruns never auto-reset or overwrite existing keys or accounts.

## 2. Private IRIS env file (real names only, no values committed)

```sh
umask 077
printf 'IRIS FHIR endpoint and credentials (operator input only):\n'
read -r -p "FHIR username: " FHIR_USER_IN
read -rs -p "FHIR password: " FHIR_PASS_IN; printf '\n'
read -r -p "FHIR base URL: " FHIR_URL_IN
[ -n "$FHIR_USER_IN" ] && [ -n "$FHIR_PASS_IN" ] && [ -n "$FHIR_URL_IN" ] \
  || { echo "refusing empty credential input" >&2; unset FHIR_USER_IN FHIR_PASS_IN FHIR_URL_IN; exit 1; }
{
  printf 'RAKATHON_IRIS_FHIR_BASE_URL=%s\n' "$FHIR_URL_IN"
  printf 'RAKATHON_IRIS_FHIR_USER=%s\n' "$FHIR_USER_IN"
  printf 'RAKATHON_IRIS_FHIR_PASSWORD=%s\n' "$FHIR_PASS_IN"
  printf 'RAKATHON_IRIS_FHIR_VERIFY_TLS=1\nRAKATHON_IRIS_FHIR_ALLOW_DIRECT=1\n'
} > "$STATE/iris.env"
chmod 600 "$STATE/iris.env"
unset FHIR_USER_IN FHIR_PASS_IN FHIR_URL_IN
```

Type values interactively: never `echo` them, never pass them as CLI args, never
enable `set -x` while they are set, and never write them to shell history or Git.
Only these five real field names are used; there is no fake fallback and no mock
clinical data is ever substituted. The file must stay `0600` and owned by your host
UID. Missing or unreadable auth state or IRIS env fails startup closed.
`demo` here names the persistent SQLite account store, not mock clinical data:
clinical storage is always real `iris-fhir`.

## 3. Build (from the repo root, backend context only)

```sh
docker build --target http -f backend/docker/http/Dockerfile -t rakathon-http:dev backend
```

The Dockerfile-specific ignore (`Dockerfile.dockerignore`) whitelists only
`pyproject.toml`, `README.md`, `src`, `scripts/run_converter.py` and the http Docker
files, so `.env`, `iris.env`, private keys, `runtime/`, `.venv/` and `tests/` never
enter the build context. There is no broad root `COPY`.

## 4. Initialize auth state (one time)

```sh
docker run --rm --network host --read-only --cap-drop ALL --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m,mode=1777 \
  --mount type=bind,src="$STATE",dst=/state \
  rakathon-http:dev auth-init --auth-store demo --auth-dir /state/auth
```

Mount the `$STATE` parent here so the CLI creates the absent `/state/auth`
directory itself. Binding a pre-existing `$STATE/auth` as `/state/auth` for
`auth-init` always fails with `already_exists`. Later steps (`auth-user-add`,
`auth-serve`) may bind only `$STATE/auth` to `/state/auth`.

`auth-init` refuses an existing directory, so reruns never wipe accounts or keys.

## 5. Add a user (password via interactive prompt, never CLI flags)

```sh
docker run --rm -it --network host --read-only --cap-drop ALL --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m,mode=1777 \
  --mount type=bind,src="$STATE/auth",dst=/state/auth \
  rakathon-http:dev auth-user-add --auth-store demo --auth-dir /state/auth \
  --username smoke.clinician --role clinician
```

Type the password at the `getpass` prompt; it never touches shell history.
The same `smoke.clinician` username is used in the section 8 login check.

## 6. Run the server (default: no socket, no key, no AI)

```sh
docker run --rm --name rakathon-http --network host --read-only --cap-drop ALL \
  --security-opt no-new-privileges --user "$(id -u):$(id -g)" \
  --tmpfs /tmp:rw,noexec,nosuid,size=256m,mode=1777 \
  --tmpfs /run/rakathon:rw,noexec,nosuid,size=64m,uid=$(id -u),gid=$(id -g),mode=700 \
  --mount type=bind,src="$STATE/auth",dst=/state/auth \
  --mount type=bind,src="$STATE/iris.env",dst=/run/secrets/iris.env,ro \
  rakathon-http:dev
```

With no CLI args the entrypoint execs (no shell):

```sh
rakathon-backend auth-serve --auth-store demo --auth-dir /state/auth \
  --origin http://localhost:5173 --allow-loopback-http --bind 127.0.0.1 --port 18765 \
  --storage iris-fhir --runtime-dir /run/rakathon --env-file /run/secrets/iris.env
```

Nonsecret overrides (never empty): `RAKATHON_HTTP_PORT`, `RAKATHON_HTTP_ORIGIN`,
`RAKATHON_HTTP_AUTH_DIR`, `RAKATHON_HTTP_RUNTIME_DIR`, `RAKATHON_HTTP_IRIS_ENV_FILE`.
Empty or invalid values fail closed. `--assistant` and `--converter-enable` are never
appended; explicit `auth-init`, `auth-user-add` or `auth-serve` args pass through for
operator use. Never pass credential values via Docker `--env-file` (visible to
`docker inspect`); always bind-mount the `0600` file. Refuse UID 0: there is no root
fallback, and running as your host UID keeps `0600` proxy-key ownership shared with
Vite. Runtime UDS state lives on the private tmpfs; the SQLite store and keys persist
on the `$STATE/auth` bind mount.

## 7. Host Vite (your own process, existing ports untouched)

`VITE_*` names are loaded by Vite itself; the server-only `RAKATHON_*` proxy
settings are read from `process.env`, so export them inline (or `export` them) in
the same command. `.env.local` does not inject server-side proxy config.

Default (`5173` free):

```sh
cd app
VITE_DATA_MODE=backend VITE_BACKEND_API_BASE=/api/v1 \
  RAKATHON_BACKEND_PROXY_TARGET=http://127.0.0.1:18765 \
  RAKATHON_BACKEND_PROXY_KEY_FILE="$STATE/auth/proxy.key" \
  npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Isolated (`5173` occupied, use `5174` and override the origin):

```sh
cd app
VITE_DATA_MODE=backend VITE_BACKEND_API_BASE=/api/v1 \
  RAKATHON_BACKEND_PROXY_TARGET=http://127.0.0.1:18765 \
  RAKATHON_BACKEND_PROXY_KEY_FILE="$STATE/auth/proxy.key" \
  npm run dev -- --host 127.0.0.1 --port 5174 --strictPort
```

Pair the `5174` Vite process with `--origin http://localhost:5174` on the backend
(`RAKATHON_HTTP_ORIGIN=http://localhost:5174` or the matching `auth-serve` flag).
The key file must live outside `app/` and stay `0600`; never use a `VITE_*`
variable for it. Open the frontend at `http://localhost:5173` (or
`http://localhost:5174` for the isolated case) so the browser Origin exactly
matches `--origin`; do not mix in a `127.0.0.1:5173` frontend URL. The server-only
Vite proxy defaults to `8765` and accepts loopback `18765` with a matching Host.

## 8. Health and login checks (key never printed)

Liveness only (does not prove clinical IRIS readiness). The proxy key is read from
the private file, never pasted:

```sh
python3 - <<'EOF'
import http.client, json, os
from pathlib import Path
state = os.environ["STATE"]
key = (Path(state) / "auth" / "proxy.key").read_bytes().decode().strip()
port = 18765
c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
c.request("GET", "/health", headers={"Host": f"127.0.0.1:{port}", "X-Rakathon-Proxy-Key": key})
r = c.getresponse()
print(r.status, json.loads(r.read().decode()))
EOF
```

Without the proxy key every `/api/v1/*` and `/health` call returns `401`. Direct
anonymous session access stays `401`. Password login sends `Origin` plus
`X-Rakathon-Auth: 1` and the proxy key; logout additionally sends the `X-CSRF-Token`.
Passwords come only from `getpass.getpass()` with a `http.cookiejar`-backed client,
never from CLI args, env-visible strings, or shell history:

```sh
python3 - <<'EOF'
import getpass, http.client, http.cookiejar, json, os, urllib.request
from pathlib import Path
state = os.environ["STATE"]
origin = "http://localhost:5173"  # use http://localhost:5174 for the isolated case
key = (Path(state) / "auth" / "proxy.key").read_bytes().decode().strip()
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
base = "http://127.0.0.1:18765"
pw = getpass.getpass("Password: ")
login_body = json.dumps({"username": "smoke.clinician", "password": pw}).encode()
del pw
req = urllib.request.Request(base + "/api/v1/auth/login", data=login_body, method="POST",
  headers={"Host": "127.0.0.1:18765", "Origin": origin,
           "X-Rakathon-Proxy-Key": key, "X-Rakathon-Auth": "1",
           "Content-Type": "application/json"})
print("login", opener.open(req, timeout=10).status, len(jar) > 0)
sess = urllib.request.Request(base + "/api/v1/auth/session", method="GET",
  headers={"Host": "127.0.0.1:18765", "Origin": origin, "X-Rakathon-Proxy-Key": key})
resp = opener.open(sess, timeout=10)
payload = json.loads(resp.read().decode())
print("session", resp.status, payload.get("authenticated"))
EOF
```

Logout sends the session cookie plus `X-CSRF-Token` and returns `204`; the next
session check returns `401`.

## 9. Optional converter worker (explicit opt-in, default off)

The default setup above mounts no Docker socket, no converter key and no AI. The
optional `http-with-converter` stage adds only the pinned official Docker CLI binary
(`docker:27.5.1-cli`, no daemon in the container, no default socket mount):

```sh
docker build --target http-with-converter -f backend/docker/http/Dockerfile \
  -t rakathon-http:converter backend
```

Mounting the host `docker.sock`, even `:ro`, is root-equivalent daemon control:
`--cap-drop` and nonroot do not mitigate it. It additionally needs `--group-add` with
the socket GID, the same absolute host paths for worker input, scratch, store, recipe
cache and secret (the in-container client passes `-v` paths that the host daemon
resolves), and the runtime scratch bound on the identical host path (the default
`/run/rakathon` tmpfs is invisible to the host daemon). The isolated worker itself
gets no socket, no host auth mount and read-only inputs. Prebuild the existing
converter image on the host first with `backend/scripts/run_converter.py` (needs
OpenCode `2.0.31` on `PATH`); the http image does not build it. A future explicit
run may pass full `auth-serve --converter-store/--converter-image/--converter-secret-file`
flags with `--converter-enable`, but that stays off and no AI runs unless an operator
opts in explicitly.
