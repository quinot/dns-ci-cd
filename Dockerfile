FROM python:3.8
COPY . /src
RUN pip install /src && rm -fr /src
