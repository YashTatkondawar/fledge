# -*- coding: utf-8 -*-

# FLEDGE_BEGIN
# See: http://fledge.readthedocs.io/
# FLEDGE_END

""" Test EDS

"""

import os
import subprocess
import http.client
import json
import time
import pytest
from pathlib import Path
import utils
from datetime import datetime

__author__ = "Yash Tatkondawar"
__copyright__ = "Copyright (c) 2020 Dianomic Systems, Inc."
__license__ = "Apache 2.0"
__version__ = "${VERSION}"

asset_name = "sinusoid"
north_plugin = "PI_Server_V2"
task_name = "eds"
host = "http://localhost:5590/api/v1/tenants/default/namespaces/default/omf"
token = ""
# This  gives the path of directory where fledge is cloned. test_file < packages < python < system < tests < ROOT
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent
SCRIPTS_DIR_ROOT = "{}/tests/system/python/packages/data/".format(PROJECT_ROOT)
FLEDGE_ROOT = os.environ.get('FLEDGE_ROOT')


@pytest.fixture
def reset_fledge(wait_time):
    try:
        subprocess.run(["cd {}/tests/system/python/scripts/package && ./reset"
                       .format(PROJECT_ROOT)], shell=True, check=True)
    except subprocess.CalledProcessError:
        assert False, "reset package script failed!"

    # Wait for fledge server to start
    time.sleep(wait_time)


@pytest.fixture
def reset_eds():
    eds_reset_url = "/api/v1/Administration/Storage/Reset"
    con = http.client.HTTPConnection("localhost", 5590)
    con.request("POST", eds_reset_url, "")
    resp = con.getresponse()


@pytest.fixture
def remove_and_add_pkgs(package_build_version):
    try:
        subprocess.run(["cd {}/tests/system/python/scripts/package && ./remove"
                       .format(PROJECT_ROOT)], shell=True, check=True)
    except subprocess.CalledProcessError:
        assert False, "remove package script failed!"

    try:
        subprocess.run(["cd {}/tests/system/python/scripts/package/ && ./setup {}"
                       .format(PROJECT_ROOT, package_build_version)], shell=True, check=True)
    except subprocess.CalledProcessError:
        assert False, "setup package script failed"

    try:
        subprocess.run(["sudo apt install -y fledge-south-sinusoid"], shell=True, check=True)
    except subprocess.CalledProcessError:
        assert False, "installation of sinusoid package failed"


def get_ping_status(fledge_url):
    _connection = http.client.HTTPConnection(fledge_url)
    _connection.request("GET", '/fledge/ping')
    r = _connection.getresponse()
    assert 200 == r.status
    r = r.read().decode()
    jdoc = json.loads(r)
    return jdoc


def get_statistics_map(fledge_url):
    _connection = http.client.HTTPConnection(fledge_url)
    _connection.request("GET", '/fledge/statistics')
    r = _connection.getresponse()
    assert 200 == r.status
    r = r.read().decode()
    jdoc = json.loads(r)
    return utils.serialize_stats_map(jdoc)


@pytest.fixture
def check_eds_installed():
    dpkg_list = os.popen('dpkg --list osisoft.edgedatastore >/dev/null; echo $?')
    ls_output = dpkg_list.read()
    assert ls_output == "0\n", "EDS not installed. Please install it first!"
    eds_data_url = "/api/v1/diagnostics/productinformation"
    con = http.client.HTTPConnection("localhost", 5590)
    con.request("GET", eds_data_url)
    resp = con.getresponse()
    r = json.loads(resp.read().decode())
    assert len(r) != 0, "EDS not installed. Please install it first!"


