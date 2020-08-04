for c in cat2 #tripod  lunchbox #picam2  #cat2 live.phisaver.com tripod 
do
	rsync -q ~/tmv/* $c:tmv/
	rsync -q -r ~/tmv/tmv/* $c:tmv/tmv/
	rsync -q -r ~/tmv/scripts/* $c:tmv/scripts/
#	rsync -q -r --exclude ~/tmv/tests ~/tmv/* $c:tmv/
done
