#!/usr/bin/env python3

import subprocess
import re
import time
import datetime
import json
from pathlib import Path

import click
from dataclasses import dataclass
import jinja2
from typing import Mapping, Optional
from rich import print

ZONES_SUFFIX = ".zone"
ZONES_PATTERN = f"*{ZONES_SUFFIX}"
ZONES_DEPLOY_STATE = "zones_deploy.json"
SERIAL_MAGIC = ""
SERIAL_RE = re.compile(
    r"(^.*\sSOA\s[^)]+\s)1\s*;\s*SERIALAUTOUPDATE",
    flags=re.DOTALL | re.IGNORECASE | re.MULTILINE,
)


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

    def list_changed_zones(self):
        if self.state is not None:
            old_ref = self.state.commit
        else:
            old_ref = "HEAD~1"
        r = subprocess.run(
            [
                "git",
                "diff",
                "-z",
                "--name-only",
                "HEAD",
                old_ref,
                "--",
                str(Path(self.zones_subdir, ZONES_PATTERN)),
            ],
            stdout=subprocess.PIPE,
        )
        return parse_git_output(r.stdout)


def parse_git_output(stdout):
    if stdout:
        return (Path(p) for p in stdout.decode("utf-8").rstrip("\0").split("\0"))
    else:
        return list()


def zone(zone_file):
    """Strip ZONE_SUFFIX from basename of zone_file"""
    return Path(zone_file).with_suffix("").name


def load_state(state_file):
    with open(state_file, "r") as f:
        return State(**json.load(f))


pass_ctxobj = click.make_pass_decorator(CtxObj)


@click.group()
@click.option(
    "--build-subdir",
    default="build",
    help="subdirectory containing built zone files (with automatically updated serial)",
)
@click.option(
    "--zones-subdir", default=".", help="subdirectory containing source zone files"
)
@click.option("--debug/--no-debug", default=False)
@click.option(
    "--all-zones/--no-all-zones", default=False, help="consider all zones as updated"
)
@click.pass_context
def main(ctx, **options):
    ctx.obj = CtxObj(**options)

    try:
        ctx.state = load_state(ZONES_DEPLOY_STATE)
    except FileNotFoundError:
        ctx.state = None

    ctx.obj.all_zones = {
        zone(zone_file): zone_file for zone_file in ctx.obj.list_zones()
    }
    ctx.obj.changed_zone_files = set(ctx.obj.list_changed_zones())


@main.command()
@click.option(
    "--conf-template",
    default="knot-zones.conf.j2",
    help="name server configuration template",
)
@pass_ctxobj
def build(ctxobj: CtxObj, conf_template):
    print(f":brick: Building in {ctxobj.zones_subdir}")

    new_state = State(commit=subprocess.check_output("git", "rev-parse", "HEAD"))
    for z, zf in ctxobj.all_zones.items():
        if (
            zf in ctxobj.changed_zone_files
            or z not in ctxobj.state.serials
            or ctxobj.all_zones
        ):
            ctxobj.state.update_serial(z)

        substituted = generate(ctxobj, z, zf)
        if substituted:
            new_state.serials[z] = ctxobj.state.serials[z]

    generate_config(ctxobj, conf_template)
    generate_state(ctxobj, new_state)


def ensure_dir(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def generate_config(ctxobj, conf_template):
    out_path = ensure_dir(Path(ctxobj.build_subdir, conf_template).with_suffix(""))

    print(f":hammer_and_wrench: Generating configuration {out_path}")
    env = jinja2.Environment(loader=jinja2.PackageLoader(__package__))
    template = env.get_template(conf_template)

    with out_path.open("w") as out_file:
        out_file.write(template.render(zones=ctxobj.all_zones))


def generate_state(ctxobj, state):
    out_path = ensure_dir(Path(ctxobj.build_subdir, ZONES_DEPLOY_STATE))

    print(f":hammer_and_wrench: Generating new state {out_path}")
    with out_path.open("w") as out_file:
        json.dump(state, out_file)


def generate(ctxobj, zone, zone_file):
    out_path = ensure_dir(Path(ctxobj.build_subdir, zone_file))
    print(f":christmas_tree: Generating zone {out_path}")

    with open(zone_file, "r") as f:
        updated, count = SERIAL_RE.subn(
            lambda m: f"{m.group(1)}{ctxobj.state.serials[zone]}",
            f.read(),
        )

        if count == 0:
            print(f"[yellow]:warning: No serial placeholder found in {zone_file}")

    with out_path.open("w") as f:
        f.write(updated)

    return count > 0


@main.command()
@click.option("--server", default="", help="master server to check for serial increase")
@click.option(
    "--check-command",
    default="kzonecheck -o {zone} {zone_file}",
    help="command to check a zone",
)
@pass_ctxobj
def check(ctxobj: CtxObj, check_command: str, server: str):
    print(":magnifying_glass_tilted_left: Checking")

    syntax_only = server == ""
    all_success = True
    new_state = load_state(Path(ctxobj.build_subdir, ZONES_DEPLOY_STATE))

    for zone, zone_file in ctxobj.all_zones.items():
        success = True
        built_zone_file = Path(ctxobj.build_subdir, zone_file)
        print(f"Checking {built_zone_file}")

        # Syntax check

        r = subprocess.run(
            check_command.format(zone=zone, zone_file=built_zone_file), shell=True
        )
        if r.returncode != 0:
            print(f"[red]:x: {zone} syntax check failed")
            success = False

        # Serial checks

        try:
            new_serial = serial_from_zone_file(zone, zone_file)
        except:
            print(f"[red]:x: Failed to get serial from {zone_file}")
            success = False

        # If zone has an auto-updated serial, check that it's consistent with persisted state

        if (
            success
            and zone in new_state.serials
            and new_serial != new_state.serials[zone]
        ):
            print(
                f"[red]:thinking_face: Inconsistent serial {new_serial} from {zone_file} (auto-update state {new_state.serials[zone]})"
            )
            success = False

        # Check changed zone against current live zone

        if success and not syntax_only and zone_file in ctxobj.changed_zone_files:
            try:
                current_serial = serial_from_query(zone, server)
            except:
                print(
                    f"[yellow]:warning: Failed to query serial for {zone}, skipping check"
                )
                current_serial = None

            try:
                new_serial = serial_from_zone_file(zone, zone_file)
            except:
                print(f"[red]:x: Failed to get serial from {zone_file}")

            if current_serial is not None and not is_serial_increased(
                current_serial, new_serial
            ):
                print(
                    f"[red]:x: {zone} serial check failed: {new_serial} is not greater than {current_serial}"
                )
                success = False

        # Checks done

        if success:
            print(f"[green]:white_check_mark: {zone}")

        all_success &= success

    return all_success


def serial_from_query(zone, server):
    from dns import message, name, query, rdatatype

    zone_name = name.from_text(zone)
    soa_query = message.make_query(zone_name, rdatatype.SOA)
    soa_reply = query.udp(soa_query, server)
    return soa_reply.answer[0][0].serial


def serial_from_zone_file(zone, zone_file):
    from dns.zone import from_file

    zdata = from_file(zone_file, origin=zone)
    soa = zdata.find_rdataset("@", "SOA")
    return soa[0].serial


# From dzonegit


def is_serial_increased(old, new):
    """Return true if serial number was increased using RFC 1982 logic."""
    old, new = (int(n) for n in [old, new])
    diff = (new - old) % 2**32
    return 0 < diff < (2**31 - 1)


def get_increased_serial(old):
    """Return increased serial number, automatically recognizing the type."""
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
