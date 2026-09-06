from rqpull.state import Manifest


def test_manifest_resume_is_idempotent(tmp_path):
    path = tmp_path / "manifest.json"
    manifest = Manifest(path)
    manifest.mark_chunk_done("daily_bar", "2020#000")
    manifest.mark_chunk_done("daily_bar", "2020#000")
    reloaded = Manifest(path)
    assert reloaded.is_done("daily_bar", "2020#000")
    assert reloaded.task("daily_bar")["chunks_done"] == ["2020#000"]

