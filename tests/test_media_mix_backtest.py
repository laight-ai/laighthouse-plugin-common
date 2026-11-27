"""media-mix-backtest-check 스킬: 저장된 응답으로 대상 달 · 총예산을 고르고, backtest 결과를 세 기준으로 판정하는지 검사한다.

기대값은 아래 픽스처에서 손으로 계산한 값이다(주석에 계산을 적었다).
"""

import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.normpath(os.path.join(HERE, "..", "skills", "media-mix-backtest-check", "assets"))
TODAY = "2026-11-26"
BRAND = "점검브랜드"


def months(first, n):
    y, m = int(first[:4]), int(first[5:]) - 1
    return [f"{y + (m + i) // 12:04d}-{(m + i) % 12 + 1:02d}" for i in range(n)]


def ad_rows():
    """2025-09(i=0) ~ 2026-10(i=13) 월 실적(Gross). 검색: 비용은 줄고 효율은 오른다(수수료 markup 10%).
    쿠팡: 효율이 떨어지고, 작년 9월 → 10월에는 비용이 13,000,000 → 10,200,000(−21.5%)으로 줄었다. 메타: 19M · 21M을 오간다."""
    rows = []
    for i, m in enumerate(months("2025-09", 14)):
        rows.append({"month": m, "media": "검색", "광고비": 11_000_000 - 500_000 * i,
                     "매출": (10_000_000 - 450_000 * i) * (1 + 0.2 * i)})
        rows.append({"month": m, "media": "쿠팡", "광고비": 13_000_000 if i == 0 else 10_000_000 + 200_000 * i,
                     "매출": 50_000_000 - 1_500_000 * i})
        rows.append({"month": m, "media": "메타", "광고비": 21_000_000 if i % 2 else 19_000_000, "매출": 60_000_000})
    return rows


def envelope():
    return {"source": "elt", "tenant": BRAND, "fee_basis": "gross",
            "fees": [{"media": "검색", "month": m, "fee_mode": "markup", "rate": 10.0} for m in months("2025-09", 14)],
            "time_grain": "month", "dimensions": ["media"], "metrics": ["광고비", "매출"], "rows": ad_rows()}


def job(target, status="succeeded"):
    def row(kind, media, cost, outcome):
        return {"kind": kind, "media": media, "cost": cost, "outcome": outcome, "outcome_per_cost": outcome / cost}
    summary = [row("current", "검색", 4_000_000, 20_000_000), row("optimized", "검색", 2_000_000, 12_000_000),
               row("current", "쿠팡", 12_000_000, 30_000_000), row("optimized", "쿠팡", 18_000_000, 40_000_000),
               row("current", "메타", 21_000_000, 60_000_000), row("optimized", "메타", 21_500_000, 61_000_000),
               row("current", "*", 37_000_000, 110_000_000), row("optimized", "*", 41_500_000, 113_000_000)]
    ok = status == "succeeded"
    return {"id": "j-" + target, "status": status, "error": None if ok else "학습 데이터 부족",
            "request": {"target_month": target, "cost_metric": "광고비", "outcome_metric": "매출",
                        "target_budget": 41_500_000, "backtest": True},
            "summary": summary if ok else None}


def save(tmp, n, tool, tool_input, response):
    """저장 훅이 남기는 모양 그대로 세션 폴더에 응답을 둔다."""
    folder = os.path.join(tmp, "laighthouse_mcp_responses", "s1")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, f"{n:03d}_{tool}.json"), "w", encoding="utf-8") as f:
        json.dump({"tool_name": f"mcp__laighthouse__{tool}", "tool_input": {"brand_name": BRAND, **tool_input},
                   "saved_at": time.time() + n,
                   "response": response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)}, f)


