from app.core.worker_modules.worker_test_runner import WorkerTestRunnerBridge


class FakeWorker:
    pass


def test_build_result_payload_counts_pytest_summary_lines():
    bridge = WorkerTestRunnerBridge(FakeWorker())
    payload = bridge.build_result_payload(
        "Host",
        [
            "tests/test_a.py::test_one PASSED [ 33%]",
            "tests/test_b.py::test_two FAILED [ 66%]",
            "tests/test_c.py::test_three ERROR [100%]",
            "=================== 1 failed, 1 passed, 1 error in 2.34s ===================",
        ],
    )

    assert payload["target_client_id"] == "Host"
    assert payload["passed"] == 1
    assert payload["failed"] == 2
    assert payload["duration"] == "2.34"
    assert "test_one PASSED" in payload["full_log"]


def test_build_result_payload_defaults_when_log_empty():
    bridge = WorkerTestRunnerBridge(FakeWorker())

    payload = bridge.build_result_payload("client_1", [])

    assert payload == {
        "target_client_id": "client_1",
        "passed": 0,
        "failed": 0,
        "duration": "0",
        "full_log": "",
    }
