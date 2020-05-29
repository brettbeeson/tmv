for c in lunchbox picam2 tripod 
do
	ssh $c sudo tmv-control -r $1 $2
	ssh $c sudo systemctl restart tmv-camapp
done
