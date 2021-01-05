#!/usr/bin/python
#
# check-aacraid.py
#
# Grabs the output from "/usr/StorMan/arcconf GETCONFIG 1 LD" then
# determines the health of the Logical Devices.
#
# Grabs the output from "/usr/StorMan/arcconf GETCONFIG 1 AL" then
# determines the health of various status indicators from the card
# and drives.
#
# After the checks are run, it deletes the file "UcliEvt.log" from
# the current working directory.
#
# Add this to your "/etc/sudoers" file:
# "nagios ALL=(root) NOPASSWD: /usr/StorMan/arcconf GETCONFIG 1 *"
# Alternately, run this script as a user who can sudo.
#
# v0.1 - only checks card information so far, not drives yet
# v0.2 - checks logical volume status & wipes log
# v0.3 - strips trailing "," & tells you the logical volume with the failure
# v0.4 - fixed for modern Python compatibility (subprocess vs popen4)
# v0.5 - do not alert on the BBU "Charging" state
# v2.0 - Fix some outputs, conditions, correctly detect ZMM battery status, add pnp4nagios support

# LICENSE/COPYRIGHT
#
# Anchor System - http://www.anchor.com.au
#
# Oliver Hookins
# Paul De Audney
# Barney Desmond
# Mark Smith <mark@bu.mp>
# Plamen Vasilev <p.vasileff@gmail.com>
#
# Scripts edited by Plamen Vasilev <p.vasileff@gmail.com> 2021-01-04

import sys, os, re, string, subprocess
from subprocess import PIPE, Popen

c_status_re = re.compile('^\s*Controller Status\s*:\s*(.*)$')
l_status_re = re.compile('^\s*Status of logical device\s*:\s*(.*)$')
l_device_re = re.compile('^Logical device number ([0-9]+).*$')
c_defunct_re = re.compile('^\s*Defunct disk drive count\s:\s*([0-9]+).*$')
c_degraded_re = re.compile('^\s*Logical devices/Failed/Degraded\s*:\s*([0-9]+)/([0-9]+)/([0-9]+).*$')
b_status_re = re.compile('^\s*Status\s*:\s*(.*)$')
b_temp_re = re.compile('^\s*Over temperature\s*:\s*(.*)$')
b_capacity_re = re.compile('\s*Capacity remaining\s*:\s*([0-9]+)\s*percent.*$')
b_time_re = re.compile('\s*Time remaining \(at current draw\)\s*:\s*([0-9]+) days, ([0-9]+) hours, ([0-9]+) minutes.*$')
d_device_re = re.compile('^\s*Device\s*\s*#([0-9]+)\s*$')
d_state_re = re.compile('^\s*State\s*:\s*(.*)$')

cstatus = lstatus = ldevice = cdefunct = cdegraded = bstatus = btemp = bcapacity = btime = ddecide = dstate = ""
lnum = ""
check_status = 0
check_warn = 0
check_crit = 0
result = ""

for line in Popen(["/usr/bin/sudo","/usr/sbin/arcconf" , "GETCONFIG","1","LD"], stdin=PIPE, stdout=PIPE, close_fds=True).stdout:
	# Match the regexs
	ldevice = l_device_re.match(line)
	if ldevice:
		lnum = ldevice.group(1)
		continue

	lstatus = l_status_re.match(line)
	if lstatus:
		if lstatus.group(1) != "Optimal":
			check_status = 2
			check_crit = 1
		result += "Logical Device: " + lnum + " " + lstatus.group(1) + ", "

for line in Popen(["/usr/bin/sudo","/usr/sbin/arcconf" , "GETCONFIG","1","AD"], stdin=PIPE, stdout=PIPE, close_fds=True).stdout:
	# Match the regexs
	cstatus = c_status_re.match(line)
	if cstatus:
		if cstatus.group(1) != "Optimal":
			check_status = 2
			check_crit = 1
		result += "Controller: " + cstatus.group(1) + ", "
		continue

	cdefunct = c_defunct_re.match(line)
	if cdefunct:
		if int(cdefunct.group(1)) > 0:
			check_status = 2
			check_crit = 1
			result += "Defunct drives: " + cdefunct_group(1) + ", "
		continue

	cdegraded = c_degraded_re.match(line)
	if cdegraded:
		if int(cdegraded.group(2)) > 0:
			check_status = 2
			check_crit = 1
			result += "Failed drives: " + cdegraded.group(2) + ", "
		if int(cdegraded.group(3)) > 0:
			check_status = 2
			check_crit = 1
			result += "Degraded drives: " + cdegraded.group(3) + ", "
		continue

	bstatus = b_status_re.match(line)
	if bstatus:
		if bstatus.group(1) == "Not Installed":
			continue
		
		if bstatus.group(1) == "Charging":
			if check_status < 2:
				check_status = 1
				check_warn = 1
		elif "Optimal" not in bstatus.group(1):
			check_status = 2
			check_crit = 1
		result += "Battery Status: " + bstatus.group(1) + ", "
		continue
	
	btemp = b_temp_re.match(line)
	if btemp:
		if btemp.group(1) != "No":
			check_status = 2
			check_crit = 1
		result += "Battery Overtemp: " + btemp.group(1) + ", "
		continue

	bcapacity = b_capacity_re.match(line)
	if bcapacity:
		result += "Battery Capacity: " + bcapacity.group(1) + "%, "
		if bcapacity.group(1) < 50:
			if check_status < 2:
				check_status = 1
				check_crit = 1
		if bcapacity.group(1) < 25:
			check_status = 2
			check_crit = 1
		continue

	btime = b_time_re.match(line)
	if btime:
		timemins = int(btime.group(1)) * 1440 + int(btime.group(2)) * 60 + int(btime.group(3))
		if timemins < 1440:
			if check_status < 2:
				check_status = 1
				check_crit = 1
		if timemins < 720:
			check_status = 28
			check_crit = 1
		result += "Battery Time: "
		if timemins < 60:
			result += str(timemins) + "mins, "
		else:
			result += str(timemins/60) + "hours, "

for line in Popen(["/usr/bin/sudo","/usr/sbin/arcconf" , "GETCONFIG","1","PD"], stdin=PIPE, stdout=PIPE, close_fds=True).stdout:
	# Match the regexs
	ddevice = d_device_re.match(line)
	if ddevice:
		dnum = ddevice.group(1)
		continue

	dstate = d_state_re.match(line)
	if dstate:
		if dstate.group(1) == "Ready":
			check_warn = 1
			check_status = 1
		elif dstate.group(1) != "Online":
			check_crit = 1
			check_status = 2
		result += "Device: " + dnum + " " + dstate.group(1) + ", "

if result == "":
	result = "No output from arcconf!"
	check_status = 3

# strip the trailing "," from the result string.
result = result.rstrip(", ")
nagios_state = "AACRAID "
if check_status == 0:
        nagios_state += "OK: " + result + " | raiddata=0"

#show critial first if they are warning and critical errors
elif check_crit == 1:
        nagios_state += "CRITICAL: " + result + " | raiddata=2"
elif check_warn == 1:
        nagios_state += "WARNING: " + result + " | raiddata=1"
else:
        nagios_state += "CRITICAL: " + result + " | raiddata=2"
print nagios_state

try:
	cwd = os.getcwd()
	fullpath = os.path.join(cwd,'UcliEvt.log')
	os.unlink(fullpath)
except:
	pass

sys.exit(check_status)

