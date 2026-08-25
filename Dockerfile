FROM python:3.12-slim
WORKDIR /app
COPY app.py config.json ./
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "app.py"]
