FROM python:3.8

WORKDIR /app

COPY requirements.txt /app
RUN pip install -r requirements.txt

COPY deploy.py /app
COPY common.py /app
COPY fasterrcnn_handler.py /app
COPY index_to_name.json /app
COPY model-xview.py /app


ENV PYTHONUNBUFFERED=1
