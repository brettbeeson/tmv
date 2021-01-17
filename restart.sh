
for c in highqual # lunchbox #turtle1 lunchbox snackbox ##dog lunchbox picam2 snackbox ## lunchbox cubey #t3610.local # tripod.local lunchbox.local #picam2  #cat2 live.phisaver.com tripod 
do
	ssh $c sudo systemctl restart tmv-camera tmv-upload tmv-interface
done