def run(tmp, script, *args, code=0):
    env = {**os.environ, "TMPDIR": tmp, "HOME": tmp}
    p = subprocess.run([sys.executable, "-I", "-S", os.path.join(ASSETS, script), "--brand", BRAND,
                        "--cost", "광고비", "--outcome", "매출", "--today", TODAY, *args],
                       env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == code, p.stderr
    return json.loads(p.stdout) if code == 0 else p.stderr


def ad_call(start, end):
    return {"start_date": start, "end_date": end, "time_grain": "month", "group_by": ["media"]}


def test_prepare_asks_for_the_window_then_gives_the_budget_in_net(tmp_path):
    tmp = str(tmp_path)
    (call,) = run(tmp, "prepare.py", "--months", "2026-10")["missing"]
    assert (call["start_date"], call["end_date"]) == ("2025-09-01", "2026-10-31")   # 13개월 전 1일 ~ 대상 달 말일
    save(tmp, 1, "get_ad_performance", ad_call("2025-09-01", "2026-10-31"), envelope())
    (m,) = run(tmp, "prepare.py", "--months", "2026-10")["months"]
    # 2026-10(i=13): 검색 Gross 4,500,000 ÷ 1.1 = 4,090,909.09 + 쿠팡 12,600,000 + 메타 21,000,000
    assert m == {"target_month": "2026-10", "base_month": "2026-09", "budget": 37_690_909, "last_year": True}


def test_prepare_suggests_every_other_month_from_the_latest(tmp_path):
    tmp = str(tmp_path)
    save(tmp, 1, "get_ad_performance", ad_call("2024-12-01", "2026-10-31"), envelope())
    out = run(tmp, "prepare.py")
    # 후보는 13개월 전 실적까지 조회 범위에 드는 2026-01 ~ 2026-10(데이터가 2025-09부터라 모두 전월이 있다)
    assert out["eligible"] == months("2026-01", 10)
    assert [m["target_month"] for m in out["months"]] == ["2026-02", "2026-04", "2026-06", "2026-08", "2026-10"]


def test_a_month_that_has_not_ended_is_refused(tmp_path):
    assert "끝나지 않은 달" in run(str(tmp_path), "prepare.py", "--months", "2026-11", code=2)


def test_report_flags_each_check(tmp_path):
    tmp = str(tmp_path)
    save(tmp, 1, "get_ad_performance", ad_call("2025-09-01", "2026-10-31"), envelope())
    assert run(tmp, "build_report.py", "--months", "2026-10")["missing_jobs"] == ["2026-10"]
    save(tmp, 2, "get_media_mix_job", {"job_id": "j-2026-10"}, {**job("2026-10"), "status": "running", "summary": None})
    assert run(tmp, "build_report.py", "--months", "2026-10")["missing_jobs"] == ["2026-10"]   # 계산 중은 결과로 치지 않는다
    save(tmp, 3, "get_media_mix_job", {"job_id": "j-2026-10"}, job("2026-10"))
    out = run(tmp, "build_report.py", "--months", "2026-10", "--out", os.path.join(tmp, "r.html"))
    flags = {(f["media"], f["check"]): f for f in out["facts"]["flagged"]}

    # ① 검색: 효율(Net) 2026-07 16.5M ÷ 5.45M = 3.03 → 2026-09 15.64M ÷ 4.55M = 3.44(+13.7%, 개선)인데 −50% —
    #    job의 평균 효율이 20/4 = 5.00 → 12/2 = 6.00으로 오른다
    assert flags[("검색", "trend")]["verdict"] == "설명 필요" and "5.00에서 6.00까지" in flags[("검색", "trend")]["note"]
    # ① 쿠팡: 효율 35M ÷ 12M = 2.92 → 32M ÷ 12.4M = 2.58(−11.5%, 악화)인데 +50% — 평균 효율 2.50 → 2.22
    assert flags[("쿠팡", "trend")]["verdict"] == "설명 필요" and "2.50에서 2.22까지" in flags[("쿠팡", "trend")]["note"]
    # ② 검색 −50%는 최근 12개월 월간 증감(−9.1% ~ −4.5%) 밖, 쿠팡 +50%는 (−21.5% ~ +2.0%) 밖이고 둘 다 ±30%를 넘는다
    assert flags[("검색", "swing")]["note"] == "최근 12개월 -9.1% ~ -4.5% · ±30% 참고선 넘음"
    assert flags[("쿠팡", "swing")]["verdict"] == "범위 밖"
    # ③ 쿠팡: 작년 9월 → 10월 −21.5%인데 제안은 +50% — 방향이 반대
    assert flags[("쿠팡", "season")]["note"] == "작년 9월 → 10월 -21.5%"
    # 메타: 효율 19M · 19M로 보합, 제안 +2.4%는 방향이 없고 월간 범위(−9.5% ~ +10.5%) 안
    assert not [k for k in flags if k[0] == "메타"]
    assert out["facts"]["counts"] == {"trend": 2, "swing": 2, "season": 1}
    page = open(out["out"], encoding="utf-8").read()
    assert "성과 검증이 아닙니다" in page and "당시 실제로 받은 제안과 다를 수 있습니다" in page


def test_a_failed_month_is_listed_and_the_rest_are_judged(tmp_path):
    tmp = str(tmp_path)
    save(tmp, 1, "get_ad_performance", ad_call("2025-08-01", "2026-10-31"), envelope())
    save(tmp, 2, "get_media_mix_job", {"job_id": "a"}, job("2026-10"))
    save(tmp, 3, "get_media_mix_job", {"job_id": "b"}, job("2026-09", status="failed"))
    out = run(tmp, "build_report.py", "--months", "2026-09,2026-10", "--out", os.path.join(tmp, "r.html"))
    assert out["facts"]["months"] == ["2026-10"]
    assert out["facts"]["failed"] == [{"target_month": "2026-09", "error": "학습 데이터 부족"}]


def test_a_medium_with_no_outcome_two_months_before_is_unknown_not_a_crash(tmp_path):
    # 검색의 2026-07(i=10) 매출이 0이면 효율 추세를 셀 수 없다 — 판단 불가로 두고 보고서는 나온다
    tmp = str(tmp_path)
    env = envelope()
    for row in env["rows"]:
        if row["media"] == "검색" and row["month"] == "2026-07":
            row["매출"] = 0
    save(tmp, 1, "get_ad_performance", ad_call("2025-09-01", "2026-10-31"), env)
    save(tmp, 2, "get_media_mix_job", {"job_id": "a"}, job("2026-10"))
    out = run(tmp, "build_report.py", "--months", "2026-10", "--out", os.path.join(tmp, "r.html"))
    assert ("검색", "trend") not in {(f["media"], f["check"]) for f in out["facts"]["flagged"]}
    assert out["facts"]["counts"]["trend"] == 1   # 쿠팡만 남는다


def test_a_saved_error_for_another_range_does_not_block_a_new_call(tmp_path):
    # 앞 범위의 조회가 오류였어도 대상 달을 덮지 못하면 다시 부르게 한다(missing). 덮는 범위의 오류는 errors 로 알린다
    tmp = str(tmp_path)
    save(tmp, 1, "get_ad_performance", ad_call("2024-12-01", "2026-10-31"), "Error: upstream timeout")
    (call,) = run(tmp, "prepare.py", "--months", "2025-03")["missing"]
    assert call["start_date"] == "2024-02-01"
    assert run(tmp, "prepare.py", "--months", "2026-10")["errors"][0]["response"].startswith("Error: upstream timeout")
    assert run(tmp, "build_report.py", "--months", "2026-10")["errors"][0]["response"].startswith("Error: upstream timeout")


def test_a_job_lookup_error_is_reported_instead_of_missing(tmp_path):
    tmp = str(tmp_path)
    save(tmp, 1, "get_ad_performance", ad_call("2025-09-01", "2026-10-31"), envelope())
    save(tmp, 2, "get_media_mix_job", {"job_id": "a"}, "Error: media-mix is not enabled for this brand")
    out = run(tmp, "build_report.py", "--months", "2026-10")
    assert out["missing_jobs"] == ["2026-10"]
    assert out["errors"] == [{"call": "get_media_mix_job", "response": "Error: media-mix is not enabled for this brand"}]


def test_a_change_that_rounds_to_zero_has_no_minus_sign():
    sys.path.insert(0, ASSETS)
    import backtest
    assert backtest.fmt_pct(-0.0004) == "0.0%"
    assert backtest.fmt_pct(0.0004) == "0.0%"
    assert backtest.fmt_pct(-0.0006) == "-0.1%"
