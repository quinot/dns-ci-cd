FROM python:3.11
COPY . /src
RUN pip install /src && rm -fr /src
