c=$1
#rsync -q ~/tmv/tests/* $c:tmv/tests/
#rsync -q  ~/tmv/* $c:tmv/
#rsync -q -r ~/tmv/tmv/* $c:tmv/tmv/
#rsync -q -r ~/tmv/scripts/* $c:tmv/scripts/
rsync -v  -r --exclude venv ~/tmv/* --exclude tests $c:~/tmv/

