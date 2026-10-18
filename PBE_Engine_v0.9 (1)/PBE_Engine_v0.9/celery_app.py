from celery import Celery
from pbe.settings import settings

celery_app = Celery("pbe", broker=settings.REDIS_URL, backend=settings.REDIS_URL)
celery_app.conf.update(task_serializer="json", accept_content=["json"], result_serializer="json", task_acks_late=True, task_time_limit=120, worker_prefetch_multiplier=1)
