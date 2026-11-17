"""hooks/capture_ad_performance.py — 플러그인마다 다른 캡처 조건·스텁을 명령 인자로 고르는지 검사한다."""

import json
import os
import subprocess
import sys
import tempfile
import uuid

HOOK = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hooks", "capture_ad_performance.py"))
ROWS = [{"media": "google" if i % 2 else "meta", "campaign_name": f"c{i}", "cost": i * 10} for i in range(200)]
ENVELOPE = json.dumps({"dimensions": ["media", "campaign_name"], "metrics": ["cost"], "metric_units": {"cost": "₩"},
                       "row_count": len(ROWS), "rows": ROWS})


def run(group_by, text, *flags):
    """훅을 실행해 모델에게 보일 스텁 텍스트를 돌려준다. 캡처하지 않으면 None."""
    inp = {"session_id": uuid.uuid4().hex, "tool_input": {"group_by": group_by},
           "tool_response": [{"type": "text", "text": text}]}
    out = subprocess.run([sys.executable, HOOK, *flags], input=json.dumps(inp),
                         capture_output=True, text=True, check=True).stdout
    if not out:
        return None
    return json.loads(out)["hookSpecificOutput"]["updatedToolOutput"][0]["text"]


def test_default_captures_only_campaign_level_dimensions():
    assert run(["media"], ENVELOPE) is None
    assert run(["campaign_name"], ENVELOPE) is not None


def test_any_group_by_captures_media_level_too():
    assert run(["media"], ENVELOPE, "--any-group-by") is not None
    assert run([], ENVELOPE, "--any-group-by") is None   # 총계 호출은 그대로 통과


def test_full_stub_shows_units_and_first_row_but_short_stub_does_not():
    full = run(["campaign_name"], ENVELOPE)
    short = run(["campaign_name"], ENVELOPE, "--short-stub")
    assert 'metric_units={"cost": "₩"}' in full and "첫 행=" in full
    assert "metric_units" not in short and "첫 행" not in short
    assert 'metrics=["cost"]' in short


def test_reads_host_spill_file_saved_as_json_block_list():
    with tempfile.TemporaryDirectory() as tmp:
        spill = os.path.join(tmp, "out.json")
        with open(spill, "w", encoding="utf-8") as f:
            json.dump([{"type": "text", "text": ENVELOPE}], f)
        stub = run(["campaign_name"], f"Output has been saved to {spill}", "--short-stub")
    assert "200행" in stub


def test_spill_path_with_json_inside_a_folder_name_is_read_whole():
    # 경로 중간의 `.json`에서 끊으면 없는 파일을 열려다 원본을 그대로 넘긴다
    with tempfile.TemporaryDirectory() as tmp:
        folder = os.path.join(tmp, "proj.json.d")
        os.makedirs(folder)
        spill = os.path.join(folder, "out.txt")
        with open(spill, "w", encoding="utf-8") as f:
            f.write(ENVELOPE)
        stub = run(["campaign_name"], f"Error: result too big. Output has been saved to {spill}. Read it in parts.")
    assert stub is not None and "200행" in stub
