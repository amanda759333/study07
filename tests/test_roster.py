# -*- coding: utf-8 -*-
# 작성일시: 2026-10-20 20:37 (KST)
"""#7 명단 CSV 읽기. 공고 2.6: BOM이 붙은 UTF-8이므로 utf-8-sig로 읽는다."""
import csv
import io

import pytest

from teamform.roster import RosterError, RosterRow, parse_roster

# 공고 2.6절의 예시 그대로
NOTICE_EXAMPLE = (
    "student_no,name,main_role,sub_roles\n"
    "2026001,가나다,기획자,보고서 작성자\n"
    "2026002,라마바,웹 프로그래머,\n"
    "2026003,사아자,테스터,기획자;발표자\n"
)

# 공고 부록 1(쉬움)의 명단
EASY = (
    "student_no,name,main_role,sub_roles\r\n"
    "2026101,학생1,기획자,보고서 작성자\r\n"
    "2026102,학생2,기획자,발표자\r\n"
    "2026103,학생3,기획자,테스터\r\n"
    "2026104,학생4,웹 프로그래머,프론트엔드 디자이너\r\n"
    "2026105,학생5,웹 프로그래머,\r\n"
    "2026106,학생6,웹 프로그래머,테스터\r\n"
    "2026107,학생7,프론트엔드 디자이너,발표자\r\n"
    "2026108,학생8,테스터,보고서 작성자;발표자\r\n"
)


def excel_bytes(text: str) -> bytes:
    """엑셀이 저장한 CSV처럼 BOM이 붙은 UTF-8."""
    return text.encode("utf-8-sig")


def errors_of(data: bytes) -> list[str]:
    with pytest.raises(RosterError) as info:
        parse_roster(data)
    return info.value.errors


# utf-8-sig로 읽기 ------------------------------------------------------------

def test_bom_file_reads_like_plain_file():
    with_bom = parse_roster(excel_bytes(NOTICE_EXAMPLE))
    without_bom = parse_roster(NOTICE_EXAMPLE.encode("utf-8"))
    assert with_bom == without_bom
    assert with_bom[0].student_no == "2026001"


def test_plain_utf8_would_break_first_column():
    """utf-8로만 읽으면 첫 열 이름 앞에 BOM이 남아 student_no를 찾지 못한다(utf-8-sig가 필요한 이유)."""
    header = next(csv.reader(io.StringIO(excel_bytes(NOTICE_EXAMPLE).decode("utf-8"))))
    assert header[0] == "﻿student_no"
    assert header[0] != "student_no"


def test_notice_example_rows():
    rows = parse_roster(excel_bytes(NOTICE_EXAMPLE))
    assert rows == [
        RosterRow("2026001", "가나다", "기획자", ("보고서 작성자",)),
        RosterRow("2026002", "라마바", "웹 프로그래머", ()),
        RosterRow("2026003", "사아자", "테스터", ("기획자", "발표자")),
    ]


def test_easy_scenario_roster_with_excel_line_endings():
    rows = parse_roster(excel_bytes(EASY))
    assert len(rows) == 8
    assert rows[4] == RosterRow("2026105", "학생5", "웹 프로그래머", ())
    assert rows[7].sub_roles == ("보고서 작성자", "발표자")


def test_spaces_and_blank_lines_are_ignored():
    text = "student_no,name,main_role,sub_roles\n 2026001 , 가나다 , 기획자 , 테스터 ; 발표자 \n\n"
    assert parse_roster(excel_bytes(text)) == [RosterRow("2026001", "가나다", "기획자", ("테스터", "발표자"))]


# 틀린 CSV ------------------------------------------------------------------

def test_wrong_header():
    errs = errors_of(excel_bytes("학번,이름,주역할,보조역할\n2026001,가나다,기획자,\n"))
    assert "첫 줄" in errs[0]


def test_missing_last_comma_makes_three_columns():
    """공고 2.6: 보조 역할이 없을 때 마지막 쉼표를 지우면 열이 3개가 되어 CSV가 틀림."""
    errs = errors_of(excel_bytes("student_no,name,main_role,sub_roles\n2026002,라마바,웹 프로그래머\n"))
    assert errs == ["2번째 줄: 열이 3개임(4개여야 함. 보조 역할이 없어도 마지막 쉼표는 남김)"]


def test_role_outside_six_roles():
    errs = errors_of(excel_bytes("student_no,name,main_role,sub_roles\n2026001,가나다,디자이너,\n"))
    assert errs == ["2번째 줄: 주 역할 '디자이너'는 6개 역할에 없음"]


def test_sub_role_outside_six_roles():
    errs = errors_of(excel_bytes("student_no,name,main_role,sub_roles\n2026001,가나다,기획자,요리사\n"))
    assert errs == ["2번째 줄: 보조 역할 '요리사'는 6개 역할에 없음"]


def test_three_sub_roles():
    errs = errors_of(excel_bytes("student_no,name,main_role,sub_roles\n2026001,가나다,기획자,테스터;발표자;보고서 작성자\n"))
    assert errs == ["2번째 줄: 보조 역할이 3개임(0~2개여야 함)"]


def test_duplicate_student_no():
    errs = errors_of(excel_bytes("student_no,name,main_role,sub_roles\n2026001,가나다,기획자,\n2026001,라마바,테스터,\n"))
    assert errs == ["3번째 줄: 학번 2026001이 2번째 줄과 겹침"]


def test_admin_student_no_is_reserved():
    errs = errors_of(excel_bytes("student_no,name,main_role,sub_roles\nadmin,가나다,기획자,\n"))
    assert errs == ["2번째 줄: 학번 admin은 관리자용이라 쓸 수 없음"]


def test_empty_values():
    errs = errors_of(excel_bytes("student_no,name,main_role,sub_roles\n,가나다,기획자,\n2026002,,테스터,\n"))
    assert errs == ["2번째 줄: 학번이 비어 있음", "3번째 줄: 이름이 비어 있음"]


def test_no_students():
    assert errors_of(excel_bytes("student_no,name,main_role,sub_roles\n")) == ["학생이 한 명도 없음"]


def test_not_utf8_file():
    """엑셀에서 'CSV(쉼표로 분리)'로 저장해 한글이 CP949가 된 파일."""
    errs = errors_of("student_no,name,main_role,sub_roles\n2026001,가나다,기획자,\n".encode("cp949"))
    assert errs == ["UTF-8 파일이 아님(엑셀에서 'CSV UTF-8'로 저장)"]
