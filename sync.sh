for c in cat2 live.phisaver.com picam2 tripod lunchbox
do
	rsync -q -r ~/tmv/tmv/* $c:tmv/tmv
#	rsync -q -r --exclude ~/tmv/tests ~/tmv/* $c:tmv/
done
