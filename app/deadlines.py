"""Bounded retrieval workers with one wall-clock budget across all retrieval stages.

A timed-out result is discarded. In-flight I/O uses the remaining budget and a
bounded worker slot; no unbounded queue or late model generation is allowed.
"""
from concurrent.futures import ThreadPoolExecutor,TimeoutError as FutureTimeout
from contextvars import ContextVar,copy_context
from dataclasses import dataclass,field
import threading
import time

class RetrievalTimeout(TimeoutError):pass
class RetrievalBusy(RuntimeError):pass

@dataclass(eq=False)
class Deadline:
    end:float
    cancelled:threading.Event=field(default_factory=threading.Event)
    def remaining(self,cap=None):
        value=self.end-time.monotonic()
        if self.cancelled.is_set() or value<=0:raise RetrievalTimeout('检索已超时')
        return min(value,cap) if cap is not None else value

_current=ContextVar('retrieval_deadline',default=None)
_lock=threading.Lock();_executor=None;_slots=threading.BoundedSemaphore(16);_active=set()

def current():return _current.get()
def remaining(cap):
    deadline=current()
    return deadline.remaining(cap) if deadline is not None else cap

def check():
    if current() is not None:current().remaining()


def run(call,seconds):
    if current() is not None:
        current().remaining();result=call();current().remaining();return result
    if not _slots.acquire(blocking=False):raise RetrievalBusy('资料查询繁忙')
    deadline=Deadline(time.monotonic()+seconds);context=copy_context()
    def work():
        token=_current.set(deadline)
        try:
            deadline.remaining();result=call();deadline.remaining();return result
        except Exception:
            deadline.remaining();raise
        finally:_current.reset(token)
    global _executor
    try:
        with _lock:
            if _executor is None:_executor=ThreadPoolExecutor(max_workers=16,thread_name_prefix='retrieval')
            _active.add(deadline);future=_executor.submit(context.run,work)
    except Exception:
        with _lock:_active.discard(deadline)
        _slots.release();raise
    def finished(future):
        with _lock:_active.discard(deadline)
        _slots.release()
    future.add_done_callback(finished)
    try:return future.result(timeout=deadline.remaining())
    except (FutureTimeout,RetrievalTimeout):
        deadline.cancelled.set();future.cancel()
        raise RetrievalTimeout('检索已超时') from None


def close():
    global _executor
    with _lock:
        executor=_executor;_executor=None
        for deadline in _active:deadline.cancelled.set()
    if executor is not None:executor.shutdown(wait=False,cancel_futures=True)
