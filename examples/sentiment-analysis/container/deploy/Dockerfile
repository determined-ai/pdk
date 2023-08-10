FROM python:3.8

WORKDIR /app

COPY requirements.txt /app
RUN pip install -r requirements.txt

COPY deploy.py /app
COPY common.py /app
COPY finbert_handler_grpc.py /app

ENV PYTHONUNBUFFERED=1