@pytest.fixture
def start_south_north(fledge_url):
    payload = {"name": "Sine", "type": "south", "plugin": "sinusoid", "enabled": True, "config": {}}
    post_url = "/fledge/service"
    conn = http.client.HTTPConnection(fledge_url)
    conn.request("POST", post_url, json.dumps(payload))
    res = conn.getresponse()
    assert 200 == res.status, "ERROR! POST {} request failed".format(post_url)

    conn = http.client.HTTPConnection(fledge_url)
    data = {"name": task_name,
            "plugin": "{}".format(north_plugin),
            "type": "north",
            "schedule_type": 3,
            "schedule_day": 0,
            "schedule_time": 0,
            "schedule_repeat": 1,
            "schedule_enabled": "true",
            "config": {"producerToken": {"value": token},
                       "URL": {"value": "{}".format(host)}
                       }
            }
    conn.request("POST", '/fledge/scheduled/task', json.dumps(data))
    r = conn.getresponse()
    assert 200 == r.status


def verify_eds_data():
    eds_data_url = "/api/v1/tenants/default/namespaces/default/streams/1measurement_sinusoid/Data/Last"
    con = http.client.HTTPConnection("localhost", 5590)
    con.request("GET", eds_data_url)
    resp = con.getresponse()
    r = json.loads(resp.read().decode())
    return r


def verify_eds_egress_asset_tracking(fledge_url):
    conn = http.client.HTTPConnection(fledge_url)
    conn.request("GET", '/fledge/asset')
    r = conn.getresponse()
    assert 200 == r.status
    r = r.read().decode()
    retval = json.loads(r)
    assert len(retval) == 1
    assert asset_name == retval[0]["assetCode"]

    tracking_details = utils.get_asset_tracking_details(fledge_url, "Ingest")
    assert len(tracking_details["track"]), "Failed to track Ingest event"
    tracked_item = tracking_details["track"][0]
    assert "Sine" == tracked_item["service"]
    assert asset_name == tracked_item["asset"]
    assert asset_name == tracked_item["plugin"]

    egress_tracking_details = utils.get_asset_tracking_details(fledge_url, "Egress")
    assert len(egress_tracking_details["track"]), "Failed to track Egress event"
    tracked_item = egress_tracking_details["track"][0]
    assert task_name == tracked_item["service"]
    assert asset_name == tracked_item["asset"]
    assert north_plugin == tracked_item["plugin"]


def verify_reconfig_eds(fledge_url, wait_time):
    r = verify_eds_data()
    ts_old = r.get("Time")

    conn = http.client.HTTPConnection(fledge_url)
    data = {"URL": "http://localhost:5591/api/v1/tenants/default/namespaces/default/omf"}
    conn.request("PUT", '/fledge/category/eds', json.dumps(data))
    r = conn.getresponse()
    assert 200 == r.status

    # time.sleep(wait_time)

    r = verify_eds_data()
    ts_new = r.get("Time")

    assert ts_old == ts_new, "EDS reconfiguration failed!"

    conn = http.client.HTTPConnection(fledge_url)
    data = {"URL": "http://localhost:5590/api/v1/tenants/default/namespaces/default/omf"}
    conn.request("PUT", '/fledge/category/eds', json.dumps(data))
    r = conn.getresponse()
    assert 200 == r.status

    assert asset_name in r, "Data in EDS not found!"
    ts = r.get("Time")
    assert ts.find(datetime.now().strftime("%Y-%m-%d")) != -1, "Latest data not found in EDS!"


class TestEDS:
    def test_eds(self, check_eds_installed, reset_eds, remove_and_add_pkgs, reset_fledge, start_south_north, fledge_url, wait_time):
        time.sleep(wait_time * 2)

        ping_response = get_ping_status(fledge_url)
        assert 0 < ping_response["dataRead"]
        assert 0 < ping_response["dataSent"]

        actual_stats_map = get_statistics_map(fledge_url)
        assert 0 < actual_stats_map['SINUSOID']
        assert 0 < actual_stats_map['READINGS']
        assert 0 < actual_stats_map['Readings Sent']
        assert 0 < actual_stats_map[task_name]

        verify_eds_egress_asset_tracking(fledge_url)

        r = verify_eds_data()
        assert asset_name in r, "Data in EDS not found!"
        ts = r.get("Time")
        assert ts.find(datetime.now().strftime("%Y-%m-%d")) != -1, "Latest data not found in EDS!"

        verify_reconfig_eds(fledge_url, wait_time)