"""Build the pinned official Chatto client into private runtime storage."""
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REVISION = "cda6bf54bb5282752169adb376f03081c09f0d89"


def main():
    os.umask(0o077)
    target = ROOT / "runtime/chatto"
    target.mkdir(parents=True, exist_ok=True)
    source = target / "upstream"
    if not source.exists():
        subprocess.run(["git", "clone", "--depth", "1", "--branch", "v0.5.0-beta.19",
                        "https://github.com/chattocorp/chatto.git", str(source)], check=True)
    actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if actual != REVISION:
        raise RuntimeError("Unexpected Chatto revision")
    for name in ("api-types", "chatto-client"):
        package = target / "packages" / name
        package.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source / "packages" / name / "src", package / "src", dirs_exist_ok=True)
        manifest = json.loads((source / "packages" / name / "package.json").read_text())
        manifest.pop("devDependencies", None)
        manifest.pop("scripts", None)
        manifest.pop("peerDependencies", None)
        manifest.pop("peerDependenciesMeta", None)
        if name == "chatto-client":
            manifest["dependencies"]["@chatto/api-types"] = "*"
        (package / "package.json").write_text(json.dumps(manifest, indent=2))
    (target / "package.json").write_text(json.dumps({
        "private": True, "type": "module", "workspaces": ["packages/*"],
        "dependencies": {"esbuild": "0.25.12"},
    }, indent=2))
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("Node 22.13+ and npm must be on PATH")
    subprocess.run([npm, "install", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=target, check=True)
    (target / "entry.ts").write_text(
        "export {createClient} from '@chatto/client';\n"
        "export {UserService, RoomDirectoryService, MessageService, MyAccountService, AssetUploadService} from '@chatto/client/types';\n")
    subprocess.run([str(target / "node_modules/.bin/esbuild"), "entry.ts", "--bundle",
                    "--platform=node", "--format=esm", "--outfile=client.mjs"], cwd=target, check=True)
    print("Chatto client built from " + REVISION)


if __name__ == "__main__":
    main()
