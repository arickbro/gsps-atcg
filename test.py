import time
import threading

class ReaderThread(threading.Thread):
    def __init__(self, data):
        super().__init__()
        self.data = data
        self.exit = False

    def run(self):
        t0=time.time()
        while not self.exit:
            # somehow modify self.data
            time.sleep(0.25)
            self.data['count'] = self.data['count'] +1

    def stop(self):
        self.exit = True
        self.join()

class MainThread():
    def __init__(self):
        self.data = {"count":0}
        self.thread = ReaderThread(self.data)

    def function(self):
        self.thread.start()
        time.sleep(2) # whoptydoo
        self.thread.stop()

mt=MainThread()
mt.function()
print(mt.data) # {225, 100, 200, 75, 175, 50, 150, 25, 125}