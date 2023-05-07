# DNS CI/CD

Continuous Integration and Continuous Delivery scripts for DNS zones

Taking inspiration from:
* CommunityRack/knotci
* oskar456/dzonegit

# Steps

## Build

For any zone changed since last successful zone publish:
* compute updated serial

For all zones:
* insert old or updated serial

## Check

For all zones:
* run `named-checkzone`

For any zone changed since last successful zone publish:
* check that new zone file has a newer serial that the current published zone

## Deploy

* Generate name server configuration from template and list of zones
* Copy configuration and zone files
* Reload name server
  * If config file changed: full reload
  * Else reload only changed zones

# Events

## Pull request

Build
Check

## Merge

Build
Check
Deploy

# State

The state of the last successfully published zones is kept in a JSON
file `dns.json`:

```
{
  commit: "HASH",
  serials: {
    "ZONE": SERIAL,
    ...
  }
}
```

# TODO

* add pre-commit
  * add black, pep8, isort