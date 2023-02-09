#!/bin/bash
# test if hdmi is connected and set cfg option accordingly
# hmm das hier brauecht ich als daemon, wie kanshi auch
# dann einfach datei aendern und signal d.h call videoEnable/Disable
# mit swaymsg guard
# /opt/vc/bin/tvservice -M (continous monitoring) outputs

u="$(/usr/bin/tvservice -s )"
set -- $u
x="${2}"

if (($x%2 == 0)) ; then
    sed -i -e '/videoOutput =/ s/= .*/= true/' /media/data/.bemused/bemused.conf 
else
    sed -i -e '/videoOutput =/ s/= .*/= false/' /media/data/.bemused/bemused.conf 
fi 
