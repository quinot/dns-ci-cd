#!/usr/bin/env python3

import os
import sys
import subprocess
import shlex
import re
import time
import datetime
import json
from collections import namedtuple
from hashlib import sha256
from pathlib import Path
from string import Template

import click
from dataclasses import dataclass
import importlib.resources
import jinja2
from typing import Mapping, Optional
from rich import print, inspect

@dataclass
class State:
    commit: str
    serials: Mapping[str, int]

    def update_serial(self, zone):
        self.serials[zone] = get_increased_serial(self.serials.get(zone, 2000010100))

@dataclass
class CtxObj:
    # Command line options

    build_subdir: str
    zones_subdir: str
    debug: bool
    all_zones: bool

    # Other global state

    state: Optional[State] = None

    def list_zones(self):
        print(f"listing {self.zones_subdir}/{ZONES_PATTERN}")
        return Path(self.zones_subdir).glob(ZONES_PATTERN)

    def changed_zones(self):
        if self.state is not None:
            old_ref = self.state.commit
        else:
            old_ref = "HEAD~1"
        r = subprocess.run(
            [
                "git", "diff", "-z", "--name-only",
                "HEAD", old_ref, "--", str(Path(self.zones_subdir, ZONES_PATTERN))
            ],
            stdout=subprocess.PIPE,
        )
        return parse_git_output(r.stdout)

def parse_git_output(stdout):
    if stdout:
        return (Path(p)
                for p in stdout.decode("utf-8").rstrip("\0").split("\0"))
    else:
        return list()

ZONES_SUFFIX=".zone"
ZONES_PATTERN = f"*{ZONES_SUFFIX}"
ZONES_DEPLOY_STATE = "zones_deploy.json"
SERIAL_MAGIC = ""
SERIAL_RE = re.compile(r"(^.*\sSOA\s[^)]+\s)1\s*;\s*SERIALAUTOUPDATE", flags=re.DOTALL | re.IGNORECASE | re.MULTILINE)

def zone(zone_file):
    """Strip ZONE_SUFFIX from basename of zone_file"""
    return Path(zone_file).with_suffix("").name

pass_ctxobj = click.make_pass_decorator(CtxObj)

@click.group()
@click.option("--build-subdir", default="build", help="subdirectory containing built zone files (with automatically updated serial)")
@click.option("--zones-subdir", default=".", help="subdirectory containing source zone files")
@click.option("--debug/--no-debug", default=False)
@click.option("--all-zones/--no-all-zones", default=False, help="consider all zones as updated")
@click.pass_context
def main(ctx, **options):
    ctx.obj = CtxObj(**options)

    try:
        with open(ZONES_DEPLOY_STATE, "r") as state_file:
            ctx.obj.state = State(**json.load(state_file))
            if ctx.obj.debug:
                inspect(ctx.obj.state)
    except OSError:
        pass

@main.command()
@click.option("--conf-template", default="knot-zones.conf.j2", help="name server configuration template")
@pass_ctxobj
def build(ctxobj: CtxObj, conf_template):
    print(f":brick: Building in {ctxobj.zones_subdir}")

    all_zones = {zone(zone_file): zone_file for zone_file in ctxobj.list_zones()}
    changed_zone_files = set(ctxobj.changed_zones())

    for z, zf in all_zones.items():
        if (
            zf in changed_zone_files
            or z not in ctxobj.state.serials
            or ctxobj.all_zones
        ):
            ctxobj.state.update_serial(z)

        generate(ctxobj, z, zf)

    generate_config(ctxobj, conf_template, all_zones)

def generate_config(ctxobj, conf_template, zones):
    build_path = Path(ctxobj.build_subdir)
    build_path.mkdir(parents=True, exist_ok=True)
    out_path = build_path.joinpath(Path(conf_template).with_suffix(""))

    print(f":hammer_and_wrench: Generating configuration {out_path}")
    env = jinja2.Environment(loader=jinja2.PackageLoader(__package__))
    template = env.get_template(conf_template)

    with out_path.open("w") as out_file:
        out_file.write(template.render(zones=zones))


