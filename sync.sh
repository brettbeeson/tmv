for c in phisaver.local #turtle1 lunchbox snackbox ##dog lunchbox picam2 snackbox ## lunchbox cubey #t3610.local # tripod.local lunchbox.local #picam2  #cat2 live.phisaver.com tripod 
do
	rsync -q ~/tmv/tests/* $c:tmv/tests/
	rsync -q ~/tmv/* $c:tmv/
	rsync -q -r ~/tmv/tmv/* $c:tmv/tmv/
	rsync -q -r ~/tmv/scripts/* $c:tmv/scripts/
#	rsync -q -r --exclude ~/tmv/tests ~/tmv/* $c:tmv/
done
