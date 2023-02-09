#!/bin/bash
# writes 0/1 to the video.out-file and sends signal.SIGUSR1 to rumba-remote
# see rumba-remote/src/devices/signal.py

echo "$1" > ~/.config/rumba-remote/video.out

pid=$(ps -ef | awk '$(NF-2) ~ /rumba-remote\.py$/ {print $2}')

if [ $pid ]
then
        kill -s SIGUSR1 $pid
fi

swaymsg "[app_id=rumba-remote] focus";
