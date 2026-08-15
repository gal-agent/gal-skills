#!/usr/bin/env python3
"""Policy gate and helper actions for the built-in gal-k8s-safe skill.

The script intentionally does not read or print kubeconfig credentials. It only
uses kubectl for RBAC setup and guarded namespace-scoped write operations after
validating the requested namespace, resource kind, and action.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_SERVICE_ACCOUNT = "gal-safe-reader"
DEFAULT_SERVICE_ACCOUNT_NAMESPACE = "gal-safe"
DEFAULT_BACKUP_RETENTION_DAYS = 15
DEFAULT_TOKEN_DURATION = "72h"
DEFAULT_KUBECONFIG_OUT = "~/.safe-mount-dir/gal-k8s-safe/kubeconfig"
DEFAULT_BACKUP_DIR = "~/.safe-mount-dir/gal-k8s-safe/backups"

PROTECTED_NAMESPACES = {
    "kube-system",
    "kube-public",
    "kube-node-lease",
    "default",
    "cert-manager",
    "ingress-nginx",
    "istio-system",
    "linkerd",
    "monitoring",
    "logging",
    "argocd",
    "flux-system",
}

# Namespace-scoped resources that are allowed to receive create/update/patch.
# Delete verbs are never generated or executed by this script.
WRITABLE_RESOURCES = {
    "configmap": ("", "configmaps", "ConfigMap"),
    "configmaps": ("", "configmaps", "ConfigMap"),
    "service": ("", "services", "Service"),
    "services": ("", "services", "Service"),
    "deployment": ("apps", "deployments", "Deployment"),
    "deployments": ("apps", "deployments", "Deployment"),
    "statefulset": ("apps", "statefulsets", "StatefulSet"),
    "statefulsets": ("apps", "statefulsets", "StatefulSet"),
    "daemonset": ("apps", "daemonsets", "DaemonSet"),
    "daemonsets": ("apps", "daemonsets", "DaemonSet"),
    "replicaset": ("apps", "replicasets", "ReplicaSet"),
    "replicasets": ("apps", "replicasets", "ReplicaSet"),
    "job": ("batch", "jobs", "Job"),
    "jobs": ("batch", "jobs", "Job"),
    "cronjob": ("batch", "cronjobs", "CronJob"),
    "cronjobs": ("batch", "cronjobs", "CronJob"),
    "ingress": ("networking.k8s.io", "ingresses", "Ingress"),
    "ingresses": ("networking.k8s.io", "ingresses", "Ingress"),
}

KIND_TO_RESOURCE = {value[2]: value[1] for value in WRITABLE_RESOURCES.values()}
ALLOWED_WRITE_KINDS = set(KIND_TO_RESOURCE)
RESTART_RESOURCES = {"deployment", "deployments", "statefulset", "statefulsets", "daemonset", "daemonsets"}

DANGEROUS_RESOURCE_HINTS = {
    "secret",
    "secrets",
    "serviceaccount",
    "serviceaccounts",
    "role",
    "roles",
    "rolebinding",
    "rolebindings",
    "clusterrole",
    "clusterroles",
    "clusterrolebinding",
    "clusterrolebindings",
    "customresourcedefinition",
    "customresourcedefinitions",
    "crd",
    "crds",
    "namespace",
    "namespaces",
    "node",
    "nodes",
    "persistentvolume",
    "persistentvolumes",
    "persistentvolumeclaim",
    "persistentvolumeclaims",
    "storageclass",
    "storageclasses",
    "validatingwebhookconfiguration",
    "validatingwebhookconfigurations",
    "mutatingwebhookconfiguration",
    "mutatingwebhookconfigurations",
    "networkpolicy",
    "networkpolicies",
}

BLOCKED_KINDS = {
    "CustomResourceDefinition",
    "ClusterRole",
    "ClusterRoleBinding",
    "Role",
    "RoleBinding",
    "ServiceAccount",
    "Secret",
    "Namespace",
    "Node",
    "PersistentVolume",
    "PersistentVolumeClaim",
    "StorageClass",
    "ValidatingWebhookConfiguration",
    "MutatingWebhookConfiguration",
    "NetworkPolicy",
}

NS_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
NAME_RE = re.compile(r"^[A-Za-z0-9._:/-]+$")
SAFE_PATH_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def fail(message: str, code: int = 2) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def kubectl_base(context: str | None) -> list[str]:
    cmd = ["kubectl"]
    if context:
        cmd += ["--context", context]
    return cmd


def create_token_supported() -> bool:
    """Return True if this kubectl client supports `create token` (>= 1.24)."""
    try:
        proc = subprocess.run(
            ["kubectl", "create", "token", "--help"],
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        fail("kubectl was not found in PATH")
    combined = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0 and "--duration" in combined


def legacy_sa_token(base: list[str], sa_namespace: str, service_account: str) -> str:
    """Read a long-lived ServiceAccount token from its secret (kubectl < 1.24).

    Kubernetes < 1.24 auto-creates a token secret for every ServiceAccount. If
    none is present yet (or it is still being populated), create a bound secret
    and wait briefly for the controller to fill in the token.
    """
    def token_from_secret(secret_name: str) -> str:
        raw = kubectl_capture(
            None, base[1:] + ["-n", sa_namespace, "get", "secret", secret_name,
                              "-o", "jsonpath={.data.token}"])
        if not raw:
            return ""
        try:
            return base64.b64decode(raw).decode("utf-8").strip()
        except Exception:
            return ""

    # 1. Look for an existing SA-owned token secret.
    secrets_json = kubectl_capture(
        None, base[1:] + ["-n", sa_namespace, "get", "secret",
                          "-o", "json"])
    secret_name = ""
    if secrets_json:
        try:
            data = json.loads(secrets_json)
        except json.JSONDecodeError:
            data = {"items": []}
        for item in data.get("items", []):
            meta = item.get("metadata", {})
            annotations = meta.get("annotations", {})
            if (item.get("type") == "kubernetes.io/service-account-token"
                    and annotations.get("kubernetes.io/service-account.name")
                    == service_account):
                secret_name = meta.get("name", "")
                if secret_name and token_from_secret(secret_name):
                    break
                secret_name = ""

    # 2. None found — create a bound token secret and wait for population.
    if not secret_name:
        secret_name = f"{service_account}-gal-safe-token"
        manifest = json.dumps({
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "name": secret_name,
                "namespace": sa_namespace,
                "annotations": {
                    "kubernetes.io/service-account.name": service_account,
                },
            },
            "type": "kubernetes.io/service-account-token",
        })
        run(base + ["-n", sa_namespace, "apply", "-f", "-"],
            input_text=manifest, capture=True)

    # 3. Poll for the token to appear (controller fills it asynchronously).
    token = ""
    for _ in range(10):
        token = token_from_secret(secret_name)
        if token:
            break
        time.sleep(1)
    if not token:
        fail(f"could not obtain a token from ServiceAccount secret {secret_name!r}; "
             "the token controller may be disabled on this cluster")
    return token


def request_sa_token(base: list[str], sa_namespace: str, service_account: str,
                     duration: str) -> str:
    """Obtain a ServiceAccount token, using the best method for this cluster.

    Prefers `kubectl create token` (short-lived, honors --duration) on kubectl
    >= 1.24. On older clients it falls back to the auto-created long-lived SA
    token secret so gen-kubeconfig/renew-token still work on legacy clusters.
    """
    if create_token_supported():
        proc = run(
            base + ["-n", sa_namespace, "create", "token",
                    service_account, f"--duration={duration}"],
            capture=True,
        )
        token = (proc.stdout or "").strip()
        if not token:
            fail("kubectl create token returned an empty token")
        return token

    # Legacy path (kubectl < 1.24): long-lived SA token secret.
    print("Note: kubectl < 1.24 detected; 'create token' is unavailable. "
          "Falling back to the long-lived ServiceAccount token secret. "
          f"The requested duration ({duration}) cannot be enforced — the token "
          "stays valid until the ServiceAccount or secret is deleted. Rotate by "
          "recreating the ServiceAccount, or upgrade kubectl to >= 1.24 for "
          "short-lived tokens.", file=sys.stderr)
    return legacy_sa_token(base, sa_namespace, service_account)


def run(cmd: list[str], *, input_text: str | None = None, capture: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            input=input_text,
            text=True,
            capture_output=capture,
            check=True,
        )
    except FileNotFoundError:
        fail("kubectl was not found in PATH")
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            print(exc.stdout, end="")
        if exc.stderr:
            print(exc.stderr, end="", file=sys.stderr)
        fail(f"command failed: {' '.join(cmd)}", exc.returncode or 1)


def validate_namespace(namespace: str) -> None:
    if not namespace:
        fail("namespace is required")
    if len(namespace) > 63 or not NS_RE.match(namespace):
        fail(f"invalid Kubernetes namespace name: {namespace!r}")
    if namespace in PROTECTED_NAMESPACES:
        fail(f"namespace {namespace!r} is protected and cannot receive write access")


def validate_service_account_namespace(namespace: str) -> None:
    if not namespace:
        fail("service-account namespace is required")
    if len(namespace) > 63 or not NS_RE.match(namespace):
        fail(f"invalid Kubernetes namespace name: {namespace!r}")


def validate_resource(resource: str) -> tuple[str, str, str]:
    key = resource.lower()
    if key in DANGEROUS_RESOURCE_HINTS:
        fail(f"resource {resource!r} is intentionally blocked by gal-k8s-safe")
    if key not in WRITABLE_RESOURCES:
        allowed = ", ".join(sorted(set(WRITABLE_RESOURCES)))
        fail(f"resource {resource!r} is not in the writable allowlist. Allowed: {allowed}")
    return WRITABLE_RESOURCES[key]


def validate_restart_resource(resource: str) -> None:
    if resource.lower() not in RESTART_RESOURCES:
        allowed = ", ".join(sorted(RESTART_RESOURCES))
        fail(f"rollout restart is limited to workload controllers. Allowed: {allowed}")


def validate_object_name(name: str) -> None:
    if not name or len(name) > 253 or not NAME_RE.match(name):
        fail(f"invalid Kubernetes object name: {name!r}")


def safe_path_part(value: str) -> str:
    cleaned = SAFE_PATH_RE.sub("_", value).strip("._")
    return cleaned or "unnamed"

def backup_root() -> Path:
    base = os.environ.get("GAL_K8S_SAFE_BACKUP_DIR")
    if base:
        root = Path(base).expanduser()
    else:
        root = Path(DEFAULT_BACKUP_DIR).expanduser()
    root = root.resolve()
    gal_dir = (Path.home() / ".gal").resolve()
    try:
        root.relative_to(gal_dir)
        fail(f"backup directory must not be under ~/.gal: {root}")
    except ValueError:
        pass
    return root


def prune_backups(root: Path, retention_days: int) -> None:
    if retention_days <= 0 or not root.exists():
        return
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=retention_days)
    for path in root.rglob("*.yaml"):
        try:
            mtime = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc)
        except OSError:
            continue
        if mtime < cutoff:
            try:
                path.unlink()
            except OSError:
                pass
    for directory in sorted([p for p in root.rglob("*") if p.is_dir()], reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass


def backup_kubectl_get(
    context: str | None,
    root: Path,
    label_parts: list[str],
    get_args: list[str],
    description: str,
) -> Path | None:
    cmd = kubectl_base(context) + get_args
    try:
        cp = subprocess.run(cmd, text=True, capture_output=True, check=False)
    except FileNotFoundError:
        fail("kubectl was not found in PATH")
    if cp.returncode != 0:
        stderr = cp.stderr or ""
        if "NotFound" in stderr or "not found" in stderr:
            print(f"Backup skipped (not found): {description}")
            return None
        if cp.stdout:
            print(cp.stdout, end="")
        if cp.stderr:
            print(cp.stderr, end="", file=sys.stderr)
        fail(f"backup failed for {description}: {' '.join(cmd)}", cp.returncode or 1)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = root.joinpath(*(safe_path_part(part) for part in label_parts[:-1]))
    out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    out = out_dir / f"{safe_path_part(label_parts[-1])}.{stamp}.yaml"
    out.write_text(cp.stdout, encoding="utf-8")
    out.chmod(0o600)
    print(f"Backup: {out}")
    return out


def backup_existing_objects(context: str | None, objects: list[dict[str, object]], retention_days: int) -> None:
    root = backup_root()
    prune_backups(root, retention_days)
    for obj in objects:
        backup_kubectl_get(
            context,
            root,
            obj["label_parts"],  # type: ignore[arg-type]
            obj["get_args"],  # type: ignore[arg-type]
            str(obj["description"]),
        )


def readonly_backup_objects(sa: str, sa_namespace: str) -> list[dict[str, object]]:
    return [
        {
            "label_parts": ["cluster", "namespaces", sa_namespace],
            "get_args": ["get", "namespace", sa_namespace, "-o", "yaml"],
            "description": f"namespace/{sa_namespace}",
        },
        {
            "label_parts": [sa_namespace, "serviceaccounts", sa],
            "get_args": ["-n", sa_namespace, "get", "serviceaccount", sa, "-o", "yaml"],
            "description": f"serviceaccount/{sa_namespace}/{sa}",
        },
        {
            "label_parts": ["cluster", "clusterroles", f"{sa}-readonly"],
            "get_args": ["get", "clusterrole", f"{sa}-readonly", "-o", "yaml"],
            "description": f"clusterrole/{sa}-readonly",
        },
        {
            "label_parts": ["cluster", "clusterrolebindings", f"{sa}-readonly"],
            "get_args": ["get", "clusterrolebinding", f"{sa}-readonly", "-o", "yaml"],
            "description": f"clusterrolebinding/{sa}-readonly",
        },
    ]


def writer_backup_objects(namespace: str) -> list[dict[str, object]]:
    return [
        {
            "label_parts": [namespace, "roles", "gal-safe-writer"],
            "get_args": ["-n", namespace, "get", "role", "gal-safe-writer", "-o", "yaml"],
            "description": f"role/{namespace}/gal-safe-writer",
        },
        {
            "label_parts": [namespace, "rolebindings", "gal-safe-writer"],
            "get_args": ["-n", namespace, "get", "rolebinding", "gal-safe-writer", "-o", "yaml"],
            "description": f"rolebinding/{namespace}/gal-safe-writer",
        },
    ]


def backup_object(context: str | None, namespace: str, resource: str, name: str, retention_days: int) -> Path | None:
    _, canonical, _ = validate_resource(resource)
    validate_namespace(namespace)
    validate_object_name(name)
    root = backup_root()
    prune_backups(root, retention_days)
    return backup_kubectl_get(
        context,
        root,
        [namespace, canonical, name],
        ["-n", namespace, "get", canonical, name, "-o", "yaml"],
        f"{canonical}/{namespace}/{name}",
    )


def manifest_backup_objects(objects: list[dict[str, str]]) -> list[dict[str, object]]:
    backups: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for obj in objects:
        namespace = obj["namespace"]
        resource = obj["resource"]
        name = obj["name"]
        key = (namespace, resource, name)
        if key in seen:
            continue
        seen.add(key)
        backups.append({
            "label_parts": [namespace, resource, name],
            "get_args": ["-n", namespace, "get", resource, name, "-o", "yaml"],
            "description": f"{resource}/{namespace}/{name}",
        })
    return backups


def readonly_yaml(sa: str, sa_namespace: str) -> str:
    validate_object_name(sa)
    validate_service_account_namespace(sa_namespace)
    return f"""apiVersion: v1