def generate(ctxobj, zone, zone_file):
    out_file = os.path.join(ctxobj.build_subdir, os.path.basename(zone_file))
    print(f":christmas_tree: Generating zone {out_file}")
    with open(zone_file, "r") as f:
        updated, count = SERIAL_RE.subn(
            lambda m: f"{m.group(1)}{ctxobj.state.serials[zone]}",
            f.read(),
        )

        if count == 0:
            print(f"[yellow]:warning: No serial placeholder found in {zone_file}")

    with open(out_file, "w") as f:
        f.write(updated)

@main.command()
@pass_ctxobj
def check(ctxobj: CtxObj):
    print(":magnifying_glass_tilted_left: Checking")

@main.command()
@pass_ctxobj
def deploy(ctxobj: CtxObj):
    print(":ship: Deploying")

class HookException(ValueError):
    """Exception raised when there is an error in input data.

    Attribures:
        message -- the cause of problem
        fname -- affected file
        stderr -- output of the specific checker
    """

    def __init__(self, message, fname=None, stderr=None):
        self.message = message
        self.fname = fname
        self.stderr = stderr

    def __str__(self):
        r = list()
        if self.fname:
            r.append("{fname}: ".format(fname=self.fname))
        r.append(self.message)
        r.append("\n")
        if self.stderr:
            r.append("\n")
            r.append(self.stderr)
            r.append("\n\n")
        return "".join(r)


def get_head(empty=False):
    if not empty:
        r = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if r.returncode == 0:
            return r.stdout.decode("ascii").strip()
    # Initial commit: diff against an empty tree object
    return "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def check_whitespace_errors(against, revision=None):
    if revision:
        cmd = ["git", "diff-tree", "--check", against, revision, "*.zone"]
    else:
        cmd = ["git", "diff-index", "--check", "--cached", against, "*.zone"]
    r = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if r.returncode != 0:
        raise HookException(
            "Whitespace errors",
            stderr=r.stdout.decode("utf-8"),
        )


