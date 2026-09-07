from worker.celery_app import celery_app
from worker.tasks import eval as eval_task  # noqa: F401


def test_evaluation_worker_task_is_registered() -> None:
    task = celery_app.tasks["worker.tasks.eval.run_eval"]
    assert task.max_retries == 3
    assert task.retry_backoff is True
