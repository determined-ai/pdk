FROM python:3.9

WORKDIR /app

COPY requirements.txt /app
RUN pip install -r requirements.txt

COPY deploy.py /app
COPY common.py /app
COPY customer_churn_handler.py /app
COPY numscale.json /app

ENV PYTHONUNBUFFERED=1
