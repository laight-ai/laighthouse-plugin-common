#!/usr/bin/env python3
"""PostToolUse 훅: `get_ad_performance` 응답 뒤에 광고 성과 도메인 규칙을 모델 컨텍스트로 넣는다.

왜 존재하나: 모델이 성과 숫자를 해석할 때 매체 상식을 놓친다 — 계약형인 네이버 브랜드검색(BRS)의 예산 증액을 제안하거나,
"광고집행 상품명"(광고 지표)과 "매출발생 상품명"(매출)을 이어 붙여 상품별 ROAS를 만드는 식이다. 스킬은 모델이 골라야
불러오므로 빠질 수 있다. 훅은 도구를 부를 때마다 실행되므로 규칙이 항상 들어간다.

무엇을 하나:
1. 같은 폴더의 `ad_performance_domain.md`를 `## ` 절로 나눈다. `match:` 주석이 있는 절은 매체 절, 없는 절은 공통 절이다.
2. 세션의 첫 호출에는 공통 절을 넣는다. 응답 행의 media 값(없으면 filters.media)에 매체 절의 키워드가 들어 있으면 그 매체 절도 넣는다.
3. 이미 넣은 절은 같은 세션에서 다시 넣지 않는다(세션별 상태 파일). 새로 넣을 절이 없으면 한 줄 알림만 붙인다.
4. group_by에 광고집행 상품 차원과 매출발생 상품 차원이 함께 있으면 매번 경고를 붙인다.

`hookSpecificOutput.additionalContext`만 쓰고 응답(updatedToolOutput)은 건드리지 않는다 — 캡처 훅과 함께 돌아도 된다.
어떤 오류가 나도 아무것도 출력하지 않고 끝난다(도구 응답은 그대로 전달된다).
"""

import json
import os
import re
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from capture_ad_performance import block_text, extract_text, unwrap_json_result  # noqa: E402  (stdin/stdout을 UTF-8로 맞춘다)

RULES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ad_performance_domain.md")
STATE_ROOT = os.path.join(tempfile.gettempdir(), "laighthouse_domain_hook")
STALE_SECS = 3 * 24 * 3600
TAG = "[laighthouse-domain-hook]"
AD_PRODUCT = "광고집행"
SALES_PRODUCT = "매출발생"


def parse_sections(md):
    """[(제목, 키워드 목록, 본문)] — 키워드가 빈 목록이면 공통 절. 본문의 HTML 주석은 뺀다."""
    md = re.sub(r"\A\s*<!--.*?-->", "", md, flags=re.S)  # 파일 머리 설명
    sections = []
    for block in re.split(r"^## ", md, flags=re.M)[1:]:
        title, _, body = block.partition("\n")
        m = re.search(r"<!--\s*match:(.*?)-->", body, flags=re.S)
        keywords = [k.strip().lower() for k in m.group(1).split(",") if k.strip()] if m else []
        body = re.sub(r"<!--.*?-->", "", body, flags=re.S).strip()
        sections.append((title.strip(), keywords, body))
    return sections


def response_text(data):
    resp = next((data[f] for f in ("tool_response", "tool_output", "tool_result") if data.get(f) is not None), None)
    text = unwrap_json_result(extract_text(resp)) if resp is not None else None
    if not text:
        return ""
    saved = re.search(r"saved to (\S+\.(?:txt|json))", text)  # 호스트가 큰 응답을 파일로 뺀 경우
    if saved and not text.lstrip().startswith("{"):
        path = saved.group(1)
        if os.name == "nt" and not path.startswith("\\\\?\\"):
            path = "\\\\?\\" + os.path.abspath(path)
        try:
            with open(path, encoding="utf-8-sig") as f:
                text = unwrap_json_result(block_text(f.read())) or ""
        except OSError:
            return ""
    return text


def media_values(data):
    """응답 행의 media 값, 없으면 filters.media — 모두 소문자."""
    values = set()
    try:
        rows = json.loads(response_text(data)).get("rows") or []
        values = {str(r.get("media")).lower() for r in rows if isinstance(r, dict) and r.get("media")}
    except (ValueError, AttributeError):
        pass
    if not values:
        filters = (data.get("tool_input") or {}).get("filters")
        media = filters.get("media") if isinstance(filters, dict) else None
        if isinstance(media, str):
            media = [media]
        if isinstance(media, list):
            values = {str(m).lower() for m in media}
    return values


def load_sent(path):
    try:
        with open(path, encoding="utf-8") as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


def save_sent(path, sent):
    try:
        os.makedirs(STATE_ROOT, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sorted(sent), f, ensure_ascii=False)
        now = time.time()
        for name in os.listdir(STATE_ROOT):
            p = os.path.join(STATE_ROOT, name)
            if now - os.path.getmtime(p) > STALE_SECS:
                os.remove(p)
    except OSError:
        pass


def build_context(data):
    with open(RULES, encoding="utf-8") as f:
        sections = parse_sections(f.read())
    session = re.sub(r"[^A-Za-z0-9_-]", "_", str(data.get("session_id") or "nosession"))[:48]
    state = os.path.join(STATE_ROOT, session + ".json")
    sent = load_sent(state)

    media = media_values(data)
    new = [(title, body) for title, keywords, body in sections
           if title not in sent and (not keywords or any(k in m for k in keywords for m in media))]

    parts = []
    group_by = [str(d) for d in ((data.get("tool_input") or {}).get("group_by") or [])]
    if any(AD_PRODUCT in d for d in group_by) and any(SALES_PRODUCT in d for d in group_by):
        parts.append(f"⚠️ 이번 group_by에 광고집행 상품 차원과 매출발생 상품 차원이 함께 있다({group_by}). 두 차원의 교차 행은 해석하지 않는다 — "
                     "광고 지표는 광고집행 상품명으로, 매출은 매출발생 상품명으로 나눠 다시 조회한다.")
    if new:
        parts.append("이 응답을 해석·설명·보고할 때 아래 광고 성과 도메인 규칙을 지킨다.")
        parts.extend(f"## {title}\n{body}" for title, body in new)
        save_sent(state, sent | {title for title, _ in new})
    else:
        parts.append("이 세션에서 앞서 안내한 광고 성과 도메인 규칙(계약형 BRS, 광고집행/매출발생 상품 구분, 매체별 특이사항)을 계속 지킨다.")
    return f"{TAG}\n" + "\n\n".join(parts)


def main():
    try:
        data = json.load(sys.stdin)
        context = build_context(data)
    except Exception:  # noqa: BLE001 — 훅 실패가 도구 응답을 막으면 안 된다
        return
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": context}},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
