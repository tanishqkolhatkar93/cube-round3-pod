import time


def stalled(connection, selection, key, prompt, payload, images):
    connection.send({'event':'attempt','model':selection['model']})
    connection.send({'event':'accounting','version':'actual','usage':{'cachedContentTokenCount':3}})
    time.sleep(30)
