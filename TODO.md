# Windows RQ fork-context Runtime Fix TODO

- [x] Inspect queue/runtime traceback and identify failing import path in `app/queue.py`
- [x] Inspect `app/services/job_service.py`, `app/workers/main.py`, and `requirements.txt`
- [ ] Pin RQ explicitly to a Windows-safe version
- [ ] Change queue import to narrow path: `from rq.queue import Queue`
- [ ] Change worker import to narrow path: `from rq.worker import Worker`
- [ ] Reinstall dependencies (`python -m pip install -r requirements.txt`)
- [ ] Start backend on Windows and capture startup result
- [ ] Start worker on Windows and capture startup result
- [ ] Re-test upload + Generate Arrangement and capture runtime truth
