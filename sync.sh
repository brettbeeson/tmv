rsync -r -v --exclude tests/testdata --exclude venv/ --exclude web-server/ * cat2:tmv
#rsync -r -v --exclude tests/testdata --exclude venv/ * pi@192.168.0.15:tmv
rsync -r -v --exclude tests/testdata --exclude venv/ --exclude web-server/ * pi@picam2:tmv
rsync -r -v --exclude tests/testdata --exclude venv/ * pi@lunchbox:tmv

