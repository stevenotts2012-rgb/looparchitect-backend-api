import inspect

from app.services import arrangement_jobs
from app.services import render_executor
from app.workers import render_worker


def test_arrangement_and_worker_bind_same_render_executor_function():
    assert arrangement_jobs.render_from_plan is render_executor.render_from_plan
    assert render_worker.render_from_plan is render_executor.render_from_plan


def test_both_paths_call_render_from_plan_in_codepath():
    arrangement_source = inspect.getsource(arrangement_jobs.run_arrangement_job)
    worker_source = inspect.getsource(render_worker.render_loop_worker)

    assert "render_from_plan(" in arrangement_source
    assert "render_from_plan(" in worker_source
