FROM cznic/knot AS base
RUN apt update && apt install -y git

ENV PYENV_ROOT /root/.pyenv
ENV PATH $PYENV_ROOT/shims:$PYENV_ROOT/bin:$PATH

FROM base AS python
ARG PYTHON_VERSION=3.11
RUN apt install -y curl \
                   build-essential libssl-dev zlib1g-dev \
                   libbz2-dev libreadline-dev libsqlite3-dev curl \
                   libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev \
                   libffi-dev liblzma-dev

RUN curl https://pyenv.run | bash

RUN pyenv install ${PYTHON_VERSION} && pyenv global ${PYTHON_VERSION} && \
    pyenv rehash

FROM base

COPY --from=python /root/.pyenv /root/.pyenv

RUN apt install -y rsync
COPY . /src
RUN pip install -U pip && pip install /src && rm -fr /src
