"""hooks/ad_performance_domain.py — get_ad_performance 응답 뒤에 도메인 규칙을 세션당 한 번씩 넣는지 검사한다."""

import json
import os
import subprocess
import sys
import uuid

HOOK = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hooks", "ad_performance_domain.py"))


def envelope(*media):
    return json.dumps({"dimensions": ["media"], "metrics": ["cost"], "rows": [{"media": m, "cost": 1} for m in media]})


def run(session, text, group_by=("media",), filters=None):
    """훅을 실행해 모델에게 붙는 additionalContext를 돌려준다. 출력이 없으면 None."""
    inp = {"session_id": session, "tool_name": "mcp__laighthouse__get_ad_performance",
           "tool_input": {"group_by": list(group_by), "filters": filters},
           "tool_response": [{"type": "text", "text": text}]}
    out = subprocess.run([sys.executable, HOOK], input=json.dumps(inp), capture_output=True,
                         text=True, encoding="utf-8", check=True).stdout
    if not out:
        return None
    hso = json.loads(out)["hookSpecificOutput"]
    assert hso["hookEventName"] == "PostToolUse"
    assert "updatedToolOutput" not in hso   # 응답 자체는 바꾸지 않는다(캡처 훅과 충돌 금지)
    return hso["additionalContext"]


def test_first_call_sends_common_rules_and_only_matching_media_sections():
    ctx = run(uuid.uuid4().hex, envelope("네이버 브랜드검색", "Meta"))
    assert "집행 도중 예산(계약 금액)을 바꿀 수 없다" in ctx          # BRS 계약형 규칙
    assert "## \"광고집행 상품명\"과 \"매출발생 상품명\"을 섞지 않는다" in ctx
    assert "## 네이버" in ctx and "## 메타(페이스북·인스타그램)" in ctx
    assert "## 쿠팡" not in ctx and "## 구글·유튜브" not in ctx and "## 틱톡" not in ctx


def test_sources_in_html_comments_are_not_sent_to_the_model():
    ctx = run(uuid.uuid4().hex, envelope("google"))
    assert "<!--" not in ctx and "출처" not in ctx and "match:" not in ctx


def test_same_session_sends_each_section_once_and_new_media_later():
    session = uuid.uuid4().hex
    run(session, envelope("naver_sa"))
    again = run(session, envelope("naver_sa"))
    assert "## " not in again and "계속 지킨다" in again             # 이미 보낸 절은 다시 보내지 않는다
    later = run(session, envelope("naver_sa", "쿠팡"))
    assert "## 쿠팡" in later
    assert "## 네이버" not in later and "## 계약형 상품" not in later


def test_other_session_gets_rules_again():
    run(uuid.uuid4().hex, envelope("tiktok"))
    assert "## 틱톡" in run(uuid.uuid4().hex, envelope("tiktok"))


def test_total_call_without_media_rows_uses_media_filter():
    total = json.dumps({"dimensions": [], "metrics": ["cost"], "rows": [{"cost": 1}]})
    ctx = run(uuid.uuid4().hex, total, group_by=(), filters={"media": ["Google Ads"]})
    assert "## 구글·유튜브" in ctx and "## 네이버" not in ctx


def test_mixing_ad_and_sales_product_dimensions_warns_every_call():
    session = uuid.uuid4().hex
    dims = ("광고집행 상품명", "매출발생 상품명")
    assert "⚠️" in run(session, envelope("meta"), group_by=dims)
    assert "⚠️" in run(session, envelope("meta"), group_by=dims)      # 세션 중복 제거와 관계없이 매번
    assert "⚠️" not in run(session, envelope("meta"), group_by=("광고집행 상품명",))


def test_bad_input_prints_nothing():
    out = subprocess.run([sys.executable, HOOK], input="not json", capture_output=True, text=True, check=True).stdout
    assert out == ""
