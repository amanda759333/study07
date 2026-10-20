# -*- coding: utf-8 -*-
# 작성일시: 2026-10-20 20:37 (KST)
"""명단 CSV 읽기(공고 2.6).

나눠 주는 CSV는 엑셀에서 한글이 깨지지 않도록 BOM이 붙은 UTF-8이다. 그냥 utf-8로 읽으면 첫 열 이름이
'\\ufeffstudent_no'가 되어 학번 열을 찾지 못하므로 utf-8-sig로 읽는다. BOM이 없는 파일도 그대로 읽힌다.
"""
import csv
import io
from dataclasses import dataclass

from teamform.service import ADMIN_NO

# [공고 2.2] 역할은 6개
ROLES = ("기획자", "웹 프로그래머", "프론트엔드 디자이너", "테스터", "보고서 작성자", "발표자")
COLUMNS = ["student_no", "name", "main_role", "sub_roles"]


@dataclass(frozen=True)
class RosterRow:
    student_no: str
    name: str
    main_role: str
    sub_roles: tuple[str, ...]


class RosterError(ValueError):
    """명단 CSV가 틀림. errors에 줄 번호가 붙은 이유가 모두 들어 있다."""

    def __init__(self, errors: list[str]):
        super().__init__(errors[0])
        self.errors = errors


def parse_roster(data: bytes) -> list[RosterRow]:
    """명단 CSV를 읽어 학생 목록을 돌려준다. 틀린 곳이 있으면 RosterError."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise RosterError(["UTF-8 파일이 아님(엑셀에서 'CSV UTF-8'로 저장)"]) from None

    lines = csv.reader(io.StringIO(text, newline=""))
    header = [h.strip() for h in next(lines, [])]
    if header != COLUMNS:
        raise RosterError([f"첫 줄은 {','.join(COLUMNS)} 이어야 함"])

    rows: list[RosterRow] = []
    errors: list[str] = []
    seen: dict[str, int] = {}  # 학번 → 처음 나온 줄
    for line_no, cells in enumerate(lines, start=2):
        if not any(c.strip() for c in cells):  # 빈 줄
            continue
        where = f"{line_no}번째 줄"
        if len(cells) != len(COLUMNS):
            # [공고 2.6] 보조 역할이 없으면 마지막 쉼표 뒤를 비워 둔다. 쉼표를 지우면 열이 3개가 되어 틀림
            errors.append(f"{where}: 열이 {len(cells)}개임(4개여야 함. 보조 역할이 없어도 마지막 쉼표는 남김)")
            continue
        student_no, name, main_role, sub_text = (c.strip() for c in cells)
        # [공고 2.6] 보조 역할 2개는 ;로 구분, 없으면 빈칸
        sub_roles = tuple(dict.fromkeys(s.strip() for s in sub_text.split(";") if s.strip()))

        if not student_no:
            errors.append(f"{where}: 학번이 비어 있음")
        elif student_no == ADMIN_NO:
            errors.append(f"{where}: 학번 admin은 관리자용이라 쓸 수 없음")
        elif student_no in seen:
            errors.append(f"{where}: 학번 {student_no}이 {seen[student_no]}번째 줄과 겹침")
        if not name:
            errors.append(f"{where}: 이름이 비어 있음")
        if main_role not in ROLES:  # [공고 2.2] 주 역할 1개, 6개 역할 가운데 하나
            errors.append(f"{where}: 주 역할 '{main_role}'는 6개 역할에 없음")
        for role in sub_roles:
            if role not in ROLES:
                errors.append(f"{where}: 보조 역할 '{role}'는 6개 역할에 없음")
        if len(sub_roles) > 2:  # [공고 2.2] 보조 역할 0~2개
            errors.append(f"{where}: 보조 역할이 {len(sub_roles)}개임(0~2개여야 함)")

        seen.setdefault(student_no, line_no)
        rows.append(RosterRow(student_no, name, main_role, sub_roles))

    if errors:
        raise RosterError(errors)
    if not rows:
        raise RosterError(["학생이 한 명도 없음"])
    return rows
