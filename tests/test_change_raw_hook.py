"""hooks/capture_change_raw.py — 변경 이력 응답을 건수·next_cursor 안내로 바꾸는지 검사한다.
이 훅은 capture_ad_performance.py의 함수를 가져다 쓰므로, 그쪽을 고쳐도 이 훅이 도는지 여기서 확인한다."""

import json
import os
import subprocess
import sys
import tempfile

HOOK = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hooks", "capture_change_raw.py"))
PAGE = {"items": [{"source": "google", "stream": "campaign"}] * 3 + [{"source": "meta", "stream": "ad"}], "next_cursor": "c2"}


def run(text):
    inp = {"tool_response": [{"type": "text", "text": text}]}
    out = subprocess.run([sys.executable, HOOK], input=json.dumps(inp), capture_output=True, text=True, check=True).stdout
    return json.loads(out)["hookSpecificOutput"]["updatedToolOutput"][0]["text"] if out else None


def test_page_becomes_counts_and_cursor():
    stub = run(json.dumps(PAGE))
    assert "원본 4건" in stub and "google/campaign=3, meta/ad=1" in stub and "next_cursor: c2" in stub
    assert "마지막 페이지" in run(json.dumps(dict(PAGE, next_cursor=None)))


def test_non_page_response_passes_through():
    assert run('{"error": "bad brand"}') is None


def test_spill_file_in_folder_with_json_in_its_name_is_read():
    with tempfile.TemporaryDirectory() as tmp:
        folder = os.path.join(tmp, "proj.json.d")
        os.makedirs(folder)
        spill = os.path.join(folder, "out.txt")
        with open(spill, "w", encoding="utf-8") as f:
            json.dump([{"type": "text", "text": json.dumps(PAGE)}], f)   # 블록 리스트로 저장된 경우
        stub = run(f"Output has been saved to {spill}. Read it in parts.")
    assert stub is not None and "원본 4건" in stub
