import threading
from types import SimpleNamespace

import pytest

from vagent import config
from vagent.api import auto_runs as runs


@pytest.mark.parametrize("consistent", [True, False])
def test_automatic_run(api, monkeypatch, consistent):
    api.data(api.post("/api/projects", json={"name": "自动流程"}))
    (config.UPLOAD_DIR / "idea.txt").write_text("少女走进车站", encoding="utf-8")
    (config.UPLOAD_DIR / "sheet.png").write_bytes(b"image")
    (config.UPLOAD_DIR / "clip.mp4").write_bytes(b"clip")
    calls = []

    def ask(system, text, paths=()):
        if "assets 数组" in system:
            assert "少女走进车站" in text
            return {"assets": [{"name": "少女", "type": "角色", "desc": "黑发", "fromImage": False}]}
        if "shots 数组" in system:
            return {"shots": [{"name": "进站", "prompt": "进入车站", "dur": 5, "assets": ["a1"]}]}
        calls.append("rewrite")
        return {"prompt": "从站门外走进站内"}

    def submit(prompt, refs, duration):
        assert refs
        calls.append("submit")
        if calls.count("submit") == 1:
            raise runs.video.VideoError("INTERNAL_ERROR", "生成服务暂时不可用", 500)
        assert prompt == "从站门外走进站内"
        return "test-job"

    def identity(*args):
        calls.append("identity")
        return consistent, "角色校验结果"

    def review(*args):
        calls.append("review")
        return {
            "verdict": "pass",
            "reason": "动作一致",
            "summary": "少女进站",
            "mode": "auto",
            "job": "test-job",
            "clip": "/uploads/clip.mp4",
            "state": "done",
        }

    monkeypatch.setattr(runs, "_ask", ask)
    monkeypatch.setattr(runs.image, "generate", lambda *a, **k: {"url": "/uploads/sheet.png"})
    monkeypatch.setattr(runs.video, "submit_reference", submit)
    monkeypatch.setattr(runs.video, "query", lambda j, timeout: {"state": "succeeded", "url": "remote"})
    monkeypatch.setattr(runs.video, "download", lambda u: "/uploads/clip.mp4")
    monkeypatch.setattr(runs, "_identity", identity)
    monkeypatch.setattr(runs, "_review_content", review)
    monkeypatch.setattr(runs.video, "stitch", lambda *a: {"url": "/uploads/final.mp4"})
    run = api.data(api.post("/api/auto/runs", json={"attachment": {"stored": "idea.txt"}}))["run"]
    assert api.post("/api/auto/runs", json={"text": "重复提交"}).status_code == 409
    runs._work(run["id"])
    result = api.data(api.get("/api/auto/runs/current"))["run"]
    if consistent:
        assert calls == ["submit", "rewrite", "submit", "identity", "review"]
        assert result["exportUrl"] == "/uploads/final.mp4"
        assert result["status"] == "done"
    else:
        assert calls.count("submit") == 3 and "review" not in calls
        assert result["status"] == "failed" and not result["exportUrl"]


def test_parallel_checkpoints_keep_order_and_skip_completed(monkeypatch):
    data = {"shots": [{"id": i} for i in range(4)]}
    data["shots"][0]["passed"] = True
    first_pair = threading.Barrier(2)
    last_started = threading.Event()
    snapshots = []

    def shot(data, shot, number, save):
        assert number > 1
        if number in (2, 3):
            first_pair.wait(5)
        if number == 2:
            assert last_started.wait(5)
        if number == 4:
            assert data["shots"][2]["passed"]
            last_started.set()
        shot.update(passed=True, clip=f"{number}.mp4")
        save("通过")

    monkeypatch.setattr(runs, "_shot", shot)
    runs._generate_shots(
        data, lambda stage: snapshots.append([s.get("passed", False) for s in data["shots"]])
    )
    assert snapshots[0] == [True, False, True, False]
    assert all(snapshots[-1])
    assert [s.get("clip") for s in data["shots"]] == [None, "2.mp4", "3.mp4", "4.mp4"]


def test_resumed_job_uses_remaining_poll_time(monkeypatch):
    now = [100.0]

    def sleep(seconds):
        now[0] += seconds

    shot = {"job": "existing", "pollDeadline": 101}
    timeouts = []

    def query(job, timeout):
        assert job == "existing"
        timeouts.append(timeout)
        return {"state": "running"}

    monkeypatch.setattr(runs, "time", SimpleNamespace(time=lambda: now[0], sleep=sleep))
    monkeypatch.setattr(runs.video, "query", query)
    with pytest.raises(ValueError, match="轮询超时"):
        runs._render(shot, [], lambda stage: pytest.fail("不应重置截止时间"))
    assert len(timeouts) == 1 and 0 < timeouts[0] <= 1
    assert now[0] == 101
