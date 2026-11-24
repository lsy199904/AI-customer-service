"""Transient account-scoped fanout; final messages remain in the existing database."""
from contextlib import contextmanager
import hashlib
import json
import queue
import threading

class LiveSync:
    def __init__(self,service):
        self.service=service;self.lock=threading.Lock();self.listeners={}
    def channel(self,actor):
        value=json.dumps([actor['tenant_id'],actor['sub']],ensure_ascii=False)
        return 'chat_'+hashlib.sha256(value.encode()).hexdigest()[:48]
    def publish(self,actor,item):
        channel=self.channel(actor)
        # NOTIFY has an 8000-byte limit. Split deltas; completion is a reload signal.
        parts=[item]
        if item.get('type')=='delta':
            text=item.get('text','')
            parts=[{**item,'text':text[i:i+500]} for i in range(0,len(text),500)]
        try:
            for part in parts:
                payload=json.dumps(part,ensure_ascii=False)
                if len(payload.encode())>7500:continue
                if self.service.config.database_url:
                    self.service.db.execute('SELECT pg_notify(?,?)',(channel,payload))
                else:
                    with self.lock:
                        for listener in self.listeners.get(channel,[]):
                            try:listener.put_nowait(part)
                            except queue.Full:pass  # reconnect/history restores committed messages
        except Exception:
            from .observability import event
            event('live_sync_publish_failed',level='WARNING')
    @contextmanager
    def subscribe(self,actor):
        channel=self.channel(actor)
        if self.service.config.database_url:
            import psycopg
            from psycopg import sql
            with psycopg.connect(self.service.config.database_url,autocommit=True,connect_timeout=10) as conn:
                conn.execute(sql.SQL('LISTEN {}').format(sql.Identifier(channel)))
                def receive():
                    notification=next(conn.notifies(timeout=1,stop_after=1),None)
                    return json.loads(notification.payload) if notification else None
                yield receive
        else:
            listener=queue.Queue(maxsize=128)
            with self.lock:self.listeners.setdefault(channel,[]).append(listener)
            try:
                def receive():
                    try:return listener.get(timeout=1)
                    except queue.Empty:return None
                yield receive
            finally:
                with self.lock:
                    self.listeners[channel].remove(listener)
                    if not self.listeners[channel]:self.listeners.pop(channel)


def broker(service):
    with service.lock:
        if not hasattr(service,'_live_sync'):service._live_sync=LiveSync(service)
        return service._live_sync
