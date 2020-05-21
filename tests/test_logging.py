import logging
import  logging.handlers
import multiprocessing
from tmv.netlog import log_server
from random import choice

class ContextFilter(logging.Filter):
    """
    This is a filter which injects contextual information into the log.

    Rather than use actual contextual information, we just use random
    data in this demo.
    """

    USERS = ['jim', 'fred', 'sheila']
    IPS = ['123.231.231.123', '127.0.0.1', '192.168.0.1']

    def filter(self, record):
        record.ip = choice(ContextFilter.IPS)
        record.user = choice(ContextFilter.USERS)
        return True

def no_test_logging():

    # start server
    #p = multiprocessing.Process(target=log_server, daemon=True) #, args=(i,))
    #p.start()

    #add_context_filter = ContextFilter()
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)-15s %(name)-5s %(levelname)-8s IP: %(ip)-15s User: %(user)-8s %(message)s')
    
  #  rootLogger = logging.getLogger('')
    
  #  rootLogger.setLevel(logging.DEBUG)
    socketHandler = logging.handlers.SocketHandler('localhost',
                        logging.handlers.DEFAULT_TCP_LOGGING_PORT)
    # don't bother with a formatter, since a socket handler sends the event as
    # an unformatted pickle
    #rootLogger.addHandler(socketHandler)

    # Now, we can log to the root logger, or any other logger. First the root...
    logging.info('Jackdaws love my big sphinx of quartz.')

    # Now, define a couple of other loggers which might represent areas in your
    # application:

    logger1 = logging.getLogger('myapp.area1')
    logger1.debug('Quick zephyrs blow, vexing daft Jim.')

    logger2 = logging.getLogger('myapp.area2')
    f=ContextFilter()
    logger1.addFilter(f)
    logger1.debug('Quick zephyrs blow, vexing daft Jim.')
    logger1.info('How quickly daft jumping zebras vex.')
    logger2.warning('Jail zesty vixen who grabbed pay from quack.')
    logger2.error('The five boxing wizards jump quickly.')
    assert False


def no_test2():
    levels = (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL)
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)-15s %(name)-5s %(levelname)-8s IP: %(ip)-15s User: %(user)-8s %(message)s')
    a1 = logging.getLogger('a.b.c')
    a2 = logging.getLogger('d.e.f')

    f = ContextFilter()
    a1.addFilter(f)
    a2.addFilter(f)
    a1.debug('A debug message')
    a1.info('An info message with %s', 'some parameters')
    for x in range(10):
        lvl = choice(levels)
        lvlname = logging.getLevelName(lvl)
        a2.log(lvl, 'A message at %s level with %d %s', lvlname, 2, 'parameters')

    assert False