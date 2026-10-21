FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 MPLBACKEND=Agg MPLCONFIGDIR=/tmp/matplotlib STORAGE_DIR=/tmp/openrad/sessions PORT=8080
COPY pyproject.toml README.md ./
COPY openrad ./openrad
COPY src ./src
COPY server.py agent_main.py SKILL.md ./
COPY skills ./skills
RUN pip install --no-cache-dir ".[api]" && useradd --uid 10001 --create-home openrad
USER openrad
EXPOSE 8080
CMD ["python", "server.py"]