kind: Namespace
metadata:
  name: {sa_namespace}
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {sa}
  namespace: {sa_namespace}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: {sa}-readonly
rules:
- apiGroups: ["*"]
  resources: ["*"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: {sa}-readonly
subjects:
- kind: ServiceAccount
  name: {sa}
  namespace: {sa_namespace}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: {sa}-readonly
"""


def writer_yaml(namespace: str, sa: str, sa_namespace: str) -> str:
    validate_namespace(namespace)
    validate_object_name(sa)
    validate_service_account_namespace(sa_namespace)
    return f"""apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: gal-safe-writer
  namespace: {namespace}
rules:
- apiGroups: [""]
  resources: ["configmaps", "services"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
- apiGroups: ["apps"]
  resources: ["deployments", "statefulsets", "daemonsets", "replicasets"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
- apiGroups: ["batch"]
  resources: ["jobs", "cronjobs"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
- apiGroups: ["networking.k8s.io"]
  resources: ["ingresses"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: gal-safe-writer
  namespace: {namespace}
subjects:
- kind: ServiceAccount
  name: {sa}
  namespace: {sa_namespace}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: gal-safe-writer
"""


def apply_yaml(
    yaml_text: str,
    context: str | None,
    dry_run: bool,
    backups: list[dict[str, object]],
    retention_days: int,
) -> None:
    if dry_run:
        print(yaml_text)
        return
    backup_existing_objects(context, backups, retention_days)
    run(kubectl_base(context) + ["apply", "-f", "-"], input_text=yaml_text)


def split_manifest_documents(manifest: str) -> list[str]:
    docs: list[str] = []
    current: list[str] = []
    for line in manifest.splitlines():
        if re.match(r"^\s*---\s*(?:#.*)?$", line):
            doc = "\n".join(current).strip()
            if doc:
                docs.append(doc)
            current = []
            continue
        current.append(line)
    doc = "\n".join(current).strip()
    if doc:
        docs.append(doc)
    return docs


def yaml_scalar(document: str, path: list[str]) -> str | None:
    if len(path) != 2 or path[0] != "metadata":
        fail("internal parser only supports top-level and metadata scalar paths")
    in_metadata = False
    metadata_indent: int | None = None
    target = path[1]
    for line in document.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if re.match(r"^metadata\s*:\s*(?:#.*)?$", stripped):
            in_metadata = True
            metadata_indent = indent
            continue
        if in_metadata and metadata_indent is not None:
            if indent <= metadata_indent and not stripped.startswith("#"):
                in_metadata = False
                metadata_indent = None
            elif indent > metadata_indent:
                match = re.match(rf"^{re.escape(target)}\s*:\s*([^#]+?)\s*(?:#.*)?$", stripped)
                if match:
                    return unquote_yaml_scalar(match.group(1).strip())
    return None


def top_level_scalar(document: str, key: str) -> str | None:
    for line in document.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent != 0:
            continue
        match = re.match(rf"^{re.escape(key)}\s*:\s*([^#]+?)\s*(?:#.*)?$", line.strip())
        if match:
            return unquote_yaml_scalar(match.group(1).strip())
    return None


def unquote_yaml_scalar(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def validate_manifest(manifest: str, namespace: str) -> list[dict[str, str]]:
    docs = split_manifest_documents(manifest)
    if not docs:
        fail("manifest must contain at least one Kubernetes object")
    objects: list[dict[str, str]] = []
    for doc in docs:
        kind = top_level_scalar(doc, "kind")
        if not kind:
            fail("each manifest document must contain kind")
        if kind in BLOCKED_KINDS:
            fail(f"manifest contains blocked kind {kind!r}")
        if kind not in ALLOWED_WRITE_KINDS:
            allowed = ", ".join(sorted(ALLOWED_WRITE_KINDS))
            fail(f"manifest kind {kind!r} is not in the writable allowlist. Allowed: {allowed}")
        name = yaml_scalar(doc, ["metadata", "name"])
        if not name:
            fail(f"manifest kind {kind!r} must include metadata.name")
        validate_object_name(name)
        doc_namespace = yaml_scalar(doc, ["metadata", "namespace"])
        if doc_namespace and doc_namespace != namespace:
            fail(f"manifest object {kind}/{name} targets namespace {doc_namespace!r}, expected {namespace!r}")
        resource = KIND_TO_RESOURCE[kind]
        objects.append({"namespace": namespace, "resource": resource, "kind": kind, "name": name})
    return objects


def guarded_apply(args: argparse.Namespace) -> None:
    validate_namespace(args.namespace)
    if args.file == "-":
        manifest = sys.stdin.read()
    else:
        path = Path(args.file).expanduser()
        if not path.is_file():
            fail(f"manifest file not found: {path}")
        manifest = path.read_text(encoding="utf-8")
    objects = validate_manifest(manifest, args.namespace)
    if args.dry_run:
        names = ", ".join(f"{obj['kind']}/{obj['name']}" for obj in objects)
        print(f"Dry run: manifest validated for namespace {args.namespace}: {names}")
        return
    backup_existing_objects(args.context, manifest_backup_objects(objects), args.retention_days)
    run(kubectl_base(args.context) + ["-n", args.namespace, "apply", "-f", "-"], input_text=manifest)


def restart(args: argparse.Namespace) -> None:
    validate_namespace(args.namespace)
    validate_restart_resource(args.resource)
    validate_resource(args.resource)
    validate_object_name(args.name)
    backup_object(args.context, args.namespace, args.resource, args.name, args.retention_days)
    if args.dry_run:
        print("Dry run: backup created; not restarting.")
        return
    run(kubectl_base(args.context) + ["-n", args.namespace, "rollout", "restart", f"{args.resource}/{args.name}"])


def kubectl_capture(context: str | None, extra: list[str]) -> str:
    proc = run(kubectl_base(context) + extra, capture=True)
    return (proc.stdout or "").strip()


def resolve_kubeconfig_out(out: str) -> Path:
    path = Path(out).expanduser().resolve()
    gal_dir = (Path.home() / ".gal").resolve()
    try:
        path.relative_to(gal_dir)
        fail(f"kubeconfig output must not be under ~/.gal: {path}")
    except ValueError:
        pass
    return path


def gen_kubeconfig(args: argparse.Namespace) -> None:
    """Create a restricted kubeconfig from a ServiceAccount token.

    The token is requested via `kubectl create token` and written straight to
    the output file with 0600 permissions. It is never printed to stdout/stderr.
    """
    validate_service_account_namespace(args.service_account_namespace)
    validate_object_name(args.service_account)

    context = args.context or kubectl_capture(None, ["config", "current-context"])
    if not context:
        fail("could not determine kubectl context; pass --context")

    base = kubectl_base(context)
    server = kubectl_capture(
        None, base[1:] + ["config", "view", "--raw", "--minify", "-o",
                          "jsonpath={.clusters[0].cluster.server}"])
    if not server:
        fail("could not read cluster server URL from current context")
    ca_data = kubectl_capture(
        None, base[1:] + ["config", "view", "--raw", "--minify", "-o",
                          "jsonpath={.clusters[0].cluster.certificate-authority-data}"])
    insecure = kubectl_capture(
        None, base[1:] + ["config", "view", "--raw", "--minify", "-o",
                          "jsonpath={.clusters[0].cluster.insecure-skip-tls-verify}"])

    if not ca_data and insecure != "true":
        fail("cluster has no certificate-authority-data and is not insecure-skip-tls-verify; "
             "ask the admin for correct CA handling instead of copying the admin kubeconfig")

    # Request the SA token. capture=True keeps it out of logs; we never print it.
    token = request_sa_token(
        base, args.service_account_namespace, args.service_account, args.duration)

    cluster = f"gal-safe-{context}"
    user = args.service_account
    ctx = f"{user}@{cluster}"

    lines = [
        "apiVersion: v1",
        "kind: Config",
        "clusters:",
        f"- name: {cluster}",
        "  cluster:",
        f"    server: {server}",
    ]
    if ca_data:
        lines.append(f"    certificate-authority-data: {ca_data}")
    elif insecure == "true":
        lines.append("    insecure-skip-tls-verify: true")
    lines += [
        "users:",
        f"- name: {user}",
        "  user:",
        f"    token: {token}",
        "contexts:",
        f"- name: {ctx}",
        "  context:",
        f"    cluster: {cluster}",
        f"    user: {user}",
        f"current-context: {ctx}",
        "",
    ]
    content = "\n".join(lines)

    out = resolve_kubeconfig_out(args.out)
    if args.dry_run:
        # Show everything except the secret token.
        preview = content.replace(token, "<redacted-token>")
        print(f"Dry run: would write restricted kubeconfig to {out}\n")
        print(preview)
        return

    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(out.parent, 0o700)
    except OSError:
        pass
    fd = os.open(str(out), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, content.encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(out, 0o600)
    del token, content
    print(f"Wrote restricted kubeconfig to {out} (mode 0600).")
    print("Token was not printed. Mount this file read-only at ~/.kube/config in the target agent's safe_mode.mounts.")


def renew_token(args: argparse.Namespace) -> None:
    """Renew the SA token in an existing restricted kubeconfig.

    Reads the existing kubeconfig to preserve server/CA/context, requests a new
    token, and rewrites the file in place with 0600 permissions. The token is
    never printed.
    """
    validate_service_account_namespace(args.service_account_namespace)
    validate_object_name(args.service_account)

    out = resolve_kubeconfig_out(args.out)
    if not out.is_file():
        fail(f"existing kubeconfig not found at {out}; run gen-kubeconfig first")

    existing = out.read_text(encoding="utf-8")

    # Extract server and CA from the existing file so we don't need cluster access
    # beyond the token request. We do a simple line scan rather than requiring yaml.
    server = None
    ca_data = None
    insecure = None
    cluster_name = None
    user_name = None
    ctx_name = None
    in_cluster_block = False
    for line in existing.splitlines():
        stripped = line.strip()
        if stripped == "clusters:":
            in_cluster_block = True
            continue
        if in_cluster_block and stripped.startswith("cluster:"):
            in_cluster_block = True
            continue
        if in_cluster_block and stripped.startswith("server:"):
            server = stripped.split(":", 1)[1].strip()
        elif in_cluster_block and stripped.startswith("certificate-authority-data:"):
            ca_data = stripped.split(":", 1)[1].strip()
        elif in_cluster_block and stripped.startswith("insecure-skip-tls-verify:"):
            insecure = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("- name: ") and cluster_name is None and in_cluster_block:
            cluster_name = stripped[len("- name: "):]
            in_cluster_block = False
        elif stripped.startswith("current-context:"):
            ctx_name = stripped.split(":", 1)[1].strip()
    # Try to extract user name from context block
    for i, line in enumerate(existing.splitlines()):
        stripped = line.strip()
        if stripped == "users:":
            # Next "- name:" is the user
            for j in range(i + 1, min(i + 5, len(existing.splitlines()))):
                ln = existing.splitlines()[j].strip()
                if ln.startswith("- name: "):
                    user_name = ln[len("- name: "):]
                    break
            break

    if not server:
        fail("could not read server from existing kubeconfig; the file may be corrupted")
    if not cluster_name:
        cluster_name = f"gal-safe-unknown"
    if not user_name:
        user_name = args.service_account
    if not ctx_name:
        ctx_name = f"{user_name}@{cluster_name}"

    context = args.context or kubectl_capture(None, ["config", "current-context"])
    if not context:
        fail("could not determine kubectl context; pass --context")

    base = kubectl_base(context)
    token = request_sa_token(
        base, args.service_account_namespace, args.service_account, args.duration)

    lines = [
        "apiVersion: v1",
        "kind: Config",
        "clusters:",
        f"- name: {cluster_name}",
        "  cluster:",
        f"    server: {server}",
    ]
    if ca_data:
        lines.append(f"    certificate-authority-data: {ca_data}")
    elif insecure == "true":
        lines.append("    insecure-skip-tls-verify: true")
    lines += [
        "users:",
        f"- name: {user_name}",
        "  user:",
        f"    token: {token}",
        "contexts:",
        f"- name: {ctx_name}",
        "  context:",
        f"    cluster: {cluster_name}",
        f"    user: {user_name}",
        f"current-context: {ctx_name}",
        "",
    ]
    content = "\n".join(lines)

    if args.dry_run:
        preview = content.replace(token, "<redacted-token>")
        print(f"Dry run: would renew token in {out}\n")
        print(preview)
        return

    fd = os.open(str(out), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, content.encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(out, 0o600)
    del token, content
    print(f"Renewed token in {out} (mode 0600).")
    print(f"New token duration: {args.duration}. The old token is now invalid.")


def main() -> None:
    parser = argparse.ArgumentParser(description="gal-k8s-safe policy gate")
    parser.add_argument("--context", help="kubectl context")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list-policy", help="print protected namespaces and writable resources")
    p.set_defaults(func=lambda a: print(json.dumps({
        "protected_namespaces": sorted(PROTECTED_NAMESPACES),
        "writable_resources": sorted(set(WRITABLE_RESOURCES)),
        "allowed_write_kinds": sorted(ALLOWED_WRITE_KINDS),
        "restart_resources": sorted(RESTART_RESOURCES),
        "blocked_resource_hints": sorted(DANGEROUS_RESOURCE_HINTS),
        "delete_allowed": False,
        "backup_dir": str(backup_root()),
        "backup_retention_days": DEFAULT_BACKUP_RETENTION_DAYS,
    }, indent=2)))

    p = sub.add_parser("readonly-rbac", help="print or apply cluster-wide read-only RBAC")
    p.add_argument("--service-account", default=DEFAULT_SERVICE_ACCOUNT)
    p.add_argument("--service-account-namespace", default=DEFAULT_SERVICE_ACCOUNT_NAMESPACE)
    p.add_argument("--retention-days", type=int, default=DEFAULT_BACKUP_RETENTION_DAYS)
    p.add_argument("--apply", action="store_true", help="backup existing generated objects, then apply with kubectl")
    p.set_defaults(func=lambda a: apply_yaml(
        readonly_yaml(a.service_account, a.service_account_namespace),
        a.context,
        not a.apply,
        readonly_backup_objects(a.service_account, a.service_account_namespace),
        a.retention_days,
    ))

    p = sub.add_parser("namespace-write-rbac", help="print or apply namespace write Role/RoleBinding")
    p.add_argument("namespace")
    p.add_argument("--service-account", default=DEFAULT_SERVICE_ACCOUNT)
    p.add_argument("--service-account-namespace", default=DEFAULT_SERVICE_ACCOUNT_NAMESPACE)
    p.add_argument("--retention-days", type=int, default=DEFAULT_BACKUP_RETENTION_DAYS)
    p.add_argument("--apply", action="store_true", help="backup existing Role/RoleBinding, then apply with kubectl")
    p.set_defaults(func=lambda a: apply_yaml(
        writer_yaml(a.namespace, a.service_account, a.service_account_namespace),
        a.context,
        not a.apply,
        writer_backup_objects(a.namespace),
        a.retention_days,
    ))

    p = sub.add_parser("backup", help="backup one existing namespace-scoped object")
    p.add_argument("namespace")
    p.add_argument("resource")
    p.add_argument("name")
    p.add_argument("--retention-days", type=int, default=DEFAULT_BACKUP_RETENTION_DAYS)
    p.set_defaults(func=lambda a: backup_object(a.context, a.namespace, a.resource, a.name, a.retention_days))

    p = sub.add_parser("guarded-apply", help="validate, backup each manifest object, then apply")
    p.add_argument("namespace")
    p.add_argument("file", help="manifest path, or - for stdin")
    p.add_argument("--retention-days", type=int, default=DEFAULT_BACKUP_RETENTION_DAYS)
    p.add_argument("--dry-run", action="store_true", help="validate only")
    p.set_defaults(func=guarded_apply)

    p = sub.add_parser("restart", help="backup and rollout restart a workload")
    p.add_argument("namespace")
    p.add_argument("resource", help="deployment, statefulset, or daemonset")
    p.add_argument("name")
    p.add_argument("--retention-days", type=int, default=DEFAULT_BACKUP_RETENTION_DAYS)
    p.add_argument("--dry-run", action="store_true", help="backup only")
    p.set_defaults(func=restart)

    p = sub.add_parser("gen-kubeconfig", help="create a restricted kubeconfig from the SA token and write it to the safe mount path")
    p.add_argument("--service-account", default=DEFAULT_SERVICE_ACCOUNT)
    p.add_argument("--service-account-namespace", default=DEFAULT_SERVICE_ACCOUNT_NAMESPACE)
    p.add_argument("--duration", default=DEFAULT_TOKEN_DURATION, help="SA token duration, e.g. 24h")
    p.add_argument("--out", default=DEFAULT_KUBECONFIG_OUT, help="output kubeconfig path (must not be under ~/.gal)")
    p.add_argument("--dry-run", action="store_true", help="show the kubeconfig with the token redacted; write nothing")
    p.set_defaults(func=gen_kubeconfig)

    p = sub.add_parser("renew-token", help="request a new SA token and rewrite the existing restricted kubeconfig in place")
    p.add_argument("--service-account", default=DEFAULT_SERVICE_ACCOUNT)
    p.add_argument("--service-account-namespace", default=DEFAULT_SERVICE_ACCOUNT_NAMESPACE)
    p.add_argument("--duration", default=DEFAULT_TOKEN_DURATION, help="SA token duration, e.g. 24h")
    p.add_argument("--out", default=DEFAULT_KUBECONFIG_OUT, help="existing kubeconfig path (must not be under ~/.gal)")
    p.add_argument("--dry-run", action="store_true", help="show the new kubeconfig with the token redacted; write nothing")
    p.set_defaults(func=renew_token)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
