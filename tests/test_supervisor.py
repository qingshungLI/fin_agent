"""守护策略回归：临时模型错误可恢复，认证、限额和研究契约错误必须停止。"""
import pytest

from scripts.supervise_research import retryable


@pytest.mark.parametrize("reason", ["ValueError", "ReadTimeout", "ConnectError", "HTTP 429", "HTTP 503"])
def test_transient_response_can_resume(reason: str) -> None:
    """输入已分类临时异常，返回允许恢复；不覆盖未提交数据。"""
    assert retryable({"type": "RuntimeError", "error": "DeepSeek request failed after bounded retries: " + reason})


@pytest.mark.parametrize("reason", ["DeepSeek authorization/balance HTTP 402", "LLM request budget exhausted", "Checkpoint artifact changed", "missing data"])
def test_contract_and_authorization_errors_stop(reason: str) -> None:
    """输入不可自动恢复异常，返回停止，不能靠重试绕过错误。"""
    assert not retryable({"type": "RuntimeError", "error": reason})