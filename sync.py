#!/usr/bin/env python3
"""공통 레포의 파일을 플러그인 레포에 사본으로 넣는다.

세 플러그인(laighthouse-plugin·laighthouse-plugin-agency·laighthouse-plugin-external)이 함께 쓰는
파일의 원본은 이 레포다. 플러그인은 설치될 때 자기 폴더만 복사되므로 공통 파일을 플러그인 안에
사본으로 두어야 한다. 플러그인 쪽 사본은 손으로 고치지 않는다.

플러그인 레포 루트의 common.json이 가져올 버전(이 레포의 태그)과 파일을 정한다:

    {
      "version": "v4.0.0",
      "targets": [
        {"root": "plugins/laighthouse-agency", "include": ["shared/assets/external_context", "hooks/save_responses.py"]}
      ]
    }

root는 플러그인 폴더(레포 루트 기준), include는 이 레포 안 경로다(폴더면 그 아래 파일 전부).
플러그인 레포 루트에서 실행한다:

    python3 ../laighthouse-plugin-common/sync.py           # version 태그의 파일로 사본을 맞춘다
    python3 ../laighthouse-plugin-common/sync.py --check   # 어긋난 사본만 보여 주고 1로 끝난다
    python3 ../laighthouse-plugin-common/sync.py --dev     # 태그 대신 이 레포의 작업 중인 파일로 맞춘다(배포 전 확인용)
"""
import argparse
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile

COMMON = os.path.dirname(os.path.abspath(__file__))


def read(path):
    with open(path, "rb") as f:
        return f.read()


def export_tag(version, dest):
    """이 레포의 version 태그 내용을 dest에 푼다."""
    try:
        data = subprocess.run(["git", "-C", COMMON, "archive", "--format=tar", version],
                              check=True, capture_output=True).stdout
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"공통 레포에 {version}이 없다 — git -C {COMMON} fetch --tags 로 받아 온다\n"
                         + e.stderr.decode(errors="replace"))
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        # filter 인자는 Python 3.12(일부 패치 버전)부터 있다. 맥 기본 python3(3.9)에는 없다.
        tar.extractall(dest, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))


def expand(source, include):
    """include 경로를 source 안의 파일 목록(상대 경로)으로 펼친다. __pycache__·*.pyc는 뺀다."""
    path = os.path.join(source, include)
    if os.path.isfile(path):
        return [include]
    if not os.path.isdir(path):
        raise SystemExit(f"공통 레포에 없는 경로: {include}")
    found = []
    for dirpath, dirnames, files in os.walk(path):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for f in files:
            if not f.endswith(".pyc"):
                found.append(os.path.relpath(os.path.join(dirpath, f), source).replace(os.sep, "/"))
    return sorted(found)


def plan(source, repo, config):
    """[(종류, 사본 경로, 써야 할 내용)] — 종류는 differs/missing. 사본 경로는 플러그인 레포 기준."""
    out = []
    for target in config["targets"]:
        for include in target["include"]:
            for rel in expand(source, include):
                dst = os.path.normpath(os.path.join(target["root"], rel)).replace(os.sep, "/")
                want = read(os.path.join(source, rel))
                if not os.path.exists(os.path.join(repo, dst)):
                    out.append(("missing", dst, want))
                elif read(os.path.join(repo, dst)) != want:
                    out.append(("differs", dst, want))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="공통 레포의 파일을 플러그인 레포에 사본으로 넣는다")
    ap.add_argument("--repo", default=".", help="플러그인 레포 루트(기본: 현재 폴더)")
    ap.add_argument("--check", action="store_true", help="사본이 공통 레포와 같은지만 확인한다")
    ap.add_argument("--dev", action="store_true", help="태그 대신 공통 레포의 작업 중인 파일을 쓴다")
    args = ap.parse_args(argv)
    config_path = os.path.join(args.repo, "common.json")
    if not os.path.exists(config_path):
        raise SystemExit(f"common.json이 없다: {config_path}")
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    with tempfile.TemporaryDirectory() as tmp:
        if args.dev:
            source = COMMON
        else:
            export_tag(config["version"], tmp)
            source = tmp
        problems = plan(source, args.repo, config)
        label = "작업 중인 파일" if args.dev else config["version"]
        if args.check:
            for kind, dst, _ in problems:
                print(f"{kind}: {dst}")
            if problems:
                print(f"사본이 공통 레포({label})와 어긋났다 — sync.py를 --check 없이 실행해 맞춘다", file=sys.stderr)
                return 1
            return 0
        for _, dst, want in problems:
            path = os.path.join(args.repo, dst)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(want)
            print(f"복사: {dst}")
        print(f"공통 레포({label})에서 {len(problems)}개 복사")
    return 0


if __name__ == "__main__":
    sys.exit(main())
