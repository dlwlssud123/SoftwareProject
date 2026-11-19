"""Package only public recipe/food snapshots and the first-import command."""

import hashlib
import io
import json
import re
import tarfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
INPUTS = {
    "recipes": "data/raw/recipes/cookrcp01_all.json",
    "nutrition": "data/raw/nutrition/foodntr_v03_representative.json",
}
SECRET_FIELDS = {
    "apikey",
    "servicekey",
    "password",
    "authorization",
    "accesstoken",
    "clientsecret",
}


def reject_credentials(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if re.sub(r"[^a-z]", "", key.lower()) in SECRET_FIELDS:
                raise ValueError("Credential-like metadata must not be packaged")
            reject_credentials(item)
    elif isinstance(value, list):
        for item in value:
            reject_credentials(item)
    elif isinstance(value, str) and value.startswith(("http://", "https://")):
        url = urlsplit(value)
        if url.username or url.password:
            raise ValueError("Credentials in a URL must not be packaged")
        reject_credentials(parse_qs(url.query))


def snapshot_info(raw: bytes, kind: str) -> dict:
    data = json.loads(raw.decode("utf-8-sig"))
    meta, items = data["meta"], data["items"]
    if kind not in INPUTS:
        raise ValueError("Unknown snapshot kind")
    valid_source = (
        meta.get("service") == "COOKRCP01"
        if kind == "recipes"
        else meta.get("service") == "식품의약품안전처_식품영양성분DB정보"
        and meta.get("api_version") == "03"
    )
    if not valid_source:
        raise ValueError("Unexpected source service/version")
    if (
        not isinstance(items, list)
        or not items
        or meta.get("complete") is not True
        or meta.get("total_count") != len(items)
        or meta.get("item_count") != len(items)
    ):
        raise ValueError("A complete snapshot with matching counts is required")
    reject_credentials(data)
    options = {"ensure_ascii": False, "sort_keys": True}
    if kind == "recipes":
        options["separators"] = (",", ":")
    actual = hashlib.sha256(json.dumps(items, **options).encode("utf-8")).hexdigest()
    if meta.get("items_sha256") != actual:
        raise ValueError("Snapshot item checksum mismatch")
    return {
        "count": len(items),
        "fetched_at": meta.get("fetched_at"),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def build_bundle(root: Path, output: Path) -> dict:
    payloads, manifest = {}, {}
    for kind, name in INPUTS.items():
        raw = (root / name).read_bytes()
        manifest[kind] = snapshot_info(raw, kind)
        payloads[name] = raw
    payloads["seed-first.sh"] = (
        (root / "deploy/seed-first.sh").read_bytes().replace(b"\r\n", b"\n")
    )
    payloads["seed.compose.yaml"] = (
        (root / "deploy/seed.compose.yaml").read_bytes().replace(b"\r\n", b"\n")
    )
    payloads["snapshots.sha256"] = "".join(
        f"{manifest[kind]['sha256']}  {name}\n" for kind, name in INPUTS.items()
    ).encode("ascii")
    payloads["manifest.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Publish only a complete archive; a failed build keeps the previous bundle.
    pending = output.with_suffix(output.suffix + ".pending")
    with tarfile.open(pending, "w:gz") as archive:
        for name, raw in payloads.items():
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            info.mode = 0o700 if name.endswith(".sh") else 0o600
            archive.addfile(info, io.BytesIO(raw))
    pending.replace(output)
    return manifest


if __name__ == "__main__":
    destination = ROOT / "dist/valueflow-initial-data.tar.gz"
    print(json.dumps(build_bundle(ROOT, destination), ensure_ascii=False, indent=2))
    print(f"Ready: {destination} ({destination.stat().st_size // 1024} KiB)")