def get_file_contents(path, revision=None):
    """ Return contents of a file in staged env or in some revision. """
    revision = "" if revision is None else revision
    r = subprocess.run(
        ["git", "show", "{r}:{p}".format(r=revision, p=path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    return r.stdout


def unixtime_directive(zonedata, unixtime=None):
    """ Filter binary zone data. Replace $UNIXTIME with current unix time. """
    if unixtime is None:
        unixtime = int(time.time())
    return re.sub(
        br'\$UNIXTIME\b',
        str(unixtime).encode("ascii"),
        zonedata,
        flags=re.IGNORECASE,
    )


def check_missing_trailing_dot(zonename, compiled_zonedata):
    badlines = []
    for line in compiled_zonedata.splitlines():
        if re.search(
                r"\sPTR\s+[^\s]*\.{}.$".format(zonename).encode("ascii"),
                line,
                re.I,
        ):
            badlines.append(line.decode("utf-8"))
    if badlines:
        raise HookException(
            "Possibly missing trailing dot after PTR records:\n{}".format(
                "\n".join(badlines),
            ),
            fname=zonename,
        )


def compile_zone(zonename, zonedata, unixtime=None, missing_dot=False):
    """ Compile the zone. Return tuple with results."""
    CompileResults = namedtuple(
        "CompileResults", "success, serial, zonehash, stderr",
    )
    r = subprocess.run(
        ["/usr/bin/env", "named-compilezone", "-o", "-", zonename, "/dev/stdin"],
        input=unixtime_directive(zonedata, unixtime),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stderr = r.stderr.decode("utf-8")
    m = re.search(r"^zone.*loaded serial ([0-9]*)$", stderr, re.MULTILINE)
    if r.returncode == 0 and m:
        serial = m.group(1)
        if missing_dot:
            check_missing_trailing_dot(zonename, r.stdout)
        zonehash = sha256(r.stdout).hexdigest()
        return CompileResults(True, serial, zonehash, stderr)
    else:
        return CompileResults(False, None, None, stderr)


def is_serial_increased(old, new):
    """ Return true if serial number was increased using RFC 1982 logic. """
    old, new = (int(n) for n in [old, new])
    diff = (new - old) % 2**32
    return 0 < diff < (2**31 - 1)


def get_increased_serial(old):
    """ Return increased serial number, automatically recognizing the type. """
    old = int(old)
    now = int(time.time())
    todayserial = int(datetime.date.today().strftime("%Y%m%d00"))
    # Note to my future self: This is expected to break on 2034-06-16
    # as unix timestamp will become in the same range as YYMMDDnn serial
    if 1e9 < old < now:
        # Serial is unix timestamp
        return str(now)
    elif 2e9 < old < todayserial:
        # Serial is YYYYMMDDnn, updated before today
        return str(todayserial)
    else:
        # No pattern recognized, just increase the number
        return str(old + 1)


def get_altered_files(against, diff_filter=None, revision=None):
    """ Return list of changed files.
        If revision is None, list changes between staging area and
        revision. Otherwise differences between two revisions are computed.
    """
    cmd = ["git", "diff", "--name-only", "-z", "--no-renames"]
    if diff_filter:
        cmd.append("--diff-filter={}".format(diff_filter))
    if revision:
        cmd.append(against)
        cmd.append(revision)
    else:
        cmd.append("--cached")
        cmd.append(against)

    r = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    if r.stdout:
        return (Path(p)
                for p in r.stdout.decode("utf-8").rstrip("\0").split("\0"))
    else:
        return list()


def get_zone_origin(zonedata):
    """
    Parse $ORIGIN directive before the SOA record.
    Return zone name without the trailing dot.
    """
    for line in zonedata.splitlines():
        if re.match(br"^[^\s;]+\s+([0-9]+\s+)?(IN\s+)?SOA\s+", line, re.I):
            break
        m = re.match(br"^\$ORIGIN\s+([^ ]+)\.\s*(;.*)?$", line, re.I)
        if m:
            return m.group(1).decode("utf-8").lower()


def get_zone_name(path, zonedata):
    """
    Try to guess zone name from either filename or the first $ORIGIN.
    Unless disabled, throw a HookException if filename and zone ORIGIN differ
    more than in slashes.
    """
    stemname = Path(path).stem.lower()
    originname = get_zone_origin(zonedata)
    if originname:
        tt = str.maketrans("", "", "/_,:-+*%^&#$")
        sn, on = [s.translate(tt) for s in [stemname, originname]]
        if sn != on and not get_config("dzonegit.allowfancynames", bool):
            raise HookException(
                "Zone origin {o} differs from zone file.".format(o=originname),
                fname=path,
            )
        return originname
    else:
        return stemname


def check_updated_zones(
        against,
        revision=None,
        autoupdate_serial=False,
        missing_dot=False,
):
    """ Check whether all updated zone files compile. """
    unixtime = int(time.time())
    for f in get_altered_files(against, "AMCR", revision):
        if not f.suffix == ".zone":
            continue
        print("Checking file {f}".format(f=f))
        zonedata = get_file_contents(f, revision)
        zname = get_zone_name(f, zonedata)
        rnew = compile_zone(zname, zonedata, unixtime, missing_dot)
        if not rnew.success:
            raise HookException(
                "New zone version does not compile",
                f, rnew.stderr,
            )
        try:
            zonedata = get_file_contents(f, against)
            zname = get_zone_name(f, zonedata)
            rold = compile_zone(zname, zonedata, unixtime-1)

            if (rold.success and rold.zonehash != rnew.zonehash and not
                    is_serial_increased(rold.serial, rnew.serial)):
                errmsg = "Zone contents changed without increasing serial."
                diagmsg = "Old revision {}, serial {}, new serial {}".format(
                    against, rold.serial, rnew.serial,
                )

                if autoupdate_serial:
                    newserial = get_increased_serial(rnew.serial)
                    if replace_serial(f, rnew.serial, newserial):
                        errmsg += " Serial has been automatically increased."
                        errmsg += " Check and recommit."
                    else:
                        errmsg += " Autoupdate of serial number failed."
                raise HookException(
                    errmsg,
                    fname=f,
                    stderr=diagmsg,
                )
        except subprocess.CalledProcessError:
            pass    # Old version of zone did not exist


def get_config(name, type_=None):
    cmd = ["git", "config", ]
    if type_ == bool:
        cmd.append("--bool")
    elif type_ == int:
        cmd.append("--int")
    elif type_:
        raise ValueError("Invalid type supplied")
    cmd.append(name)
    r = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
    )
    if r.returncode != 0:
        return None
    if type_ == bool:
        return r.stdout == b"true\n"
    elif type_ == int:
        return int(r.stdout)
    else:
        return r.stdout.decode("utf-8").rstrip("\n")


def replace_serial(path, oldserial, newserial):
    contents = path.read_text()
    updated, count = re.subn(
        r'(^.*\sSOA\s.+?\s){}([^0-9])'.format(oldserial),
        r'\g<1>{}\g<2>'.format(newserial),
        contents,
        count=1,
        flags=re.DOTALL | re.IGNORECASE | re.MULTILINE,
    )
    if count != 1:
        return False
    path.write_text(updated)
    return True


def get_zone_wildcards(name):
    """ A generator of wildcards out of a zone name.
    For a DNS name, returns series of:
     - the name itself
     - the name with first label substitued as *
     - the name with first label dropped and second substittuted as *
     - ...
     - single *
"""
    yield name
    labels = name.split(".")
    while labels:
        labels[0] = "*"
        yield ".".join(labels)
        labels.pop(0)


def template_config(checkoutpath, template, blacklist=set(), whitelist=set()):
    """ Recursively find all *.zone files and template config file using
    a simple JSON based template like this:

    {
      "header": "# Managed by dzonegit, do not edit.\n",
      "footer": "",
      "item": " - zone: \"$zonename\"\n   file: \"$zonefile\"\n   $zonevar\n",
      "defaultvar": "template: default",
      "zonevars": {
        "example.com": "template: signed",
        "*.com": "template: dotcom",
        "*": "template: uberdefault"
      }
    }

    Available placeholders are:
      - $datetime - timestamp of file creation
      - $zonename - zone name, without trailing dot
      - $zonefile - full path to zone file
      - $zonevar - per-zone specific variables, content of `defaultvar` if
                   not defined for current zone
    """
    tpl = json.loads(template)
    headertpl = Template(tpl.get("header", ""))
    footertpl = Template(tpl.get("footer", ""))
    itemtpl = Template(tpl.get("item", ""))
    defaultvar = tpl.get("defaultvar", "")
    zonevars = tpl.get("zonevars", dict())
    out = list()
    zones = dict()
    mapping = {"datetime": datetime.datetime.now().strftime("%c")}
    if headertpl.template:
        out.append(headertpl.substitute(mapping))
    for f in sorted(Path(checkoutpath).glob("**/*.zone")):
        zonename = get_zone_name(f, f.read_bytes())
        if whitelist and not any(
                n in whitelist
                for n in get_zone_wildcards(zonename)
        ):
            print(
                "WARNING: Ignoring zone {} - not whitelisted for "
                "this repository.".format(zonename),
            )
            continue
        if any(n in blacklist for n in get_zone_wildcards(zonename)):
            print(
                "WARNING: Ignoring zone {} - blacklisted for "
                "this repository.".format(zonename),
            )
            continue
        if zonename in zones:
            print(
                "WARNING: Duplicate zone file found for zone {}. "
                "Using file {}, ignoring {}.".format(
                    zonename, zones[zonename],
                    f.relative_to(checkoutpath),
                ),
            )
            continue
        zones[zonename] = f.relative_to(checkoutpath)
        for name in get_zone_wildcards(zonename):
            if name in zonevars:
                zonevar = zonevars[name]
                break
        else:
            zonevar = defaultvar
        out.append(itemtpl.substitute(
            mapping, zonename=zonename,
            zonefile=str(f), zonerelfile=str(f.relative_to(checkoutpath)), zonevar=zonevar,
        ))
    if footertpl.template:
        out.append(footertpl.substitute(mapping))
    return "\n".join(out)


def load_set_file(path):
    if path is None:
        return set()
    with open(path) as inf:
        return {
            l.strip() for l in inf
            if not l.strip().startswith("#") and len(l) > 1
        }


def do_commit_checks(
        against,
        revision=None,
        autoupdate_serial=False,
        missing_dot=False,
):
    try:
        if not get_config("dzonegit.ignorewhitespaceerrors", bool):
            check_whitespace_errors(against, revision=revision)
        check_updated_zones(
            against, revision=revision,
            autoupdate_serial=autoupdate_serial,
            missing_dot=missing_dot,
        )
    except HookException as e:
        print(e)
        raise SystemExit(1)


def pre_commit():
    against = get_head()
    autoupdate_serial = not get_config("dzonegit.noserialupdate", bool)
    missing_dot = not get_config("dzonegit.nomissingdotcheck", bool)
    do_commit_checks(
        against,
        autoupdate_serial=autoupdate_serial,
        missing_dot=missing_dot,
    )


def update(argv=sys.argv):
    if "GIT_DIR" not in os.environ:
        raise SystemExit("Don't run this hook from the command line")
    if len(argv) < 4:
        raise SystemExit(
            "Usage: {} <ref> <oldrev> <newrev>".format(argv[0]),
        )
    refname, against, revision = argv[1:4]

    if against == "0000000000000000000000000000000000000000":
        against = get_head(True)  # Empty commit

    if refname != "refs/heads/master":
        raise SystemExit("Nothing else than master branch is accepted here")
    do_commit_checks(against, revision)


def pre_receive(stdin=sys.stdin):
    if stdin.isatty():
        raise SystemExit("Don't run this hook from the command line")
    for line in stdin:
        against, revision, refname = line.rstrip().split(" ")
        if refname != "refs/heads/master":
            raise SystemExit(
                "Nothing else than master branch "
                "is accepted here",
            )
        if against == "0000000000000000000000000000000000000000":
            against = get_head(True)  # Empty commit
        do_commit_checks(against, revision)


def post_receive(stdin=sys.stdin):
    """Checkout the repository to a path specified in the config.
    Re-generate config files using defined templates. Issue reload
    commands for modified zone files, issue reconfig command if zones were
    added or delefed.
    """
    suffixes = list(str(n) if n else "" for n in range(10))
    blacklist = load_set_file(get_config("dzonegit.zoneblacklist"))
    whitelist = load_set_file(get_config("dzonegit.zonewhitelist"))
    checkoutpath = get_config("dzonegit.checkoutpath")
    if not checkoutpath:
        raise SystemExit("Checkout path not defined. Nothing to do.")

    print("Checking out repository into {}…".format(checkoutpath))
    Path(checkoutpath).mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "checkout", "-f", "master"],
        check=True,
        env=dict(os.environ, GIT_WORK_TREE=checkoutpath),
        stderr=subprocess.DEVNULL,
    )
    for s in suffixes:
        cfpath = get_config("dzonegit.conffilepath{}".format(s))
        tplpath = get_config("dzonegit.conffiletemplate{}".format(s))
        if cfpath is None or tplpath is None:
            continue
        print("Templating config file {}…".format(cfpath))
        Path(cfpath).write_text(
            template_config(
                checkoutpath,
                Path(tplpath).read_text(),
                blacklist=blacklist,
                whitelist=whitelist,
            ),
        )

    if stdin.isatty():
        raise SystemExit(
            "Standard input should be redirected. Not issuing any reload "
            "commands.",
        )
    for line in stdin:
        against, revision, refname = line.rstrip().split(" ")
        if refname != "refs/heads/master":
            continue
        if against == "0000000000000000000000000000000000000000":
            against = get_head(True)  # Empty commit
        should_reconfig = [
            f for f in get_altered_files(against, "ACDRU", revision)
            if f.suffix == ".zone"
        ]
        zones_to_reload = [
            get_zone_name(f, (checkoutpath / f).read_bytes())
            for f in get_altered_files(against, "M", revision)
            if f.suffix == ".zone"
        ]
        if should_reconfig:
            print("Zone list change detected, reloading configuration")
            for s in suffixes:
                reconfigcmd = get_config("dzonegit.reconfigcmd{}".format(s))
                if reconfigcmd:
                    print("Calling {}…".format(reconfigcmd))
                    subprocess.run(reconfigcmd, shell=True)

        for z in zones_to_reload:
            for s in suffixes:
                zonereloadcmd = get_config(
                    "dzonegit.zonereloadcmd{}".format(s),
                )
                if zonereloadcmd:
                    cmd = shlex.split(zonereloadcmd)
                    cmd.append(z)
                    print("Calling {}…".format(" ".join(cmd)))
                    subprocess.run(cmd)


def smudge_serial(
        bstdin=sys.stdin.buffer,
        bstdout=sys.stdout.buffer,
        unixtime=None,
):
    """Replace all $UNIXTIME directives with current unix time."""
    bstdout.write(unixtime_directive(bstdin.read(), unixtime))
