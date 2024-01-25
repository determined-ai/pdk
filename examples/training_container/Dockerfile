FROM python:3.10

WORKDIR /app

COPY requirements.txt /app
RUN pip install -r requirements.txt

COPY train.py /app

ENV PYTHONUNBUFFERED=1
