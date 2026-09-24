#!/bin/bash
D=/mnt/sdb/soundspaces/echoloc/echoloc_dataset/zind
prev=""; same=0
while pgrep -f finish_zind_resume2.sh >/dev/null; do
  t=$(( $(cat /sys/class/thermal/thermal_zone*/temp | sort -n | tail -1) / 1000 ))
  cur="$(find $D/rir -type f | wc -l) $(find /file2/changwoo/echoloc_dataset/zind -type f 2>/dev/null | wc -l) $(find /file1/changwoo/echoloc_dataset/zind -type f 2>/dev/null | wc -l)"
  if [ "$cur" = "$prev" ]; then same=$((same+1)); else same=0; fi
  echo "$(date '+%m-%d %H:%M') pkg=${t}C load=$(cut -d' ' -f1 /proc/loadavg) local/f2/f1=$cur $( [ $same -ge 30 ] && echo STALL_${same}min )"
  prev=$cur; sleep 60
done
echo "$(date '+%m-%d %H:%M') chain exited"
