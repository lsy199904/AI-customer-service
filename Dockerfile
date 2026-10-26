FROM python:3.12-slim
WORKDIR /srv/assistant
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY app ./app
COPY data ./data
COPY manage.py ./
RUN useradd --uid 10001 --create-home assistant && mkdir var knowledge_sources && chown assistant:assistant var knowledge_sources
USER assistant
ENV HOST=0.0.0.0 PORT=8000
EXPOSE 8000
CMD ["python", "-m", "app.server"]
