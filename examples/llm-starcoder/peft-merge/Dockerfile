FROM python:3.9

RUN pip install transformers torch==1.13.1 determined git+https://github.com/huggingface/peft.git huggingface-hub==0.17.3

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY peft_merge.py /app
