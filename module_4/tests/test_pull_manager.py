import sys

from pull_manager import PullManager

SLEEP_2S = [sys.executable, "-c", "import time; time.sleep(2)"]


def _python(code):
    return [sys.executable, "-c", code]


def test_starting_while_running_is_refused_and_leaves_first_process_alone():
    manager = PullManager(SLEEP_2S)

    assert manager.start() is True
    assert manager.is_running()
    assert manager.start() is False
    assert manager.is_running()

    manager.wait()
    assert not manager.is_running()


def test_finished_pull_reports_last_output_line_and_success():
    manager = PullManager(_python("print('Reading'); print('Added 3 new records')"))

    manager.start()
    manager.wait()

    assert not manager.is_running()
    assert manager.last_message == "Added 3 new records"
    assert manager.last_succeeded is True


def test_failed_pull_reports_failure_with_the_error_text():
    manager = PullManager(_python(
        "import sys; print('Grad Cafe blocked the request (HTTP 403).'); sys.exit(2)"
    ))

    manager.start()
    manager.wait()

    assert manager.last_succeeded is False
    assert "HTTP 403" in manager.last_message


def test_failed_pull_with_no_output_still_gives_a_message():
    manager = PullManager(_python("import sys; sys.exit(3)"))
    manager.start()
    manager.wait()
    assert manager.last_succeeded is False
    assert "exit code 3" in manager.last_message


def test_can_start_again_after_the_previous_pull_finished():
    manager = PullManager(_python("print('done')"))
    assert manager.start() is True
    manager.wait()
    assert manager.start() is True
    manager.wait()


def test_command_that_cannot_launch_is_reported_not_raised():
    manager = PullManager(["definitely-not-a-real-program-xyz"])

    assert manager.start() is False
    assert not manager.is_running()
    assert manager.last_succeeded is False
    assert "could not be started" in manager.last_message.lower()


def test_idle_manager_has_no_message_and_no_result_yet():
    manager = PullManager(SLEEP_2S)
    assert manager.last_message == ""
    assert manager.last_succeeded is None
    assert not manager.is_running()


def test_progress_line_is_visible_while_running():
    manager = PullManager(_python(
        "import time; print('Fetching page 1', flush=True); time.sleep(2)"
    ))
    manager.start()
    for _ in range(100):
        if manager.last_message:
            break
        import time
        time.sleep(0.05)
    assert manager.is_running()
    assert manager.last_message == "Fetching page 1"
    manager.wait()
