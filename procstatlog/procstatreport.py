#!/usr/bin/python
#
# Copyright (C) 2010 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import cgi
import csv
import json
import math
import os
import re
import sys
import time
import urllib

"""Interpret output from procstatlog and write an HTML report file."""


# TODO: Rethink dygraph-combined.js source URL?
PAGE_BEGIN = """
<html><head>
<title>%(filename)s</title>
<script type="text/javascript" src="http://www.corp.google.com/~egnor/no_crawl/dygraph-combined.js"></script>
<script>
var allCharts = [];
var inDrawCallback = false;

OnDraw = function(me, initial) {
    if (inDrawCallback || initial) return;
    inDrawCallback = true;
    var range = me.xAxisRange();
    for (var j = 0; j < allCharts.length; j++) {
        if (allCharts[j] == me) continue;
        allCharts[j].updateOptions({dateWindow: range});
    }
    inDrawCallback = false;
}

MakeChart = function(id, filename, options) {
    options.width = "75%%";
    options.xTicker = Dygraph.dateTicker;
    options.xValueFormatter = Dygraph.dateString_;
    options.xAxisLabelFormatter = Dygraph.dateAxisFormatter;
    options.drawCallback = OnDraw;
    allCharts.push(new Dygraph(document.getElementById(id), filename, options));
}
</script>
</head><body>
<p>
<span style="font-size: 150%%">%(filename)s</span>
- stat report generated by %(user)s on %(date)s</p>
<table cellpadding=0 cellspacing=0 margin=0 border=0>
"""

CHART = """
<tr>
<td valign=top width=25%%>%(label_html)s</td>
<td id="%(id)s"> </td>
</tr>
<script>
MakeChart(%(id_js)s, %(filename_js)s, %(options_js)s)

</script>
"""

SPACER = """
<tr><td colspan=2 height=20> </td></tr>
"""

TOTAL_CPU_LABEL = """
<b style="font-size: 150%%">Total CPU</b><br>
jiffies: <nobr>%(sys)d sys</nobr>, <nobr>%(user)d user</nobr>
"""

CONTEXT_LABEL = """
context: <nobr>%(switches)d switches</nobr>
"""

FAULTS_LABEL = """
<nobr>page faults:</nobr> <nobr>%(major)d major</nobr>
"""

PROC_CPU_LABEL = """
<span style="font-size: 150%%">%(process)s</span> (%(pid)d)<br>
jiffies: <nobr>%(sys)d sys</nobr>, <nobr>%(user)d user</nobr>
</div>
"""

YAFFS_LABEL = """
<span style="font-size: 150%%">%(partition)s</span> (yaffs)<br>
pages: <nobr>%(nPageReads)d read</nobr>,
<nobr>%(nPageWrites)d written</nobr><br>
blocks: <nobr>%(nBlockErasures)d erased</nobr>
"""

PAGE_END = """
</table></body></html>
"""


def WriteChartData(titles, datasets, filename):
    writer = csv.writer(file(filename, "w"))
    writer.writerow(["Time"] + titles)

    merged_rows = {}
    for set_num, data in enumerate(datasets):
        for when, datum in data.iteritems():
            if type(datum) == tuple: datum = "%d/%d" % datum
            merged_rows.setdefault(when, {})[set_num] = datum

    num_cols = len(datasets)
    for when, values in sorted(merged_rows.iteritems()):
        msec = "%d" % (when * 1000)
        writer.writerow([msec] + [values.get(n, "") for n in range(num_cols)])


