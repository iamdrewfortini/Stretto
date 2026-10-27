#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Release builder. From a CLEAN git tree: runs the release checks, builds one wheel (+ sdist) per package with SOURCE_DATE_EPOCH = the commit time, builds the Rust crates with
`--locked`, writes a hash-pinned requirements.lock, a CycloneDX SBOM, MANIFEST.json and SHA256SUMS (optionally signed with OpenSSH), and packs a deterministic bundle.
Usage: python scripts/package.py [--out dist] [--sign-key KEY] [--skip-rust] [--allow-dirty]"""
import argparse, glob, gzip, hashlib, io, json, os, platform, shutil, subprocess, sys, tarfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
def sh(cmd, **kw): print("+", " ".join(cmd), flush=True); return subprocess.run(cmd, check=True, **kw)
def out(cmd, **kw): return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw).stdout.strip()
def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", default="dist"); ap.add_argument("--sign-key"); ap.add_argument("--skip-rust", action="store_true"); ap.add_argument("--allow-dirty", action="store_true"); a = ap.parse_args()
    version = open(os.path.join(ROOT, "VERSION")).read().strip(); os.chdir(ROOT)
    if not a.allow_dirty and out(["git", "status", "--porcelain"]): sys.exit("refusing to package a dirty tree (commit first, or pass --allow-dirty for a non-release build)")
    commit = out(["git", "rev-parse", "HEAD"]); sde = out(["git", "log", "-1", "--format=%ct"]); env = dict(os.environ, SOURCE_DATE_EPOCH=sde)
    sh([sys.executable, "scripts/release_check.py"])
    dist = os.path.join(ROOT, a.out); name = f"metacoh-{version}"; bundle = os.path.join(dist, name)
    shutil.rmtree(dist, ignore_errors=True)
    for d in ("wheelhouse", "native/lib/pkgconfig", "native/include", "installer", "docs"): os.makedirs(os.path.join(bundle, d), exist_ok=True)
    os.makedirs(os.path.join(dist, "sdist"))
    pk = sorted(d for d in os.listdir(os.path.join(ROOT, "packages")) if os.path.isdir(os.path.join(ROOT, "packages", d)))
    import tempfile
    for p in pk:                                    # build from a clean temporary copy: building in place would write build/ and *.egg-info into the tree and dirty it
        with tempfile.TemporaryDirectory() as tmp:
            work = os.path.join(tmp, p); shutil.copytree(os.path.join(ROOT, "packages", p), work, ignore=shutil.ignore_patterns("build", "*.egg-info", "__pycache__", "dist"))
            sh([sys.executable, "-m", "build", "--wheel", "--outdir", os.path.join(bundle, "wheelhouse"), work], env=env)
            sh([sys.executable, "-m", "build", "--sdist", "--outdir", os.path.join(dist, "sdist"), work], env=env)
    wheels = sorted(glob.glob(os.path.join(bundle, "wheelhouse", "*.whl")))
    with open(os.path.join(bundle, "wheelhouse", "requirements.lock"), "w") as f:
        for w in wheels:
            n, v = os.path.basename(w).split("-")[:2]; f.write(f"{n.replace('_', '-')}=={v} --hash=sha256:{sha256(w)}\n")
    native = []
    if not a.skip_rust:
        sh(["cargo", "build", "--release", "--locked", "--manifest-path", os.path.join(ROOT, "crates", "Cargo.toml")], env=dict(env, RUSTFLAGS=f"--remap-path-prefix={ROOT}=/src"))
        for lib in ("wf13d_core", "ant"):
            for ext in ("so", "a"):
                src = os.path.join(ROOT, "crates", "target", "release", f"lib{lib}.{ext}")
                if os.path.exists(src): shutil.copy2(src, os.path.join(bundle, "native", "lib")); native.append(f"lib{lib}.{ext}")
        for h in glob.glob(os.path.join(ROOT, "crates", "include", "*.h")): shutil.copy2(h, os.path.join(bundle, "native", "include"))
        for lib, desc in (("wf13d-core", "WF-13D bridge arithmetic"), ("ant", "Langton's ant to lock")):
            open(os.path.join(bundle, "native", "lib", "pkgconfig", f"{lib}.pc"), "w").write(
                f"prefix=@PREFIX@\nlibdir=${{prefix}}/lib\nincludedir=${{prefix}}/include\n\nName: {lib}\nDescription: {desc}\nVersion: {version}\nLibs: -L${{libdir}} -l{lib.replace('-', '_')}\nCflags: -I${{includedir}}\n")
    for src, dst in (("installer/install.sh", "installer/install.sh"), ("installer/install.ps1", "installer/install.ps1"), ("docs/PACKAGING.md", "docs/PACKAGING.md"), ("LICENSE", "LICENSE"), ("NOTICE", "NOTICE"), ("THIRD_PARTY.md", "THIRD_PARTY.md")):
        shutil.copy2(os.path.join(ROOT, src), os.path.join(bundle, dst))
    os.chmod(os.path.join(bundle, "installer", "install.sh"), 0o755)
    deps = {p: open(os.path.join(ROOT, "packages", p, "DEPS")).read().split() for p in pk}
    comps = [{"type": "library", "bom-ref": f"metacoh-{p}", "name": f"metacoh-{p}", "version": version, "licenses": [{"license": {"id": "Apache-2.0"}}], "purl": f"pkg:pypi/metacoh-{p}@{version}"} for p in pk]
    comps += [{"type": "library", "bom-ref": "cryptography", "name": "cryptography", "scope": "optional", "licenses": [{"expression": "Apache-2.0 OR BSD-3-Clause"}], "purl": "pkg:pypi/cryptography"},
              {"type": "library", "bom-ref": "rust-std", "name": "rust-std", "scope": "required", "licenses": [{"expression": "MIT OR Apache-2.0"}], "description": "statically linked into the native artifacts"}]
    sbom = {"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1, "metadata": {"component": {"type": "application", "name": "metacoh", "version": version}},
            "components": comps, "dependencies": [{"ref": f"metacoh-{p}", "dependsOn": [f"metacoh-{d}" for d in deps[p]]} for p in pk]}
    json.dump(sbom, open(os.path.join(bundle, "SBOM.cdx.json"), "w"), indent=1, sort_keys=True)
    json.dump({"name": "metacoh", "version": version, "commit": commit, "source_date_epoch": int(sde), "python": platform.python_version(), "platform": f"{platform.system().lower()}-{platform.machine()}", "native": native,
               "wheels": [os.path.basename(w) for w in wheels]}, open(os.path.join(bundle, "MANIFEST.json"), "w"), indent=1, sort_keys=True)
    files = sorted(os.path.relpath(os.path.join(dp, f), bundle).replace(os.sep, "/") for dp, _, fs in os.walk(bundle) for f in fs if f not in ("SHA256SUMS", "SHA256SUMS.sig"))
    open(os.path.join(bundle, "SHA256SUMS"), "w").write("".join(f"{sha256(os.path.join(bundle, f))}  {f}\n" for f in files))
    if a.sign_key: sh(["ssh-keygen", "-Y", "sign", "-q", "-f", a.sign_key, "-n", "file", os.path.join(bundle, "SHA256SUMS")])
    tar_path = os.path.join(dist, f"{name}-{platform.system().lower()}-{platform.machine()}.tar.gz"); mtime = int(sde)
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as t:
        for dp, dn, fs in os.walk(bundle):
            dn.sort()
            for f in sorted(fs) + [""]:
                p = os.path.join(dp, f) if f else dp; ti = t.gettarinfo(p, arcname=os.path.join(name, os.path.relpath(p, bundle)).rstrip("/.")); ti.mtime = mtime; ti.uid = ti.gid = 0; ti.uname = ti.gname = ""
                if ti.isdir(): ti.mode = 0o755
                if ti.isfile():
                    ti.mode = 0o755 if (os.stat(p).st_mode & 0o111) else 0o644
                    with open(p, "rb") as fh: t.addfile(ti, fh)
                else: t.addfile(ti)
    with open(tar_path, "wb") as fo, gzip.GzipFile(fileobj=fo, mode="wb", mtime=mtime) as gz: gz.write(raw.getvalue())
    print(f"\nbundle  {tar_path}\nsha256  {sha256(tar_path)}\nwheels  {len(wheels)}   native  {native or 'skipped'}   signed  {bool(a.sign_key)}")

if __name__ == "__main__": main()
