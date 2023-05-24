FROM cznic/knot AS base
RUN apt update && apt install -y rsync
COPY files/ /