def WriteOutput(history, log_filename, filename):
    out = []

    out.append(PAGE_BEGIN % {
        "filename": cgi.escape(log_filename),
        "user": cgi.escape(os.environ.get("USER", "unknown")),
        "date": cgi.escape(time.ctime()),
    })

    files_dir = "%s_files" % os.path.splitext(filename)[0]
    files_url = os.path.basename(files_dir)
    if not os.path.isdir(files_dir): os.makedirs(files_dir)

    sorted_history = sorted(history.iteritems())
    date_window = [1000 * sorted_history[0][0], 1000 * sorted_history[-1][0]]

    #
    # Output total CPU statistics
    #

    sys_jiffies = {}
    sys_user_jiffies = {}
    all_jiffies = {}
    total_sys = total_user = 0

    last_state = {}
    for when, state in sorted_history:
        last = last_state.get("/proc/stat:cpu", "").split()
        next = state.get("/proc/stat:cpu", "").split()
        if last and next:
            stime = sum([int(next[x]) - int(last[x]) for x in [2, 5, 6]])
            utime = sum([int(next[x]) - int(last[x]) for x in [0, 1]])
            idle = sum([int(next[x]) - int(last[x]) for x in [3, 4]])
            all = stime + utime + idle
            total_sys += stime
            total_user += utime

            sys_jiffies[when] = (stime, all)
            sys_user_jiffies[when] = (stime + utime, all)
            all_jiffies[when] = all

        last_state = state

    WriteChartData(
        ["sys", "sys+user"],
        [sys_jiffies, sys_user_jiffies],
        os.path.join(files_dir, "total_cpu.csv"))

    out.append(CHART % {
        "id": cgi.escape("total_cpu"),
        "id_js": json.write("total_cpu"),
        "label_html": TOTAL_CPU_LABEL % {"sys": total_sys, "user": total_user},
        "filename_js": json.write(files_url + "/total_cpu.csv"),
        "options_js": json.write({
            "colors": ["blue", "green"],
            "dateWindow": date_window,
            "fillGraph": True,
            "fractions": True,
            "height": 100,
            "valueRange": [0, 110],
        }),
    })

    #
    # Output total context switch statistics
    #

    switches = {}

    last_state = {}
    for when, state in sorted_history:
        last = int(last_state.get("/proc/stat:ctxt", -1))
        next = int(state.get("/proc/stat:ctxt", -1))
        if last != -1 and next != -1:
            switches[when] = next - last

        last_state = state

    WriteChartData(
        ["switches"],
        [switches],
        os.path.join(files_dir, "context_switches.csv"))

    out.append(CHART % {
        "id": cgi.escape("context_switches"),
        "id_js": json.write("context_switches"),
        "label_html": CONTEXT_LABEL % {"switches": sum(switches.values())},
        "filename_js": json.write(files_url + "/context_switches.csv"),
        "options_js": json.write({
            "colors": ["blue"],
            "dateWindow": date_window,
            "fillGraph": True,
            "height": 50,
        }),
    })

    #
    # Collect (no output yet) per-process CPU and major faults
    #

    process_name = {}
    process_start = {}
    process_sys = {}
    process_sys_user = {}

    process_faults = {}
    total_faults = {}
    max_faults = 0

    last_state = {}
    zero_stat = "0 (zero) Z 0 0 0 0 0 0 0 0 0 0 0 0"
    for when, state in sorted_history:
        for key in state:
            if not key.endswith("/stat"): continue

            last = last_state.get(key, zero_stat).split()
            next = state.get(key, "").split()
            if not next: continue

            pid = int(next[0])
            process_start.setdefault(pid, when)
            process_name[pid] = next[1][1:-1]

            all = all_jiffies.get(when, 0)
            if not all: continue

            faults = int(next[11]) - int(last[11])
            process_faults.setdefault(pid, {})[when] = faults
            tf = total_faults[when] = total_faults.get(when, 0) + faults
            max_faults = max(max_faults, tf)

            stime = int(next[14]) - int(last[14])
            utime = int(next[13]) - int(last[13])
            process_sys.setdefault(pid, {})[when] = (stime, all)
            process_sys_user.setdefault(pid, {})[when] = (stime + utime, all)

        last_state = state

    #
    # Output total major faults (sum over all processes)
    #

    WriteChartData(
        ["major"],
        [total_faults],
        os.path.join(files_dir, "total_faults.csv"))

    out.append(CHART % {
        "id": cgi.escape("total_faults"),
        "id_js": json.write("total_faults"),
        "label_html": FAULTS_LABEL % {"major": sum(total_faults.values())},
        "filename_js": json.write(files_url + "/total_faults.csv"),
        "options_js": json.write({
            "colors": ["gray"],
            "dateWindow": date_window,
            "fillGraph": True,
            "height": 50,
            "valueRange": [0, max_faults * 11 / 10],
        }),
    })

    #
    # YAFFS statistics
    #

    out.append(SPACER)

    yaffs_vars = ["nBlockErasures", "nPageReads", "nPageWrites"]
    partition_ops = {}

    last_state = {}
    for when, state in sorted_history:
        for key in state:
            if not key.startswith("/proc/yaffs:"): continue

            last = int(last_state.get(key, -1))
            next = int(state.get(key, -1))
            if last == -1 or next == -1: continue

            value = next - last
            yaffs, partition, var = key.split(":")
            ops = partition_ops.setdefault(partition, {})
            if var in yaffs_vars:
                ops.setdefault(var, {})[when] = value

        last_state = state

    for num, (partition, ops) in enumerate(sorted(partition_ops.iteritems())):
        totals = [sum(ops.get(var, {}).values()) for var in yaffs_vars]
        if not sum(totals): continue

        WriteChartData(
            yaffs_vars,
            [ops.get(var, {}) for var in yaffs_vars],
            os.path.join(files_dir, "yaffs%d.csv" % num))

        values = {"partition": partition}
        values.update(zip(yaffs_vars, totals))
        out.append(CHART % {
            "id": cgi.escape("yaffs%d" % num),
            "id_js": json.write("yaffs%d" % num),
            "label_html": YAFFS_LABEL % values,
            "filename_js": json.write("%s/yaffs%d.csv" % (files_url, num)),
            "options_js": json.write({
                "colors": ["maroon", "gray", "teal"],
                "dateWindow": date_window,
                "fillGraph": True,
                "height": 75,
            })
        })

    #
    # Output per-process CPU and page faults collected earlier
    #

    cpu_cutoff = (total_sys + total_user) / 1000
    faults_cutoff = sum(total_faults.values()) / 200
    for start, pid in sorted([(s, p) for p, s in process_start.iteritems()]):
        sys = sum([n for n, d in process_sys.get(pid, {}).values()])
        sys_user = sum([n for n, d in process_sys_user.get(pid, {}).values()])
        if sys_user <= cpu_cutoff: continue

        out.append(SPACER)

        WriteChartData(
            ["sys", "sys+user"],
            [process_sys.get(pid, {}), process_sys_user.get(pid, {})],
            os.path.join(files_dir, "proc%d.csv" % pid))

        out.append(CHART % {
            "id": cgi.escape("proc%d" % pid),
            "id_js": json.write("proc%d" % pid),
            "label_html": PROC_CPU_LABEL % {
                "pid": pid,
                "process": cgi.escape(process_name.get(pid, "(unknown)")),
                "sys": sys,
                "user": sys_user - sys,
            },
            "filename_js": json.write("%s/proc%d.csv" % (files_url, pid)),
            "options_js": json.write({
                "colors": ["blue", "green"],
                "dateWindow": date_window,
                "fillGraph": True,
                "fractions": True,
                "height": 75,
                "valueRange": [0, 110],
            }),
        })

        faults = sum(process_faults.get(pid, {}).values())
        if faults <= faults_cutoff: continue

        WriteChartData(
            ["major"],
            [process_faults.get(pid, {})],
            os.path.join(files_dir, "proc%d_faults.csv" % pid))

        out.append(CHART % {
            "id": cgi.escape("proc%d_faults" % pid),
            "id_js": json.write("proc%d_faults" % pid),
            "label_html": FAULTS_LABEL % {"major": faults},
            "filename_js": json.write("%s/proc%d_faults.csv" % (files_url, pid)),
            "options_js": json.write({
                "colors": ["gray"],
                "dateWindow": date_window,
                "fillGraph": True,
                "height": 50,
                "valueRange": [0, max_faults * 11 / 10],
            }),
        })

    out.append(PAGE_END)
    file(filename, "w").write("\n".join(out))


def main(argv):
    if len(argv) != 3:
        print >>sys.stderr, "usage: procstatreport.py procstat.log output.html"
        return

    history = {}
    current_state = {}
    scan_time = 0.0

    for line in file(argv[1]):
        parts = line.split(None, 2)
        if len(parts) < 2 or parts[1] not in "+-=":
            print >>sys.stderr, "Invalid input:", line
            sys.exit(1)

        name, op = parts[:2]

        if name == "T" and op == "+":  # timestamp: scan about to begin
            scan_time = float(line[4:])
            continue

        if name == "T" and op == "-":  # timestamp: scan complete
            time = (scan_time + float(line[4:])) / 2.0
            history[time] = dict(current_state)

        elif op == "-":
            if name in current_state: del current_state[name]

        else:
            current_state[name] = "".join(parts[2:]).strip()

    WriteOutput(history, argv[1], argv[2])


if __name__ == "__main__":
    sys.exit(main(sys.argv))