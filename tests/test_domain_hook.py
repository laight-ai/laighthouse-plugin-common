"""hooks/ad_performance_domain.py — get_ad_performance 응답 뒤에 도메인 규칙을 세션당 한 번씩 넣는지 검사한다."""

import json
import os
import subprocess
import sys
import uuid

import pytest

HOOK = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hooks", "ad_performance_domain.py"))


@pytest.fixture(autouse=True)
def state_dir(tmp_path, monkeypatch):
    """세션 상태 파일을 시스템 temp가 아닌 테스트 폴더에 둔다(subprocess가 환경변수를 물려받는다)."""
    monkeypatch.setenv("LAIGHTHOUSE_DOMAIN_HOOK_STATE", str(tmp_path / "state"))
    return tmp_path


def envelope(*media):
    return json.dumps({"dimensions": ["media"], "metrics": ["cost"], "rows": [{"media": m, "cost": 1} for m in media]})


def run(session, text, group_by=("media",), filters=None, agent_id=None):
    """훅을 실행해 모델에게 붙는 additionalContext를 돌려준다. 출력이 없으면 None."""
    inp = {"session_id": session, "hook_event_name": "PostToolUse", "tool_name": "mcp__laighthouse__get_ad_performance",
           "tool_input": {"group_by": group_by if isinstance(group_by, str) else list(group_by), "filters": filters},
           "tool_response": [{"type": "text", "text": text}]}
    if agent_id:
        inp["agent_id"] = agent_id
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
    assert "계약 기간 중에는 예산(계약 금액)을 바꿀 수 없다" in ctx    # BRS 계약형 규칙
    assert "## \"광고집행 상품명\"과 \"매출발생 상품명\"을 섞지 않는다" in ctx
    assert "## 네이버" in ctx and "## 메타(페이스북·인스타그램)" in ctx
    assert "## 쿠팡" not in ctx and "## 구글·유튜브" not in ctx and "## 틱톡" not in ctx


def test_sources_in_html_comments_are_not_sent_to_the_model():
    ctx = run(uuid.uuid4().hex, envelope("google"))
    assert "<!--" not in ctx and "https://" not in ctx and "match:" not in ctx


def test_same_session_sends_each_section_once_and_new_media_later():
    session = uuid.uuid4().hex
    run(session, envelope("naver_sa"))
    again = run(session, envelope("naver_sa"))
    assert "## " not in again and "계속 지킨다" in again             # 이미 보낸 절은 다시 보내지 않는다
    titles = again[again.index("규칙(") + 3:again.index(")을 계속")].split(", ")
    assert "네이버" in titles and "쿠팡" not in titles                 # 알림은 실제로 보낸 절 제목으로 만든다
    later = run(session, envelope("naver_sa", "쿠팡"))
    assert "## 쿠팡" in later
    assert "## 네이버" not in later and "## 계약형 상품" not in later


def test_other_session_gets_rules_again():
    run(uuid.uuid4().hex, envelope("tiktok"))
    assert "## 틱톡" in run(uuid.uuid4().hex, envelope("tiktok"))


def test_naver_alias_without_naver_in_media_value_still_gets_naver_rules():
    # 매체 값에 naver·gfa 없이 ADVoost 오표기만 들어와도 네이버 절이 빠지면 안 된다
    ctx = run(uuid.uuid4().hex, envelope("Adboost 쇼핑"))
    assert "## 네이버" in ctx and "## 쿠팡" not in ctx


def test_total_call_without_media_rows_uses_media_filter():
    total = json.dumps({"dimensions": [], "metrics": ["cost"], "rows": [{"cost": 1}]})
    ctx = run(uuid.uuid4().hex, total, group_by=(), filters={"media": ["Google Ads"]})
    assert "## 구글·유튜브" in ctx and "## 네이버" not in ctx


def test_media_filter_given_as_single_string():
    total = json.dumps({"rows": [{"cost": 1}]})
    assert "## 쿠팡" in run(uuid.uuid4().hex, total, group_by=(), filters={"media": "Coupang"})


def test_host_spill_file_is_read_for_media(state_dir):
    # 호스트가 큰 응답을 파일로 빼고 안내문만 넘겨도 그 파일의 media로 매체 절을 고른다
    spill = state_dir / "out.txt"
    spill.write_text(envelope("TikTok"), encoding="utf-8")
    ctx = run(uuid.uuid4().hex, f"Output has been saved to {spill}")
    assert "## 틱톡" in ctx and "## 네이버" not in ctx


def test_mixing_ad_and_sales_product_dimensions_warns_every_call():
    session = uuid.uuid4().hex
    dims = ("광고집행 상품명", "매출발생 상품명")
    assert "⚠️" in run(session, envelope("meta"), group_by=dims)
    assert "⚠️" in run(session, envelope("meta"), group_by=dims)      # 세션 중복 제거와 관계없이 매번
    assert "⚠️" not in run(session, envelope("meta"), group_by=("광고집행 상품명",))


def test_one_sided_product_query_asks_for_the_other_side():
    # 쿠팡 보고서 열 이름("광고전환매출발생 상품명")도 매출발생 쪽으로 본다
    session = uuid.uuid4().hex
    ad = run(session, envelope("쿠팡"), group_by=("media", "광고집행 상품명"))
    assert "📌" in ad and "매출발생 상품 차원을 찾아" in ad
    sales = run(session, envelope("쿠팡"), group_by=("광고전환매출발생 상품명",))
    assert "📌" in sales and "광고집행 상품 차원을 찾아" in sales
    assert "📌" not in run(session, envelope("쿠팡"), group_by=("media", "campaign_name"))
    assert "📌" not in run(session, envelope("쿠팡"), group_by=("광고집행 상품명", "매출발생 상품명"))   # 둘 다면 경고 쪽


def test_subagent_in_same_session_gets_its_own_copy_of_the_rules():
    session = uuid.uuid4().hex
    run(session, envelope("meta"))
    sub = run(session, envelope("meta"), agent_id="agent-1")
    assert "## 계약형 상품" in sub and "## 메타(페이스북·인스타그램)" in sub
    assert "## " not in run(session, envelope("meta"), agent_id="agent-1")
    assert "## " not in run(session, envelope("meta"))                  # 메인 기록은 그대로


def test_compaction_makes_the_next_call_resend_the_rules():
    session, other = uuid.uuid4().hex, uuid.uuid4().hex
    run(session, envelope("meta"))
    run(session, envelope("meta"), agent_id="agent-1")
    run(other, envelope("meta"))
    out =subprocess.run([sys.executable, HOOK], capture_output=True, text=True, encoding="utf-8", check=True,
                         input=json.dumps({"session_id": session, "hook_event_name": "SessionStart", "source": "compact"})).stdout
    assert out == ""
    assert "## 계약형 상품" in run(session, envelope("meta"))
    assert "## 계약형 상품" in run(session, envelope("meta"), agent_id="agent-1")
    assert "## " not in run(other, envelope("meta"))                     # 다른 세션 기록은 지우지 않는다


def test_escaped_korean_media_is_still_matched():
    escaped = json.dumps({"rows": [{"media": "쿠팡"}]}, ensure_ascii=True)   # 원문에 "쿠팡" 글자가 없다
    assert "## 쿠팡" in run(uuid.uuid4().hex, escaped)


def test_bad_input_prints_nothing():
    out = subprocess.run([sys.executable, HOOK], input="not json", capture_output=True, text=True, check=True).stdout
    assert out == ""
