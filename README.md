# DNS CI/CD

Continuous Integration and Continuous Delivery scripts for DNS zones

Automated builds of the image are available on:

- DockerHub: [quinot/dns_ci_cd](https://hub.docker.com/r/quinot/dns_ci_cd)
  - ![Docker Image CI Status](https://github.com/quinot/dns-ci-cd/workflows/Docker%20Image%20CI/badge.svg)


Taking inspiration from:
* [CommunityRack/knotci](https://github.com/CommunityRack/knotci)
* [oskar456/dzonegit](https://github.com/oskar456/dzonegit)

# Steps

## Build

There is no build step: zone files and config files are handed directly to Knot,
which takes care of serial management.

## Check

* Config file: `knotc conf-check`
* Zone files: `kzonecheck`

## Deploy

* Copy configuration and zone files
  * Config and zone files are expected to reside in /config and /config/zones, respectively (as in https://github.com/quinot/docker-knot-ssh)
* Reload name server
  * If config file changed: full reload
  * Else reload only changed zones
