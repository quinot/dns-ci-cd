FROM python:3.11
COPY . /src
RUN pip install /src && rm -fr /src
RUN apt update && apt install -y rsync
