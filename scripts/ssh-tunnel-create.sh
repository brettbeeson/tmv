#!/bin/bash
# eg

# 1: ec2-user@live.phisaver.com
# 2: 2000
# 3: 2020

# Setup

# cd ~
# mkdir .ssh
# echo YOUR_NAME > 0-HOSTe
# wget -O .ssh/id_rsa_new link-to-a-private-key
# cat .ssh/id_rsa_new >> .ssh/id_rsa
# chmod 400 .ssh/id_rsa
# wget "https://www.dropbox.com/s/jws97vzofrokkbj/ssh-tunnel-create.sh"
# chmod 755 ssh-tunnel-create.sh
# sudo cp /usr/bin/ssh /usr/bin/ssh-tunnel
# ./ssh-tunnel-create.sh ec2-user@live.phisaver.com 2000 2020


# Once in, create further tunnels
# ssh -f -N -R 3030:raspberrypi.local:3000 ec2-user@live.phisaver.com
# ssh -f -N -R 8080:hfs02a.local:80 ec2-user@live.phisaver.com
#
#
if [ $# -ne 3 ]; then
    echo "Wrong/no arguments supplied" 1>&2
    exit 2
fi
26928s as remote listening port taken. Trying next.
    elif [ $ret -eq 0 ]; then
      echo An unknown error creating a tunnel to "$1":"$p". RC was $ret. Trying next but not hopeful. 1>&2
    fi
  done
  echo Tunnel failed to "$1":"$p" ports available? 1>&2
  exit 1
fi

 #echo $(hostname),$(ls | head -n 1),8888 | ssh ec2-user@live.phisaver.com '/usr/bin/cat - >> ~/ssh-tunnels.csv'

