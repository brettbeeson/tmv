import tmv.server


def test2():
    client = tmv.server.socketio.test_client(tmv.server.app)
    client.get_received()
    client.send('echo this message back')

    received = client.get_received()
    assert len(received) == 1
    assert received[0]['args'] == 'echo this message back'
    print(received)

    client.emit("status","gimme")
    received = client.get_received()
    assert received[0]['args'][0]['data'] == "I am your status"
    print  (received)
