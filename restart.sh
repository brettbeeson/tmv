for c in picam2 tripod lunchbox
do
	ssh $c sudo tmv-control -r $1 $2
done
