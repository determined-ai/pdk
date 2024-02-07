FROM python:3.10

RUN pip install transformers torch peft determined
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY peft_merge.py /app
