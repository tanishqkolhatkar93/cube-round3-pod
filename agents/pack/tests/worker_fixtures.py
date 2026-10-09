"""Lightweight spawn target: isolate cleanup timeout from SDK import duration."""
import time


def stalled_sdk(connection,selection,key,prompt,payload,images):
    connection.send({'event':'attempt','model':selection['model']})
    connection.send({'event':'accounting','version':'sdk-version','usage':{'cached_content_token_count':3}})
    time.sleep(30)
