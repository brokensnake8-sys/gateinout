#!/bin/bash

WATCH="/var/lib/fprint"
TARGET="pi@raspberrypi.local:/var/lib/fprint/"

inotifywait -m -r -e create -e modify -e delete $WATCH |
while read path action file; do
    rsync -az $WATCH/ $TARGET
done
