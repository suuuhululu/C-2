"""Check authored text and simple relative Markdown links without executing code."""

import ast
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^\]\n]+\]\(([^\s)]+)\)")


def main():
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    names = sorted(set(result.stdout.decode("utf-8").split("\0")) - {""})
    errors = []
    checked = 0
    for name in names:
        path = ROOT / name
        if not path.is_file():
            continue
        if path.suffix not in {".md", ".py", ".sh", ".yml", ".yaml"} and name != ".githooks/pre-push":
            continue
        checked += 1
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeError as error:
            errors.append(f"{name}: UTF-8 읽기 실패: {error}")
            continue
        for number, line in enumerate(content.splitlines(), 1):
            if line.rstrip() != line:
                errors.append(f"{name}:{number}: 줄 끝 공백")
            if line.startswith(("<<<<<<< ", ">>>>>>> ")) or line == "=======":
                errors.append(f"{name}:{number}: 병합 충돌 표시")
        if content and not content.endswith("\n"):
            errors.append(f"{name}: 파일 끝 개행 없음")
        if path.suffix == ".py":
            try:
                ast.parse(content, filename=name)
            except SyntaxError as error:
                errors.append(f"{name}: {error}")
        if path.suffix == ".md":
            for link in LINK.findall(content):
                parsed = urlsplit(link)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                target = (path.parent / unquote(parsed.path)).resolve()
                if not target.is_relative_to(ROOT) or not target.exists():
                    errors.append(f"{name}: 누락 또는 저장소 외부 문서 링크: {link}")
    if errors:
        print("\n".join(errors))
        return 1
    print(f"통과: 텍스트·Python 구문·상대 문서 링크 ({checked}개 파일). ROS/실기 검증 아님.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
