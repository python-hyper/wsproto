# Things that would be nice:
# - less hard-coding of paths here

from __future__ import print_function

import sys
import os.path
import argparse
import errno
import subprocess
import json
import socket
import time
import copy

PORT = 8642

CLIENT_CONFIG = {
   "options": {"failByDrop": False},
   "outdir": "./reports/servers",

   "servers": [
       {
           "agent": "wsproto",
           "url": "ws://localhost:{}".format(PORT),
           "options": {"version": 18},
       },
   ],

   "cases": ["*"],
   "exclude-cases": [],
   "exclude-agent-cases": {},
}

SERVER_CONFIG = {
   "url": "ws://localhost:{}".format(PORT),

   "options": {"failByDrop": False},
   "outdir": "./reports/clients",
   "webport": 8080,

   "cases": ["*"],
   "exclude-cases": [],
   "exclude-agent-cases": {}
}

CASES = {
    "all": ["*"],
    "fast":
        # The core functionality tests
        ["{}.*".format(i) for i in range(1, 12)]
        # Compression tests -- in each section, the tests get progressively
        # slower until they're taking 10s of seconds apiece. And it's
        # mostly stress tests, without much extra coverage to show for
        # it. (Weird trick: autobahntestsuite treats these as regexps
        # except that . is quoted and * becomes .*)
        + ["12.*.[1234]$", "13.*.[1234]$"]
        # At one point these were catching a unique bug that none of the
        # above were -- they're relatively quick and involve
        # fragmentation.
        + ["12.1.11", "12.1.12", "13.1.11", "13.1.12"],
}

def say(*args):
    print("run-autobahn-tests.py:", *args)

def setup_venv():
    if not os.path.exists("autobahntestsuite-venv"):
        say("Creating Python 2.7 environment and installing autobahntestsuite")
        subprocess.check_call(
            ["virtualenv", "-p", "python2.7", "autobahntestsuite-venv"])
        subprocess.check_call(
            ["autobahntestsuite-venv/bin/pip", "install", "autobahntestsuite>=0.8.0"])

def wait_for_listener(port):
    while True:
        sock = socket.socket()
        try:
            sock.connect(("localhost", port))
        except socket.error as exc:
            if exc.errno == errno.ECONNREFUSED:
                time.sleep(0.01)
            else:
                raise
        else:
            return
        finally:
            sock.close()

def coverage(command, coverage_settings):
    if not coverage_settings["enabled"]:
        return [sys.executable] + command

    return ([sys.executable, "-m", "coverage", "run",
             "--include", coverage_settings["wsproto-path"]]
            + command)

def summarize(report_path):
    with open(os.path.join(report_path, "index.json")) as f:
        result_summary = json.load(f)["wsproto"]
    failed = 0
    total = 0
    PASS = {"OK", "INFORMATIONAL"}
    for test_name, results in sorted(result_summary.items()):
        total += 1
        if (results["behavior"] not in PASS
              or results["behaviorClose"] not in PASS):
            say("FAIL:", test_name, results)
            say("Details:")
            with open(os.path.join(report_path, results["reportfile"])) as f:
                print(f.read())
            failed += 1

    speed_ordered = sorted(result_summary.items(),
                           key=lambda kv: -kv[1]["duration"])
    say("Slowest tests:")
    for test_name, results in speed_ordered[:5]:
        say("    {}: {} seconds".format(test_name, results["duration"] / 1000))

    return failed, total

def run_client_tests(cases, coverage_settings):
    say("Starting autobahntestsuite server")
    server_config = copy.deepcopy(SERVER_CONFIG)
    server_config["cases"] = cases
    with open("auto-tests-server-config.json", "w") as f:
        json.dump(server_config, f)
    server = subprocess.Popen(
        ["autobahntestsuite-venv/bin/wstest", "-m", "fuzzingserver",
         "-s", "auto-tests-server-config.json"])
    say("Waiting for server to start")
    wait_for_listener(PORT)
    try:
        say("Running wsproto test client")
        subprocess.check_call(coverage(["./test_client.py"], coverage_settings))
        # the client doesn't exit until the server closes the connection on the
        # /updateReports call, and the server doesn't close the connection until
        # after it writes the reports, so there's no race condition here.
    finally:
        say("Stopping server...")
        server.terminate()
        server.wait()

    return summarize("reports/clients")

def run_server_tests(cases, coverage_settings):
    say("Starting wsproto test server")
    server = subprocess.Popen(coverage(["./test_server.py"], coverage_settings))
    try:
        say("Waiting for server to start")
        wait_for_listener(PORT)

        client_config = copy.deepcopy(CLIENT_CONFIG)
        client_config["cases"] = cases
        with open("auto-tests-client-config.json", "w") as f:
            json.dump(client_config, f)
        say("Starting autobahntestsuite client")
        subprocess.check_call(
            ["autobahntestsuite-venv/bin/wstest", "-m", "fuzzingclient",
             "-s", "auto-tests-client-config.json"])
    finally:
        say("Stopping server...")
        # Connection on this port triggers a shutdown
        sock = socket.socket()
        sock.connect(("localhost", PORT + 1))
        sock.close()
        server.wait()

    return summarize("reports/servers")

def main():
    if not os.path.exists("test_client.py"):
        say("Run me from the compliance/ directory")
        sys.exit(2)
    coverage_settings = {
        "coveragerc": "../.coveragerc",
    }
    try:
        import wsproto
    except ImportError:
        say("wsproto must be on python path -- set PYTHONPATH or install it")
        sys.exit(2)
    else:
        coverage_settings["wsproto-path"] = os.path.dirname(wsproto.__file__)

    parser = argparse.ArgumentParser()

    parser.add_argument("MODE", help="'client' or 'server'")
    # can do e.g.
    #   --cases='["1.*"]'
    parser.add_argument("--cases",
                        help="'fast' or 'all' or a JSON list",
                        default="fast")
    parser.add_argument("--cov", help="enable coverage", action="store_true")

    args = parser.parse_args()

    coverage_settings["enabled"] = args.cov
    cases = args.cases
    #pylint: disable=consider-using-get
    if cases in CASES:
        cases = CASES[cases]
    else:
        cases = json.loads(cases)

    setup_venv()

    if args.MODE == "client":
        failed, total = run_client_tests(cases, coverage_settings)
    elif args.MODE == "server":
        failed, total = run_server_tests(cases, coverage_settings)
    else:
        say("Unrecognized mode, try 'client' or 'server'")
        sys.exit(2)

    say("in {} mode: failed {} out of {} total"
        .format(args.MODE.upper(), failed, total))

    if failed:
        say("Test failed")
        sys.exit(1)
    else:
        say("SUCCESS!")


if __name__ == "__main__":
    main()
