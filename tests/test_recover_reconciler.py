"""恢复验证管线：合成已提交测量和无效缓存，验证真实重试、证据保留与拒绝错误响应。"""

from pathlib import Path
from typing import Any

import pytest

from engine.audit import digest, write_json
from engine.cache import file_hash
from scripts.recover_reconciler import expected_groups, matches_groups, read_json, repair_response


def test_reconciler_validation() -> None:
    """检查漏项、错组、重复和非法类型，无参数，返回空并断言均拒绝。"""
    expected = expected_groups([{"id": "P1", "state": "hold"}, {"id": "P2", "state": "untested"}])
    assert matches_groups({"aligned": ["P1"], "divergent": [], "unresolved": ["P2"]}, expected)
    for invalid in (None, [], {"aligned": [], "divergent": [], "unresolved": []},
                    {"aligned": ["P1", "P1"], "divergent": [], "unresolved": ["P2"]},
                    {"aligned": "P1", "divergent": [], "unresolved": ["P2"]},
                    {"aligned": ["P2"], "divergent": [], "unresolved": ["P1"]}):
        assert not matches_groups(invalid, expected)
    with pytest.raises(ValueError):
        expected_groups([{"id": "P1", "state": "unknown"}])


@pytest.mark.parametrize("success", [True, False])
def test_repair_preserves_measurement(tmp_path: Path, success: bool) -> None:
    """构造冻结测量，参数控制模型是否纠正，返回空；失败保留原缓存，成功不改测量。"""
    sid = "S-test-002"
    folder, cache = tmp_path / "run", tmp_path / "cache"
    assertions = [{"id": "P1", "state": "hold"}, {"id": "P2", "state": "untested"}]
    result = folder / sid / "result.json"
    write_json(result, {"blades": {"assertions": assertions}})
    original_hash = file_hash(result)
    state = {"status": "FAILED", "pending_postprocess": sid,
             "artifact_hashes": {str(result.relative_to(folder)): original_hash}}
    write_json(folder / "checkpoint.json", state)
    identity = {"role": "reconciler", "context": {"structure_id": sid, "assertion_results": assertions},
                "nonce": "", "instruction": "classify"}
    invalid = {"aligned": [], "divergent": [], "unresolved": []}
    cached = {"identity": identity, "result": invalid}
    path = cache / (digest(identity) + ".json")
    write_json(path, cached)
    calls = []

    class Model:
        """提供受控修正响应，无构造参数，假设第一次重试仍返回无效分类。"""

        def request(self, role: str, context: dict, instruction: str, nonce: str) -> Any:
            """记录 nonce 并返回测试响应，参数对应真实接口，不生成研究结果。"""
            calls.append(nonce)
            return expected_groups(assertions) if success and len(calls) > 1 else invalid

    if success:
        repair_response(folder, cache, Model())
        assert len(calls) == 2 and len(set(calls)) == 2
        assert matches_groups(read_json(path)["result"], expected_groups(assertions))
        assert read_json(folder / "recovery" / sid / "original-response.json") == cached
    else:
        with pytest.raises(ValueError, match="three audited"):
            repair_response(folder, cache, Model())
        assert len(calls) == 3
        assert read_json(path) == cached
    assert file_hash(result) == original_hash
    assert read_json(folder / "checkpoint.json") == state