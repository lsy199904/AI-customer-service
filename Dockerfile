FROM python:3.12-slim
WORKDIR /srv/assistant
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY data ./data
COPY knowledge_sources ./knowledge_sources
COPY manage.py ./
RUN useradd --uid 10001 --create-home assistant && mkdir var && chown assistant:assistant var
USER assistant
ENV HOST=0.0.0.0 PORT=8000
EXPOSE 8000
CMD ["python", "-m", "app.server"]
