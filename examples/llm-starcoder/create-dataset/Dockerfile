FROM python:3.10

RUN pip install pyarrow pandas
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY create_dataset.py /app
