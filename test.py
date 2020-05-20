import multiprocessing
from random import randint, random
from time import sleep

def worker(i):
    """worker function"""
    while True:
        print(f'Worker {i}')
        sleep(randint(1,5))
    return

if __name__ == '__main__':
    jobs = []
    for i in range(5):
        p = multiprocessing.Process(target=worker, args=(i,))
        jobs.append(p)
        print("Starting")
        p.start()
        print("Started")
    print("waiting 5s")
    sleep(5)
    for j in jobs:
        j.terminate()
        j.join()
    
