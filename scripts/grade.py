#!/usr/bin/env python3
"""grade.py — 맡긴 일이 돌아왔을 때 기계가 먼저 채점한다.

`HOW.md` 3절 「돌아온 것은 기계가 먼저 채점하고, 지휘하는 쪽은 낙제만 본다」의 장치.
합격표(JSON)에 적힌 검사만 돌리고, 통과·낙제를 찍는다.

사용:
    python scripts/grade.py <합격표.json>
    python scripts/grade.py <합격표.json> --dry-run   # 돌리지 않고 무엇을 돌릴지만 본다
    python scripts/grade.py <합격표.json> --quiet     # 낙제만 출력

종료 코드: 전부 통과 0 · 하나라도 낙제 1 · 합격표 자체가 잘못됨 2

## 왜 표준 라이브러리만 쓰나

이 저장소는 도구(클로드·코덱스·커서)와 기기(윈도우·맥)를 가리지 않는 공용 정본이다.
바깥 꾸러미를 하나라도 쓰면 「깔린 파이썬과 부르는 파이썬이 다른」 상태에서 조용히 죽는다.
2026-09-07 에 그 병을 하루에 세 번 봤다(mem0·numpy·기억 백업). 그래서 여기엔 안 들인다.

## 안전

돌리는 명령은 **합격표에 적힌 것뿐**이다. 스스로 명령을 지어내지 않는다.
합격표는 일을 맡기는 쪽이 쓰고, 돌아온 쪽이 고칠 수 없다(고쳤으면 그건 채점이 아니다).
돌리기 전에 무엇을 돌리는지 항상 찍는다 — `--dry-run` 으로 미리 볼 수 있다.
"""

import json
import os
import subprocess
import sys

TIMEOUT_DEFAULT = 300  # 검사 하나당 최대 5분


def fail(msg, code=2):
    print(f"[합격표 오류] {msg}")
    sys.exit(code)


def load(path):
    if not os.path.exists(path):
        fail(f"파일이 없다: {path}")
    try:
        with open(path, encoding="utf-8") as f:
            sheet = json.load(f)
    except json.JSONDecodeError as e:
        fail(f"JSON 이 깨졌다: {e}")
    checks = sheet.get("checks")
    if not isinstance(checks, list) or not checks:
        fail("`checks` 가 비어 있다. 검사가 없는 합격표는 채점이 아니다.")
    return sheet


def read_text(path):
    """텍스트를 읽는다. 인코딩이 무엇이든 죽지 않는다."""
    with open(path, "rb") as f:
        return f.read().decode("utf-8", errors="replace")


def run_check(c, dry):
    """검사 하나를 돌린다 → (통과여부, 사유)"""
    name = c.get("name", "(이름 없음)")

    # ① 명령을 돌린다
    if "run" in c:
        cmd = c["run"]
        if dry:
            extra = " (stdin 있음)" if "stdin" in c else ""
            return None, f"돌릴 명령: {cmd}{extra}"
        try:
            p = subprocess.run(
                cmd, shell=True, capture_output=True,
                timeout=c.get("timeout", TIMEOUT_DEFAULT),
                cwd=c.get("cwd") or None,
                # 파이프(`echo ... | prog`)를 쓰지 말고 여기로 넣는다.
                # shell=True 는 윈도우에서 cmd.exe, 맥·리눅스에서 sh 라 따옴표 처리가 서로 다르다.
                # 2026-09-07 첫 판에서 실제로 물렸다 — cmd.exe 가 JSON 따옴표를 먹어
                # **종료 코드는 0인데 출력이 비었다**. 출력까지 안 봤으면 통과로 찍혔을 것이다.
                input=c["stdin"].encode("utf-8") if "stdin" in c else None,
            )
        except subprocess.TimeoutExpired:
            return False, f"시간 초과 ({c.get('timeout', TIMEOUT_DEFAULT)}초)"
        out = (p.stdout + p.stderr).decode("utf-8", errors="replace")

        want_exit = c.get("expect_exit", 0)
        if p.returncode != want_exit:
            head = out.strip().splitlines()[-3:] if out.strip() else ["(출력 없음)"]
            return False, f"종료 코드 {p.returncode} (기대 {want_exit}) · " + " / ".join(head)

        # 종료 코드만 보면 「조용한 성공」을 놓친다. 기대 출력이 없는 검사는 그 사실을 알린다.
        if "expect_stdout" not in c and not out.strip():
            return False, "종료 코드는 통과인데 출력이 비었다 — 정말 돌았는지 `expect_stdout` 으로 못박아라"

        if "expect_stdout" in c and c["expect_stdout"] not in out:
            return False, f"출력에 「{c['expect_stdout']}」 가 없다"
        if "reject_stdout" in c and c["reject_stdout"] in out:
            return False, f"출력에 「{c['reject_stdout']}」 가 있다"
        return True, ""

    # ② 산출물이 실제로 있는지 본다 — 「됐습니다」 말고 실물
    if "exists" in c:
        if dry:
            return None, f"있는지 볼 자리: {c['exists']}"
        return (True, "") if os.path.exists(c["exists"]) else (False, f"없다: {c['exists']}")

    # ③ 파일 안에 있어야 할 것 / 없어야 할 것
    for key, want in (("contains", True), ("absent", False)):
        if key in c:
            path = c.get("file")
            if not path:
                return False, f"`{key}` 를 쓰려면 `file` 도 있어야 한다"
            if dry:
                return None, f"{path} 안에서 「{c[key]}」 를 {'찾는다' if want else '없는지 본다'}"
            if not os.path.exists(path):
                return False, f"파일이 없다: {path}"
            found = c[key] in read_text(path)
            if found is want:
                return True, ""
            return False, (f"「{c[key]}」 가 없다" if want else f"「{c[key]}」 가 아직 있다") + f" — {path}"

    return False, "검사 종류를 모르겠다 (run · exists · contains · absent 중 하나여야 한다)"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    quiet = "--quiet" in sys.argv
    if not args:
        print(__doc__.split("사용:")[1].split("종료 코드")[0].strip())
        sys.exit(2)

    sheet = load(args[0])
    checks = sheet["checks"]

    if not quiet:
        print(f"채점: {sheet.get('task', '(제목 없음)')}")
        if sheet.get("id"):
            print(f"  표 번호 {sheet['id']}")
        print()

    failed = []
    for i, c in enumerate(checks, 1):
        ok, why = run_check(c, dry)
        name = c.get("name", "(이름 없음)")
        if dry:
            print(f"  {i}. {name}\n     {why}")
            continue
        if ok:
            if not quiet:
                print(f"  O {i}. {name}")
        else:
            failed.append((i, name, why))
            print(f"  X {i}. {name}\n       {why}")

    if dry:
        print(f"\n(미리보기 — 아무것도 돌리지 않았다. 검사 {len(checks)}개)")
        sys.exit(0)

    print()
    if failed:
        print(f"낙제 {len(failed)} / {len(checks)}")
        sys.exit(1)
    print(f"전부 통과 ({len(checks)}개)")
    sys.exit(0)


if __name__ == "__main__":
    main()
