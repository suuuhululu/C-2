#!/usr/bin/env python3
"""절대 경로 금지 규칙 시험 — 통합 시험·최종은 PC 한 대에서 돌리므로 코드와 데이터 파일에 고정 경로를 넣지 않는다.

폴더는 명령 인자·ROS 파라미터·환경 변수로 받고, 저장소 안 파일은 소스 위치(__file__) 기준 상대 경로로 찾는다.
"""
import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 파일 시스템 절대 경로처럼 보이는 문자열: 유닉스 고정 폴더, 홈, 윈도 드라이브, file:// URL
ABSOLUTE = re.compile(r"^(?:/(?:home|Users|mnt|tmp|root|opt|var|etc|usr|srv|media)(?:/|$)|~[/\\]|[A-Za-z]:[\\/]|file://)")
# 데이터 파일 안에서는 값 중간에 나와도 잡는다 (예: "path": "/home/roh/x.png")
EMBEDDED = re.compile(r"(?:\"|')(?:/(?:home|Users|mnt|tmp|root|opt|var|etc|usr|srv|media)/|[A-Za-z]:[\\/]|file://)")

SOURCE_FILES = sorted([*ROOT.glob("c2_path/*.py"), *ROOT.glob("*.py")])
DATA_FILES = sorted(p for p in (ROOT / "samples").rglob("*") if p.is_file() and p.suffix in (".json", ".svg", ".md", ".yaml"))


def string_constants(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            yield node.lineno, node.value


class TestNoAbsolutePaths(unittest.TestCase):
    def test_source_files_are_found(self):
        names = {p.name for p in SOURCE_FILES}
        self.assertIn("bundle.py", names)
        self.assertIn("pipeline.py", names)
        self.assertIn("build_bundle_samples.py", names)

    def test_no_hardcoded_absolute_paths_in_source(self):
        found = [f"{p.relative_to(ROOT)}:{line}: {value!r}"
                 for p in SOURCE_FILES for line, value in string_constants(p) if ABSOLUTE.match(value)]
        self.assertEqual(found, [], "코드에 고정 경로가 있음 — 명령 인자·파라미터·환경 변수·__file__ 상대 경로를 쓸 것")

    def test_sample_data_has_no_absolute_paths(self):
        self.assertTrue(DATA_FILES, "samples 가 비어 있음")
        found = []
        for path in DATA_FILES:
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if EMBEDDED.search(line):
                    found.append(f"{path.relative_to(ROOT)}:{number}")
        self.assertEqual(found, [], "샘플 데이터에 절대 경로가 있음")

    def test_bundle_manifest_files_are_bare_names(self):
        import json
        manifests = sorted((ROOT / "samples" / "bundles").glob("*/*/manifest.json"))
        self.assertGreaterEqual(len(manifests), 4)
        for path in manifests:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            for entry in [*manifest["files"], *manifest["documents"]]:
                self.assertEqual(entry["file"], Path(entry["file"]).name, path)
                self.assertFalse(Path(entry["file"]).is_absolute(), path)

    def test_relative_input_output_dirs_work_from_any_working_folder(self):
        # 명령을 실행한 폴더 기준 상대 경로로 묶음을 읽고 쓸 수 있어야 한다 (절대 경로 없이 PC 한 대에서 돌리기).
        import os
        import shutil
        import tempfile
        from c2_path import bundle
        source = ROOT / "samples" / "bundles" / "heart_ok" / "input"
        with tempfile.TemporaryDirectory() as workdir:
            shutil.copytree(source, Path(workdir) / "in")
            previous = os.getcwd()
            os.chdir(workdir)
            try:
                result = bundle.run_bundle("in", "out")
                self.assertTrue(result["success"], result)
                self.assertEqual(bundle.verify_bundle("out"), [])
                manifest_text = (Path("out") / "manifest.json").read_text(encoding="utf-8")
                self.assertNotIn(workdir, manifest_text)
                for name in ("result.json", "request.json", "c2-path.json"):
                    self.assertNotIn(workdir, (Path("out") / name).read_text(encoding="utf-8"), name)
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main(verbosity=2)
