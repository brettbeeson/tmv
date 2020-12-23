
for c in lunchbox cubey #t3610.local # tripod.local lunchbox.local #picam2  #cat2 live.phisaver.com tripod 
do
	rsync -q -r --exclude ~/tmv/tests ~/tmv/* $c:tmv/
done
